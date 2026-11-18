#!/usr/bin/env python3
"""Генерация .xlsx-графика договорных сроков с диаграммой Ганта.

Форма — по мотивам Vertex42 simple-gantt-chart, но файл собственный: колонки
подобраны под договор (пункт, дословный срок, статус даты), формулы свои.

Масштаб шкалы выбирается автоматически по длительности договора: до ~2 месяцев —
дни, до года — недели, дальше — месяцы. Точные даты всегда в колонках
НАЧАЛО/ОКОНЧАНИЕ, поэтому огрубляется только картинка, не данные.

Usage:
    python -m tools.contract_schedule.xlsx_writer selftest
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..safe_cell import safe_cell
from .resolver import CHECK_MARK

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HEADER_ROW = 6
FIRST_DATA_ROW = 7
CHART_FIRST_COL = 12  # L

KIND_COLORS = {
    "payment":    "FFC7CE",
    "delivery":   "C6EFCE",
    "stage":      "BDD7EE",
    "acceptance": "FFE699",
    "notice":     "E4DFEC",
    "warranty":   "D9D9D9",
    "term":       "F8CBAD",
}
KIND_LABELS = {
    "payment": "оплата", "delivery": "поставка", "stage": "этап",
    "acceptance": "приёмка", "notice": "уведомление",
    "warranty": "гарантия", "term": "срок действия",
}
STATUS_LABELS = {
    "fixed": "по договору",
    "calculated": f"расчёт {CHECK_MARK}",
    "derived": f"расчёт по цепочке {CHECK_MARK}",
    "not_computed": f"не вычислено {CHECK_MARK}",
}
# Ширина колонки статуса должна вмещать самую длинную подпись без переноса
# в соседние ячейки (там начинается диаграмма Ганта).
STATUS_COL_WIDTH = max(len(v) for v in STATUS_LABELS.values())

COLUMNS = [
    ("№", 6), ("Пункт", 10), ("Обязательство", 42), ("Сторона", 18),
    ("Сумма", 14), ("Срок по договору (дословно)", 46), ("Опорное событие", 22),
    ("НАЧАЛО", 12), ("ОКОНЧАНИЕ", 12), ("ДНЕЙ", 7), ("СТАТУС ДАТЫ", STATUS_COL_WIDTH),
]

# Пояснение, выводимое в область диаграммы, когда ни одна дата не вычислена
# и горизонт диаграммы построить не из чего (periods == 0).
EMPTY_CHART_NOTE = (
    "Диаграмма не построена: ни одна дата не вычислена — "
    "см. столбец «СТАТУС ДАТЫ» и причины справа"
)

# Колонка с note (причина not_computed ИЛИ оговорка о расчётном календаре
# для вычисленной даты) идёт сразу за диаграммой Ганта — её положение
# зависит от количества периодов, поэтому ширина/заголовок задаются отдельно.
NOTE_COL_HEADER = "ПРИМЕЧАНИЕ"
NOTE_COL_WIDTH = 60


def choose_scale(span_days: int) -> str:
    if span_days <= 62:
        return "day"
    if span_days <= 366:
        return "week"
    return "month"


def _month_end(d: dt.date) -> dt.date:
    if d.month == 12:
        return dt.date(d.year, 12, 31)
    return dt.date(d.year, d.month + 1, 1) - dt.timedelta(days=1)


def build_periods(start: dt.date, end: dt.date, scale: str) -> list[tuple[dt.date, dt.date, str]]:
    """Колонки диаграммы: (начало периода, конец периода, подпись)."""
    if end < start:
        raise ValueError("build_periods: конец раньше начала")
    periods: list[tuple[dt.date, dt.date, str]] = []

    if scale == "day":
        cur = start
        while cur <= end:
            periods.append((cur, cur, str(cur.day)))
            cur += dt.timedelta(days=1)
    elif scale == "week":
        cur = start - dt.timedelta(days=start.weekday())
        while cur <= end:
            last = cur + dt.timedelta(days=6)
            periods.append((cur, last, cur.strftime("%d.%m")))
            cur = last + dt.timedelta(days=1)
    elif scale == "month":
        cur = dt.date(start.year, start.month, 1)
        while cur <= end:
            last = _month_end(cur)
            periods.append((cur, last, cur.strftime("%m.%y")))
            cur = last + dt.timedelta(days=1)
    else:
        raise ValueError(f"неизвестный масштаб: {scale!r}")

    return periods


def write_xlsx(path, resolved: list[dict], meta: dict) -> dict:
    wb = Workbook()
    ws = wb.active
    ws.title = "График"

    bold = Font(bold=True)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="D9E1F2")

    # --- Шапка документа ---
    ws["A1"] = "ГРАФИК ДОГОВОРНЫХ УСЛОВИЙ"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = safe_cell(meta.get("title", ""))
    ws["A3"] = safe_cell(meta.get("parties", ""))
    anchors = meta.get("anchors") or {}
    ws["A4"] = "Опорные даты: " + (
        "; ".join(f"{k} = {v.isoformat()}" for k, v in anchors.items()) or "не заданы"
    )
    generated = meta.get("generated") or dt.date.today()
    ws["H1"] = "Сформировано:"
    ws["I1"] = generated.isoformat()
    ws["H2"] = "Черновик — все расчётные даты проверяет юрист"
    ws["H2"].font = Font(italic=True)

    # --- Шапка таблицы ---
    for idx, (name, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=HEADER_ROW, column=idx, value=name)
        cell.font = bold
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(idx)].width = width

    # --- Горизонт диаграммы ---
    dates = [d for o in resolved for d in (o.get("start"), o.get("end")) if d]
    if meta.get("contract_start"):
        dates.append(meta["contract_start"])
    if meta.get("contract_end"):
        dates.append(meta["contract_end"])

    if dates:
        span_start, span_end = min(dates), max(dates)
        scale = choose_scale((span_end - span_start).days)
        periods = build_periods(span_start, span_end, scale)
    else:
        scale, periods = "day", []

    if not periods:
        empty_cell = ws.cell(row=HEADER_ROW, column=CHART_FIRST_COL, value=EMPTY_CHART_NOTE)
        empty_cell.font = Font(italic=True, color="9C5700")
        empty_cell.fill = PatternFill("solid", fgColor="FFF2CC")
        empty_cell.alignment = Alignment(vertical="center", wrap_text=True)

    for offset, (p_start, _p_end, label) in enumerate(periods):
        col = CHART_FIRST_COL + offset
        cell = ws.cell(row=HEADER_ROW, column=col, value=label)
        cell.font = Font(bold=True, size=8)
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = 4 if scale == "day" else 6
        ws.cell(row=HEADER_ROW - 1, column=col,
                value=p_start.strftime("%m.%y") if scale == "day" else "")

    # --- Заголовок колонки примечаний (сразу за диаграммой) ---
    note_col = CHART_FIRST_COL + len(periods) + 1
    note_col_letter = get_column_letter(note_col)
    note_header_cell = ws.cell(row=HEADER_ROW, column=note_col, value=NOTE_COL_HEADER)
    note_header_cell.font = bold
    note_header_cell.fill = header_fill
    note_header_cell.border = border
    note_header_cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.column_dimensions[note_col_letter].width = NOTE_COL_WIDTH

    # --- Строки обязательств ---
    for row_offset, item in enumerate(resolved):
        row = FIRST_DATA_ROW + row_offset
        start, end = item.get("start"), item.get("end")
        days = (end - start).days + 1 if start and end else None

        values = [
            item.get("id"),
            item.get("clause") or "",
            item.get("title") or "",
            item.get("obligor") or "",
            item.get("amount"),
            item.get("term_verbatim") or "",
            item.get("anchor") or "",
            start,
            end,
            days,
            STATUS_LABELS.get(item.get("date_status"), item.get("date_status")),
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=idx, value=safe_cell(value))
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=idx in (3, 6, 11))
            if idx in (8, 9) and value:
                cell.number_format = "DD.MM.YYYY"
            if idx == 5 and value is not None:
                cell.number_format = "# ##0"

        # Полосы диаграммы.
        if start and end:
            fill = PatternFill("solid", fgColor=KIND_COLORS.get(item.get("kind"), "D9D9D9"))
            for offset, (p_start, p_end, _label) in enumerate(periods):
                if start <= p_end and end >= p_start:
                    bar = ws.cell(row=row, column=CHART_FIRST_COL + offset)
                    bar.fill = fill
                    bar.border = border

        # Note: причина, по которой дата не вычислена (not_computed), ИЛИ
        # оговорка о расчётном (не подтверждённом юристом) календаре для
        # уже вычисленной даты — колонка «ПРИМЕЧАНИЕ» справа от диаграммы.
        if item.get("note"):
            note_cell = ws.cell(row=row, column=note_col, value=safe_cell(item["note"]))
            note_cell.font = Font(italic=True, size=9)
            note_cell.alignment = Alignment(vertical="top", wrap_text=True)

    last_row = FIRST_DATA_ROW + len(resolved) - 1 if resolved else FIRST_DATA_ROW

    # --- Легенда ---
    legend_row = last_row + 2
    ws.cell(row=legend_row, column=1, value="Легенда:").font = bold
    for offset, (kind, color) in enumerate(KIND_COLORS.items()):
        cell = ws.cell(row=legend_row + 1 + offset, column=2, value=KIND_LABELS.get(kind, kind))
        ws.cell(row=legend_row + 1 + offset, column=1).fill = PatternFill("solid", fgColor=color)
        cell.font = Font(size=9)

    # --- Навигация ---
    ws.freeze_panes = ws.cell(row=FIRST_DATA_ROW, column=CHART_FIRST_COL)
    if resolved:
        ws.auto_filter.ref = f"A{HEADER_ROW}:K{last_row}"
    ws.row_dimensions[HEADER_ROW].height = 30

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return {"rows": len(resolved), "scale": scale, "periods": len(periods)}


def selftest() -> int:
    # Выбор масштаба.
    assert choose_scale(30) == "day"
    assert choose_scale(62) == "day"
    assert choose_scale(63) == "week"
    assert choose_scale(366) == "week"
    assert choose_scale(367) == "month"

    # Периоды по дням: границы включительно.
    periods = build_periods(dt.date(2026, 3, 1), dt.date(2026, 3, 5), "day")
    assert len(periods) == 5, len(periods)
    assert periods[0][0] == dt.date(2026, 3, 1)
    assert periods[-1][1] == dt.date(2026, 3, 5)

    # Периоды по месяцам: последний период накрывает конец.
    periods = build_periods(dt.date(2026, 1, 15), dt.date(2026, 4, 2), "month")
    assert len(periods) == 4, len(periods)
    assert periods[-1][0] == dt.date(2026, 4, 1)
    assert periods[-1][1] >= dt.date(2026, 4, 2)

    # Генерация файла и обратное чтение.
    resolved = [
        {"id": 1, "clause": "п. 4.1", "title": "Аванс 30%", "obligor": "Покупатель",
         "kind": "payment", "amount": 1500000, "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "start": dt.date(2026, 1, 29),
         "end": dt.date(2026, 1, 29), "date_status": "calculated", "depth": 0, "note": ""},
        {"id": 2, "clause": "п. 3.1", "title": "Поставка товара", "obligor": "Поставщик",
         "kind": "delivery", "amount": None, "term_verbatim": "30 к.д. с даты аванса",
         "anchor": "item:1.end", "start": dt.date(2026, 2, 1),
         "end": dt.date(2026, 3, 2), "date_status": "derived", "depth": 1, "note": ""},
        {"id": 3, "clause": "п. 4.5", "title": "Оплата после приёмки", "obligor": "Покупатель",
         "kind": "payment", "amount": 3500000, "term_verbatim": "5 р.д. после приёмки",
         "anchor": "acceptance_done", "start": None, "end": None,
         "date_status": "not_computed", "depth": 0,
         "note": f"{CHECK_MARK} опорная дата «acceptance_done» не задана юристом"},
    ]
    meta = {
        "title": "Договор поставки № 1 от 15.01.2026",
        "parties": "ООО «Альфа» — ООО «Бета»",
        "anchors": {"contract_signing": dt.date(2026, 1, 15)},
        "contract_start": dt.date(2026, 1, 15),
        "contract_end": dt.date(2026, 6, 30),
        "generated": dt.date(2026, 7, 21),
    }

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "график.xlsx"
        stats = write_xlsx(out, resolved, meta)
        assert out.exists(), "файл не создан"
        assert stats["rows"] == 3, stats

        wb = load_workbook(out)
        ws = wb.active
        assert ws["A6"].value == "№"
        assert ws["H6"].value == "НАЧАЛО"
        assert ws["K6"].value == "СТАТУС ДАТЫ"
        # Строка 1: обязательство с расчётной датой.
        assert ws["C7"].value == "Аванс 30%"
        assert ws["F7"].value == "10 р.д. с подписания"
        assert CHECK_MARK in str(ws["K7"].value)
        # Невычисленная строка: даты пустые, статус с маркером.
        assert ws["H9"].value is None
        assert CHECK_MARK in str(ws["K9"].value)
        # Диаграмма построена: есть хотя бы одна колонка периода.
        assert stats["periods"] > 0
        assert ws.cell(row=HEADER_ROW, column=CHART_FIRST_COL).value is not None

        # Колонка K («СТАТУС ДАТЫ»): ширина вмещает самую длинную подпись
        # статуса и включён wrap_text — маркер не наезжает на диаграмму.
        longest_status = max(len(v) for v in STATUS_LABELS.values())
        k_width = ws.column_dimensions["K"].width
        assert k_width is not None and k_width >= longest_status, k_width
        status_cell = ws["K7"]
        assert status_cell.alignment.wrap_text is True, status_cell.alignment

        # amount == 0 — falsy, но всё равно должен получить числовой формат.
        assert ws["E7"].number_format == "# ##0"

        # Находка 3: у колонки примечаний есть заголовок в шапке (в том же
        # стиле — wrap_text) и разумная ширина, а не пустая безымянная колонка.
        note_col = CHART_FIRST_COL + stats["periods"] + 1
        note_col_letter = get_column_letter(note_col)
        header_cell = ws[f"{note_col_letter}{HEADER_ROW}"]
        assert header_cell.value, "у колонки примечаний нет заголовка"
        assert header_cell.alignment.wrap_text is True, header_cell.alignment
        note_width = ws.column_dimensions[note_col_letter].width
        assert note_width is not None and note_width >= 20, note_width

    # Находка 2: все строки not_computed, в meta нет contract_start/contract_end —
    # диаграмму строить не из чего, но пустая область не должна выглядеть сломанной.
    resolved_empty_chart = [
        {"id": 1, "clause": "п. 4.1", "title": "Аванс", "obligor": "Покупатель",
         "kind": "payment", "amount": 0, "term_verbatim": "10 р.д. с подписания",
         "anchor": "contract_signing", "start": None, "end": None,
         "date_status": "not_computed", "depth": 0,
         "note": f"{CHECK_MARK} опорная дата «contract_signing» не задана юристом"},
    ]
    meta_no_dates = {
        "title": "Договор без опорных дат",
        "parties": "ООО «Альфа» — ООО «Бета»",
        "anchors": {},
        "generated": dt.date(2026, 7, 21),
    }
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "график-без-дат.xlsx"
        stats = write_xlsx(out, resolved_empty_chart, meta_no_dates)
        assert stats["periods"] == 0, stats

        wb = load_workbook(out)
        ws = wb.active
        note_value = ws.cell(row=HEADER_ROW, column=CHART_FIRST_COL).value
        assert note_value, "пояснение об отсутствии диаграммы не выведено"
        assert isinstance(note_value, str) and len(note_value) > 10

        # amount == 0 — falsy, но всё равно должен получить числовой формат.
        assert ws["E7"].number_format == "# ##0"

    # Находка 3 (дополнительно): пустой список обязательств не должен ронять запись.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "график-пусто.xlsx"
        stats = write_xlsx(out, [], meta_no_dates)
        assert stats["rows"] == 0, stats
        wb = load_workbook(out)
        ws = wb.active
        assert ws["A6"].value == "№"

    print("xlsx_writer selftest: OK")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
