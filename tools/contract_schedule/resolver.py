#!/usr/bin/env python3
"""Резолвер договорных сроков: якоря, цепочки, статусы дат.

Safety contract:
- Даты, которые выдаёт резолвер, — операционная проекция, а не юридическое
  исчисление срока. Всё, что не взято дословно из договора (fixed), помечается
  статусом, требующим проверки юристом.
- Никаких приближений: нет якоря, нет календаря на год, цикл в цепочке —
  строка получает not_computed с пустыми датами, а не догадку.

Статусы даты:
  fixed        — календарная дата прямо в договоре
  calculated   — посчитана от опорной даты, заданной юристом
  derived      — посчитана по цепочке от другой РАСЧЁТНОЙ даты (условность копится)
  not_computed — посчитать нельзя

Usage:
    python -m tools.contract_schedule.resolver selftest
"""
from __future__ import annotations

import datetime as dt
import re
import sys

from .calendar_ru import CalendarError, WorkCalendar, end_of_term, spans_generated_year

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DATE_STATUSES = ("fixed", "calculated", "derived", "not_computed")
CHECK_MARK = "[ПРОВЕРИТЬ СРОК]"
ITEM_REF_PREFIX = "item:"


class ResolverError(Exception):
    pass


def parse_item_ref(anchor) -> tuple[int, str] | None:
    """'item:5.end' -> (5, 'end'). Не ссылка (не начинается с 'item:') — None.

    Кривой синтаксис ссылки (нечисловой id, поле не start/end) — это плохая
    входная строка, не сломанный батч: бросает ValueError, а не ResolverError.
    ResolverError зарезервирована за обнаружением цикла в цепочке зависимостей
    (см. _order). Вызывающая сторона (_order, _resolve_one) обязана ловить
    ValueError и переводить эту строку в not_computed, не роняя остальные.

    Публичная: единственное место разбора этой ссылки в проекте, checks.py импортирует её.
    """
    if not isinstance(anchor, str) or not anchor.startswith(ITEM_REF_PREFIX):
        return None
    body = anchor[len(ITEM_REF_PREFIX):]
    ref_id, _, field = body.partition(".")
    field = field or "end"
    if field not in ("start", "end"):
        raise ValueError(f"недопустимая ссылка на обязательство: {anchor!r}")
    try:
        return int(ref_id), field
    except ValueError:
        raise ValueError(f"недопустимая ссылка на обязательство: {anchor!r}")


