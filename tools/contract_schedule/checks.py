#!/usr/bin/env python3
"""Арифметические проверки нестыковок в графике договорных сроков.

Safety contract:
- Проверяется ТОЛЬКО то, что проверяется арифметикой дат. Никаких юридических
  суждений: результат — сигнал юристу «посмотрите сюда», а не вывод о нарушении.
- Цикл в цепочке якорей проверяется не здесь, а в resolver (там он делает
  расчёт невозможным и потому бросает исключение).

Usage:
    python -m tools.contract_schedule.checks selftest
"""
from __future__ import annotations

import datetime as dt
import sys

from .resolver import parse_item_ref

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _label(item: dict) -> str:
    clause = item.get("clause") or ""
    prefix = f"{clause} " if clause else ""
    return f"{prefix}«{item.get('title', '')}» (id={item['id']})"


def run_checks(resolved: list[dict], contract_end: dt.date | None = None,
               contract_start: dt.date | None = None) -> list[str]:
    warnings: list[str] = []
    by_id = {o["id"]: o for o in resolved}

    for item in resolved:
        start, end = item.get("start"), item.get("end")

        # 1. Окончание раньше начала.
        if start and end and end < start:
            warnings.append(
                f"{_label(item)}: окончание {end.isoformat()} раньше начала {start.isoformat()}"
            )

        # 2. Выход за срок действия договора (проверка симметрична: и
        # окончание позже contract_end, и начало раньше contract_start).
        if contract_end and end and end > contract_end:
            warnings.append(
                f"{_label(item)}: {end.isoformat()} выходит за срок действия договора "
                f"({contract_end.isoformat()})"
            )
        if contract_start and start and start < contract_start:
            warnings.append(
                f"{_label(item)}: {start.isoformat()} начинается раньше срока действия "
                f"договора ({contract_start.isoformat()})"
            )

        # 3. Оплата раньше встречного исполнения, к которому привязана.
        # Кривой синтаксис ссылки (parse_item_ref бросает ValueError) здесь не
        # роняет проверку всего графика: строка уже помечена резолвером как
        # not_computed (anchor некорректен), эту проверку для неё просто
        # пропускаем — её поймает проверка №4.
        if item.get("kind") == "payment" and start:
            try:
                ref = parse_item_ref(item.get("anchor"))
            except ValueError:
                ref = None
            parent = by_id.get(ref[0]) if ref is not None else None
            if parent is not None:
                parent_point = parent.get(ref[1])
                if parent_point and start < parent_point:
                    point_label = "начала" if ref[1] == "start" else "окончания"
                    warnings.append(
                        f"{_label(item)}: оплата {start.isoformat()} раньше {point_label} "
                        f"исполнения по {_label(parent)} ({parent_point.isoformat()})"
                    )

        # 4. Обязательство без вычисленного срока.
        if item.get("date_status") == "not_computed":
            warnings.append(f"{_label(item)}: срок не вычислен — обязательство без срока в графике")

    return warnings


