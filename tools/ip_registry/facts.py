"""Факты из документов (ip_document_facts.v1): проверка цитат, внесение событиями, отчёт. Класс A.

Правила внесения — чистые функции в fact_rules.py; здесь ввод-вывод и порядок шагов.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

from tools.evidence_anchor import anchor

from . import fact_rules as rules
from .documents import check_doc_id, list_cards, load_card, save_card
from .fact_rules import (CREATE_TYPES, DATE_FIELDS, DOC_TYPES, FACT_STATUSES, HAS_CONTACTS, NOT_IN_QUOTE,
                         TYPE_NOT_CONFIRMED, VALUE_FIELDS)
from .journal import MANUAL_FIELDS, TERRITORY_PREFIX, _reverted_ids, make_event, new_mark_id, read_events, replay
from .normalize import RECORD_STATUS_LABELS, TERRITORY_STATUS_LABELS, CountryBook, number_key
from .publish import EVENTS, _free_name, publish

SCHEMA = "ip_document_facts.v1"
ACCEPTED = anchor.VERIFIED_CHECKS
REVERTED_REASON = "внесение отменено"
OTHER_REG_TYPE = "номер найден у знака другого вида регистрации"
OFFICE_UNKNOWN = "ведомство не распознано"
OFFICES = ("RU", "WIPO")

__all__ = ["SCHEMA", "DOC_TYPES", "CREATE_TYPES", "FACT_STATUSES", "VALUE_FIELDS", "DATE_FIELDS", "load_facts",
           "apply_facts", "set_field", "revert_event", "dismiss"]


# ---------- схема ----------

def _date(value, where: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: ожидается дата ГГГГ-ММ-ДД, получено {value!r}") from None


def _check_value(field: str, item, where: str) -> None:
    if not isinstance(item, dict) or set(item) != {"value", "quote"}:
        raise ValueError(f"{where}.{field}: ожидается объект {{value, quote}}")
    if not isinstance(item["quote"], str) or not item["quote"].strip():
        raise ValueError(f"{where}.{field}: нет цитаты")
    value = item["value"]
    if field == "nice_classes":
        if not isinstance(value, list) or not value or not all(type(c) is int and 1 <= c <= 45 for c in value):
            raise ValueError(f"{where}.nice_classes: ожидается список номеров классов 1–45")
    elif field in DATE_FIELDS:
        _date(value, f"{where}.{field}")
    elif field == "status":
        if value not in FACT_STATUSES:
            raise ValueError(f"{where}.status: недопустимый статус {value!r}")
    elif not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{field}: ожидается непустая строка")


def _check_territory(item, where: str) -> None:
    if not isinstance(item, dict) or not {"code", "status", "quote"} <= set(item) or \
            not set(item) <= {"code", "status", "since", "quote"}:
        raise ValueError(f"{where}: ожидается {{code, status, since, quote}}")
    if not isinstance(item["code"], str) or len(item["code"]) != 2 or not item["code"].isalpha():
        raise ValueError(f"{where}.code: ожидается двухбуквенный код страны")
    if item["status"] not in TERRITORY_STATUS_LABELS:
        raise ValueError(f"{where}.status: недопустимый статус страны {item['status']!r}")
    if not isinstance(item["quote"], str) or not item["quote"].strip():
        raise ValueError(f"{where}: нет цитаты")
    _date(item.get("since"), f"{where}.since", nullable=True)


def load_facts(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"файл фактов не читается: {error}") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(f"факты: ожидается схема {SCHEMA}")
    if data.get("doc_id") is not None:
        check_doc_id(data["doc_id"])
    if not isinstance(data.get("document"), str) or not data["document"]:
        raise ValueError("факты: не указан документ (document)")
    if data.get("doc_type") not in DOC_TYPES:
        raise ValueError(f"факты: недопустимый doc_type {data.get('doc_type')!r}")
    _date(data.get("doc_date"), "факты: doc_date", nullable=True)
    for key in ("doc_type_quote", "doc_date_quote", "notes"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError(f"факты: {key} должен быть строкой или null")
    if data.get("office") is not None and not isinstance(data["office"], str):
        raise ValueError("факты: office должен быть строкой")
    if not isinstance(data.get("marks"), list):
        raise ValueError("факты: marks должен быть списком")
    for index, mark in enumerate(data["marks"], 1):
        where = f"факты: знак {index}"
        if not isinstance(mark, dict):
            raise ValueError(f"{where}: ожидается объект")
        unknown = set(mark) - set(VALUE_FIELDS) - {"territories"}
        if unknown:
            raise ValueError(f"{where}: неизвестные поля {sorted(unknown)}")
        for field in VALUE_FIELDS:
            if field in mark:
                _check_value(field, mark[field], where)
        if not isinstance(mark.get("territories", []), list):
            raise ValueError(f"{where}.territories: ожидается список")
        for t_index, territory in enumerate(mark.get("territories", []), 1):
            _check_territory(territory, f"{where}.territories[{t_index}]")
    return data


# ---------- карточка документа ----------

def _load_card(root: Path, doc_id: str) -> dict:
    check_doc_id(doc_id)
    try:
        card = load_card(root, doc_id)
    except (OSError, ValueError):
        raise ValueError(f"карточка документа {doc_id} не найдена или не читается") from None
    if not isinstance(card, dict) or not card.get("doc_id"):
        raise ValueError(f"карточка документа {doc_id} повреждена")
    return card


def _find_card(root: Path, facts: dict) -> dict:
    if facts.get("doc_id"):
        card = _load_card(root, facts["doc_id"])
        if card.get("document") != facts["document"]:
            raise ValueError(f"факты относятся к документу {facts['document']}, карточка — к {card.get('document')}")
        return card
    cards = [c for c in list_cards(root) if c.get("document") == facts["document"]]
    if len(cards) != 1:
        raise ValueError(f"карточка документа {facts['document']} не найдена" if not cards
                         else f"несколько карточек документа {facts['document']}")
    return cards[0]


def _rel(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


# ---------- проверка цитат ----------

def _office(office, book: CountryBook, dropped: list) -> str | None:
    """Ведомство: RU, WIPO или двухбуквенный ISO-код из справочника стран; иначе null и строка в «Отброшено»."""
    if office is None:
        return None
    if office in OFFICES or (len(office) == 2 and office.isascii() and office.isupper() and book.by_iso(office)):
        return office
    dropped.append({"field": "office", "reason": OFFICE_UNKNOWN})
    return None


def _confirm_document(text_path: Path, facts: dict, dropped: list, book: CountryBook) -> dict:
    """Сведения о документе после проверки цитат: тип подтверждён заголовком, дата — цитатой.

    Неподтверждённая дата не используется (None); заметка с контактами отбрасывается.
    """
    doc_type, type_quote = facts["doc_type"], facts.get("doc_type_quote")
    type_ok = False
    if type_quote and rules.has_contacts(type_quote):
        dropped.append({"field": "doc_type", "reason": HAS_CONTACTS})
    elif type_quote:
        check = anchor.check(text_path, type_quote)["quote_check"]
        if check not in ACCEPTED:
            dropped.append({"field": "doc_type", "reason": f"цитата не подтверждена ({check})"})
        elif not rules.doc_type_in_quote(doc_type, type_quote):
            dropped.append({"field": "doc_type", "reason": NOT_IN_QUOTE})
        else:
            type_ok = True
    doc_date, date_quote = facts.get("doc_date"), facts.get("doc_date_quote")
    date_ok = False
    if doc_date:
        if not date_quote:
            dropped.append({"field": "doc_date", "reason": "нет цитаты"})
        elif rules.has_contacts(date_quote):
            dropped.append({"field": "doc_date", "reason": HAS_CONTACTS})
        else:
            check = anchor.check(text_path, date_quote)["quote_check"]
            if check not in ACCEPTED:
                dropped.append({"field": "doc_date", "reason": f"цитата не подтверждена ({check})"})
            elif not rules.date_in_quote(doc_date, date_quote):
                dropped.append({"field": "doc_date", "reason": NOT_IN_QUOTE})
            else:
                date_ok = True
    if facts.get("notes") and rules.has_contacts(facts["notes"]):
        dropped.append({"field": "notes", "reason": HAS_CONTACTS})
    return {"doc_type": doc_type, "doc_type_confirmed": type_ok, "doc_date": doc_date if date_ok else None,
            "office": _office(facts.get("office"), book, dropped)}


def _confirm(text_path: Path, fact: dict, label: str, dropped: list, book: CountryBook) -> tuple[dict, dict]:
    """Подтверждённые значения {поле: (значение, якорь)} и страны {код: (факт, якорь)}."""
    values: dict = {}
    for field in VALUE_FIELDS:
        if field not in fact:
            continue
        value, quote = fact[field]["value"], fact[field]["quote"]
        if rules.has_contacts(quote):
            dropped.append({"field": f"{label}: {field}", "reason": HAS_CONTACTS})
            continue
        check = anchor.check(text_path, quote)["quote_check"]
        if check not in ACCEPTED:
            dropped.append({"field": f"{label}: {field}", "reason": f"цитата не подтверждена ({check})"})
        elif not rules.value_in_quote(field, value, quote):
            dropped.append({"field": f"{label}: {field}", "reason": NOT_IN_QUOTE})
        else:
            values[field] = (value, {"field": field, "quote": quote, "quote_check": check})
    territories: dict = {}
    for item in fact.get("territories", []):
        code = item["code"].upper()
        where = f"{label}: {TERRITORY_PREFIX}{code}"
        if rules.has_contacts(item["quote"]):
            dropped.append({"field": where, "reason": HAS_CONTACTS})
            continue
        check = anchor.check(text_path, item["quote"])["quote_check"]
        if check not in ACCEPTED:
            dropped.append({"field": where, "reason": f"цитата не подтверждена ({check})"})
        elif not rules.territory_in_quote(code, item["status"], item["quote"], book):
            dropped.append({"field": where, "reason": NOT_IN_QUOTE})
        else:
            territories[code] = (item, {"field": TERRITORY_PREFIX + code, "quote": item["quote"],
                                        "quote_check": check})
    return values, territories


def _fact_label(fact: dict) -> str:
    for field in ("registration_no", "application_no", "mark_text"):
        if field in fact:
            return f"№ {fact[field]['value']}" if field != "mark_text" else fact[field]["value"]
    return "знак без номера"


def _mark_label(mark: dict) -> str:
    number = mark.get("registration_no") or mark.get("application_no") or "без номера"
    return f"{mark.get('mark_text') or '[изобразительный знак]'} (№ {number})"


def _reg_type(doc_type: str) -> str | None:
    if doc_type.startswith("wipo_"):
        return "madrid"
    if doc_type.startswith("ru_"):
        return "national"
    return None


def _lookup(marks: list[dict], values: dict, reg_type: str | None) -> tuple[list[dict], bool]:
    """Знаки с номером документа и того же вида регистрации; второй элемент — номер есть только у знака другого вида."""
    other = False
    for field in ("registration_no", "application_no"):
        if field in values:
            key = number_key(values[field][0])
            found = [m for m in marks if m.get(field) and number_key(m[field]) == key]
            same = [m for m in found if reg_type is None or m.get("reg_type") == reg_type]
            if same:
                return same, False
            other = other or bool(found)
    return [], other


# ---------- внесение ----------

def _source(card: dict, doc: dict) -> dict:
    """doc — сведения о документе после проверки цитат (_confirm_document): дата только подтверждённая."""
    return {"file": card["document"], "sha256": card.get("sha256"), "doc_id": card["doc_id"],
            "doc_type": doc["doc_type"], "doc_date": doc.get("doc_date"), "office": doc.get("office")}


def _manual_source(today: dt.date) -> dict:
    return {"file": None, "sha256": None, "doc_type": "manual", "doc_date": today.isoformat(), "office": None}


def _events_path(root: Path) -> Path:
    return root / "data" / EVENTS


def apply_facts(root: Path, facts_path: Path, *, today: dt.date, force_fields=(), comment: str | None = None) -> dict:
    root = Path(root)
    facts = load_facts(facts_path)
    card = _find_card(root, facts)
    if card.get("status") == "applied":
        raise ValueError("документ уже внесён")
    if card.get("status") == "dismissed":
        raise ValueError("документ отклонён юристом — внесение не выполняется")
    if not card.get("text"):
        raise ValueError(f"у карточки {card['doc_id']} нет текста документа (text)")
    force_fields = tuple(force_fields)
    if force_fields and not (comment or "").strip():
        raise ValueError("для внесения вопреки правилу нужен комментарий юриста")
    events = read_events(_events_path(root))
    marks = replay(events)
    book = CountryBook.load()
    report = {"doc_id": card["doc_id"], "applied": [], "worsened": [], "created": [], "stale": [], "dropped": [],
              "decisions": []}
    text_path = root / card["text"]
    doc = _confirm_document(text_path, facts, report["dropped"], book)
    doc_drops = len(report["dropped"])  # отброшенные тип, дата, заметка сами по себе не делают документ спорным
    source = _source(card, doc)
    new_events: list[dict] = []
    forceable: set[str] = set()
    confirmed_any = False
    if facts["doc_type"] == "unknown":
        report["decisions"].append({"mark": None, "fields": [], "reason": "тип документа не определён"})
    else:
        for fact in facts["marks"]:
            label = _fact_label(fact)
            values, territories = _confirm(text_path, fact, label, report["dropped"], book)
            confirmed_any = confirmed_any or bool(values or territories)
            if values or territories:
                forceable |= _apply_mark(marks, events, new_events, fact_ctx=(label, values, territories, fact),
                                         facts=doc, source=source, book=book, force_fields=force_fields,
                                         comment=comment, today=today, report=report)
        if not confirmed_any:
            report["decisions"].append({"mark": None, "fields": [],
                                        "reason": "нет ни одного значения, подтверждённого цитатой"})
    unknown = sorted(set(force_fields) - forceable)
    if unknown:
        raise ValueError(f"force_fields: поля {', '.join(unknown)} не меняются этим документом"
                         + (f"; допустимо: {', '.join(sorted(forceable))}" if forceable else ""))
    if not new_events and len(report["dropped"]) > doc_drops and not report["decisions"]:
        report["decisions"].append({"mark": None, "fields": [], "reason": "значения не подтверждены цитатой"})
    return _finish(root, card, doc, facts_path, events + new_events, new_events, report, today)


def _apply_mark(marks, events, new_events, *, fact_ctx, facts, source, book, force_fields, comment, today,
                report) -> set[str]:
    """Вносит один знак; возвращает имена полей, которые допустимо указать в force_fields."""
    label, values, territories, fact = fact_ctx
    found, other_kind = _lookup(marks, values, _reg_type(facts["doc_type"]))
    all_events = events + new_events
    if len(found) > 1:
        report["decisions"].append({"mark": label, "fields": [], "reason": "несколько знаков с этим номером"})
        return set()
    if other_kind:
        report["decisions"].append({"mark": label, "fields": [], "reason": OTHER_REG_TYPE})
        return set()
    if not found:
        number = "registration_no" in values or "application_no" in values
        if facts["doc_type"] in CREATE_TYPES and number and not facts["doc_type_confirmed"]:
            report["decisions"].append({"mark": label, "fields": [],
                                        "reason": f"знак не найден по номеру; новый знак не создан: {TYPE_NOT_CONFIRMED}"})
        elif facts["doc_type"] in CREATE_TYPES and number and (
                ("status" in fact and "status" not in values)
                or (fact.get("territories") and not territories)):
            report["decisions"].append({"mark": label, "fields": [],
                                        "reason": "знак не найден по номеру; новый знак не создан: "
                                                  "статус или территория не подтверждены цитатой"})
        elif facts["doc_type"] in CREATE_TYPES and number:
            mark_id = new_mark_id({m["mark_id"] for m in marks})
            mark = rules.new_mark(mark_id, facts, values, territories, book)
            derived = rules.derived_defaults(facts, values, territories)
            anchors = ([a for _v, a in values.values()] + [a for _i, a in territories.values()]
                       + rules.derived_anchors(derived))
            event = make_event(events=all_events, today=today, kind="document", mark_id=mark_id, op="create",
                               source=source, mark=mark, anchors=anchors)
            new_events.append(event)
            marks.append({**mark, "mark_id": mark_id, "provenance": {}})
            report["created"].append({"mark_id": mark_id, "label": _mark_label(mark), "derived": derived})
        else:
            report["decisions"].append({"mark": label, "fields": [], "reason": "знак не найден по номеру"})
        return set()
    mark = found[0]
    cands = rules.candidates(mark, values, territories, book)
    decision = rules.decide(mark, cands, facts, force_fields, _mark_label(mark))
    report["stale"].extend(decision["stale"])
    if decision["conflicts"]:
        report["decisions"].append({"mark": _mark_label(mark), "fields": sorted(decision["conflicts"]),
                                    "reason": "; ".join(decision["conflicts"].values())})
        return rules.force_names(cands)
    if not decision["changes"]:
        return rules.force_names(cands)
    event = make_event(events=all_events, today=today, kind="document", mark_id=mark["mark_id"], op="update",
                       source=source, changes=decision["changes"], anchors=decision["anchors"],
                       forced=decision["forced"], comment=comment if decision["forced"] else None)
    new_events.append(event)
    quotes = {a["field"]: a["quote"] for a in decision["anchors"]}
    report["applied"].append({"mark_id": mark["mark_id"], "label": _mark_label(mark),
                              "changes": decision["changes"], "quotes": quotes})
    report["worsened"].extend(rules.worsened(mark, decision["changes"], source["file"], quotes))
    return rules.force_names(cands)


def _finish(root, card, facts, facts_path, events, new_events, report, today) -> dict:
    """Карточка и публикация — вместе; файл отчёта пишется только после успешной публикации."""
    stem = Path(card["document"]).stem
    folder = root / "changes"
    report_path = _free_name(folder, f"{today.isoformat()}-документ-{stem}.md")
    report["changes_path"] = _rel(root, report_path)
    text = rules.render_report(stem, card, facts, report)
    old_card = copy.deepcopy(card)
    card.update({"status": "needs_decision" if report["decisions"] else "applied",
                 "reason": "; ".join(d["reason"] + (f" ({d['mark']})" if d["mark"] else "")
                                     for d in report["decisions"]) or None,
                 "facts": _rel(root, Path(facts_path)),
                 "applied_events": card.get("applied_events", []) + [e["event_id"] for e in new_events],
                 "report": report["changes_path"]})
    _save_and_publish(root, [(card, old_card)], events, today)
    folder.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return report


def _save_and_publish(root: Path, cards: list[tuple[dict, dict]], events: list[dict], today: dt.date) -> None:
    """Сохраняет карточки (их видит снимок) и публикует; при сбое публикации возвращает прежние карточки."""
    for new, _old in cards:
        save_card(root, new)
    try:
        publish(root, events, today=today)
    except BaseException:
        for _new, old in cards:
            save_card(root, old)
        raise


# ---------- ручные правки, отмена, отклонение ----------

def _manual_value(field: str, value):
    if field == "nice_classes":
        if not isinstance(value, list) or not all(type(c) is int and 1 <= c <= 45 for c in value):
            raise ValueError("nice_classes: ожидается список номеров классов 1–45")
    elif field in ("priority_date", "expiry_date", "next_payment_date") and value is not None:
        _date(value, field)
    elif field == "status" and value not in RECORD_STATUS_LABELS:
        raise ValueError(f"недопустимый статус {value!r}")
    return value


def set_field(root: Path, *, mark: str, field: str, value, comment: str, today: dt.date) -> dict:
    root = Path(root)
    if field not in MANUAL_FIELDS:
        raise ValueError(f"поле не правится вручную: {field}; допустимо: {', '.join(MANUAL_FIELDS)}")
    if not (comment or "").strip():
        raise ValueError("для ручной правки нужен комментарий")
    events = read_events(_events_path(root))
    marks = replay(events)
    key = number_key(mark)
    found = [m for m in marks if m["mark_id"] == mark] or \
        [m for m in marks if key and key in {number_key(m.get(f)) for f in ("registration_no", "application_no")}]
    if len(found) != 1:
        raise ValueError(f"знак {mark} не найден" if not found else f"номеру {mark} соответствует несколько знаков")
    target = found[0]
    value = _manual_value(field, value)
    if target.get(field) == value:
        raise ValueError(f"значение {field} уже равно {value!r}")
    event = make_event(events=events, today=today, kind="manual", mark_id=target["mark_id"], op="update",
                       source=_manual_source(today), changes={field: [target.get(field), value]}, comment=comment)
    publish(root, events + [event], today=today)
    return event


def revert_event(root: Path, event_id: str, *, comment: str, today: dt.date) -> dict:
    root = Path(root)
    if not (comment or "").strip():
        raise ValueError("для отмены нужен комментарий")
    events = read_events(_events_path(root))
    target = next((e for e in events if e["event_id"] == event_id), None)
    if target is None:
        raise ValueError(f"событие {event_id} не найдено")
    if target["kind"] == "seed":
        raise ValueError("первичную загрузку из Excel отменять нельзя")
    if any(e["kind"] == "revert" and e.get("reverts") == event_id for e in events):
        raise ValueError(f"событие {event_id} уже отменено")
    event = make_event(events=events, today=today, kind="revert", mark_id=target["mark_id"], op="update",
                       source=_manual_source(today), reverts=event_id, comment=comment)
    all_events = events + [event]
    reverted = _reverted_ids(all_events)
    reopened = []
    for card in list_cards(root):
        applied = card.get("applied_events") or []
        if event_id in applied and all(e in reverted for e in applied) and card.get("status") != "awaiting_facts":
            old = copy.deepcopy(card)
            card.update({"status": "awaiting_facts", "reason": REVERTED_REASON})
            reopened.append((card, old))
    _save_and_publish(root, reopened, all_events, today)
    return event


def dismiss(root: Path, doc_id: str, *, comment: str, today: dt.date) -> dict:
    root = Path(root)
    if not (comment or "").strip():
        raise ValueError("для отклонения документа нужен комментарий")
    card = _load_card(root, doc_id)
    if card.get("status") == "applied":
        raise ValueError("документ уже внесён — для отмены используйте revert")
    old = copy.deepcopy(card)
    card.update({"status": "dismissed", "reason": comment, "dismissed": today.isoformat()})
    _save_and_publish(root, [(card, old)], read_events(_events_path(root)), today)
    return card
