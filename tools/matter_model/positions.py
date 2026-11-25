#!/usr/bin/env python3
"""Слой позиций сторон — issues / positions дела (третья коллекция matter_model).

`matter-positions.yaml` в папке дела рядом с `matter-timeline.yaml` (model.py) и
`matter-facts.yaml` (facts.py). Хранит, ЧТО стороны заявляют (факт о деле), а не
правовой анализ: выводы и стратегия живут в `_analysis/` (skill case-analysis).

Две коллекции:
- issues    — спорные вопросы (I-001…): question, status, depth, stance, desired_position;
- positions — позиции сторон (C-001…): party_ref → matter-facts.parties, issue_ref → issues,
              kind, statement, evidence, stated_basis, source_doc + source_fragment.

Разделение LLM vs код:
- ИЗВЛЕЧЕНИЕ позиций, формулировка и группировка вопросов — агент (класс C);
  подтверждение вопросов, глубины и режима — юрист на чекпоинте.
- Скрипт: схема, traceability, ссылочная целостность (party_ref / issue_ref),
  формальные лиды (unanswered / no_evidence / empty_issue / no_our_side) и карта
  для чекпоинта. Лид — повод посмотреть, не вывод.

Реестр сторон не дублируется: стороны и роли берутся из соседнего matter-facts.yaml.

Usage:
    python tools/matter_model/positions.py init --file PATH --matter NAME
    python tools/matter_model/positions.py add-issue --file PATH --question Q
        [--status proposed|confirmed|dropped] [--depth quick|standard|deep]
        [--stance neutral|position_led] [--desired-position P] [--notes ...]
    python tools/matter_model/positions.py add-position --file PATH --party-ref P-00N
        --issue-ref I-00N --kind claim|argument|defense|procedural_request --statement S
        --source-doc D --source-fragment F [--evidence E ...] [--stated-basis B] [--notes ...]
    python tools/matter_model/positions.py update --file PATH --id I-001|C-001 [поля...]
    python tools/matter_model/positions.py validate --file PATH
    python tools/matter_model/positions.py report --file PATH [--chart]
    python tools/matter_model/positions.py add-support --file PATH --id C-001 --source-doc D
        --quote "дословно" [--quote-location "п. 5.1"] --stance supports|contradicts [--note ...]
    python tools/matter_model/positions.py set-state --file PATH --id C-001 --support-state supported|partial
    python tools/matter_model/positions.py mark-checked --file PATH --id C-001 [--undo]
    python tools/matter_model/positions.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.workflow_layout import case_for_artifact, technical_path  # noqa: E402
import facts  # noqa: E402  (реестр сторон, роли, хелперы хранения — один источник истины)
import model  # noqa: E402

# Windows-консоль по умолчанию cp1251 — кириллица ломается.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ModelError = model.ModelError
save = facts.save
next_id = facts.next_id

SCHEMA_VERSION = 1
ISSUE_STATUSES = ("proposed", "confirmed", "dropped")
DEPTHS = ("quick", "standard", "deep")
STANCES = ("neutral", "position_led")
POSITION_KINDS = ("claim", "argument", "defense", "procedural_request")
# Т3: доказательство позиции — якорь с цитатой (tools/evidence_anchor/anchor.py) и направлением.
SUPPORT_STANCES = ("supports", "contradicts")
# Состояние позиции. gap / needs_evidence / disputed вычисляет код; supported / partial — суждение
# агента, допустимое только при ≥1 проверенной подтверждающей цитате и без опровергающей.
SUPPORT_STATES = ("supported", "partial", "disputed", "gap", "needs_evidence")
DECLARABLE_STATES = ("supported", "partial")
# Роли, чьи позиции не требуют ответа нашей стороны (лид unanswered их не считает).
NOT_OPPOSING_ROLES = ("our_side", "court")

COLLECTIONS = ("issues", "positions")
FACTS_FILE = "matter-facts.yaml"


# ---------- storage ----------

def load(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ModelError(f"matter-positions не найден: {path} (сначала init)")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not any(k in data for k in COLLECTIONS):
        raise ModelError(f"файл не похож на matter-positions: {path}")
    for coll in COLLECTIONS:
        data[coll] = data.get(coll) or []
    return data


def load_parties(path: Path) -> list[dict]:
    """Стороны из соседнего matter-facts.yaml — реестр сторон живёт там, не здесь."""
    ff = technical_path(case_for_artifact(Path(path)), FACTS_FILE)
    if not ff.exists():
        raise ModelError(f"рядом нет {FACTS_FILE}: {ff} — сначала реестр сторон "
                         "(facts.py init / add-party)")
    return facts.load(ff).get("parties") or []


def _blank(val) -> bool:
    return val is None or not str(val).strip()


def effective_state(p: dict) -> str:
    """Состояние позиции по её якорям; заявленное агентом учитывается, только если якоря позволяют."""
    support = p.get("support") or []
    contra = [s for s in support if s.get("stance") == "contradicts" and s.get("quote_check") != "mismatch"]
    pro = [s for s in support if s.get("stance") == "supports"]
    if contra:
        return "disputed"
    if not pro:
        return "needs_evidence" if p.get("evidence") else "gap"
    if not any(model.evidence_anchor.is_verified(s) for s in pro):
        return "needs_evidence"
    declared = p.get("support_state")
    return declared if declared in DECLARABLE_STATES else "partial"


# ---------- validation ----------

def validate_issue(i: dict) -> list[str]:
    errs = []
    iid = i.get("id", "?")
    if _blank(i.get("question")):
        errs.append(f"{iid}: пустой question")
    for field, allowed in (("status", ISSUE_STATUSES), ("depth", DEPTHS), ("stance", STANCES)):
        if i.get(field) not in allowed:
            errs.append(f"{iid}: {field} должен быть из {allowed}, а не {i.get(field)!r}")
    if i.get("stance") == "position_led" and _blank(i.get("desired_position")):
        errs.append(f"{iid}: stance=position_led требует непустой desired_position")
    return errs


def validate_position(p: dict, issue_ids: set, party_ids: set) -> list[str]:
    errs = []
    cid = p.get("id", "?")
    if _blank(p.get("statement")):
        errs.append(f"{cid}: пустой statement")
    if p.get("kind") not in POSITION_KINDS:
        errs.append(f"{cid}: kind должен быть из {POSITION_KINDS}, а не {p.get('kind')!r}")
    if _blank(p.get("source_doc")):
        errs.append(f"{cid}: пустой source_doc (traceability обязательна)")
    if _blank(p.get("source_fragment")):
        errs.append(f"{cid}: пустой source_fragment (traceability обязательна)")
    if p.get("party_ref") not in party_ids:
        errs.append(f"{cid}: party_ref {p.get('party_ref')!r} нет в matter-facts.parties")
    if p.get("issue_ref") not in issue_ids:
        errs.append(f"{cid}: issue_ref {p.get('issue_ref')!r} нет среди issues")
    ev = p.get("evidence")
    if ev is not None:
        if not isinstance(ev, list):
            errs.append(f"{cid}: evidence должен быть списком строк, а не {type(ev).__name__}")
        else:
            errs.extend(f"{cid}: evidence[{n}] должен быть непустой строкой"
                        for n, x in enumerate(ev, 1) if not isinstance(x, str) or _blank(x))
    support = p.get("support") or []
    if not isinstance(support, list):
        errs.append(f"{cid}: support должен быть списком")
        support = []
    for n, s in enumerate(support, 1):
        where = f"{cid}.support[{n}]"
        if not isinstance(s, dict):
            errs.append(f"{where}: должен быть словарём")
            continue
        if s.get("stance") not in SUPPORT_STANCES:
            errs.append(f"{where}: stance должен быть из {SUPPORT_STANCES}")
        if _blank(s.get("source_doc")):
            errs.append(f"{where}: пустой source_doc")
        errs.extend(model.evidence_anchor.validate_anchor(s, where))
    declared = p.get("support_state")
    if declared is not None:
        if declared not in DECLARABLE_STATES:
            errs.append(f"{cid}: support_state задаётся только как {DECLARABLE_STATES}; "
                        "gap / needs_evidence / disputed вычисляются по цитатам")
        elif effective_state(p) != declared:
            errs.append(f"{cid}: support_state={declared}, но по цитатам — {effective_state(p)}")
    if p.get("lawyer_checked") not in (None, True, False):
        errs.append(f"{cid}: lawyer_checked должен быть true/false")
    return errs


def validate_all(data: dict, parties: list[dict]) -> list[str]:
    errs = []
    ids = [it.get("id") for coll in COLLECTIONS for it in data.get(coll, [])]
    if len(ids) != len(set(ids)):
        errs.append(f"дублирующиеся id: {ids}")
    issue_ids = {i.get("id") for i in data.get("issues", [])}
    party_ids = {p.get("id") for p in parties}
    for i in data.get("issues", []):
        errs.extend(validate_issue(i))
    for p in data.get("positions", []):
        errs.extend(validate_position(p, issue_ids, party_ids))
    return errs


# ---------- leads (формальные, не вывод) ----------

def detect_leads(data: dict, parties: list[dict]) -> list[dict]:
    """Лиды для чекпоинта. Снятые (dropped) вопросы не рассматриваются."""
    roles = {p.get("id"): p.get("role") for p in parties}
    has_our_side = "our_side" in roles.values()
    leads: list[dict] = []
    if not has_our_side:
        leads.append({"type": "no_our_side", "ids": [],
                      "detail": "в matter-facts нет стороны с role: our_side — уточнить у юриста"})
    live = [i for i in data.get("issues", []) if i.get("status") != "dropped"]
    for issue in live:
        iid = issue.get("id")
        own = [p for p in data.get("positions", []) if p.get("issue_ref") == iid]
        if not own:
            leads.append({"type": "empty_issue", "ids": [iid],
                          "detail": f"{iid} «{issue.get('question')}»: позиций нет"})
            continue
        opposing = [p.get("id") for p in own
                    if roles.get(p.get("party_ref")) not in NOT_OPPOSING_ROLES]
        answered = any(roles.get(p.get("party_ref")) == "our_side" for p in own)
        if has_our_side and opposing and not answered:
            leads.append({"type": "unanswered", "ids": [iid] + opposing,
                          "detail": f"{iid} «{issue.get('question')}»: доводы "
                                    f"{', '.join(opposing)} без позиции нашей стороны"})
    live_ids = {i.get("id") for i in live}
    for p in data.get("positions", []):
        if p.get("issue_ref") not in live_ids:
            continue
        if not p.get("evidence") and not p.get("support"):
            leads.append({"type": "no_evidence", "ids": [p.get("id")],
                          "detail": f"{p.get('id')}: позиция без доказательств — "
                                    f"«{p.get('statement')}»"})
        elif p.get("support") and effective_state(p) == "needs_evidence":
            leads.append({"type": "unverified_quote", "ids": [p.get("id")],
                          "detail": f"{p.get('id')}: ни одна подтверждающая цитата не найдена в "
                                    f"источнике — «{p.get('statement')}»"})
    return leads


def _support_line(s: dict) -> str:
    loc = f"{s.get('location')}; " if s.get("location") else ""
    note = f" — {s['note']}" if s.get("note") else ""
    return f"«{s.get('quote')}» ({loc}{s.get('source_doc')}) [{s.get('quote_check', 'not_checked')}]{note}"


def render_chart(data: dict, parties: list[dict]) -> str:
    """Карта «позиция → цитата → опровержение → состояние». Пробелы — первым блоком."""
    today = dt.date.today().isoformat()
    by_id = {p.get("id"): p for p in parties}
    live = {i.get("id"): i for i in data.get("issues", []) if i.get("status") != "dropped"}
    positions = [p for p in data.get("positions", []) if p.get("issue_ref") in live]
    lines = [f"# Карта доказательств: {data.get('matter', 'дело')} (на {today})", "",
             "_Черновик для юриста. Цитаты сверены с источником кодом; суждение «подтверждено / "
             "частично» — агента, финальная оценка — юриста._", ""]

    def who(p):
        party = by_id.get(p.get("party_ref"), {})
        return f"{party.get('name', p.get('party_ref'))} [{party.get('role', '?')}]"

    weak = [p for p in positions if effective_state(p) in ("gap", "needs_evidence", "disputed")]
    lines.append("## Пробелы и спорное")
    if not weak:
        lines.append("_нет_")
    for p in weak:
        lines.append(f"- {p.get('id')} [{effective_state(p)}] {who(p)}: {p.get('statement')} "
                     f"(вопрос {p.get('issue_ref')})")
    lines.append("")
    for iid, issue in live.items():
        lines.append(f"## {iid} {issue.get('question')}")
        own = [p for p in positions if p.get("issue_ref") == iid]
        if not own:
            lines.append("_позиций нет_")
        for p in own:
            checked = " · проверено юристом" if p.get("lawyer_checked") else ""
            lines.append(f"- {p.get('id')} [{effective_state(p)}{checked}] {who(p)} · "
                         f"{p.get('kind')}: {p.get('statement')}")
            for s in p.get("support") or []:
                label = "подтверждает" if s.get("stance") == "supports" else "опровергает"
                lines.append(f"  - {label}: {_support_line(s)}")
            legacy = p.get("evidence") or []
            if legacy and not p.get("support"):
                lines.append(f"  - названо без цитаты: {'; '.join(legacy)} {model.FACT_CHECK}")
        lines.append("")
    counts: dict[str, int] = {}
    for p in positions:
        counts[effective_state(p)] = counts.get(effective_state(p), 0) + 1
    lines.append("Итого: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "позиций нет") + ".")
    return "\n".join(lines)


def render_report(data: dict, parties: list[dict]) -> str:
    today = dt.date.today().isoformat()
    by_id = {p.get("id"): p for p in parties}
    lines = [f"# Карта позиций: {data.get('matter', 'дело')} (на {today})", ""]
    ours = [p for p in parties if p.get("role") == "our_side"]
    lines.append("Наша сторона: " + (", ".join(f"{p.get('id')} {p.get('name')}" for p in ours)
                                     if ours else "не задана"))
    lines.append("")
    for issue in data.get("issues", []):
        iid = issue.get("id")
        lines.append(f"## {iid} [{issue.get('status')}] {issue.get('question')}")
        mode = f"глубина: {issue.get('depth')} · режим: {issue.get('stance')}"
        if issue.get("stance") == "position_led":
            mode += f" · требуемая позиция: {issue.get('desired_position')}"
        lines.append(f"_{mode}_")
        own = [p for p in data.get("positions", []) if p.get("issue_ref") == iid]
        if not own:
            lines.append("_позиций нет_")
        for p in own:
            party = by_id.get(p.get("party_ref"), {})
            who = f"{party.get('name', p.get('party_ref'))} [{party.get('role', '?')}]"
            evidence = "; ".join(p.get("evidence") or []) or "нет"
            basis = f" · сослалась на: {p['stated_basis']}" if p.get("stated_basis") else ""
            lines.append(f"- {p.get('id')} {who} · {p.get('kind')}: {p.get('statement')} "
                         f"— {p.get('source_doc')}, {p.get('source_fragment')} "
                         f"· доказательства: {evidence}{basis}")
        lines.append("")
    leads = detect_leads(data, parties)
    if leads:
        lines.append("## ⚠️ Лиды для чекпоинта")
        lines.append("_Формальный детект — повод посмотреть, не вывод._")
        for lead in leads:
            lines.append(f"- [{lead['type']}] {lead['detail']}")
        lines.append("")
    lines.append(f"Итого: вопросов {len(data.get('issues', []))}, "
                 f"позиций {len(data.get('positions', []))}, лидов {len(leads)}.")
    return "\n".join(lines)


# ---------- commands ----------

def cmd_init(args) -> int:
    path = Path(args.file)
    if path.exists():
        raise ModelError(f"matter-positions уже существует: {path} (init повторно не выполняется)")
    today = dt.date.today().isoformat()
    save(path, {
        "schema_version": SCHEMA_VERSION,
        "matter": args.matter,
        "created": today,
        "updated": today,
        "issues": [],
        "positions": [],
    })
    print(f"OK: создан matter-positions {path} (matter: {args.matter})")
    return 0


def cmd_add_issue(args) -> int:
    path = Path(args.file)
    data = load(path)
    today = dt.date.today().isoformat()
    i = {
        "id": next_id(data["issues"], "I"),
        "question": args.question,
        "status": args.status,
        "depth": args.depth,
        "stance": args.stance,
        "desired_position": args.desired_position or "",
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    errs = validate_issue(i)
    if errs:
        raise ModelError("вопрос не прошёл валидацию:\n  " + "\n  ".join(errs))
    data["issues"].append(i)
    save(path, data)
    print(f"OK: {i['id']} «{i['question']}» [{i['status']}, {i['depth']}, {i['stance']}]")
    return 0


def cmd_add_position(args) -> int:
    path = Path(args.file)
    data = load(path)
    parties = load_parties(path)
    today = dt.date.today().isoformat()
    p = {
        "id": next_id(data["positions"], "C"),
        "party_ref": args.party_ref,
        "issue_ref": args.issue_ref,
        "kind": args.kind,
        "statement": args.statement,
        "evidence": list(args.evidence or []),
        "stated_basis": args.stated_basis or "",
        "source_doc": args.source_doc,
        "source_fragment": args.source_fragment,
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    errs = validate_position(p, {i.get("id") for i in data["issues"]},
                             {x.get("id") for x in parties})
    if errs:
        raise ModelError("позиция не прошла валидацию:\n  " + "\n  ".join(errs))
    data["positions"].append(p)
    save(path, data)
    print(f"OK: {p['id']} {p['party_ref']} → {p['issue_ref']} [{p['kind']}] «{p['statement']}»")
    return 0


def _position(data: dict, cid: str) -> dict:
    p = next((x for x in data.get("positions", []) if x.get("id") == cid), None)
    if p is None:
        raise ModelError(f"позиция {cid} не найдена")
    return p


def _save_validated(path: Path, data: dict, p: dict) -> None:
    parties = load_parties(path)
    errs = validate_position(p, {i.get("id") for i in data["issues"]}, {x.get("id") for x in parties})
    if errs:
        raise ModelError("позиция не прошла валидацию:\n  " + "\n  ".join(errs))
    p["updated"] = dt.date.today().isoformat()
    save(path, data)


def cmd_add_support(args) -> int:
    path = Path(args.file)
    data = load(path)
    p = _position(data, args.id)
    anchor = model.evidence_anchor.make_anchor(args.source_doc, args.quote, args.quote_location, case_for_artifact(path))
    entry = {"source_doc": args.source_doc, "stance": args.stance, **anchor, "note": args.note or ""}
    p.setdefault("support", []).append(entry)
    if p.get("support_state") and effective_state({**p, "support_state": None}) in ("gap", "needs_evidence", "disputed"):
        p.pop("support_state")  # заявленное суждение больше не подходит — снимается, а не ломает файл
    _save_validated(path, data, p)
    mark = "" if model.evidence_anchor.is_verified(anchor) else f" — {anchor['check_detail']}"
    print(f"OK: {args.id} + {args.stance} [{anchor['quote_check']}]{mark}; состояние: {effective_state(p)}")
    return 0


def cmd_set_state(args) -> int:
    path = Path(args.file)
    data = load(path)
    p = _position(data, args.id)
    p["support_state"] = args.support_state
    _save_validated(path, data, p)
    print(f"OK: {args.id} support_state={args.support_state}")
    return 0


def cmd_mark_checked(args) -> int:
    path = Path(args.file)
    data = load(path)
    p = _position(data, args.id)
    p["lawyer_checked"] = not args.undo
    _save_validated(path, data, p)
    print(f"OK: {args.id} lawyer_checked={p['lawyer_checked']}")
    return 0


def _find(data: dict, item_id: str) -> tuple[dict | None, str | None]:
    for coll, typ in (("issues", "issue"), ("positions", "position")):
        for it in data.get(coll, []):
            if it.get("id") == item_id:
                return it, typ
    return None, None


# поля, доступные для update, по типу объекта
_UPDATE_FIELDS = {
    "issue": ("question", "status", "depth", "stance", "desired_position", "notes"),
    "position": ("party_ref", "issue_ref", "kind", "statement", "evidence", "stated_basis",
                 "source_doc", "source_fragment", "notes"),
}


def cmd_update(args) -> int:
    path = Path(args.file)
    data = load(path)
    item, typ = _find(data, args.id)
    if item is None:
        raise ModelError(f"объект {args.id} не найден в {path}")
    for field in _UPDATE_FIELDS[typ]:
        val = getattr(args, field, None)
        if val is not None:
            item[field] = list(val) if field == "evidence" else val
    if typ == "issue":
        errs = validate_issue(item)
    else:
        parties = load_parties(path)
        errs = validate_position(item, {i.get("id") for i in data["issues"]},
                                 {p.get("id") for p in parties})
    if errs:
        raise ModelError("после update объект не валиден:\n  " + "\n  ".join(errs))
    item["updated"] = dt.date.today().isoformat()
    save(path, data)
    print(f"OK: {args.id} обновлён")
    return 0


def cmd_validate(args) -> int:
    path = Path(args.file)
    data = load(path)
    errs = validate_all(data, load_parties(path))
    if errs:
        print(f"НЕВАЛИДНО ({len(errs)}):")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"OK: matter-positions валиден — вопросов {len(data['issues'])}, "
          f"позиций {len(data['positions'])}")
    return 0


def cmd_report(args) -> int:
    path = Path(args.file)
    render = render_chart if getattr(args, "chart", False) else render_report
    print(render(load(path), load_parties(path)))
    return 0


# ---------- selftest ----------

def selftest() -> int:
    import tempfile

    ok = 0
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td) / "Альфа"
        ff = str(folder / "matter-facts.yaml")
        f = str(folder / "matter-positions.yaml")
        facts.run(["init", "--file", ff, "--matter", "Альфа"])
        facts.run(["add-party", "--file", ff, "--name", "ООО «Альфа»", "--role", "our_side",
                   "--source-doc", "отзыв", "--source-fragment", "шапка"])
        facts.run(["add-party", "--file", ff, "--name", "ООО «Бета»", "--role", "opponent",
                   "--source-doc", "иск", "--source-fragment", "шапка"])

        run(["init", "--file", f, "--matter", "Альфа"])
        run(["add-issue", "--file", f, "--question", "Пропущен ли срок исковой давности?"])
        run(["add-position", "--file", f, "--party-ref", "P-002", "--issue-ref", "I-001",
             "--kind", "claim", "--statement", "Взыскать 105 000 руб. долга",
             "--source-doc", "иск", "--source-fragment", "просительная часть",
             "--evidence", "Иск_приложения/договор.pdf"])
        data = load(Path(f))
        parties = load_parties(Path(f))
        assert validate_all(data, parties) == [], validate_all(data, parties)
        ok += 1

        assert "unanswered" in {lead["type"] for lead in detect_leads(data, parties)}
        ok += 1

        try:
            run(["add-position", "--file", f, "--party-ref", "P-404", "--issue-ref", "I-001",
                 "--kind", "claim", "--statement", "x", "--source-doc", "d",
                 "--source-fragment", "p"])
            raise AssertionError("неизвестный party_ref должен падать")
        except ModelError:
            ok += 1

        run(["update", "--file", f, "--id", "I-001", "--status", "confirmed"])
        assert run(["validate", "--file", f]) == 0
        run(["report", "--file", f])
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

    p = sub.add_parser("add-issue")
    p.add_argument("--file", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--status", default="proposed", choices=ISSUE_STATUSES)
    p.add_argument("--depth", default="standard", choices=DEPTHS)
    p.add_argument("--stance", default="neutral", choices=STANCES)
    p.add_argument("--desired-position", dest="desired_position")
    p.add_argument("--notes")

    p = sub.add_parser("add-position")
    p.add_argument("--file", required=True)
    p.add_argument("--party-ref", dest="party_ref", required=True)
    p.add_argument("--issue-ref", dest="issue_ref", required=True)
    p.add_argument("--kind", required=True, choices=POSITION_KINDS)
    p.add_argument("--statement", required=True)
    p.add_argument("--source-doc", dest="source_doc", required=True)
    p.add_argument("--source-fragment", dest="source_fragment", required=True)
    p.add_argument("--evidence", action="append")
    p.add_argument("--stated-basis", dest="stated_basis")
    p.add_argument("--notes")

    p = sub.add_parser("update")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--question")
    p.add_argument("--status", choices=ISSUE_STATUSES)
    p.add_argument("--depth", choices=DEPTHS)
    p.add_argument("--stance", choices=STANCES)
    p.add_argument("--desired-position", dest="desired_position")
    p.add_argument("--party-ref", dest="party_ref")
    p.add_argument("--issue-ref", dest="issue_ref")
    p.add_argument("--kind", choices=POSITION_KINDS)
    p.add_argument("--statement")
    p.add_argument("--evidence", action="append")
    p.add_argument("--stated-basis", dest="stated_basis")
    p.add_argument("--source-doc", dest="source_doc")
    p.add_argument("--source-fragment", dest="source_fragment")
    p.add_argument("--notes")

    p = sub.add_parser("validate")
    p.add_argument("--file", required=True)

    p = sub.add_parser("report")
    p.add_argument("--file", required=True)
    p.add_argument("--chart", action="store_true",
                   help="карта «позиция → цитата → опровержение → состояние», пробелы первыми")

    p = sub.add_parser("add-support")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--source-doc", dest="source_doc", required=True)
    p.add_argument("--quote", required=True, help="дословная цитата из source_doc")
    p.add_argument("--quote-location", dest="quote_location", help="место цитаты: пункт, страница")
    p.add_argument("--stance", required=True, choices=SUPPORT_STANCES)
    p.add_argument("--note")

    p = sub.add_parser("set-state")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--support-state", dest="support_state", required=True, choices=DECLARABLE_STATES)

    p = sub.add_parser("mark-checked")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--undo", action="store_true")

    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {
        "init": cmd_init, "add-issue": cmd_add_issue, "add-position": cmd_add_position,
        "update": cmd_update, "validate": cmd_validate, "report": cmd_report,
        "add-support": cmd_add_support, "set-state": cmd_set_state, "mark-checked": cmd_mark_checked,
    }[args.cmd](args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except ModelError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
