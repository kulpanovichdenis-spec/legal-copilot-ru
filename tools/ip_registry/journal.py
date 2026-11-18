"""Журнал изменений реестра ТЗ (ip_event.v1): только дописывается; снимок = replay."""
from __future__ import annotations

import copy
import datetime as dt
import json
import secrets
from pathlib import Path

from .normalize import number_key

SCHEMA = "ip_event.v1"
KINDS = ("seed", "document", "verification", "reconcile", "revert", "manual")
UPDATABLE = ("registration_no", "application_no", "mark_text", "product", "nice_classes", "priority_date",
             "expiry_date", "next_payment_date", "status", "verification")
TERRITORY_PREFIX = "territories."
DERIVED = "derived_from_doc_type"  # якорь поля нового знака, выведенного из типа документа, а не из цитаты
MANUAL_FIELDS = tuple(name for name in UPDATABLE if name != "verification")  # verification — только событием сверки


def new_mark_id(existing: set[str]) -> str:
    while True:
        candidate = "tm-" + secrets.token_hex(4)
        if candidate not in existing:
            return candidate


def next_event_id(events: list[dict], today: dt.date) -> str:
    return f"ev-{today:%Y%m%d}-{len(events) + 1:04d}"


def make_event(*, events: list[dict], today: dt.date, kind: str, mark_id: str, op: str, source: dict,
               changes: dict | None = None, mark: dict | None = None, anchors: list | None = None,
               reverts: str | None = None, comment: str | None = None, forced: list | None = None,
               now: dt.datetime | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид события: {kind}")
    if op not in ("create", "update"):
        raise ValueError(f"неизвестная операция: {op}")
    for name in changes or {}:
        if name not in UPDATABLE and not name.startswith(TERRITORY_PREFIX):
            raise ValueError(f"поле {name} нельзя менять событием")
    if op == "create":
        if not isinstance(mark, dict):
            raise ValueError("для создания записи нужна карточка знака (mark)")
        if changes:
            raise ValueError("создание записи не принимает изменения (changes)")
    elif kind == "revert":
        if not reverts:
            raise ValueError("для отмены нужно указать отменяемое событие (reverts)")
    elif not changes:
        raise ValueError("для обновления нужны непустые изменения (changes)")
    for name, pair in (changes or {}).items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"изменение {name} должно быть парой [было, стало]")
    moment = now or dt.datetime.now().astimezone()
    return {
        "schema": SCHEMA,
        "event_id": next_event_id(events, today),
        "at": moment.isoformat(timespec="seconds"),
        "kind": kind,
        "source": source,
        "mark_id": mark_id,
        "op": op,
        "mark": mark,
        "changes": changes or {},
        "anchors": anchors or [],
        "reverts": reverts,
        "comment": comment,
        "forced": forced or [],
    }


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dump_events(events: list[dict]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _provenance(event: dict) -> dict:
    source = event.get("source") or {}
    return {"event_id": event["event_id"], "kind": event["kind"], "file": source.get("file"),
            "doc_date": source.get("doc_date"), "doc_type": source.get("doc_type")}


def _set_territory(mark: dict, code: str, value: dict | None) -> None:
    """Одна запись на страну: на месте первой, прочие записи с этим кодом убираются."""
    territories = mark.setdefault("territories", [])
    first = next((i for i, t in enumerate(territories) if t["code"] == code), None)
    old_name = territories[first].get("name") if first is not None else None
    rest = [t for t in territories if t["code"] != code]
    if value is None:
        mark["territories"] = rest
        return
    entry = {"basis": None, "note": None, **value, "code": code}
    if "name" not in value and old_name is not None:
        entry["name"] = old_name
    rest.insert(len(rest) if first is None else sum(1 for t in territories[:first] if t["code"] != code), entry)
    mark["territories"] = rest


def _reverted_ids(events: list[dict]) -> set[str]:
    """Отмены разбираются от новых к старым: отмена действует, только если её саму не отменила действующая отмена."""
    reverted: set[str] = set()
    for event in reversed(events):
        if event["kind"] == "revert" and event.get("reverts") and event["event_id"] not in reverted:
            reverted.add(event["reverts"])
    return reverted


def validate_events(events: list[dict]) -> list[str]:
    problems: list[str] = []
    by_id: dict[str, dict] = {}
    created: set[str] = set()
    for event in events:
        event_id = event.get("event_id")
        if event.get("schema") != SCHEMA:
            problems.append(f"{event_id}: неверная схема {event.get('schema')}")
        if event_id in by_id:
            problems.append(f"{event_id}: повтор event_id")
        known = by_id.get(event_id) is None
        if event.get("kind") == "revert":
            target = event.get("reverts")
            if target not in {e.get("event_id") for e in events}:
                problems.append(f"{event_id}: отмена ссылается на отсутствующее событие {target}")
            else:
                target_event = next(e for e in events if e.get("event_id") == target)
                if target_event.get("mark_id") != event.get("mark_id"):
                    problems.append(f"{event_id}: mark_id отмены отличается от mark_id события {target}")
        elif event.get("op") == "create":
            if event.get("mark_id") in created:
                problems.append(f"{event_id}: второй create для {event.get('mark_id')}")
            created.add(event.get("mark_id"))
        elif event.get("op") == "update" and event.get("mark_id") not in created:
            problems.append(f"{event_id}: обновление {event.get('mark_id')} без create")
        if known:
            by_id[event_id] = event
    return problems


def replay(events: list[dict]) -> list[dict]:
    reverted = _reverted_ids(events)
    marks: dict[str, dict] = {}
    for event in events:
        if event["kind"] == "revert" or event["event_id"] in reverted:
            continue
        mark_id = event["mark_id"]
        if event["op"] == "create":
            mark = copy.deepcopy(event["mark"])
            mark["mark_id"] = mark_id
            mark.setdefault("provenance", {})
            mark["history"] = [event["event_id"]]
            if event["kind"] != "seed":
                derived = {a.get("field") for a in event.get("anchors") or [] if a.get("quote_check") == DERIVED}
                for name in UPDATABLE:
                    if mark.get(name) is not None and name not in derived:
                        mark["provenance"][name] = _provenance(event)
            marks[mark_id] = mark
            continue
        mark = marks.get(mark_id)
        if mark is None:
            continue
        for name, (_old, new) in event["changes"].items():
            if name.startswith(TERRITORY_PREFIX):
                _set_territory(mark, name[len(TERRITORY_PREFIX):], copy.deepcopy(new))
            else:
                mark[name] = copy.deepcopy(new)
            mark["provenance"][name] = _provenance(event)
        mark["history"].append(event["event_id"])
    result = list(marks.values())
    for mark in result:
        mark["search_numbers"] = sorted({number_key(mark.get(key)) for key in ("application_no", "registration_no")
                                         if mark.get(key)})
    return result