def selftest() -> int:
    # 1. Окончание раньше начала.
    items = [{"id": 1, "clause": "п. 2.1", "title": "Этап 1", "kind": "stage",
              "start": dt.date(2026, 3, 10), "end": dt.date(2026, 3, 1),
              "date_status": "calculated", "anchor": None}]
    warns = run_checks(items)
    assert any("раньше начала" in w for w in warns), warns

    # 2. Дата выходит за срок действия договора (конец позже contract_end).
    items = [{"id": 1, "clause": "п. 5.1", "title": "Поставка", "kind": "delivery",
              "start": dt.date(2026, 12, 1), "end": dt.date(2026, 12, 20),
              "date_status": "calculated", "anchor": None}]
    warns = run_checks(items, contract_end=dt.date(2026, 11, 30))
    assert any("срок действия договора" in w for w in warns), warns

    # 2b. М4: проверка симметрична — начало раньше contract_start тоже
    # предупреждение (спека говорит «выходит за срок действия» с любой
    # границы, не только по end).
    items = [{"id": 1, "clause": "п. 5.1", "title": "Поставка", "kind": "delivery",
              "start": dt.date(2026, 1, 1), "end": dt.date(2026, 1, 20),
              "date_status": "calculated", "anchor": None}]
    warns = run_checks(items, contract_start=dt.date(2026, 2, 1))
    assert any("раньше срока действия договора" in w for w in warns), warns

    # 2c. Контроль: старт в пределах contract_start -> предупреждения нет.
    items = [{"id": 1, "clause": "п. 5.1", "title": "Поставка", "kind": "delivery",
              "start": dt.date(2026, 3, 1), "end": dt.date(2026, 3, 20),
              "date_status": "calculated", "anchor": None}]
    warns = run_checks(items, contract_start=dt.date(2026, 2, 1))
    assert not any("раньше срока действия договора" in w for w in warns), warns

    # 3. Оплата привязана к item:1.start («оплата при отгрузке») и не
    # раньше начала родителя -> предупреждения НЕТ (М2: сравнивать нужно с
    # той точкой родителя, к которой оплата реально привязана, а не всегда
    # с end).
    items = [
        {"id": 1, "clause": "п. 3.1", "title": "Поставка", "kind": "delivery",
         "start": dt.date(2026, 5, 1), "end": dt.date(2026, 5, 20),
         "date_status": "calculated", "anchor": None},
        {"id": 2, "clause": "п. 4.2", "title": "Оплата за поставку", "kind": "payment",
         "start": dt.date(2026, 5, 10), "end": dt.date(2026, 5, 10),
         "date_status": "derived", "anchor": "item:1.start"},
    ]
    warns = run_checks(items)
    assert not any("исполнени" in w for w in warns), warns

    # 3b. Оплата привязана к item:1.end и её start раньше окончания
    # родителя -> предупреждение ЕСТЬ (существующий сценарий, не сломать).
    items = [
        {"id": 1, "clause": "п. 3.1", "title": "Поставка", "kind": "delivery",
         "start": dt.date(2026, 5, 1), "end": dt.date(2026, 5, 20),
         "date_status": "calculated", "anchor": None},
        {"id": 2, "clause": "п. 4.2", "title": "Оплата за поставку", "kind": "payment",
         "start": dt.date(2026, 5, 10), "end": dt.date(2026, 5, 10),
         "date_status": "derived", "anchor": "item:1.end"},
    ]
    warns = run_checks(items)
    assert any("раньше" in w and "исполнени" in w for w in warns), warns

    # 4. Обязательство без срока.
    items = [{"id": 1, "clause": "п. 7.1", "title": "Уведомление", "kind": "notice",
              "start": None, "end": None, "date_status": "not_computed", "anchor": None}]
    warns = run_checks(items)
    assert any("без срока" in w or "не вычислен" in w for w in warns), warns

    # 5. Корректный график — предупреждений нет.
    items = [
        {"id": 1, "clause": "п. 3.1", "title": "Поставка", "kind": "delivery",
         "start": dt.date(2026, 5, 1), "end": dt.date(2026, 5, 20),
         "date_status": "calculated", "anchor": None},
        {"id": 2, "clause": "п. 4.2", "title": "Оплата", "kind": "payment",
         "start": dt.date(2026, 5, 25), "end": dt.date(2026, 5, 25),
         "date_status": "derived", "anchor": "item:1.end"},
    ]
    assert run_checks(items, contract_end=dt.date(2026, 12, 31)) == []

    # 6. Кривой синтаксис ссылки в anchor не роняет run_checks; остальные
    # проверки в том же вызове по-прежнему отрабатывают.
    items = [
        {"id": 1, "clause": "п. 4.5", "title": "Оплата с кривой ссылкой", "kind": "payment",
         "start": None, "end": None, "date_status": "not_computed", "anchor": "item:abc.end"},
        {"id": 2, "clause": "п. 2.1", "title": "Этап с ошибкой", "kind": "stage",
         "start": dt.date(2026, 3, 10), "end": dt.date(2026, 3, 1),
         "date_status": "calculated", "anchor": None},
    ]
    warns = run_checks(items)
    assert any("раньше начала" in w for w in warns), warns
    assert any("без срока" in w or "не вычислен" in w for w in warns), warns

    print("checks selftest: OK")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
