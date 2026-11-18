#!/usr/bin/env python3
"""Deadline tracker: per-matter YAML tracker of legal deadlines (stateful skill core).

Stores deadlines for a matter (court case, prescription of a state body,
contract) in a YAML file inside workflow/, and produces a "what's burning"
status report: overdue / blocking / at-risk / upcoming.

Safety contract (mirrors the gate in skills/procedural-document-drafter/SKILL.md):
- The script NEVER computes legal deadlines. It does not know about
  business days, receipt dates, or roll-over of non-working days.
  A due date enters the tracker only as data already confirmed by the
  lawyer/agent per the gate, or with date_status=needs_check, which is
  rendered as [ПРОВЕРИТЬ СРОК] in every report.
- date_status=confirmed REQUIRES a non-empty basis (norm + how the date
  was derived). Refused otherwise.
- The only arithmetic performed is calendar-day distance from today to an
  already-entered due date (for sorting and at-risk detection).
- Never deletes the tracker file; items are closed by status, not removal.

At-risk rule (critical path): an open item is at risk when
(due_date - today) < lead_time_days (estimated working time to complete).

Usage:
    python tools/deadline_tracker/tracker.py init   --file PATH --matter NAME
    python tools/deadline_tracker/tracker.py add    --file PATH --title T
        [--due-date YYYY-MM-DD] --date-status confirmed|needs_check
        [--basis ...] [--category procedural|prescription|contract|other]
        [--blocking] [--lead-time N] [--responsible ...] [--source-doc ...]
        [--notes ...]
    python tools/deadline_tracker/tracker.py update --file PATH --id D-001
        [--status open|in_progress|done|cancelled] [--due-date YYYY-MM-DD]
        [--date-status confirmed|needs_check] [--basis ...]
        [--blocking | --no-blocking] [--notes ...]
    python tools/deadline_tracker/tracker.py report --file PATH [--today YYYY-MM-DD]
    python tools/deadline_tracker/tracker.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

# Windows-консоль по умолчанию cp1251 — кириллица и значки отчёта ломаются.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = 1
CATEGORIES = ("procedural", "prescription", "contract", "other")
STATUSES = ("open", "in_progress", "done", "cancelled")
DATE_STATUSES = ("confirmed", "needs_check")
DEFAULT_LEAD_TIME = 3
CHECK_MARK = "[ПРОВЕРИТЬ СРОК]"


class TrackerError(Exception):
    pass


# ---------- storage ----------

def load(path: Path) -> dict:
    if not path.exists():
        raise TrackerError(f"трекер не найден: {path} (сначала init)")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "items" not in data:
        raise TrackerError(f"файл не похож на трекер сроков: {path}")
    return data


def save(path: Path, data: dict) -> None:
    data["updated"] = dt.date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def parse_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise TrackerError(f"дата должна быть в формате YYYY-MM-DD: {s!r}") from e


def next_id(data: dict) -> str:
    mx = 0
    for it in data["items"]:
        try:
            mx = max(mx, int(str(it.get("id", "")).split("-")[-1]))
        except ValueError:
            continue
    return f"D-{mx + 1:03d}"


# ---------- commands ----------

def cmd_init(args) -> int:
    path = Path(args.file)
    if path.exists():
        raise TrackerError(f"трекер уже существует: {path} (init повторно не выполняется)")
    today = dt.date.today().isoformat()
    save(path, {
        "schema_version": SCHEMA_VERSION,
        "matter": args.matter,
        "created": today,
        "updated": today,
        "items": [],
    })
    print(f"OK: создан трекер {path} (matter: {args.matter})")
    return 0


def validate_date_fields(due_date: str | None, date_status: str, basis: str) -> None:
    if date_status not in DATE_STATUSES:
        raise TrackerError(f"date_status должен быть одним из {DATE_STATUSES}")
    if date_status == "confirmed":
        if not due_date:
            raise TrackerError("date_status=confirmed требует --due-date")
        if not basis.strip():
            raise TrackerError(
                "date_status=confirmed требует непустой --basis "
                "(норма + как исчислена дата); иначе вносить как needs_check"
            )
    if due_date:
        parse_date(due_date)


def cmd_add(args) -> int:
    path = Path(args.file)
    data = load(path)
    if args.category not in CATEGORIES:
        raise TrackerError(f"category должна быть одной из {CATEGORIES}")
    validate_date_fields(args.due_date, args.date_status, args.basis or "")
    today = dt.date.today().isoformat()
    item = {
        "id": next_id(data),
        "title": args.title,
        "category": args.category,
        "due_date": args.due_date,
        "date_status": args.date_status,
        "basis": args.basis or "",
        "responsible": args.responsible or "",
        "status": "open",
        "blocking": bool(args.blocking),
        "lead_time_days": args.lead_time,
        "source_doc": args.source_doc or "",
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    data["items"].append(item)
    save(path, data)
    mark = "" if args.date_status == "confirmed" else f" {CHECK_MARK}"
    print(f"OK: {item['id']} «{args.title}» due={args.due_date or '—'}{mark}")
    return 0


def cmd_update(args) -> int:
    path = Path(args.file)
    data = load(path)
    item = next((it for it in data["items"] if it.get("id") == args.id), None)
    if item is None:
        raise TrackerError(f"элемент {args.id} не найден в {path}")
    if args.status is not None:
        if args.status not in STATUSES:
            raise TrackerError(f"status должен быть одним из {STATUSES}")
        item["status"] = args.status
    new_due = args.due_date if args.due_date is not None else item.get("due_date")
    new_ds = args.date_status if args.date_status is not None else item.get("date_status")
    new_basis = args.basis if args.basis is not None else item.get("basis", "")
    if (args.due_date, args.date_status, args.basis) != (None, None, None):
        validate_date_fields(new_due, new_ds, new_basis or "")
        item["due_date"], item["date_status"], item["basis"] = new_due, new_ds, new_basis
    if args.blocking is not None:
        item["blocking"] = args.blocking
    if args.notes is not None:
        item["notes"] = args.notes
    item["updated"] = dt.date.today().isoformat()
    save(path, data)
    print(f"OK: {args.id} обновлён (status={item['status']})")
    return 0


def classify(items: list[dict], today: dt.date) -> dict[str, list[dict]]:
    """Split OPEN items into report buckets. Closed items are counted elsewhere."""
    buckets = {"overdue": [], "at_risk": [], "upcoming": [], "no_date": []}
    for it in items:
        if it.get("status") not in ("open", "in_progress"):
            continue
        due = it.get("due_date")
        if not due:
            buckets["no_date"].append(it)
            continue
        days = (parse_date(due) - today).days
        it["_days"] = days
        if days < 0:
            buckets["overdue"].append(it)
        elif days < int(it.get("lead_time_days", DEFAULT_LEAD_TIME)):
            buckets["at_risk"].append(it)
        else:
            buckets["upcoming"].append(it)
    key = lambda it: (not it.get("blocking", False), it.get("_days", 0))
    for name in ("overdue", "at_risk", "upcoming"):
        buckets[name].sort(key=key)
    return buckets


def fmt_line(it: dict) -> str:
    days = it.get("_days")
    if days is None:
        when = "дата не внесена"
    elif days < 0:
        when = f"{it['due_date']}, просрочено на {-days} дн."
    elif days == 0:
        when = f"{it['due_date']}, СЕГОДНЯ"
    else:
        when = f"{it['due_date']}, через {days} дн."
    flags = []
    if it.get("blocking"):
        flags.append("BLOCKING")
    if it.get("date_status") != "confirmed":
        flags.append(CHECK_MARK)
    flag_s = (" [" + ", ".join(f for f in flags if f != CHECK_MARK) + "]") if it.get("blocking") else ""
    check_s = f" {CHECK_MARK}" if it.get("date_status") != "confirmed" else ""
    basis = f" — {it['basis']}" if it.get("basis") else ""
    return f"- {it['id']} «{it['title']}» ({when}){flag_s}{check_s}{basis}"


def cmd_report(args) -> int:
    path = Path(args.file)
    data = load(path)
    today = parse_date(args.today) if args.today else dt.date.today()
    buckets = classify(data["items"], today)
    done = [it for it in data["items"] if it.get("status") == "done"]
    cancelled = [it for it in data["items"] if it.get("status") == "cancelled"]

    lines = [f"# Сроки: {data.get('matter', path.stem)} (на {today.isoformat()})", ""]
    sections = [
        ("🔴 Просрочено", buckets["overdue"]),
        ("🟠 В зоне риска (осталось меньше lead time)", buckets["at_risk"]),
        ("🟢 Предстоит", buckets["upcoming"]),
        (f"⚪ Без подтверждённой даты — {CHECK_MARK}", buckets["no_date"]),
    ]
    for title, items in sections:
        if items:
            lines.append(f"## {title}")
            lines.extend(fmt_line(it) for it in items)
            lines.append("")
    open_n = sum(len(v) for v in buckets.values())
    if open_n == 0:
        lines.append("Открытых сроков нет.")
        lines.append("")
    lines.append(f"Итого: открыто {open_n}, закрыто {len(done)}, снято {len(cancelled)}.")
    needs = [it for it in data["items"]
             if it.get("status") in ("open", "in_progress") and it.get("date_status") != "confirmed"]
    if needs:
        lines.append(f"⚠️ Дат со статусом needs_check: {len(needs)} — "
                     f"исчисление подтверждает юрист до опоры на эти даты.")
    print("\n".join(lines))
    return 0


# ---------- selftest ----------

def selftest() -> int:
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        f = str(Path(td) / "case" / "deadlines.yaml")

        run(["init", "--file", f, "--matter", "А40-TEST/2026"])
        try:
            run(["init", "--file", f, "--matter", "x"])
            raise AssertionError("повторный init должен падать")
        except TrackerError:
            ok += 1

        try:
            run(["add", "--file", f, "--title", "апелляция",
                 "--due-date", "2026-08-15", "--date-status", "confirmed"])
            raise AssertionError("confirmed без basis должен падать")
        except TrackerError:
            ok += 1

        run(["add", "--file", f, "--title", "апелляционная жалоба",
             "--due-date", "2026-08-15", "--date-status", "confirmed",
             "--basis", "ч. 1 ст. 259 АПК РФ; решение от 14.07.2026",
             "--blocking", "--lead-time", "5"])
        run(["add", "--file", f, "--title", "ответ на предписание",
             "--due-date", "2026-07-18", "--date-status", "needs_check",
             "--category", "prescription"])
        run(["add", "--file", f, "--title", "просроченный пункт",
             "--due-date", "2026-07-01", "--date-status", "needs_check"])
        run(["add", "--file", f, "--title", "без даты", "--date-status", "needs_check"])

        data = load(Path(f))
        assert [it["id"] for it in data["items"]] == ["D-001", "D-002", "D-003", "D-004"], "id-нумерация"
        ok += 1

        b = classify(data["items"], dt.date(2026, 7, 17))
        assert [i["id"] for i in b["overdue"]] == ["D-003"], "overdue"
        assert [i["id"] for i in b["at_risk"]] == ["D-002"], "at_risk: due-today=1 < lead 3"
        assert [i["id"] for i in b["upcoming"]] == ["D-001"], "upcoming: 29 дн. > lead 5"
        assert [i["id"] for i in b["no_date"]] == ["D-004"], "no_date"
        ok += 1

        run(["update", "--file", f, "--id", "D-003", "--status", "done"])
        data = load(Path(f))
        b = classify(data["items"], dt.date(2026, 7, 17))
        assert not b["overdue"], "done уходит из отчёта"
        ok += 1

        run(["update", "--file", f, "--id", "D-002",
             "--date-status", "confirmed",
             "--basis", "ч. 6 ст. 40 ФЗ-248; получено 04.07.2026"])
        data = load(Path(f))
        assert next(i for i in data["items"] if i["id"] == "D-002")["date_status"] == "confirmed"
        ok += 1

        try:
            run(["update", "--file", f, "--id", "D-404", "--status", "done"])
            raise AssertionError("несуществующий id должен падать")
        except TrackerError:
            ok += 1

        run(["report", "--file", f, "--today", "2026-07-17"])
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--file", required=True)
    p.add_argument("--matter", required=True)

    p = sub.add_parser("add")
    p.add_argument("--file", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--due-date", dest="due_date")
    p.add_argument("--date-status", dest="date_status", required=True, choices=DATE_STATUSES)
    p.add_argument("--basis")
    p.add_argument("--category", default="other", choices=CATEGORIES)
    p.add_argument("--blocking", action="store_true")
    p.add_argument("--lead-time", dest="lead_time", type=int, default=DEFAULT_LEAD_TIME)
    p.add_argument("--responsible")
    p.add_argument("--source-doc", dest="source_doc")
    p.add_argument("--notes")

    p = sub.add_parser("update")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--due-date", dest="due_date")
    p.add_argument("--date-status", dest="date_status", choices=DATE_STATUSES)
    p.add_argument("--basis")
    p.add_argument("--blocking", dest="blocking", action="store_true", default=None)
    p.add_argument("--no-blocking", dest="blocking", action="store_false")
    p.add_argument("--notes")

    p = sub.add_parser("report")
    p.add_argument("--file", required=True)
    p.add_argument("--today")

    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {"init": cmd_init, "add": cmd_add, "update": cmd_update, "report": cmd_report}[args.cmd](args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except TrackerError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
