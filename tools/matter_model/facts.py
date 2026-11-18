#!/usr/bin/env python3
"""Factual layer — parties / facts / gaps дела (расширение matter_model).

Персистентный слой фактов дела `matter-facts.yaml` в папке дела внутри workflow/,
рядом с уже существующей хронологией `matter-timeline.yaml` (тул model.py). Факт
отделён от юридической квалификации, у каждого факта locator на первоисточник,
слой переиспользуется downstream-скиллами без перечитывания исходников.

Три хранимые коллекции (объекты, которых нет в timeline):
- parties — реестр сторон (кто есть кто + реквизиты + статус проверки);
- facts   — объекты FACT: факты-состояния/утверждения (не события), со statement,
            fact_status, locator, legal_relevance, contradicted_by;
- gaps     — объекты GAP: чего фактически не хватает (unknown/why_relevant/…).

Три производных представления (НЕ хранятся — вычисляются в report, DRY):
- evidence-map    — факт/событие → документ-источник (переход в обе стороны);
- disputed-facts  — DISPUTED-факты + contradicted_by + status_conflict из timeline;
- contradictions  — формальный детект кандидатов (timeline + fact-уровень).

Разделение LLM vs код (architecture-first, low-freedom для детерминированного):
- ИЗВЛЕЧЕНИЕ фактов/сторон/пробелов, их формулировка, определение fact_status и
  legal_relevance, ЮРИДИЧЕСКАЯ ОЦЕНКА кандидатов противоречий — работа агента/юриста.
- Скрипт: валидация схемы и traceability, ревалидация при update, контроль
  принципа 1 (не повышать до CONFIRMED без нового источника), формальный детект
  кандидатов, рендер представлений и сводки. Кандидат — лид для юриста, не вывод.

Инварианты (единый источник истины — references/matter-model-usage.md, ≤7 принципов):
- fact_status берётся из fact-matrix через model.FACT_STATUSES (НЕ переопределяется).
- traceability обязательна: party/fact без source_doc+source_fragment не вносится.
- принцип 1: факт не повышается до CONFIRMED без нового/изменённого источника;
  смена статуса пишется в status_history (прежний → новый, дата).
- legal_relevance отделён от факта (дефолт not_assessed); тул сам material не ставит.
- файл не удаляется; объекты закрываются статусом/правкой, а не удалением.

Usage:
    python tools/matter_model/facts.py init --file PATH --matter NAME
    python tools/matter_model/facts.py add-party --file PATH --name N --role ROLE
        --source-doc D --source-fragment F [--requisites R] [--req-status S] [--notes ...]
    python tools/matter_model/facts.py add-fact --file PATH --statement S
        --fact-status STATUS --source-doc D --source-fragment F
        [--legal-relevance L] [--contradicted-by ID ...] [--related-event T-00N ...]
        [--party-ref P-00N] [--notes ...]
    python tools/matter_model/facts.py add-gap --file PATH --unknown U --why-relevant W
        [--potential-evidence E ...] [--status S] [--related ID ...] [--notes ...]
    python tools/matter_model/facts.py update --file PATH --id F-001 [поля...]
    python tools/matter_model/facts.py validate --file PATH
    python tools/matter_model/facts.py report --file PATH
    python tools/matter_model/facts.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model  # noqa: E402  (единый источник схемы fact_status и хелперов)

# Windows-консоль по умолчанию cp1251 — кириллица ломается.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Переиспользуем из model.py — один источник истины.
ModelError = model.ModelError
FACT_STATUSES = model.FACT_STATUSES
FACT_CHECK = model.FACT_CHECK

SCHEMA_VERSION = 1
PARTY_ROLES = ("our_side", "counterparty", "opponent", "court", "gov_body", "third_party")
LEGAL_RELEVANCE = ("not_assessed", "potentially_relevant", "material")
GAP_STATUSES = ("open", "searching", "resolved", "unavailable")
REQ_STATUSES = ("verified", "unverified")
REQ_CHECK = "[ПРОВЕРИТЬ РЕКВИЗИТЫ]"

COLLECTIONS = ("parties", "facts", "gaps")


# ---------- storage ----------

def load(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ModelError(f"matter-facts не найден: {path} (сначала init)")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not any(k in data for k in COLLECTIONS):
        raise ModelError(f"файл не похож на matter-facts: {path}")
    for coll in COLLECTIONS:
        data.setdefault(coll, [])
    return data


def save(path: Path, data: dict) -> None:
    path = Path(path)
    data["updated"] = dt.date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def next_id(items: list[dict], prefix: str) -> str:
    mx = 0
    for it in items:
        try:
            mx = max(mx, int(str(it.get("id", "")).split("-")[-1]))
        except ValueError:
            continue
    return f"{prefix}-{mx + 1:03d}"


def _list(val) -> list:
    return list(val) if val else []


# ---------- validation ----------

def validate_party(p: dict) -> list[str]:
    errs = []
    pid = p.get("id", "?")
    if not str(p.get("name", "")).strip():
        errs.append(f"{pid}: пустое name")
    if p.get("role") not in PARTY_ROLES:
        errs.append(f"{pid}: role должен быть из {PARTY_ROLES}, а не {p.get('role')!r}")
    if not str(p.get("source_doc", "")).strip():
        errs.append(f"{pid}: пустой source_doc (traceability обязательна)")
    if not str(p.get("source_fragment", "")).strip():
        errs.append(f"{pid}: пустой source_fragment (traceability обязательна)")
    if p.get("req_status", "unverified") not in REQ_STATUSES:
        errs.append(f"{pid}: req_status должен быть из {REQ_STATUSES}")
    return errs


def validate_fact(f: dict) -> list[str]:
    errs = []
    fid = f.get("id", "?")
    if not str(f.get("statement", "")).strip():
        errs.append(f"{fid}: пустой statement")
    if f.get("fact_status") not in FACT_STATUSES:
        errs.append(f"{fid}: fact_status должен быть из {FACT_STATUSES}, а не {f.get('fact_status')!r}")
    if not str(f.get("source_doc", "")).strip():
        errs.append(f"{fid}: пустой source_doc (traceability обязательна)")
    if not str(f.get("source_fragment", "")).strip():
        errs.append(f"{fid}: пустой source_fragment (traceability обязательна)")
    if f.get("legal_relevance", "not_assessed") not in LEGAL_RELEVANCE:
        errs.append(f"{fid}: legal_relevance должен быть из {LEGAL_RELEVANCE}")
    errs.extend(model.evidence_anchor.validate_anchor(f.get("anchor"), fid))
    return errs


def validate_gap(g: dict) -> list[str]:
    errs = []
    gid = g.get("id", "?")
    if not str(g.get("unknown", "")).strip():
        errs.append(f"{gid}: пустой unknown")
    if not str(g.get("why_relevant", "")).strip():
        errs.append(f"{gid}: пустой why_relevant")
    if g.get("status", "open") not in GAP_STATUSES:
        errs.append(f"{gid}: status должен быть из {GAP_STATUSES}")
    return errs


def validate_all(data: dict) -> list[str]:
    errs = []
    ids = [it.get("id") for coll in COLLECTIONS for it in data.get(coll, [])]
    if len(ids) != len(set(ids)):
        errs.append(f"дублирующиеся id: {ids}")
    for p in data.get("parties", []):
        errs.extend(validate_party(p))
    for f in data.get("facts", []):
        errs.extend(validate_fact(f))
    for g in data.get("gaps", []):
        errs.extend(validate_gap(g))
    return errs


# ---------- views (derived, not stored) ----------

def build_evidence_map(facts: list[dict], events: list[dict]) -> dict[str, list[dict]]:
    """source_doc → [{kind, id, ref, statement}] по фактам и событиям timeline."""
    out: dict[str, list[dict]] = {}
    for f in facts:
        doc = str(f.get("source_doc") or "").strip()
        if doc:
            out.setdefault(doc, []).append({
                "kind": "fact", "id": f.get("id"),
                "ref": f.get("source_fragment"), "statement": f.get("statement"),
            })
    for ev in events:
        doc = str(ev.get("source_doc") or "").strip()
        if doc:
            out.setdefault(doc, []).append({
                "kind": "event", "id": ev.get("id"),
                "ref": ev.get("source_fragment"), "statement": ev.get("event"),
            })
    return out


def build_disputed(facts: list[dict], events: list[dict]) -> list[dict]:
    """DISPUTED-факты + contradicted_by + status_conflict из timeline."""
    out: list[dict] = []
    for f in facts:
        if f.get("fact_status") == "DISPUTED" or _list(f.get("contradicted_by")):
            out.append({
                "id": f.get("id"), "type": "disputed_fact",
                "detail": f.get("statement"),
                "contradicted_by": _list(f.get("contradicted_by")),
            })
    for cand in model.detect_candidates(events):
        if cand["type"] == "status_conflict":
            out.append({"id": ", ".join(cand["ids"]), "type": "status_conflict",
                        "detail": cand["detail"]})
    return out


def detect_fact_candidates(facts: list[dict]) -> list[dict]:
    """Fact-уровень: contradicted_by → кандидат противоречия (лид, не вывод)."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for f in facts:
        for other in _list(f.get("contradicted_by")):
            ids = tuple(sorted({str(f.get("id")), str(other)}))
            if ids in seen:
                continue
            seen.add(ids)
            out.append({"type": "fact_contradiction", "ids": list(ids),
                        "detail": f"факт «{f.get('statement')}» ({f.get('id')}) "
                                  f"противоречит {other}"})
    return out


