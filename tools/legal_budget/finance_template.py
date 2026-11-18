"""Finance template -> requirements card. Unknown fields stay open, they are not guessed."""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import load_workbook

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

FIELD_MAP = {
    "period start": "period_start",
    "period end": "period_end",
    "currency": "currency",
    "phasing": "phasing",
    "materiality": "materiality_threshold",
    "deadline": "deadline",
    "headcount block": "headcount_block",
    "scenarios": "scenario_requirements",
    "commentary": "mandatory_commentary",
}


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_finance_template(path: Path) -> dict:
    path = Path(path)
    before = path.read_bytes()
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        names = book.sheetnames
        card = {
            "source": str(path),
            "period_start": None,
            "period_end": None,
            "currency": None,
            "phasing": None,
            "materiality_threshold": None,
            "deadline": None,
            "headcount_block": None,
            "scenario_requirements": None,
            "mandatory_commentary": None,
            "categories": [],
            "cost_centers": [],
            "open_questions": [],
        }
        if "Instructions" not in names:
            card["open_questions"].append("В шаблоне нет листа Instructions. Параметры Finance не извлечены.")
        else:
            for row in book["Instructions"].iter_rows(values_only=True):
                if not row or row[0] is None:
                    continue
                key = _text(row[0]).lower()
                value = _text(row[1]) if len(row) > 1 else ""
                field = FIELD_MAP.get(key)
                if field is None:
                    card["open_questions"].append(f"Неизвестное поле шаблона: {row[0]}")
                    continue
                card[field] = value or None
                if not value:
                    card["open_questions"].append(f"Поле «{row[0]}» пустое.")
        if "Categories" in names:
            rows = list(book["Categories"].iter_rows(values_only=True))
            headers = [_text(cell).lower() for cell in (rows[0] if rows else [])]
            for raw in rows[1:]:
                record = {headers[i]: _text(raw[i]) if i < len(raw) else "" for i in range(len(headers))}
                if record.get("category"):
                    card["categories"].append(record["category"])
                if record.get("cost center"):
                    card["cost_centers"].append(record["cost center"])
        else:
            card["open_questions"].append("В шаблоне нет листа Categories.")
    finally:
        book.close()
    if path.read_bytes() != before:
        raise RuntimeError("разбор шаблона изменил исходный файл")
    return card


def apply_finance_card(context: dict, card: dict) -> dict:
    """Fill empty context fields. Do not create budget lines from the template."""
    updated = dict(context)
    period = dict(updated.get("budget_period") or {})
    if card.get("period_start") and not period.get("start"):
        period["start"] = card["period_start"]
    if card.get("period_end") and not period.get("end"):
        period["end"] = card["period_end"]
    updated["budget_period"] = period
    if card.get("currency") and not updated.get("reporting_currency"):
        updated["reporting_currency"] = card["currency"]
    if card.get("materiality_threshold") and updated.get("materiality_threshold") is None:
        updated["materiality_threshold"] = card["materiality_threshold"]
    updated["finance_requirements"] = {
        "phasing": card.get("phasing"),
        "categories": list(card.get("categories") or []),
        "cost_centers": list(card.get("cost_centers") or []),
        "open_questions": list(card.get("open_questions") or []),
    }
    updated.pop("lines", None)
    return updated

