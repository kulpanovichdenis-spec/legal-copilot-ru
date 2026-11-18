"""Tag historical rows. Dropping a row from the recurring baseline needs an assumption."""
from __future__ import annotations

from lb_local import load

_model = load("model")
NORMALIZE_TAGS = _model.NORMALIZE_TAGS
BudgetError = _model.BudgetError


def normalize_actuals(rows: list[dict], tags: dict[str, str]) -> list[dict]:
    normalized = []
    for row in rows:
        item = dict(row)
        row_id = str(item.get("id") or "")
        tag = tags.get(row_id, item.get("tag") or "unknown")
        if tag not in NORMALIZE_TAGS:
            raise BudgetError(f"неизвестный тег: {tag}")
        item["tag"] = tag
        exclude = bool(item.get("exclude_from_recurring_baseline"))
        if exclude and not str(item.get("assumption_id") or "").strip():
            raise BudgetError(f"{row_id}: исключение из baseline без assumption_id")
        item["in_recurring_baseline"] = tag == "recurring" and not exclude
        normalized.append(item)
    return normalized