def build_contradictions(facts: list[dict], events: list[dict]) -> list[dict]:
    """Кандидаты противоречий: fact-уровень + timeline (model.detect_candidates)."""
    return detect_fact_candidates(facts) + model.detect_candidates(events)


# ---------- commands ----------

def cmd_init(args) -> int:
    path = Path(args.file)
    if path.exists():
        raise ModelError(f"matter-facts уже существует: {path} (init повторно не выполняется)")
    today = dt.date.today().isoformat()
    save(path, {
        "schema_version": SCHEMA_VERSION,
        "matter": args.matter,
        "created": today,
        "updated": today,
        "parties": [],
        "facts": [],
        "gaps": [],
    })
    print(f"OK: создан matter-facts {path} (matter: {args.matter})")
    return 0


def cmd_add_party(args) -> int:
    path = Path(args.file)
    data = load(path)
    today = dt.date.today().isoformat()
    p = {
        "id": next_id(data["parties"], "P"),
        "name": args.name,
        "role": args.role,
        "requisites": args.requisites or "",
        "req_status": args.req_status,
        "source_doc": args.source_doc,
        "source_fragment": args.source_fragment,
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    errs = validate_party(p)
    if errs:
        raise ModelError("сторона не прошла валидацию:\n  " + "\n  ".join(errs))
    data["parties"].append(p)
    save(path, data)
    mark = f" {REQ_CHECK}" if p["req_status"] != "verified" else ""
    print(f"OK: {p['id']} «{p['name']}» [{p['role']}]{mark}")
    return 0


def cmd_add_fact(args) -> int:
    path = Path(args.file)
    data = load(path)
    today = dt.date.today().isoformat()
    f = {
        "id": next_id(data["facts"], "F"),
        "statement": args.statement,
        "fact_status": args.fact_status,
        "source_doc": args.source_doc,
        "source_fragment": args.source_fragment,
        "legal_relevance": args.legal_relevance,
        "contradicted_by": _list(args.contradicted_by),
        "related_events": _list(args.related_event),
        "party_ref": args.party_ref or "",
        "notes": args.notes or "",
        "status_history": [],
        "created": today,
        "updated": today,
    }
    anchor = model.build_anchor(args.source_doc, args.quote, args.quote_location, path.parent)
    if anchor:
        f["anchor"] = anchor
    errs = validate_fact(f)
    if errs:
        raise ModelError("факт не прошёл валидацию:\n  " + "\n  ".join(errs))
    if model.enforce_confirmed(f):
        print(f"ВНИМАНИЕ: {f['id']} понижен до REPORTED — {model.UNANCHORED}; "
              f"{(f.get('anchor') or {}).get('check_detail') or 'укажите --quote'}")
    data["facts"].append(f)
    save(path, data)
    mark = f" {FACT_CHECK}" if f["fact_status"] != "CONFIRMED" else ""
    print(f"OK: {f['id']} «{f['statement']}» [{f['fact_status']}]{mark}")
    return 0


def cmd_add_gap(args) -> int:
    path = Path(args.file)
    data = load(path)
    today = dt.date.today().isoformat()
    g = {
        "id": next_id(data["gaps"], "G"),
        "unknown": args.unknown,
        "why_relevant": args.why_relevant,
        "potential_evidence": _list(args.potential_evidence),
        "status": args.status,
        "related": _list(args.related),
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    errs = validate_gap(g)
    if errs:
        raise ModelError("пробел не прошёл валидацию:\n  " + "\n  ".join(errs))
    data["gaps"].append(g)
    save(path, data)
    print(f"OK: {g['id']} «{g['unknown']}» [{g['status']}]")
    return 0


def _find(data: dict, item_id: str) -> tuple[dict | None, str | None]:
    for coll, typ in (("parties", "party"), ("facts", "fact"), ("gaps", "gap")):
        for it in data.get(coll, []):
            if it.get("id") == item_id:
                return it, typ
    return None, None


# поля, доступные для update, по типу объекта
_UPDATE_FIELDS = {
    "party": ("name", "role", "requisites", "req_status", "source_doc",
              "source_fragment", "notes"),
    "fact": ("statement", "fact_status", "source_doc", "source_fragment",
             "legal_relevance", "party_ref", "notes"),
    "gap": ("unknown", "why_relevant", "status", "notes"),
}


def cmd_update(args) -> int:
    path = Path(args.file)
    data = load(path)
    item, typ = _find(data, args.id)
    if item is None:
        raise ModelError(f"объект {args.id} не найден в {path}")

    # принцип 1: факт не повышается до CONFIRMED без нового/изменённого источника
    if typ == "fact" and args.fact_status is not None:
        old_status = item.get("fact_status")
        if args.fact_status == "CONFIRMED" and old_status != "CONFIRMED":
            src_changed = (
                (args.source_doc is not None and args.source_doc != item.get("source_doc"))
                or (args.source_fragment is not None
                    and args.source_fragment != item.get("source_fragment"))
            )
            if not src_changed:
                raise ModelError(
                    f"{args.id}: принцип 1 — нельзя повысить факт до CONFIRMED без "
                    "нового/изменённого источника (укажите source-doc/source-fragment "
                    "с появившимся доказательством)")

    old_status = item.get("fact_status") if typ == "fact" else None
    for field in _UPDATE_FIELDS[typ]:
        val = getattr(args, field, None)
        if val is not None:
            item[field] = val
    if typ == "fact" and (args.quote is not None or (args.source_doc is not None and item.get("anchor"))):
        quote = args.quote if args.quote is not None else item["anchor"]["quote"]
        qloc = (args.quote_location if args.quote_location is not None
                else (item.get("anchor") or {}).get("location"))
        item["anchor"] = model.build_anchor(item["source_doc"], quote, qloc, path.parent)
    if (typ == "fact" and args.fact_status == "CONFIRMED"
            and not model.evidence_anchor.is_verified(item.get("anchor"))):
        raise ModelError(f"{args.id}: CONFIRMED требует цитату, найденную в источнике "
                         "(--quote, при необходимости --quote-location)")

    validator = {"party": validate_party, "fact": validate_fact, "gap": validate_gap}[typ]
    errs = validator(item)
    if errs:
        raise ModelError("после update объект не валиден:\n  " + "\n  ".join(errs))

    if typ == "fact" and args.fact_status is not None and args.fact_status != old_status:
        item.setdefault("status_history", []).append({
            "from": old_status, "to": args.fact_status, "date": dt.date.today().isoformat(),
        })
    item["updated"] = dt.date.today().isoformat()
    save(path, data)
    print(f"OK: {args.id} обновлён")
    return 0


def cmd_validate(args) -> int:
    data = load(Path(args.file))
    errs = validate_all(data)
    if errs:
        print(f"НЕВАЛИДНО ({len(errs)}):")
        for e in errs:
            print(f"  - {e}")
        return 1
    n = sum(len(data[c]) for c in COLLECTIONS)
    print(f"OK: matter-facts валиден — объектов {n} "
          f"(сторон {len(data['parties'])}, фактов {len(data['facts'])}, пробелов {len(data['gaps'])})")
    return 0


def _sibling_events(path: Path) -> list[dict]:
    """Подхватить события соседней matter-timeline.yaml, если она есть."""
    tl = Path(path).parent / "matter-timeline.yaml"
    if tl.exists():
        try:
            return model.load(tl).get("events", [])
        except ModelError:
            return []
    return []


def render_report(data: dict, events: list[dict]) -> str:
    today = dt.date.today().isoformat()
    matter = data.get("matter", "дело")
    lines = [f"# Factual layer: {matter} (на {today})", ""]

    # parties
    lines.append("## Стороны")
    if data["parties"]:
        for p in data["parties"]:
            req = f" — {p['requisites']}" if p.get("requisites") else ""
            mark = f" {REQ_CHECK}" if p.get("req_status") != "verified" else ""
            lines.append(f"- {p['id']} [{p['role']}] {p['name']}{req}{mark} "
                         f"— {p.get('source_doc')}, {p.get('source_fragment')}")
    else:
        lines.append("_нет_")
    lines.append("")

    # facts
    lines.append("## Факты")
    if data["facts"]:
        for f in data["facts"]:
            fs = f.get("fact_status")
            mark = f" {FACT_CHECK}" if fs != "CONFIRMED" else ""
            rel = f" · значимость: {f.get('legal_relevance')}"
            lines.append(f"- {f['id']} [{fs}]{rel} {f['statement']}{mark} "
                         f"— {f.get('source_doc')}, {f.get('source_fragment')}{model.anchor_note(f)}")
    else:
        lines.append("_нет_")
    lines.append("")

    # gaps
    lines.append("## Пробелы (чего не хватает)")
    if data["gaps"]:
        for g in data["gaps"]:
            ev = f" (закрыть: {'; '.join(g['potential_evidence'])})" if g.get("potential_evidence") else ""
            lines.append(f"- {g['id']} [{g['status']}] {g['unknown']} — {g['why_relevant']}{ev}")
    else:
        lines.append("_нет_")
    lines.append("")

    # derived views
    emap = build_evidence_map(data["facts"], events)
    if emap:
        lines.append("## Карта доказательств (факт/событие → документ)")
        for doc in sorted(emap):
            lines.append(f"### {doc}")
            for it in emap[doc]:
                lines.append(f"- {it['id']} ({it['kind']}): {it['statement']} — {it['ref']}")
        lines.append("")

    disputed = build_disputed(data["facts"], events)
    if disputed:
        lines.append("## Спорные факты")
        for d in disputed:
            lines.append(f"- [{d['type']}] {d['id']}: {d['detail']}")
        lines.append("")

    cands = build_contradictions(data["facts"], events)
    if cands:
        lines.append("## ⚠️ Кандидаты противоречий / двойного счёта")
        lines.append("_Формальный детект. Юридическую оценку даёт юрист — это лид, не вывод._")
        for c in cands:
            lines.append(f"- [{c['type']}] {c['detail']}")
        lines.append("")

    n_facts = sum(1 for f in data["facts"] if f.get("fact_status") != "CONFIRMED")
    n_req = sum(1 for p in data["parties"] if p.get("req_status") != "verified")
    n_gaps = sum(1 for g in data["gaps"] if g.get("status") in ("open", "searching"))
    lines.append(f"Итого: сторон {len(data['parties'])}, фактов {len(data['facts'])}, "
                 f"пробелов {len(data['gaps'])}, кандидатов {len(cands)}.")
    if n_facts:
        lines.append(f"⚠️ Фактов с непроверенным статусом (≠ CONFIRMED): {n_facts} — {FACT_CHECK}.")
    if n_req:
        lines.append(f"⚠️ Сторон с непроверенными реквизитами: {n_req} — {REQ_CHECK}.")
    if n_gaps:
        lines.append(f"⚠️ Открытых пробелов: {n_gaps}.")
    return "\n".join(lines)


def cmd_report(args) -> int:
    path = Path(args.file)
    data = load(path)
    events = _sibling_events(path)
    print(render_report(data, events))
    return 0


# ---------- selftest ----------

def selftest() -> int:
    import tempfile

    ok = 0
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td) / "ДелоАльфа"
        f = str(folder / "matter-facts.yaml")
        tl = str(folder / "matter-timeline.yaml")

        run(["init", "--file", f, "--matter", "ДелоАльфа"])
        run(["add-party", "--file", f, "--name", "ООО «Ромашка»", "--role", "counterparty",
             "--source-doc", "договор", "--source-fragment", "преамбула"])
        run(["add-fact", "--file", f, "--statement", "продавец не получил оплату",
             "--fact-status", "REPORTED", "--source-doc", "письмо контрагента", "--source-fragment", "абз.2"])
        run(["add-fact", "--file", f, "--statement", "оплата произведена",
             "--fact-status", "DISPUTED", "--source-doc", "платёжка", "--source-fragment", "стр.1",
             "--contradicted-by", "F-001"])
        run(["add-gap", "--file", f, "--unknown", "куда перечислены средства",
             "--why-relevant", "определяет обязанного субъекта"])

        data = load(Path(f))
        assert [p["id"] for p in data["parties"]] == ["P-001"]
        assert [x["id"] for x in data["facts"]] == ["F-001", "F-002"]
        assert data["gaps"][0]["id"] == "G-001"
        assert validate_all(data) == [], validate_all(data)
        ok += 1

        # принцип 1
        try:
            run(["update", "--file", f, "--id", "F-001", "--fact-status", "CONFIRMED"])
            raise AssertionError("повышение до CONFIRMED без источника должно падать")
        except ModelError:
            ok += 1
        (folder / "выписка.md").write_text("Стр. 2. Оплата по договору не поступала.", encoding="utf-8")
        run(["update", "--file", f, "--id", "F-001", "--fact-status", "CONFIRMED",
             "--source-doc", "выписка.md", "--source-fragment", "стр.2",
             "--quote", "Оплата по договору не поступала"])
        data = load(Path(f))
        assert data["facts"][0]["fact_status"] == "CONFIRMED"
        assert data["facts"][0]["status_history"][-1]["from"] == "REPORTED"
        ok += 1

        model.run(["init", "--file", tl, "--matter", "ДелоАльфа"])
        run(["report", "--file", f])
        run(["validate", "--file", f])
        ok += 1

    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--file", required=True)
    p.add_argument("--matter", required=True)

    p = sub.add_parser("add-party")
    p.add_argument("--file", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--role", required=True, choices=PARTY_ROLES)
    p.add_argument("--requisites")
    p.add_argument("--req-status", dest="req_status", default="unverified", choices=REQ_STATUSES)
    p.add_argument("--source-doc", dest="source_doc", required=True)
    p.add_argument("--source-fragment", dest="source_fragment", required=True)
    p.add_argument("--notes")

    p = sub.add_parser("add-fact")
    p.add_argument("--file", required=True)
    p.add_argument("--statement", required=True)
    p.add_argument("--fact-status", dest="fact_status", required=True, choices=FACT_STATUSES)
    p.add_argument("--source-doc", dest="source_doc", required=True)
    p.add_argument("--source-fragment", dest="source_fragment", required=True)
    p.add_argument("--legal-relevance", dest="legal_relevance",
                   default="not_assessed", choices=LEGAL_RELEVANCE)
    p.add_argument("--contradicted-by", dest="contradicted_by", action="append")
    p.add_argument("--related-event", dest="related_event", action="append")
    p.add_argument("--party-ref", dest="party_ref")
    p.add_argument("--notes")
    p.add_argument("--quote", help="дословная цитата из source_doc (проверяется по тексту)")
    p.add_argument("--quote-location", dest="quote_location", help="место цитаты: пункт, страница")

    p = sub.add_parser("add-gap")
    p.add_argument("--file", required=True)
    p.add_argument("--unknown", required=True)
    p.add_argument("--why-relevant", dest="why_relevant", required=True)
    p.add_argument("--potential-evidence", dest="potential_evidence", action="append")
    p.add_argument("--status", default="open", choices=GAP_STATUSES)
    p.add_argument("--related", action="append")
    p.add_argument("--notes")

    p = sub.add_parser("update")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--name")
    p.add_argument("--role", choices=PARTY_ROLES)
    p.add_argument("--requisites")
    p.add_argument("--req-status", dest="req_status", choices=REQ_STATUSES)
    p.add_argument("--statement")
    p.add_argument("--fact-status", dest="fact_status", choices=FACT_STATUSES)
    p.add_argument("--source-doc", dest="source_doc")
    p.add_argument("--source-fragment", dest="source_fragment")
    p.add_argument("--legal-relevance", dest="legal_relevance", choices=LEGAL_RELEVANCE)
    p.add_argument("--party-ref", dest="party_ref")
    p.add_argument("--unknown")
    p.add_argument("--why-relevant", dest="why_relevant")
    p.add_argument("--status", choices=GAP_STATUSES)
    p.add_argument("--notes")
    p.add_argument("--quote")
    p.add_argument("--quote-location", dest="quote_location")

    p = sub.add_parser("validate")
    p.add_argument("--file", required=True)

    p = sub.add_parser("report")
    p.add_argument("--file", required=True)

    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {
        "init": cmd_init, "add-party": cmd_add_party, "add-fact": cmd_add_fact,
        "add-gap": cmd_add_gap, "update": cmd_update,
        "validate": cmd_validate, "report": cmd_report,
    }[args.cmd](args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except ModelError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
