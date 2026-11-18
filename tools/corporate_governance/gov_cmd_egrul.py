# -*- coding: utf-8 -*-
"""Команды выписки ЕГРЮЛ: fetch-egrul, check-edition, egrul-summary.

fetch-egrul получает официальную выписку ФНС сам, без участия юриста; юрист нужен
только когда ФНС недоступна или требует капчу (тогда выписку кладут вручную и
регистрируют register-source --kind egrul_extract). check-edition сверяет ГРН с
титульного листа устава с последней записью об учредительном документе в выписке
и по результату ставит или снимает статус current. Правовой оценки нет: это сверка
с реестром, одобрение правил устава остаётся за юристом (confirm).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_cmd_checks as checks  # noqa: E402
import gov_egrul as egrul  # noqa: E402
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402
from gov_cmd_entity import find_source  # noqa: E402

KIND = "egrul_extract"
MANUAL = ("Получите выписку вручную: https://egrul.nalog.ru → ОГРН → «Получить выписку»; положите PDF "
          "в profile/knowledge/corporate/_inbox/, перенесите в originals/ и зарегистрируйте: "
          "register-source --kind egrul_extract --title \"Выписка из ЕГРЮЛ …\" --file originals/<файл> "
          "--edition-date <дата выписки>; затем check-edition.")


def _free_name(originals: Path, stem: str) -> str:
    name, n = f"{stem}.pdf", 2
    while (originals / name).exists():
        name, n = f"{stem} ({n}).pdf", n + 1
    return name


def _write_page_texts(entity: store.Entity, source_id: str, texts: list[str]) -> None:
    """Текст страниц выписки туда, где verify-quotes ищет текст (слой ФНС дословный, OCR не нужен)."""
    for number, text in enumerate(texts, start=1):
        path = checks.page_file(entity, source_id, "ocr", number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _last_charter_line(info: dict) -> str:
    last = egrul.latest_charter_record(info["records"])
    if last is None:
        return "записей об учредительном документе в выписке нет"
    docs = "; ".join(d["name"] for d in last["documents"]) or "—"
    return (f"ГРН {last['grn']} от {last['date']} ({last['charter_kind']}), стр. {last['page']}; "
            f"документы: {docs}")


def summary_text(source_id: str, info: dict) -> str:
    lines = [f"Выписка {source_id}: {info['full_name']} | ОГРН {info['ogrn']} | ИНН {info['inn']} | "
             f"по состоянию на {info['extract_date']} | стр. {info['pages']}"]
    lines.append("Без доверенности действуют:")
    for m in info["managers"] or [{}]:
        if not m:
            lines.append("  нет сведений")
            continue
        flag = " [в ЕГРЮЛ отмечена недостоверность]" if m["unreliable"] else ""
        lines.append(f"  {m['name']} — {m['position']} (ГРН {m['grn']} от {m['date']}), стр. {m['page']}{flag}")
    lines.append("Участники:")
    for p in info["participants"] or [{}]:
        if not p:
            lines.append("  нет сведений")
            continue
        who = f"{p['name']} (ОГРН {p['ogrn']})" if p["ogrn"] else p["name"]
        flag = " [в ЕГРЮЛ отмечена недостоверность]" if p["unreliable"] else ""
        lines.append(f"  {who} — {p['percent']} %, номинал {p['nominal']} руб., стр. {p['page']}{flag}")
    lines.append("Последняя запись об учредительном документе: " + _last_charter_line(info))
    return "\n".join(lines)


def cmd_fetch_egrul(args) -> int:
    entity = store.entity_from_args(args)
    originals = entity.domain_dir / "originals"
    rel = f"originals/{_free_name(originals, f'ЕГРЮЛ {args.ogrn.strip()} {store.today()}')}"
    target = entity.domain_dir / rel
    try:
        meta = egrul.fetch_extract(args.ogrn, target)
    except ValueError as exc:
        raise store.GovError(str(exc)) from exc
    except egrul.EgrulUnavailable as exc:
        raise store.GovError(f"выписка не получена автоматически ({exc}). {MANUAL}") from exc
    try:
        texts = egrul.pdf_page_texts(target)
        info = egrul.parse_pages(texts)
        if info["ogrn"] != meta["ogrn"]:
            raise store.GovError(f"в полученном файле выписка другой компании (ОГРН {info['ogrn']}, "
                                 f"запрошен {meta['ogrn']}): файл не зарегистрирован")
    except (store.GovError, egrul.NotEgrulExtract) as exc:
        target.unlink(missing_ok=True)
        raise store.GovError(str(exc)) from exc
    data = entity.load_sources()
    date = info["extract_date"]
    src = {
        "source_id": store.next_id("S", data["sources"], "source_id"),
        "kind": KIND,
        "title": f"Выписка из ЕГРЮЛ {meta.get('short_name') or info['full_name']} (ОГРН {info['ogrn']}) от {date}",
        "edition_date": date,
        "registry_record": None,
        "file": rel,
        "pages": info["pages"],
        "status": "current",
        "supersedes": None,
        "current_basis": f"официальная выписка ФНС с egrul.nalog.ru по состоянию на {date}, "
                         f"получена {store.today()} (fetch-egrul)",
        "registered_at": store.today(),
    }
    errors = schema.validate_source(src)
    if errors:
        target.unlink(missing_ok=True)
        raise store.GovError("; ".join(errors))
    data["sources"].append(src)
    rev = entity.save_sources(data)
    _write_page_texts(entity, src["source_id"], texts)
    entity.audit("fetch-egrul", src["source_id"], actor=args.actor,
                 new={**src, "ogrn": info["ogrn"], "inn": info["inn"]},
                 source=f"{egrul.BASE_URL} (ОГРН {info['ogrn']})", rev=rev)
    print(f"OK: {src['source_id']} — {src['title']}, стр. {src['pages']}")
    print(summary_text(src["source_id"], info))
    return 0


def _charter(sources: list[dict], wanted: str | None) -> dict:
    if wanted:
        src = find_source({"sources": sources}, wanted)
        if src.get("kind") != "charter":
            raise store.GovError(f"{wanted} — не устав (kind={src.get('kind')})")
        return src
    charters = [s for s in sources if s.get("kind") == "charter" and s.get("status") != "superseded"]
    if len(charters) != 1:
        raise store.GovError(f"действующих редакций устава в профиле: {len(charters)}; укажите --charter")
    return charters[0]


def _extracts_with(entity: store.Entity, sources: list[dict], grn: str, wanted: str | None) -> list[tuple]:
    """(выписка, разбор) из выписок профиля, где есть запись с этим ГРН; при --extract — только она."""
    if wanted:
        src = find_source({"sources": sources}, wanted)
        if src.get("kind") != KIND:
            raise store.GovError(f"{wanted} — не выписка ЕГРЮЛ (kind={src.get('kind')})")
        candidates = [src]
    else:
        candidates = [s for s in sources if s.get("kind") == KIND and s.get("status") != "superseded"]
    found = []
    for src in candidates:
        try:
            info = egrul.parse_pages(egrul.pdf_page_texts(entity.domain_dir / src["file"]))
        except Exception as exc:  # noqa: BLE001 — нечитаемая выписка не должна ронять проверку по остальным
            if wanted:
                raise store.GovError(f"{src['source_id']}: выписку не удалось прочитать ({exc})") from exc
            print(f"  пропуск {src['source_id']}: выписку не удалось прочитать ({exc})")
            continue
        if egrul.record_by_grn(info["records"], grn) is not None:
            found.append((src, info))
    return found


def cmd_check_edition(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_sources()
    charter = _charter(data["sources"], args.charter)
    grn = str((charter.get("registry_record") or {}).get("grn") or "").strip()
    if not grn:
        raise store.GovError(f"на уставе {charter['source_id']} не записан ГРН редакции: перечитайте отметку "
                             "налогового органа на титульном листе и запишите её: update-source --source-id <устав> --grn <ГРН> --grn-date <дата>")
    found = _extracts_with(entity, data["sources"], grn, args.extract)
    if not found:
        raise store.GovError(f"ни в одной выписке ЕГРЮЛ профиля нет записи ГРН {grn}: получите выписку "
                             "общества (fetch-egrul --ogrn <ОГРН общества>) либо проверьте ГРН на титульном листе")
    extract, info = max(found, key=lambda pair: (pair[1]["extract_date"] or "", pair[0]["source_id"]))
    anchor = egrul.record_by_grn(info["records"], grn)
    if not anchor["charter"]:
        raise store.GovError(f"запись ГРН {grn} в выписке {extract['source_id']} не об учредительном документе "
                             f"(«{anchor['reason']}»): проверьте ГРН на титульном листе устава")
    later = egrul.charter_records_after(info["records"], grn)
    old = {key: charter.get(key) for key in ("status", "current_basis", "verified_by_extract")}
    if not later and not anchor["invalid"]:
        charter["status"] = "current"
        charter["current_basis"] = (f"выписка ЕГРЮЛ {extract['source_id']} по состоянию на {info['extract_date']}: "
                                    f"последняя запись об изменении учредительного документа — ГРН {grn} "
                                    f"от {anchor['date']} (стр. {anchor['page']}), совпадает с отметкой на уставе")
        charter["verified_by_extract"] = extract["source_id"]
        verdict, code = "current", 0
    else:
        charter.update(status="unverified", current_basis=None, verified_by_extract=None,
                       approved_by=None, approved_at=None)
        verdict, code = "not_current", 1
    errors = schema.validate_source(charter)
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_sources(data)
    entity.audit("check-edition", charter["source_id"], actor=args.actor, old=old,
                 new={"result": verdict, "grn": grn, "status": charter["status"],
                      "current_basis": charter.get("current_basis"),
                      "later_records": [{"grn": r["grn"], "date": r["date"], "page": r["page"]} for r in later],
                      "invalid": anchor["invalid"]},
                 source=extract["source_id"], rev=rev)
    if code == 0:
        print(f"OK: редакция {charter['source_id']} подтверждена выпиской {extract['source_id']} "
              f"({info['extract_date']}): ГРН {grn} от {anchor['date']} — последняя запись об уставе. "
              "Статус current.")
        return 0
    print(f"ОТКАЗ: редакция {charter['source_id']} (ГРН {grn}) по выписке {extract['source_id']} "
          f"({info['extract_date']}) не текущая:")
    if anchor["invalid"]:
        print(f"  запись ГРН {grn} признана недействительной ({anchor['status']})")
    for r in later:
        docs = "; ".join(d["name"] for d in r["documents"]) or "—"
        print(f"  позже: ГРН {r['grn']} от {r['date']} ({r['charter_kind']}), стр. {r['page']}; документы: {docs}")
    print("  Нужна действующая редакция устава: получите её, зарегистрируйте (register-source --kind charter "
          "--grn …) и выполните supersede-source; статус устава — unverified.")
    return 1


def cmd_egrul_summary(args) -> int:
    entity = store.entity_from_args(args)
    src = find_source(entity.load_sources(), args.source_id)
    if src.get("kind") != KIND:
        raise store.GovError(f"{args.source_id} — не выписка ЕГРЮЛ (kind={src.get('kind')}): нужен egrul_extract")
    try:
        info = egrul.parse_pages(egrul.pdf_page_texts(entity.domain_dir / src["file"]))
    except Exception as exc:  # noqa: BLE001 — любой сбой чтения сообщается как ошибка команды
        raise store.GovError(f"{args.source_id}: выписку не удалось прочитать ({exc})") from exc
    print(summary_text(args.source_id, info))
    return 0


def register(sub) -> None:
    p = sub.add_parser("fetch-egrul", parents=[store.common_parser()],
                       help="получить официальную выписку ЕГРЮЛ с egrul.nalog.ru и зарегистрировать её")
    p.add_argument("--ogrn", required=True, help="ОГРН (13 цифр) или ИНН (10 цифр) юридического лица")
    p.set_defaults(func=cmd_fetch_egrul)

    p = sub.add_parser("check-edition", parents=[store.common_parser()],
                       help="сверить редакцию устава с выпиской ЕГРЮЛ (ставит или снимает current)")
    p.add_argument("--charter", help="source_id устава (по умолчанию единственная действующая редакция)")
    p.add_argument("--extract", help="source_id выписки (по умолчанию самая свежая, где есть ГРН устава)")
    p.set_defaults(func=cmd_check_edition)

    p = sub.add_parser("egrul-summary", parents=[store.common_parser()],
                       help="ЕИО, участники и последняя запись об уставе из выписки (со страницами)")
    p.add_argument("--source-id", required=True)
    p.set_defaults(func=cmd_egrul_summary, no_lock=True)  # только чтение