def _order(obligations: list[dict]) -> list[int]:
    """Топологический порядок по ссылкам item:<id>. Цикл -> ResolverError.

    Итеративный обход с явным стеком (не рекурсия): на длинных цепочках
    (тысячи звеньев в порядке, обратном зависимостям) рекурсивный visit()
    упирался в RecursionError. Кривой синтаксис ссылки (parse_item_ref
    бросает ValueError) здесь не роняет батч — строка просто считается без
    зависимости; not_computed для неё выставит _resolve_one.
    """
    ids = [o["id"] for o in obligations]
    if len(set(ids)) != len(ids):
        raise ResolverError("повторяющиеся id обязательств")
    id_set = set(ids)
    deps: dict[int, set[int]] = {}
    for o in obligations:
        try:
            ref = parse_item_ref(o.get("anchor"))
        except ValueError:
            ref = None
        deps[o["id"]] = {ref[0]} if ref and ref[0] in id_set else set()

    ordered: list[int] = []
    state: dict[int, int] = {}  # 0/отсутствует — не посещён, 1 — в обработке, 2 — готов

    for start in ids:
        if state.get(start) == 2:
            continue
        stack = [(start, iter(deps[start]))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            dep = next(it, None)
            if dep is None:
                stack.pop()
                state[node] = 2
                ordered.append(node)
                continue
            if state.get(dep) == 2:
                continue
            if state.get(dep) == 1:
                cycle_path = [n for n, _ in stack] + [dep]
                cycle = " -> ".join(str(x) for x in cycle_path)
                raise ResolverError(f"цикл в цепочке сроков: {cycle}")
            state[dep] = 1
            stack.append((dep, iter(deps[dep])))
    return ordered


def resolve(obligations: list[dict], anchors: dict[str, dt.date],
            cal: WorkCalendar) -> list[dict]:
    """Развернуть сроки в даты. Возвращает новый список, вход не мутируется."""
    result = {o["id"]: dict(o) for o in obligations}
    for item in result.values():
        item.setdefault("duration", 0)
        item.setdefault("direction", "after")
        item.update(start=None, end=None, date_status="not_computed", depth=0, note="")

    for node_id in _order(obligations):
        item = result[node_id]
        _resolve_one(item, result, anchors, cal)

    return [result[o["id"]] for o in obligations]


def _resolve_one(item: dict, result: dict[int, dict],
                 anchors: dict[str, dt.date], cal: WorkCalendar) -> None:
    def give_up(note: str) -> None:
        item.update(start=None, end=None, date_status="not_computed",
                    depth=0, note=f"{CHECK_MARK} {note}")

    fixed = item.get("fixed_date")
    if fixed:
        try:
            base = dt.date.fromisoformat(str(fixed))
        except ValueError:
            give_up(f"дата в договоре не распознана: {fixed!r}")
            return
        item.update(start=base, end=base, date_status="fixed", depth=0, note="")
        _apply_duration(item, cal, give_up)
        # duration>0 превращает веху в полосу: ОКОНЧАНИЕ вычислено скриптом
        # (start + duration по ст. 192-193 ГК), а не взято дословно из
        # договора. Строка с "fixed" по-прежнему means «дата целиком из
        # договора» — если конец расчётный, статус нужно понизить до
        # "calculated", чтобы STATUS_LABELS дал [ПРОВЕРИТЬ СРОК]. Чистая
        # веха (duration=0, start==end) остаётся "fixed" без маркера.
        if item["date_status"] == "fixed" and item["end"] != item["start"]:
            item["date_status"] = "calculated"
        _note_generated_years(item, base, cal, give_up)
        return

    anchor = item.get("anchor")
    if not anchor:
        give_up("опорное событие в договоре не определено")
        return

    try:
        ref = parse_item_ref(anchor)
    except ValueError as exc:
        give_up(str(exc))
        return
    if ref is not None:
        ref_id, field = ref
        parent = result.get(ref_id)
        if parent is None:
            give_up(f"ссылка на несуществующее обязательство id={ref_id}")
            return
        if parent["date_status"] == "not_computed" or parent.get(field) is None:
            give_up(f"дата обязательства id={ref_id} не вычислена")
            return
        base = parent[field]
        # От достоверной (fixed) даты расчёт не накапливает условность.
        if parent["date_status"] == "fixed":
            status, depth = "calculated", 0
        else:
            status, depth = "derived", parent["depth"] + 1
        # Оговорка о расчётном (не подтверждённом юристом) календаре
        # наследуется по цепочке так же, как depth: если родитель прошёл
        # через сгенерированный по ст. 112 ТК год, потомок несёт эту оговорку
        # дальше, даже если его собственный диапазон дат в такой год не попадает.
        inherited_years = _extract_generated_years(parent.get("note") or "")
    else:
        if anchor not in anchors:
            give_up(f"опорная дата «{anchor}» не задана юристом")
            return
        base = anchors[anchor]
        status, depth = "calculated", 0
        inherited_years = frozenset()

    try:
        offset = int(item.get("offset") or 0)
    except (ValueError, TypeError):
        give_up(f"offset не является числом: {item.get('offset')!r}")
        return
    unit = item.get("unit") or "calendar_days"
    direction = item.get("direction") or "after"

    try:
        point = end_of_term(base, offset, unit, cal, direction=direction) if offset else base
        if offset == 0:
            cal.require_year(point)
    except CalendarError as exc:
        give_up(str(exc))
        return

    item.update(start=point, end=point, date_status=status, depth=depth, note="")
    _apply_duration(item, cal, give_up)
    _note_generated_years(item, base, cal, give_up, inherited_years=inherited_years)


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _extract_generated_years(note: str) -> set[int]:
    """Годы, уже упомянутые в оговорке о расчётном календаре (см.
    _format_generated_years_note). Используется, чтобы пробросить оговорку
    родителя дальше по цепочке потомку, не задваивая один и тот же год."""
    return {int(y) for y in _YEAR_RE.findall(note)}


def _format_generated_years_note(years: list[int]) -> str:
    years_str = ", ".join(str(y) for y in years)
    if len(years) == 1:
        return (
            f"{CHECK_MARK} календарь на {years_str} расчётный по ст. 112 ТК: "
            f"перенос выходных Правительством на этот год не опубликован"
        )
    return (
        f"{CHECK_MARK} календари на {years_str} расчётные по ст. 112 ТК: "
        f"переносы выходных Правительством на эти годы не опубликованы"
    )


def _note_generated_years(item: dict, base: dt.date, cal: WorkCalendar, give_up,
                          inherited_years: frozenset[int] = frozenset()) -> None:
    """Дописать в note предупреждение, если расчёт задел год без официального
    постановления о переносе выходных (год расчётный по ст. 112 ТК, не
    подтверждён юристом). Статус даты (calculated/derived) не меняется —
    дата вычислена, это только оговорка. give_up уже мог перевести строку в
    not_computed раньше — тогда start/end пустые и предупреждать не о чем.

    Неподтверждённый год вне границ генератора (GENERATOR_MIN_YEAR..
    GENERATOR_MAX_YEAR; fixed_date или якорная дата вне диапазона) — это
    плохая входная строка, а не повод ронять весь батч:
    spans_generated_year может бросить CalendarError, и тогда эта строка
    деградирует через give_up так же, как остальные кривые данные в
    _resolve_one, не мешая соседним строкам.

    inherited_years — оговорка родителя по цепочке (уже посчитанная им
    _extract_generated_years из его note): наследуется вниз так же, как
    depth, и объединяется со своими годами без дублирования."""
    if item["date_status"] == "not_computed" or item["end"] is None:
        return
    points = [p for p in (base, item.get("start"), item["end"]) if p is not None]
    range_start, range_end = min(points), max(points)
    try:
        own_years = set(spans_generated_year(range_start, range_end, cal))
    except CalendarError as exc:
        give_up(str(exc))
        return
    years = sorted(own_years | set(inherited_years))
    if not years:
        return
    item["note"] = _format_generated_years_note(years)


def _apply_duration(item: dict, cal: WorkCalendar, give_up) -> None:
    """duration>0 превращает веху в полосу."""
    try:
        duration = int(item.get("duration") or 0)
    except (ValueError, TypeError):
        give_up(f"duration не является числом: {item.get('duration')!r}")
        return
    if duration <= 0 or item["start"] is None:
        return
    unit = item.get("unit") or "calendar_days"
    try:
        item["end"] = end_of_term(item["start"], duration, unit, cal, direction="after")
    except CalendarError as exc:
        give_up(str(exc))


def selftest() -> int:
    cal = WorkCalendar.load()
    signing = dt.date(2026, 1, 15)

    # 1. Расчёт от именованного якоря -> calculated, depth 0.
    items = [{"id": 1, "clause": "п. 4.1", "title": "Аванс 30%", "obligor": "Покупатель",
              "kind": "payment", "term_verbatim": "10 рабочих дней с подписания",
              "anchor": "contract_signing", "offset": 10, "unit": "business_days"}]
    out = resolve(items, {"contract_signing": signing}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["end"] == dt.date(2026, 1, 29), out[0]["end"]
    assert out[0]["depth"] == 0

    # 2. Цепочка от расчётной даты -> derived, depth 1.
    items = [
        {"id": 1, "title": "Аванс", "obligor": "Покупатель", "kind": "payment",
         "clause": "п. 4.1", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
        {"id": 2, "title": "Поставка", "obligor": "Поставщик", "kind": "delivery",
         "clause": "п. 3.1", "term_verbatim": "30 календарных дней с даты аванса",
         "anchor": "item:1.end", "offset": 30, "unit": "calendar_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[2]["date_status"] == "derived", by_id[2]["date_status"]
    assert by_id[2]["depth"] == 1, by_id[2]["depth"]
    assert by_id[2]["end"] == dt.date(2026, 3, 2), by_id[2]["end"]

    # 3. Цепочка от fixed-даты -> calculated (родитель достоверен), depth 0.
    items = [
        {"id": 1, "title": "Дата поставки", "obligor": "Поставщик", "kind": "delivery",
         "clause": "п. 3.1", "term_verbatim": "не позднее 02.03.2026",
         "fixed_date": "2026-03-02"},
        {"id": 2, "title": "Оплата после поставки", "obligor": "Покупатель",
         "kind": "payment", "clause": "п. 4.3", "term_verbatim": "5 р.д. после поставки",
         "anchor": "item:1.end", "offset": 5, "unit": "business_days"},
    ]
    out = resolve(items, {}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "fixed"
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]
    assert by_id[2]["depth"] == 0

    # 4. Якорь не задан -> not_computed, даты пустые, маркер в note.
    items = [{"id": 1, "title": "Оплата", "obligor": "Покупатель", "kind": "payment",
              "clause": "п. 4.5", "term_verbatim": "5 дней после приёмки",
              "anchor": "acceptance_done", "offset": 5, "unit": "calendar_days"}]
    out = resolve(items, {}, cal)
    assert out[0]["date_status"] == "not_computed"
    assert out[0]["start"] is None and out[0]["end"] is None
    assert CHECK_MARK in out[0]["note"]

    # 5. Цикл в цепочке -> ResolverError.
    items = [
        {"id": 1, "title": "A", "obligor": "X", "kind": "term", "clause": "",
         "term_verbatim": "", "anchor": "item:2.end", "offset": 1, "unit": "calendar_days"},
        {"id": 2, "title": "B", "obligor": "X", "kind": "term", "clause": "",
         "term_verbatim": "", "anchor": "item:1.end", "offset": 1, "unit": "calendar_days"},
    ]
    try:
        resolve(items, {}, cal)
        raise AssertionError("цикл должен падать")
    except ResolverError:
        pass

    # 6. Год вне подтверждённого календаря (2027) больше НЕ отказ — считается
    # по сгенерированному по ст. 112 ТК календарю, но с оговоркой в note.
    items = [{"id": 1, "title": "Оплата", "obligor": "Покупатель", "kind": "payment",
              "clause": "п. 4.9", "term_verbatim": "5 рабочих дней",
              "anchor": "contract_signing", "offset": 5, "unit": "business_days"}]
    out = resolve(items, {"contract_signing": dt.date(2026, 12, 29)}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["end"] == dt.date(2027, 1, 14), out[0]["end"]
    assert "2027" in out[0]["note"], out[0]["note"]
    assert CHECK_MARK in out[0]["note"], out[0]["note"]

    # 6b. Обязательство целиком внутри подтверждённого 2026 -> note пустой.
    items = [{"id": 1, "title": "Аванс", "obligor": "Покупатель", "kind": "payment",
              "clause": "п. 4.1", "term_verbatim": "10 р.д. с подписания",
              "anchor": "contract_signing", "offset": 10, "unit": "business_days"}]
    out = resolve(items, {"contract_signing": signing}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["note"] == "", repr(out[0]["note"])

    # 6c. Гарантийный срок 12 месяцев от даты в 2026, уходящей в 2027:
    # ОКОНЧАНИЕ вычислено (fixed_date + duration>0) -> "calculated", не
    # "fixed" (см. находку C1), дата заполнена, оговорка про 2027 в note.
    items = [{"id": 1, "title": "Гарантия", "obligor": "Продавец", "kind": "warranty",
              "clause": "п. 6.1", "term_verbatim": "12 месяцев с даты приёмки",
              "fixed_date": "2026-03-10", "duration": 12, "unit": "months"}]
    out = resolve(items, {}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["end"] == dt.date(2027, 3, 10), out[0]["end"]
    assert "2027" in out[0]["note"], out[0]["note"]
    assert CHECK_MARK in out[0]["note"], out[0]["note"]

    # 7. duration>0 даёт полосу: start != end.
    items = [{"id": 1, "title": "Этап 1", "obligor": "Подрядчик", "kind": "stage",
              "clause": "п. 2.1", "term_verbatim": "20 календарных дней с подписания",
              "anchor": "contract_signing", "offset": 0, "unit": "calendar_days",
              "duration": 20}]
    out = resolve(items, {"contract_signing": signing}, cal)
    assert out[0]["start"] is not None and out[0]["end"] is not None
    assert out[0]["end"] > out[0]["start"]

    # 8. Ссылка на несуществующий id -> not_computed, без падения.
    items = [{"id": 1, "title": "X", "obligor": "Y", "kind": "term", "clause": "",
              "term_verbatim": "", "anchor": "item:99.end", "offset": 1,
              "unit": "calendar_days"}]
    out = resolve(items, {}, cal)
    assert out[0]["date_status"] == "not_computed"

    # 9. Нечисловой offset -> эта строка not_computed, соседняя корректная строка считается.
    items = [
        {"id": 1, "title": "Кривой offset", "obligor": "X", "kind": "term",
         "clause": "п. 1", "term_verbatim": "", "anchor": "contract_signing",
         "offset": "десять", "unit": "calendar_days"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]
    assert by_id[2]["end"] == dt.date(2026, 1, 29), by_id[2]["end"]

    # 10. Нечисловой duration -> эта строка not_computed, соседняя корректная строка считается.
    items = [
        {"id": 1, "title": "Кривой duration", "obligor": "X", "kind": "stage",
         "clause": "п. 1", "term_verbatim": "", "anchor": "contract_signing",
         "offset": 0, "unit": "calendar_days", "duration": "двадцать"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]
    assert by_id[2]["end"] == dt.date(2026, 1, 29), by_id[2]["end"]

    # 11. Кривой синтаксис ссылки (item:abc.end, item:2.middle) -> not_computed,
    # соседняя корректная строка считается.
    items = [
        {"id": 1, "title": "Кривая ссылка A", "obligor": "X", "kind": "term",
         "clause": "п. 1", "term_verbatim": "", "anchor": "item:abc.end",
         "offset": 1, "unit": "calendar_days"},
        {"id": 2, "title": "Кривая ссылка B", "obligor": "X", "kind": "term",
         "clause": "п. 2", "term_verbatim": "", "anchor": "item:2.middle",
         "offset": 1, "unit": "calendar_days"},
        {"id": 3, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 3", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "not_computed", by_id[2]["date_status"]
    assert CHECK_MARK in by_id[2]["note"]
    assert by_id[3]["date_status"] == "calculated", by_id[3]["date_status"]
    assert by_id[3]["end"] == dt.date(2026, 1, 29), by_id[3]["end"]

    # 12. Длинная цепочка (1500 звеньев) в обратном порядке -> без RecursionError.
    # offset=0 держит все точки на дате подписания (в пределах загруженного 2026 года) —
    # проверяем именно глубину обхода, а не многолетний календарь.
    n = 1500
    items = [{"id": 1, "title": "Звено 1", "obligor": "X", "kind": "term",
              "clause": "", "term_verbatim": "", "anchor": "contract_signing",
              "offset": 0, "unit": "calendar_days"}]
    for i in range(2, n + 1):
        items.append({"id": i, "title": f"Звено {i}", "obligor": "X", "kind": "term",
                       "clause": "", "term_verbatim": "",
                       "anchor": f"item:{i - 1}.end", "offset": 0,
                       "unit": "calendar_days"})
    items_reversed = list(reversed(items))
    out = resolve(items_reversed, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[n]["date_status"] == "derived", by_id[n]["date_status"]
    assert by_id[n]["start"] == signing, by_id[n]["start"]

    # 13. Циклы по-прежнему обязаны ловиться: самоссылка, прямой и косвенный цикл.
    items = [{"id": 1, "title": "A", "obligor": "X", "kind": "term", "clause": "",
              "term_verbatim": "", "anchor": "item:1.end", "offset": 1,
              "unit": "calendar_days"}]
    try:
        resolve(items, {}, cal)
        raise AssertionError("самоссылка должна падать")
    except ResolverError:
        pass

    items = [
        {"id": 1, "title": "A", "obligor": "X", "kind": "term", "clause": "",
         "term_verbatim": "", "anchor": "item:2.end", "offset": 1, "unit": "calendar_days"},
        {"id": 2, "title": "B", "obligor": "X", "kind": "term", "clause": "",
         "term_verbatim": "", "anchor": "item:3.end", "offset": 1, "unit": "calendar_days"},
        {"id": 3, "title": "C", "obligor": "X", "kind": "term", "clause": "",
         "term_verbatim": "", "anchor": "item:1.end", "offset": 1, "unit": "calendar_days"},
    ]
    try:
        resolve(items, {}, cal)
        raise AssertionError("косвенный цикл A->B->C->A должен падать")
    except ResolverError:
        pass

    # 14. Год ниже допустимой границы (1900, fixed_date) не роняет весь батч —
    # только эта строка not_computed, соседняя корректная строка считается.
    items = [
        {"id": 1, "title": "Слишком старая дата", "obligor": "X", "kind": "term",
         "clause": "", "term_verbatim": "", "fixed_date": "1900-01-01"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]
    assert by_id[2]["end"] == dt.date(2026, 1, 29), by_id[2]["end"]

    # 14b. Год выше допустимой границы (2101, fixed_date) — тоже not_computed,
    # батч цел.
    items = [
        {"id": 1, "title": "Слишком поздняя дата", "obligor": "X", "kind": "term",
         "clause": "", "term_verbatim": "", "fixed_date": "2101-01-01"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]

    # 14c. Якорь 1900-01-01 с большим offset (calendar_days) уводит расчёт
    # в допустимые границы, но диапазон spans_generated_year всё равно
    # задевает год ниже границы через базовую (якорную) дату — тоже
    # not_computed, не роняя батч.
    items = [
        {"id": 1, "title": "Древний якорь", "obligor": "X", "kind": "term",
         "clause": "", "term_verbatim": "", "anchor": "ancient_anchor",
         "offset": 50000, "unit": "calendar_days"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"ancient_anchor": dt.date(1900, 1, 1),
                          "contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]

    # 15. Оговорка о расчётном календаре наследуется вниз по цепочке: внук,
    # чей собственный расчёт целиком лежит в подтверждённом 2026 году,
    # обязан унаследовать оговорку про 2027 от деда через родителя.
    items = [
        {"id": 1, "title": "Родитель (fixed, расчётный 2027)", "obligor": "X",
         "kind": "term", "clause": "", "term_verbatim": "",
         "fixed_date": "2027-02-01"},
        {"id": 2, "title": "Ребёнок (before, уходит в подтверждённый 2026)",
         "obligor": "X", "kind": "term", "clause": "", "term_verbatim": "",
         "anchor": "item:1.end", "offset": 45, "unit": "calendar_days",
         "direction": "before"},
        {"id": 3, "title": "Внук (после ребёнка, целиком в 2026)",
         "obligor": "X", "kind": "term", "clause": "", "term_verbatim": "",
         "anchor": "item:2.end", "offset": 5, "unit": "business_days"},
    ]
    out = resolve(items, {}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "fixed"
    assert "2027" in by_id[1]["note"], by_id[1]["note"]
    assert by_id[2]["end"] == dt.date(2026, 12, 18), by_id[2]["end"]
    assert by_id[3]["date_status"] == "derived", by_id[3]["date_status"]
    assert by_id[3]["end"] is not None
    # Внук зависит от расчёта, прошедшего через 2027, — оговорка наследуется,
    # хотя собственный диапазон внука целиком лежит в подтверждённом 2026.
    assert "2027" in by_id[3]["note"], by_id[3]["note"]
    assert CHECK_MARK in by_id[3]["note"], by_id[3]["note"]

    # 16. Несколько расчётных лет в оговорке — текст согласован (ед./мн. число
    # не расходятся: не должно быть одновременно «этот год» и «не опубликованы»).
    items = [{"id": 1, "title": "Длинная гарантия", "obligor": "Продавец",
              "kind": "warranty", "clause": "п. 6.1",
              "term_verbatim": "длинный срок из расчётных годов",
              "fixed_date": "2028-01-01", "duration": 800, "unit": "calendar_days"}]
    out = resolve(items, {}, cal)
    note = out[0]["note"]
    assert CHECK_MARK in note, note
    years_found = [int(y) for y in re.findall(r"\d{4}", note)]
    assert len(years_found) >= 2, years_found
    if len(years_found) == 1:
        assert "этот год" in note and "не опубликован" in note
        assert "не опубликованы" not in note, note
    else:
        assert "эти годы" in note and "не опубликованы" in note, note
        assert "этот год" not in note, note

    # 17. Task 4b (правка): fixed_date в 2003 (не подтверждён в calendar,
    # ниже GENERATOR_MIN_YEAR=2015) — строка not_computed, соседняя
    # корректная строка батч не роняет.
    items = [
        {"id": 1, "title": "Старая дата (2003)", "obligor": "X", "kind": "term",
         "clause": "", "term_verbatim": "", "fixed_date": "2003-11-04"},
        {"id": 2, "title": "Нормальная строка", "obligor": "Y", "kind": "term",
         "clause": "п. 2", "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "offset": 10, "unit": "business_days"},
    ]
    out = resolve(items, {"contract_signing": signing}, cal)
    by_id = {o["id"]: o for o in out}
    assert by_id[1]["date_status"] == "not_computed", by_id[1]["date_status"]
    assert CHECK_MARK in by_id[1]["note"]
    assert by_id[2]["date_status"] == "calculated", by_id[2]["date_status"]
    assert by_id[2]["end"] == dt.date(2026, 1, 29), by_id[2]["end"]

    # 18. Task 4b: direction=before + duration уводит start в сгенерированный
    # год (2025), пока base и end остаются в подтверждённом 2026 — note
    # обязан нести оговорку про 2025, статус остаётся calculated (не
    # not_computed), т.к. дата всё равно посчитана.
    items = [{"id": 1, "title": "Полоса перед подписанием", "obligor": "X",
              "kind": "term", "clause": "", "term_verbatim": "",
              "anchor": "contract_signing", "offset": 30, "unit": "calendar_days",
              "direction": "before", "duration": 20}]
    out = resolve(items, {"contract_signing": signing}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["start"] is not None and out[0]["end"] is not None
    assert "2025" in out[0]["note"], repr(out[0]["note"])
    assert CHECK_MARK in out[0]["note"], repr(out[0]["note"])

    # 18b. Контроль: обязательство целиком внутри подтверждённого 2026
    # (без ухода start в другой год) -> note по-прежнему пустой.
    items = [{"id": 1, "title": "Полоса внутри 2026", "obligor": "X",
              "kind": "term", "clause": "", "term_verbatim": "",
              "anchor": "contract_signing", "offset": 5, "unit": "calendar_days",
              "direction": "before", "duration": 3}]
    out = resolve(items, {"contract_signing": signing}, cal)
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["note"] == "", repr(out[0]["note"])

    # C1. fixed_date + duration>0 -> ОКОНЧАНИЕ вычислено скриптом, а не взято
    # из договора дословно. Строка НЕ должна остаться "fixed" (это выглядело
    # бы как «дата целиком из договора» без маркера) — статус "calculated",
    # маркер [ПРОВЕРИТЬ СРОК] обязателен.
    items = [{"id": 1, "title": "Гарантия 30 к.д.", "obligor": "Продавец",
              "kind": "warranty", "clause": "п. 6.1",
              "term_verbatim": "30 календарных дней с 10.01.2026",
              "fixed_date": "2026-01-10", "duration": 30, "unit": "calendar_days"}]
    out = resolve(items, {}, cal)
    # Маркер приходит через STATUS_LABELS в xlsx_writer по date_status
    # (не через note — note несёт только оговорку про расчётный год).
    assert out[0]["date_status"] == "calculated", out[0]["date_status"]
    assert out[0]["start"] == dt.date(2026, 1, 10), out[0]["start"]
    assert out[0]["end"] == dt.date(2026, 2, 9), out[0]["end"]

    # C1 контроль: чистая веха fixed_date + duration=0 (start==end, оба из
    # договора дословно) обязана ОСТАТЬСЯ "fixed" без маркера.
    items = [{"id": 1, "title": "Дата подписания", "obligor": "Стороны",
              "kind": "term", "clause": "п. 1.1", "term_verbatim": "15.01.2026",
              "fixed_date": "2026-01-15"}]
    out = resolve(items, {}, cal)
    assert out[0]["date_status"] == "fixed", out[0]["date_status"]
    assert out[0]["note"] == "", repr(out[0]["note"])

    print("resolver selftest: OK")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
