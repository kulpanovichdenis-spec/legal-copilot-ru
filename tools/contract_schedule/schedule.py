#!/usr/bin/env python3
"""График договорных условий: CLI и сборка пайплайна.

Разделение труда (паттерн low freedom):
- модель читает договор и извлекает обязательства в JSON по schema.md;
- этот скрипт разворачивает сроки в даты, ищет нестыковки и пишет .xlsx.

Даты, которые выдаёт скрипт, — операционная проекция, а не юридическое
исчисление срока: всё, кроме дат, взятых из договора дословно, помечается
[ПРОВЕРИТЬ СРОК]. Исчисление подтверждает юрист.

Usage:
    python -m tools.contract_schedule.schedule build --in obligations.json
        --out "workflow/<договор>/график.xlsx"
        [--anchor contract_signing=2026-08-01 ...] [--calendar PATH]
        [--title T] [--parties P] [--contract-start D] [--contract-end D]
    python -m tools.contract_schedule.schedule selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

from .calendar_ru import CalendarError, WorkCalendar
from .checks import run_checks
from .resolver import ResolverError, resolve
from .xlsx_writer import write_xlsx

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


class ScheduleError(Exception):
    pass


def _parse_date(raw: str, what: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise ScheduleError(f"{what}: ожидается дата в формате YYYY-MM-DD, получено {raw!r}")


def parse_anchor(raw: str) -> tuple[str, dt.date]:
    """'contract_signing=2026-01-15' -> ('contract_signing', date(2026,1,15))."""
    name, sep, value = str(raw).partition("=")
    if not sep or not name.strip() or not value.strip():
        raise ScheduleError(
            f"опорная дата задаётся как ИМЯ=YYYY-MM-DD, получено {raw!r}"
        )
    return name.strip(), _parse_date(value.strip(), f"опорная дата «{name.strip()}»")


def _validate_obligations(obligations: list) -> None:
    """Минимальная проверка структуры ДО resolve(): резолвер требует, чтобы
    каждый элемент был словарём с ключом "id" (его контракт менять нельзя).
    Кривой JSON от модели без этой проверки даёт сырой TypeError/KeyError
    вместо понятной ошибки юристу. Более глубокую валидацию (title, obligor
    и т. д.) сюда не добавляем — резолвер сам корректно обрабатывает
    отсутствие необязательных полей."""
    for i, item in enumerate(obligations, start=1):
        if not isinstance(item, dict):
            raise ScheduleError(f"обязательство №{i} в файле не является объектом JSON")
        if "id" not in item:
            raise ScheduleError(f"у обязательства №{i} нет обязательного поля id")


def build(args) -> int:
    src = Path(args.src)
    if not src.exists():
        raise ScheduleError(f"файл с обязательствами не найден: {src}")

    try:
        obligations = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"не удалось разобрать JSON {src}: {exc}")
    if not isinstance(obligations, list) or not obligations:
        raise ScheduleError(f"ожидался непустой список обязательств в {src}")
    _validate_obligations(obligations)

    anchors = dict(parse_anchor(a) for a in args.anchor)
    cal = WorkCalendar.load(Path(args.calendar) if args.calendar else None)

    contract_start = _parse_date(args.contract_start, "--contract-start") if args.contract_start else None
    contract_end = _parse_date(args.contract_end, "--contract-end") if args.contract_end else None

    resolved = resolve(obligations, anchors, cal)
    warnings = run_checks(resolved, contract_end=contract_end, contract_start=contract_start)

    meta = {
        "title": args.title,
        "parties": args.parties,
        "anchors": anchors,
        "contract_start": contract_start,
        "contract_end": contract_end,
        "generated": dt.date.today(),
    }
    stats = write_xlsx(Path(args.out), resolved, meta)

    counts: dict[str, int] = {}
    for item in resolved:
        counts[item["date_status"]] = counts.get(item["date_status"], 0) + 1

    print(f"Файл: {args.out}")
    print(f"Обязательств: {stats['rows']}; шкала: {stats['scale']}; колонок периода: {stats['periods']}")
    print("Статусы дат: " + ", ".join(f"{k} — {v}" for k, v in sorted(counts.items())))
    need_check = sum(v for k, v in counts.items() if k != "fixed")
    if need_check:
        print(f"Требуют проверки юристом: {need_check} (все, кроме взятых из договора дословно)")
    if warnings:
        print("\nНестыковки — проверить:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


def selftest() -> int:
    from . import calendar_ru, checks, resolver, xlsx_writer

    assert calendar_ru.selftest() == 0
    assert resolver.selftest() == 0
    assert checks.selftest() == 0
    assert xlsx_writer.selftest() == 0

    # Разбор --anchor.
    name, value = parse_anchor("contract_signing=2026-01-15")
    assert name == "contract_signing" and value == dt.date(2026, 1, 15)
    for bad in ("contract_signing", "x=15.01.2026", "=2026-01-15"):
        try:
            parse_anchor(bad)
            raise AssertionError(f"некорректный якорь должен падать: {bad!r}")
        except ScheduleError:
            pass

    # Сквозной сценарий: JSON -> .xlsx.
    # id=1 — якорь contract_signing, +10 р.д. -> calculated, 2026-01-29.
    # id=2 — цепочка от id=1 (end), +30 к.д. -> derived, 2026-02-28.
    # id=3 — опорная дата "acceptance_done" юристом не задана -> not_computed.
    obligations = [
        {"id": 1, "clause": "п. 4.1", "title": "Аванс 30%", "obligor": "Покупатель",
         "kind": "payment", "amount": 1500000,
         "term_verbatim": "в течение 10 рабочих дней с момента подписания Договора",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
        {"id": 2, "clause": "п. 3.1", "title": "Поставка товара", "obligor": "Поставщик",
         "kind": "delivery", "amount": None,
         "term_verbatim": "в течение 30 календарных дней с даты поступления аванса",
         "anchor": "item:1.end", "offset": 30, "unit": "calendar_days"},
        {"id": 3, "clause": "п. 4.5", "title": "Окончательный расчёт", "obligor": "Покупатель",
         "kind": "payment", "amount": 3500000,
         "term_verbatim": "в течение 5 рабочих дней после подписания УПД",
         "anchor": "acceptance_done", "offset": 5, "unit": "business_days"},
    ]

    # Известные ожидаемые даты/статусы на тех же данных, напрямую через
    # resolve()/run_checks() — до write_xlsx, чтобы e2e-часть ниже ловила
    # регрессию в логике, а не только падение/отсутствие файла.
    from . import calendar_ru as _calendar_ru_mod
    cal = _calendar_ru_mod.WorkCalendar.load()
    anchors = {"contract_signing": dt.date(2026, 1, 15)}
    resolved = resolve(obligations, anchors, cal)
    by_id = {o["id"]: o for o in resolved}
    assert by_id[1]["date_status"] == "calculated", by_id[1]["date_status"]
    assert by_id[1]["end"] == dt.date(2026, 1, 29), by_id[1]["end"]
    assert by_id[2]["date_status"] == "derived", by_id[2]["date_status"]
    assert by_id[2]["end"] == dt.date(2026, 3, 2), by_id[2]["end"]
    assert by_id[3]["date_status"] == "not_computed", by_id[3]["date_status"]
    assert by_id[3]["start"] is None and by_id[3]["end"] is None

    # Чистый сценарий (contract_end покрывает все посчитанные даты) -> кроме
    # ожидаемого not_computed по id=3 других нестыковок нет.
    clean_warnings = run_checks(resolved, contract_end=dt.date(2026, 12, 31))
    assert len(clean_warnings) == 1, clean_warnings
    assert "id=3" in clean_warnings[0], clean_warnings

    # Сценарий с заведомой нестыковкой: contract_end раньше, чем end у id=2
    # (2026-03-02) -> появляется вторая нестыковка "срок за пределами".
    dirty_warnings = run_checks(resolved, contract_end=dt.date(2026, 2, 1))
    assert len(dirty_warnings) == 2, dirty_warnings
    assert any("id=2" in w and "2026-02-01" in w for w in dirty_warnings), dirty_warnings

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "obligations.json"
        src.write_text(json.dumps(obligations, ensure_ascii=False), encoding="utf-8")
        out = Path(td) / "график.xlsx"

        parser = build_parser()
        args = parser.parse_args([
            "build", "--in", str(src), "--out", str(out),
            "--anchor", "contract_signing=2026-01-15",
            "--title", "Договор поставки № 1",
            "--contract-end", "2026-12-31",
        ])
        assert build(args) == 0
        assert out.exists(), "сквозной прогон не создал файл"

        meta = {
            "title": "Договор поставки № 1", "parties": "", "anchors": anchors,
            "contract_start": None, "contract_end": dt.date(2026, 12, 31),
            "generated": dt.date.today(),
        }
        stats = write_xlsx(out, resolved, meta)
        assert stats["rows"] == 3, stats
        assert stats["periods"] > 0, stats

        # Кривая структура JSON: элемент не словарь -> ScheduleError с
        # понятным текстом, не сырой TypeError.
        bad_src = Path(td) / "bad_strings.json"
        bad_src.write_text(json.dumps(["foo", "bar"], ensure_ascii=False), encoding="utf-8")
        bad_args = parser.parse_args([
            "build", "--in", str(bad_src), "--out", str(Path(td) / "out1.xlsx"),
            "--anchor", "contract_signing=2026-01-15",
        ])
        try:
            build(bad_args)
            raise AssertionError("список строк вместо объектов должен падать ScheduleError")
        except ScheduleError as exc:
            assert "№1" in str(exc), str(exc)

        # Кривая структура JSON: объект без "id" -> ScheduleError, не KeyError.
        bad_src2 = Path(td) / "bad_no_id.json"
        bad_src2.write_text(
            json.dumps([{"title": "Без id"}], ensure_ascii=False), encoding="utf-8"
        )
        bad_args2 = parser.parse_args([
            "build", "--in", str(bad_src2), "--out", str(Path(td) / "out2.xlsx"),
            "--anchor", "contract_signing=2026-01-15",
        ])
        try:
            build(bad_args2)
            raise AssertionError("обязательство без id должно падать ScheduleError")
        except ScheduleError as exc:
            assert "№1" in str(exc) and "id" in str(exc), str(exc)

    print("contract_schedule selftest: OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedule.py", description="График договорных условий из JSON обязательств"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="построить .xlsx-график")
    b.add_argument("--in", dest="src", required=True, help="JSON с обязательствами")
    b.add_argument("--out", dest="out", required=True, help="путь к .xlsx")
    b.add_argument("--anchor", action="append", default=[],
                   metavar="NAME=YYYY-MM-DD", help="опорная дата (можно несколько раз)")
    b.add_argument("--calendar", default=None, help="путь к holidays_ru.yaml")
    b.add_argument("--title", default="", help="название договора")
    b.add_argument("--parties", default="", help="стороны")
    b.add_argument("--contract-start", default=None, help="начало срока действия, YYYY-MM-DD")
    b.add_argument("--contract-end", default=None, help="окончание срока действия, YYYY-MM-DD")

    sub.add_parser("selftest")
    return parser


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return build(args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except (ScheduleError, ResolverError, CalendarError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
