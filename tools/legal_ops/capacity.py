"""Volume x time. None is a gap, never a zero."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


class CalcGap(Exception):
    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def _as_decimal(value, field: str) -> Decimal:
    if value is None:
        raise CalcGap(field)
    text = str(value).strip()
    if not text or text.upper() == "UNKNOWN":
        raise CalcGap(field)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise CalcGap(field) from exc
    if not number.is_finite():
        raise CalcGap(field)
    return number


def capacity_hours(volume, minutes_each) -> Decimal:
    return _as_decimal(volume, "volume") * _as_decimal(minutes_each, "minutes_each") / Decimal(60)


def fte(hours, hours_per_fte) -> Decimal:
    denominator = _as_decimal(hours_per_fte, "hours_per_fte")
    if denominator <= 0:
        raise CalcGap("hours_per_fte")
    return _as_decimal(hours, "hours") / denominator
