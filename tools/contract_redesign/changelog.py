#!/usr/bin/env python3
"""Contract redesign change log: validator and renderer for skills/contract-redesign.

Модель (LLM) разбирает legacy-договор или цепочку «договор + ДС» и пишет
YAML-журнал. Скрипт не толкует договор и не решает, существенно ли изменение;
он проверяет, что журнал внутренне непротиворечив и что ни одно изменение
существа не прошло молча мимо юриста:

legacy_redesign (entries):
- уровень C (изменение существа) ⇒ substantive: true;
- удаление содержательного (rd_category A) или остаточного (D) пункта ⇒ substantive: true;
- уровень B (переформулирование) ⇒ equivalence_check обязателен; failed ⇒ substantive: true;
- substantive: true или conflict: true ⇒ lawyer_decision ≠ not_needed;
- action delete ⇒ target пуст; иные действия ⇒ target обязателен;
- merge (дубль, категория B) с conflict: true — это не дубль, а противоречие.

restatement (clauses):
- статус amended / added / excluded ⇒ history из ≥1 записи со ссылкой на source роли amendment;
- ДС без effective_from ⇒ предупреждение [ПРОВЕРИТЬ СРОК];
- ДС, на которое не ссылается ни один пункт ⇒ предупреждение (ДС могло быть не учтено);
- история пункта не по возрастанию effective_from ⇒ предупреждение;
- conflict: true ⇒ lawyer_decision ≠ not_needed.

Схема — tools/contract_redesign/schema.md.

Usage:
    python tools/contract_redesign/changelog.py validate --file PATH
    python tools/contract_redesign/changelog.py report   --file PATH
    python tools/contract_redesign/changelog.py docx     --file PATH --out PATH.docx
    python tools/contract_redesign/changelog.py selftest
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1
MODES = ("legacy_redesign", "restatement")
SOURCE_ROLES = ("legacy_template", "prior_contract", "counterparty_draft", "main_contract", "amendment", "other")
RD_CATEGORIES = ("A", "B", "C", "D", None)
LEVELS = ("A", "B", "C")
ACTIONS = ("keep", "relocate", "merge", "rewrite", "delete")
EQUIVALENCE = ("passed", "failed", "n/a")
DECISIONS = ("not_needed", "required", "approved", "rejected")
CLAUSE_STATUSES = ("original", "amended", "added", "excluded")

ACTION_RU = {"keep": "без изменений", "relocate": "перенос", "merge": "объединение",
             "rewrite": "новая редакция", "delete": "удаление"}
STATUS_RU = {"original": "исходная редакция", "amended": "изменён", "added": "добавлен", "excluded": "исключён"}
DECISION_RU = {"not_needed": "не требуется", "required": "ТРЕБУЕТСЯ", "approved": "одобрено", "rejected": "отклонено"}


class ChangelogError(Exception):
    pass


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ChangelogError("корень YAML должен быть словарём")
    return data


def _req(obj: dict, key: str, where: str, errors: list[str]):
    if obj.get(key) in (None, "", []):
        errors.append(f"{where}: не заполнено поле {key}")
        return False
    return True


def validate(data: dict) -> tuple[list[str], list[str]]:
    """Возвращает (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version должен быть {SCHEMA_VERSION}")
    mode = data.get("mode")
    if mode not in MODES:
        errors.append(f"mode должен быть одним из {MODES}")
        return errors, warnings
    _req(data, "title", "документ", errors)

    sources = data.get("sources") or []
    if not sources:
        errors.append("sources: нужен хотя бы один исходный документ")
    src_by_id: dict[str, dict] = {}
    for i, s in enumerate(sources):
        where = f"sources[{i}]"
        if _req(s, "id", where, errors):
            if s["id"] in src_by_id:
                errors.append(f"{where}: повторный id {s['id']}")
            src_by_id[s["id"]] = s
        _req(s, "title", where, errors)
        if s.get("role") not in SOURCE_ROLES:
            errors.append(f"{where}: role должен быть одним из {SOURCE_ROLES}")

    if mode == "legacy_redesign":
        _validate_entries(data.get("entries") or [], src_by_id, errors, warnings)
    else:
        _validate_clauses(data.get("clauses") or [], src_by_id, errors, warnings)
    return errors, warnings


def _validate_entries(entries, src_by_id, errors, warnings):
    if not entries:
        errors.append("entries: журнал пуст")
    seen = set()
    for i, e in enumerate(entries):
        where = f"entries[{i}] ({e.get('id', '?')})"
        if _req(e, "id", where, errors):
            if e["id"] in seen:
                errors.append(f"{where}: повторный id")
            seen.add(e["id"])
        if e.get("source") not in src_by_id:
            errors.append(f"{where}: source не найден среди sources")
        for k in ("location", "legal_function", "reason"):
            _req(e, k, where, errors)
        rd = e.get("rd_category")
        level, action = e.get("level"), e.get("action")
        eq, decision = e.get("equivalence_check", "n/a"), e.get("lawyer_decision")
        substantive, conflict = e.get("substantive"), bool(e.get("conflict", False))
        if rd not in RD_CATEGORIES:
            errors.append(f"{where}: rd_category должен быть A/B/C/D или пусто")
        if level not in LEVELS:
            errors.append(f"{where}: level должен быть A/B/C")
        if action not in ACTIONS:
            errors.append(f"{where}: action должен быть одним из {ACTIONS}")
        if eq not in EQUIVALENCE:
            errors.append(f"{where}: equivalence_check должен быть одним из {EQUIVALENCE}")
        if decision not in DECISIONS:
            errors.append(f"{where}: lawyer_decision должен быть одним из {DECISIONS}")
        if not isinstance(substantive, bool):
            errors.append(f"{where}: substantive должен быть true/false")
            continue

        if action == "delete" and e.get("target"):
            errors.append(f"{where}: у удаляемого пункта не должно быть target")
        if action in ACTIONS and action != "delete" and not e.get("target"):
            errors.append(f"{where}: для действия {action} нужен target (новое место)")
        if level == "C" and not substantive:
            errors.append(f"{where}: уровень C — изменение существа, substantive должен быть true")
        if action == "delete" and rd in ("A", "D") and not substantive:
            errors.append(f"{where}: удаление пункта категории {rd} без переноса — изменение существа (substantive: true)")
        if level == "B" and eq == "n/a":
            errors.append(f"{where}: переформулирование (уровень B) требует equivalence_check passed/failed")
        if eq == "failed" and not substantive:
            errors.append(f"{where}: проверка эквивалентности не пройдена — это изменение существа (substantive: true)")
        if (substantive or conflict) and decision == "not_needed":
            why = "изменение существа" if substantive else "противоречие"
            errors.append(f"{where}: {why} без решения юриста (lawyer_decision ≠ not_needed)")
        if action == "merge" and rd == "B" and conflict:
            warnings.append(f"{where}: дубль с расхождением формулировок — это противоречие, не объединять молча")
        if rd == "C" and action != "delete":
            warnings.append(f"{where}: общее положение без регулирования (C) сохранено — указать зачем")
        if decision == "rejected" and action != "keep":
            warnings.append(f"{where}: юрист отклонил изменение, а действие не keep — проверить итоговый текст")


def _validate_clauses(clauses, src_by_id, errors, warnings):
    if not clauses:
        errors.append("clauses: консолидированная редакция пуста")
    amendments = {sid for sid, s in src_by_id.items() if s.get("role") == "amendment"}
    if not any(s.get("role") == "main_contract" for s in src_by_id.values()):
        errors.append("sources: для restatement нужен источник роли main_contract")
    for sid in sorted(amendments):
        if not src_by_id[sid].get("effective_from"):
            warnings.append(f"sources {sid}: нет effective_from — [ПРОВЕРИТЬ СРОК]")
    used: set[str] = set()
    seen = set()
    for i, c in enumerate(clauses):
        where = f"clauses[{i}] ({c.get('id', '?')})"
        if _req(c, "id", where, errors):
            if c["id"] in seen:
                errors.append(f"{where}: повторный id")
            seen.add(c["id"])
        _req(c, "location", where, errors)
        status, decision = c.get("status"), c.get("lawyer_decision", "not_needed")
        if status not in CLAUSE_STATUSES:
            errors.append(f"{where}: status должен быть одним из {CLAUSE_STATUSES}")
        if decision not in DECISIONS:
            errors.append(f"{where}: lawyer_decision должен быть одним из {DECISIONS}")
        history = c.get("history") or []
        for h in history:
            if h.get("source") not in src_by_id:
                errors.append(f"{where}: history ссылается на неизвестный source {h.get('source')}")
            else:
                used.add(h["source"])
        if status in ("amended", "added", "excluded"):
            if not any(h.get("source") in amendments for h in history):
                errors.append(f"{where}: статус {status} без ссылки на ДС в history")
        # YAML превращает 2024-06-01 в date — сравниваем в ISO-строках
        dates = [str(src_by_id[h["source"]].get("effective_from")) for h in history
                 if h.get("source") in amendments and src_by_id[h["source"]].get("effective_from")]
        if dates != sorted(dates):
            warnings.append(f"{where}: history не по возрастанию effective_from")
        if c.get("conflict") and decision == "not_needed":
            errors.append(f"{where}: конфликт между ДС без решения юриста")
    for sid in sorted(amendments - used):
        warnings.append(f"sources {sid}: ни один пункт не ссылается на это ДС — проверить, учтено ли оно")


# ---------- отчёты ----------

def summary(data: dict) -> dict:
    if data["mode"] == "legacy_redesign":
        es = data.get("entries") or []
        s = {a: sum(1 for e in es if e.get("action") == a) for a in ACTIONS}
        s["substantive"] = sum(1 for e in es if e.get("substantive"))
        s["pending"] = sum(1 for e in es if e.get("lawyer_decision") == "required")
        s["total"] = len(es)
        return s
    cs = data.get("clauses") or []
    s = {st: sum(1 for c in cs if c.get("status") == st) for st in CLAUSE_STATUSES}
    s["conflicts"] = sum(1 for c in cs if c.get("conflict"))
    s["pending"] = sum(1 for c in cs if c.get("lawyer_decision") == "required")
    s["total"] = len(cs)
    return s


def render_md(data: dict) -> str:
    errors, warnings = validate(data)
    src = {s["id"]: s for s in data.get("sources") or [] if s.get("id")}
    out = [f"# Журнал изменений: {data.get('title', '')}", ""]
    s = summary(data)
    if data["mode"] == "legacy_redesign":
        out.append(f"Пунктов: {s['total']} · сохранено {s['keep']} · перенесено {s['relocate']} · "
                   f"объединено {s['merge']} · переформулировано {s['rewrite']} · удалено {s['delete']} · "
                   f"**изменений существа {s['substantive']}** · ждут решения юриста {s['pending']}")
        pend = [e for e in data.get("entries") or [] if e.get("lawyer_decision") == "required"]
        if pend:
            out += ["", "## Требует решения юриста", ""]
            out += [f"- {e['id']} · {e.get('location')} → {e.get('target') or 'удаление'}: {e.get('reason')}" for e in pend]
        out += ["", "## Журнал", "", "| Было | Функция | Действие | Стало | Существенно | Причина |", "|---|---|---|---|---|---|"]
        for e in data.get("entries") or []:
            where = f"{src.get(e.get('source'), {}).get('title', e.get('source'))}, {e.get('location')}"
            out.append(f"| {where} | {e.get('legal_function')} | {ACTION_RU.get(e.get('action'), e.get('action'))} | "
                       f"{e.get('target') or '—'} | {'ДА' if e.get('substantive') else 'нет'} | {e.get('reason')} |")
    else:
        out.append(f"Пунктов: {s['total']} · изменено {s['amended']} · добавлено {s['added']} · исключено {s['excluded']} · "
                   f"конфликтов {s['conflicts']} · ждут решения юриста {s['pending']}")
        out += ["", "## История пунктов", "", "| Пункт | Статус | Источники | Решение юриста |", "|---|---|---|---|"]
        for c in data.get("clauses") or []:
            hist = "; ".join(f"{src.get(h.get('source'), {}).get('title', h.get('source'))} {h.get('location', '')}".strip()
                             for h in c.get("history") or []) or "—"
            out.append(f"| {c.get('location')} | {STATUS_RU.get(c.get('status'), c.get('status'))} | {hist} | "
                       f"{DECISION_RU.get(c.get('lawyer_decision', 'not_needed'))} |")
    if errors or warnings:
        out += ["", "## Проверка журнала", ""]
        out += [f"- ОШИБКА: {x}" for x in errors] + [f"- предупреждение: {x}" for x in warnings]
    return "\n".join(out) + "\n"


def render_docx(data: dict, out_path: str) -> str:
    errors, _ = validate(data)
    if errors:
        raise ChangelogError("журнал не прошёл проверку — сначала validate:\n" + "\n".join(errors))
    from tools.docx_style.profiles import NoteDoc

    src = {s["id"]: s for s in data.get("sources") or []}
    d = NoteDoc()
    kind = "переработки договора" if data["mode"] == "legacy_redesign" else "консолидированной редакции"
    d.title("ЖУРНАЛ ИЗМЕНЕНИЙ", f"{kind}: {data['title']}")
    d.heading("1. Источники")
    for s in data.get("sources") or []:
        extra = f", действует с {s['effective_from']}" if s.get("effective_from") else ""
        d.bullet(f"{s['id']} — {s['title']}{extra}")
    s = summary(data)
    d.heading("2. Итог")
    if data["mode"] == "legacy_redesign":
        d.para(f"Пунктов: {s['total']}; сохранено {s['keep']}, перенесено {s['relocate']}, объединено {s['merge']}, "
               f"переформулировано {s['rewrite']}, удалено {s['delete']}. **Изменений существа: {s['substantive']}**; "
               f"ждут решения юриста: {s['pending']}.")
        d.heading("3. Журнал")
        rows = []
        for e in data["entries"]:
            rows.append([f"{e['source']}, {e['location']}", e["legal_function"],
                         ACTION_RU[e["action"]], e.get("target") or "—",
                         "**ДА**" if e["substantive"] else "нет",
                         f"{e['reason']} (решение юриста: {DECISION_RU[e['lawyer_decision']]})"])
        d.table(["Было", "Функция", "Действие", "Стало", "Сущ.", "Причина"], rows,
                [2.2, 3.4, 2.4, 2.0, 1.3, 5.7], center_cols=(4,))
    else:
        d.para(f"Пунктов: {s['total']}; изменено {s['amended']}, добавлено {s['added']}, исключено {s['excluded']}; "
               f"конфликтов {s['conflicts']}; ждут решения юриста: {s['pending']}.")
        d.heading("3. История пунктов")
        rows = []
        for c in data["clauses"]:
            hist = "; ".join(f"{h['source']} {h.get('location', '')}".strip() for h in c.get("history") or []) or "—"
            rows.append([c["location"], STATUS_RU[c["status"]], hist,
                         DECISION_RU[c.get("lawyer_decision", "not_needed")], c.get("note", "")])
        d.table(["Пункт", "Статус", "Источники", "Решение юриста", "Комментарий"], rows,
                [2.2, 2.6, 4.2, 2.6, 5.4])
    d.footer()
    return d.save(out_path)


# ---------- selftest ----------

GOOD_REDESIGN = {
    "schema_version": 1, "mode": "legacy_redesign", "title": "Договор поставки (тест)",
    "sources": [{"id": "S1", "title": "Шаблон 2019", "role": "legacy_template"}],
    "entries": [
        {"id": "C-001", "source": "S1", "location": "п. 4.1.3", "legal_function": "передача документов о качестве",
         "rd_category": "A", "level": "A", "action": "relocate", "target": "п. 4.2", "substantive": False,
         "equivalence_check": "n/a", "reason": "процесс «Документы на товар»", "lawyer_decision": "not_needed"},
        {"id": "C-002", "source": "S1", "location": "п. 4.1.1", "legal_function": "общее обязательство исполнять договор",
         "rd_category": "C", "level": "A", "action": "delete", "substantive": False,
         "equivalence_check": "n/a", "reason": "не создаёт регулирования", "lawyer_decision": "not_needed"},
        {"id": "C-003", "source": "S1", "location": "п. 7.2", "legal_function": "срок оплаты",
         "level": "B", "action": "rewrite", "target": "п. 7.2", "substantive": False,
         "equivalence_check": "passed", "reason": "сокращение канцелярита", "lawyer_decision": "not_needed"},
        {"id": "C-004", "source": "S1", "location": "п. 9.4", "legal_function": "ограничение ответственности",
         "level": "C", "action": "rewrite", "target": "п. 10.3", "substantive": True,
         "equivalence_check": "failed", "reason": "исключены косвенные убытки", "lawyer_decision": "required"},
    ],
}

GOOD_RESTATEMENT = {
    "schema_version": 1, "mode": "restatement", "title": "Договор услуг (тест)",
    "sources": [
        {"id": "S0", "title": "Договор", "role": "main_contract", "date": "2024-01-23"},
        {"id": "S1", "title": "ДС № 1", "role": "amendment", "effective_from": "2024-06-01"},
        {"id": "S2", "title": "ДС № 2", "role": "amendment", "effective_from": "2025-02-01"},
    ],
    "clauses": [
        {"id": "R-001", "location": "п. 3.1", "status": "original", "history": [{"source": "S0", "location": "п. 3.1"}]},
        {"id": "R-002", "location": "п. 3.2", "status": "amended",
         "history": [{"source": "S0", "location": "п. 3.2"}, {"source": "S1", "location": "п. 1"}, {"source": "S2", "location": "п. 2"}],
         "conflict": True, "lawyer_decision": "required", "note": "ДС № 2 меняет срок иначе, чем ДС № 1"},
        {"id": "R-003", "location": "п. 3.2.2", "status": "added", "history": [{"source": "S2", "location": "п. 1"}]},
    ],
}


def selftest() -> int:
    import copy
    ok = 0

    def expect(data, needle, kind="error"):
        nonlocal ok
        errors, warnings = validate(data)
        pool = errors if kind == "error" else warnings
        if not any(needle in x for x in pool):
            raise AssertionError(f"ожидалось {kind} «{needle}», получено: {errors} / {warnings}")
        ok += 1

    for good in (GOOD_REDESIGN, GOOD_RESTATEMENT):
        errors, warnings = validate(good)
        assert not errors and not warnings, (errors, warnings)
        ok += 1

    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][3]["substantive"] = False
    expect(bad, "уровень C")
    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][0].update(action="delete", target=None)
    expect(bad, "категории A без переноса")
    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][3]["lawyer_decision"] = "not_needed"
    expect(bad, "изменение существа без решения юриста")
    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][2]["equivalence_check"] = "n/a"
    expect(bad, "требует equivalence_check")
    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][2]["equivalence_check"] = "failed"
    expect(bad, "проверка эквивалентности не пройдена")
    bad = copy.deepcopy(GOOD_REDESIGN)
    bad["entries"][0]["target"] = None
    expect(bad, "нужен target")

    bad = copy.deepcopy(GOOD_RESTATEMENT)
    bad["clauses"][2]["history"] = []
    expect(bad, "без ссылки на ДС")
    bad = copy.deepcopy(GOOD_RESTATEMENT)
    bad["clauses"][1]["lawyer_decision"] = "not_needed"
    expect(bad, "конфликт между ДС без решения юриста")
    bad = copy.deepcopy(GOOD_RESTATEMENT)
    bad["sources"].append({"id": "S3", "title": "ДС № 3", "role": "amendment", "effective_from": "2025-09-01"})
    expect(bad, "ни один пункт не ссылается", kind="warning")
    bad = copy.deepcopy(GOOD_RESTATEMENT)
    del bad["sources"][1]["effective_from"]
    expect(bad, "[ПРОВЕРИТЬ СРОК]", kind="warning")

    bad = copy.deepcopy(GOOD_RESTATEMENT)
    bad["clauses"][1]["history"] = [bad["clauses"][1]["history"][i] for i in (0, 2, 1)]
    expect(bad, "не по возрастанию", kind="warning")

    tmp = tempfile.mkdtemp(prefix="changelog_")
    # round-trip через YAML-файл: даты становятся datetime.date
    yml = os.path.join(tmp, "restatement.yaml")
    with open(yml, "w", encoding="utf-8") as f:
        yaml.safe_dump(GOOD_RESTATEMENT, f, allow_unicode=True)
    raw = open(yml, encoding="utf-8").read().replace("'2024-06-01'", "2024-06-01").replace("'2025-02-01'", "2025-02-01")
    open(yml, "w", encoding="utf-8").write(raw)
    loaded = load(yml)
    assert type(loaded["sources"][1]["effective_from"]).__name__ == "date", "даты не распарсились как date"
    errors, warnings = validate(loaded)
    assert not errors and not warnings, ("round-trip YAML", errors, warnings)
    ok += 1
    for name, good in (("redesign", GOOD_REDESIGN), ("restatement", GOOD_RESTATEMENT)):
        assert "Журнал изменений" in render_md(good)
        render_docx(good, os.path.join(tmp, f"{name}.docx"))
        ok += 1
    try:
        bad = copy.deepcopy(GOOD_REDESIGN)
        bad["entries"][3]["substantive"] = False
        render_docx(bad, os.path.join(tmp, "bad.docx"))
        raise AssertionError("docx собран из журнала с ошибками")
    except ChangelogError:
        ok += 1
    print(f"SELFTEST OK: {ok} проверок пройдено ({tmp})")
    return 0


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "report"):
        sub.add_parser(name).add_argument("--file", required=True)
    p = sub.add_parser("docx")
    p.add_argument("--file", required=True)
    p.add_argument("--out", required=True)
    sub.add_parser("selftest")
    args = ap.parse_args()
    try:
        if args.cmd == "selftest":
            return selftest()
        data = load(args.file)
        if args.cmd == "validate":
            errors, warnings = validate(data)
            for x in errors:
                print(f"ОШИБКА: {x}")
            for x in warnings:
                print(f"предупреждение: {x}")
            print(f"Итог: ошибок {len(errors)}, предупреждений {len(warnings)}")
            return 1 if errors else 0
        if args.cmd == "report":
            print(render_md(data))
            return 0
        print(render_docx(data, args.out))
        return 0
    except ChangelogError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
