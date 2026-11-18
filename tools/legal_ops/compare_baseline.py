"""Baseline versus later measurement. A one-sided key is UNKNOWN, not zero."""
from __future__ import annotations

from decimal import Decimal

UNKNOWN = "UNKNOWN"


def _number(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        return number
    if isinstance(value, str):
        try:
            number = Decimal(value.replace(",", "."))
        except Exception:
            return None
        if not number.is_finite():
            return None
        return number
    return None


def compare_baseline(baseline: dict, actual: dict) -> dict:
    out: dict = {}
    for key in sorted(set(baseline) | set(actual)):
        if key not in baseline or key not in actual:
            out[key] = UNKNOWN
            continue
        left = _number(baseline[key])
        right = _number(actual[key])
        if left is None or right is None:
            out[key] = UNKNOWN
        else:
            out[key] = str(right - left)
    return out
