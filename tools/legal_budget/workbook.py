"""Workbook from the view model. Cells display the canonical numbers."""
from __future__ import annotations

import sys
from pathlib import Path

from decimal import Decimal, InvalidOperation

from openpyxl import Workbook

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from tools.safe_cell import safe_cell, safe_row  # noqa: E402


def _number(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return value


def write_workbook(view: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    summary = book.active
    summary.title = "Summary"
    summary.append(["field", "value"])
    summary.append(["total", _number(view.get("total"))])
    summary.append(["currency", safe_cell(view.get("currency"))])
    summary.append(["bridge_total", _number(view.get("bridge_total"))])
    summary.append(["scenario_saving", _number(view.get("scenario_saving"))])
    for cell in (summary["B2"], summary["B4"], summary["B5"]):
        if isinstance(cell.value, Decimal):
            cell.number_format = "0.00"
    categories = book.create_sheet("Categories")
    categories.append(["category", "amount"])
    for name, amount in (view.get("categories") or {}).items():
        categories.append(safe_row([name, amount]))
    months = book.create_sheet("Months")
    months.append(["month", "amount"])
    for month, amount in (view.get("monthly") or {}).items():
        months.append(safe_row([month, amount]))
    lines = book.create_sheet("Lines")
    lines.append(["id", "category", "annual_amount", "owner"])
    for line in view.get("lines") or []:
        lines.append(safe_row([line.get("id"), line.get("category"), line.get("annual_amount"), line.get("owner")]))
    book.save(path)
    return path
