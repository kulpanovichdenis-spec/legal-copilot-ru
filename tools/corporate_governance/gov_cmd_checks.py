# -*- coding: utf-8 -*-
"""Команды-проверки: render-pages, verify-quotes, validate, inconsistencies, stale."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_cmd_rules  # noqa: E402
import gov_decisions as decisions  # noqa: E402
import gov_quotes as quotes  # noqa: E402
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402
import gov_views as views  # noqa: E402
from gov_cmd_entity import find_source  # noqa: E402

ROOT = store.ROOT
TEXT_LAYER_MIN = 20  # столько символов на каждой странице — признак электронного PDF, а не скана


# ---------- render-pages ----------

def page_file(entity: store.Entity, source_id: str, kind: str, page: int) -> Path:
    """_work/<source>/png|ocr/page-NNN.png|txt"""
    ext = "png" if kind == "png" else "txt"
    return entity.work_dir / source_id / kind / f"page-{page:03d}.{ext}"


def cmd_render_pages(args) -> int:
    entity = store.entity_from_args(args)
    src = find_source(entity.load_sources(), args.source_id)
    pdf = entity.domain_dir / src["file"]
    if not pdf.is_file():
        raise store.GovError(f"файл источника не найден: {pdf}")
    try:
        import fitz
    except ImportError as exc:
        raise store.GovError("нужен PyMuPDF: pip install pymupdf") from exc
    png_dir = entity.work_dir / src["source_id"] / "png"
    png_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(pdf)) as doc:
        total = len(doc)
        layer = [page.get_text() for page in doc]
        for number, page in enumerate(doc, start=1):
            page.get_pixmap(dpi=args.dpi_png).save(str(page_file(entity, src["source_id"], "png", number)))
    print(f"OK: страниц PNG: {total} → {png_dir}")
    if args.no_ocr:
        return 0
    ocr_dir = entity.work_dir / src["source_id"] / "ocr"
    if layer and all(len(text.strip()) >= TEXT_LAYER_MIN for text in layer):
        # электронный документ (выписка ФНС и т. п.): текстовый слой дословный, OCR только исказил бы его
        ocr_dir.mkdir(parents=True, exist_ok=True)
        for number, text in enumerate(layer, start=1):
            page_file(entity, src["source_id"], "ocr", number).write_text(text, encoding="utf-8")
        print(f"OK: страниц текста: {total} → {ocr_dir} (текстовый слой PDF, дословно; OCR не нужен)")
        return 0
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.doc_ingest import ocr_tesseract  # noqa: PLC0415

    try:
        texts = ocr_tesseract.ocr_pdf_pages(pdf, dpi=args.dpi_ocr)
    except ocr_tesseract.OcrUnavailable as exc:
        print(f"[ОЦР НЕДОСТУПЕН] {exc}. Страницы PNG готовы, сверка цитат будет unchecked.")
        return 0
    ocr_dir.mkdir(parents=True, exist_ok=True)
    for number, text in enumerate(texts, start=1):
        page_file(entity, src["source_id"], "ocr", number).write_text(text, encoding="utf-8")
    print(f"OK: страниц OCR: {len(texts)} → {ocr_dir} (OCR недословный: только поиск и нечёткая сверка)")
    return 0


# ---------- verify-quotes ----------

def _page_text(entity: store.Entity, prov: dict) -> str | None:
    path = page_file(entity, prov["source_id"], "ocr", prov["page"])
    return path.read_text(encoding="utf-8") if path.is_file() else None


def cmd_verify_quotes(args) -> int:
    entity = store.entity_from_args(args)
    wanted = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids else None
    rules, profile = entity.load_rules(), entity.load_profile()
    counts = {"matched": 0, "fuzzy": 0, "not_found": 0, "unchecked": 0}
    problems: list[str] = []
    pending: list[tuple[str, dict, dict]] = []  # (id, record, collection-owner)
    for rule in rules["rules"]:
        pending.append((rule["rule_id"], rule, rules))
    for fact in profile["facts"]:
        pending.append((fact["fact_id"], fact, profile))
    if wanted is not None:
        unknown = sorted(wanted - {oid for oid, _, _ in pending})
        if unknown:
            raise store.GovError(
                "verify-quotes --ids: запись не найдена среди правил и фактов: " + ", ".join(unknown))
    touched = {"rules": False, "profile": False}
    for oid, record, owner in pending:
        if wanted is not None and oid not in wanted:
            continue
        prov = record["provenance"]
        old_quote_check = prov.get("quote_check")
        text = _page_text(entity, prov)
        if text is None:
            result = {"status": "unchecked", "score": None}
        else:
            result = quotes.check_quote(prov["quote"], text, args.threshold)
        prov["quote_check"] = {"method": "ocr_fuzzy", "score": result["score"],
                               "status": result["status"], "checked_at": store.today()}
        counts[result["status"]] += 1
        downgraded = False
        if result["status"] == "not_found":
            problems.append(f"{oid} ({views.locator(prov)})")
            # verified-запись с quote_check=not_found validate не пропускает: не оставлять такое
            # состояние молча (I2) — понижаем и фиксируем понижение в том же аудит-событии
            downgraded = gov_cmd_rules._reset_verification(record)
        touched["rules" if owner is rules else "profile"] = True
        new_value = {"quote_check": prov["quote_check"], "downgraded_from_verified": downgraded} \
            if downgraded else {"quote_check": prov["quote_check"]}
        entity.audit("verify-quote", oid, actor=args.actor, old=old_quote_check, new=new_value,
                     source=prov["source_id"])
    if touched["rules"]:
        entity.save_rules(rules)
    if touched["profile"]:
        entity.save_profile(profile)
    print("Сверка цитат: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    for item in problems:
        print(f"  НЕ НАЙДЕНА: {item} — проверить цитату по скану {views.MARK_SOURCE}")
    return 0


# ---------- validate ----------

def collect_errors(entity: store.Entity, catalog_path: Path | None = None) -> tuple[list[str], dict]:
    errors: list[str] = []
    sources = entity.load_sources()["sources"]
    rules = entity.load_rules()["rules"]
    profile = entity.load_profile()
    by_id = {s["source_id"]: s for s in sources}

    def duplicates(items, key, label):
        seen = set()
        for item in items:
            value = item.get(key)
            if value in seen:
                errors.append(f"{label}: повторяющийся идентификатор {value}")
            seen.add(value)

    duplicates(sources, "source_id", "sources.yaml")
    duplicates(rules, "rule_id", "rules.yaml")
    duplicates(profile["facts"], "fact_id", "profile.yaml (facts)")
    duplicates(profile["assumptions"], "assumption_id", "profile.yaml (assumptions)")
    for src in sources:
        errors.extend(schema.validate_source(src))
        if src.get("supersedes") and src["supersedes"] not in by_id:
            errors.append(f"{src['source_id']}: supersedes указывает на неизвестный {src['supersedes']}")
        by_extract = src.get("verified_by_extract")
        if by_extract and (by_id.get(by_extract) or {}).get("kind") != "egrul_extract":
            errors.append(f"{src['source_id']}: verified_by_extract {by_extract} — не выписка ЕГРЮЛ этого профиля")
    for rule in rules:
        errors.extend(schema.validate_rule(rule, by_id))
        if rule.get("freshness") and not rule.get("law_ref"):
            errors.append(f"{rule['rule_id']}: freshness без law_ref")
    tagged = [r for r in rules if isinstance(r.get("decisions"), list) and r["decisions"]]
    if tagged:
        try:
            known = decisions.decision_ids(decisions.read_catalog(catalog_path or decisions.CATALOG_PATH))
        except store.GovError as exc:
            errors.append(f"rules.yaml: привязки decisions не проверены: {exc}")
        else:
            for rule in tagged:
                for did in rule["decisions"]:
                    if did not in known:
                        errors.append(f"{rule['rule_id']}: decisions: {did!r} нет в каталоге решений")
    keys = set()
    for fact in profile["facts"]:
        errors.extend(schema.validate_fact(fact, by_id))
        if fact.get("section") == "classification" and not fact.get("needs_review"):
            if fact.get("key") in keys:
                errors.append(f"{fact['fact_id']}: поле классификации {fact['key']!r} задано дважды")
            keys.add(fact.get("key"))
    for item in profile["assumptions"]:
        errors.extend(schema.validate_assumption(item))
    counts = {"sources": len(sources), "rules": len(rules), "facts": len(profile["facts"]),
              "assumptions": len(profile["assumptions"])}
    return errors, counts


def cmd_validate(args) -> int:
    entity = store.entity_from_args(args)
    errors, counts = collect_errors(entity, Path(args.catalog) if args.catalog else None)
    if errors:
        print(f"ОШИБОК: {len(errors)}")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("OK: ошибок нет (" + ", ".join(f"{k} {v}" for k, v in counts.items()) + ")")
    return 0


# ---------- inconsistencies / stale ----------

def cmd_inconsistencies(args) -> int:
    entity = store.entity_from_args(args)
    found = views.find_inconsistencies(entity.load_rules()["rules"])
    if not found:
        print("Кандидатов на противоречие нет.")
        return 0
    print(f"Кандидатов на противоречие: {len(found)} (лид для юриста, не вывод)")
    for item in found:
        print(f"  {item['topic']} / {item['subject']}")
        for r in item["rules"]:
            print(f"    {r['rule_id']} [{r['layer']}] {r['locator']}: {r['value']}")
    return 0


def cmd_stale(args) -> int:
    entity = store.entity_from_args(args)
    today = schema.to_date(args.today) if args.today else dt.date.today()
    if today is None:
        raise store.GovError("--today должен быть датой YYYY-MM-DD")
    stale = views.find_stale(entity.load_rules()["rules"], today, args.days)
    if not stale:
        print(f"Устаревших и непроверенных правил нет (порог {args.days} дн.).")
        return 0
    print(f"Требуют проверки: {len(stale)} (порог {args.days} дн.) {views.MARK_NORM}")
    for item in stale:
        print(f"  {item['rule_id']}: {item['reason']}")
    return 0


def register(sub) -> None:
    common = store.common_parser()

    p = sub.add_parser("render-pages", parents=[common],
                       help="PDF → PNG страниц и OCR-текст в _work/")
    p.add_argument("--source-id", required=True)
    p.add_argument("--dpi-png", type=int, default=100, help="разрешение PNG для чтения агентом")
    p.add_argument("--dpi-ocr", type=int, default=300)
    p.add_argument("--no-ocr", action="store_true", help="только PNG")
    # долгий OCR не держит блокировку: команда пишет только в _work/ и не трогает yaml
    p.set_defaults(func=cmd_render_pages, no_lock=True)

    p = sub.add_parser("verify-quotes", parents=[common],
                       help="нечёткая сверка цитат с OCR-текстом страниц")
    p.add_argument("--ids", help="R-001,F-002 (по умолчанию все)")
    p.add_argument("--threshold", type=float, default=quotes.DEFAULT_THRESHOLD)
    p.set_defaults(func=cmd_verify_quotes)

    # validate, inconsistencies, stale только читают: os.replace даёт им целый файл, блокировка не нужна
    p = sub.add_parser("validate", parents=[common], help="схема, provenance, ссылки")
    p.add_argument("--catalog", help="каталог решений для проверки привязок decisions")
    p.set_defaults(func=cmd_validate, no_lock=True)

    p = sub.add_parser("inconsistencies", parents=[common],
                       help="кандидаты на внутренние противоречия (лид, не вывод)")
    p.set_defaults(func=cmd_inconsistencies, no_lock=True)

    p = sub.add_parser("stale", parents=[common],
                       help="правила без проверки нормы или с устаревшей проверкой")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--today", help="дата для расчёта YYYY-MM-DD (по умолчанию сегодня)")
    p.set_defaults(func=cmd_stale, no_lock=True)
