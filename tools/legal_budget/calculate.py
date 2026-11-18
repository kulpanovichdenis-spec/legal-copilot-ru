"""Reproducible budget arithmetic. Missing inputs raise CalcGap instead of becoming zero."""
from __future__ import annotations

from decimal import Decimal

from lb_local import load

_model = load("model")
BRIDGE_KEYS = _model.BRIDGE_KEYS
VARIANCE_DRIVERS = _model.VARIANCE_DRIVERS
CalcGap = _model.CalcGap
DoubleCountError = _model.DoubleCountError
D = _model.D
log_entry = _model.log_entry
money = _model.money


def annual_amount(monthly: dict) -> Decimal:
    total = sum((D(value) for value in monthly.values()), Decimal("0"))
    return total


def eac(actual, accrual_adjustment, etc, actual_invoices=None, accrual_invoices=None) -> Decimal:
    left = set(actual_invoices or [])
    right = set(accrual_invoices or [])
    overlap = left & right
    if overlap:
        raise DoubleCountError(",".join(sorted(overlap)))
    return D(actual) + D(accrual_adjustment) + D(etc)


def variance(phased_budget, actual, eac_total, driver: str | None = None) -> dict:
    label = driver if driver in VARIANCE_DRIVERS else "unknown"
    actual_gap = D(actual) - D(phased_budget)
    eac_gap = D(eac_total) - D(phased_budget)
    return {
        "driver": label,
        "actual_vs_budget": money(actual_gap),
        "eac_vs_budget": money(eac_gap),
        "timing": money(actual_gap) if label == "timing" else "UNKNOWN",
        "permanent": money(eac_gap) if label not in {"timing", "unknown"} else "UNKNOWN",
    }


def bridge(parts: dict) -> Decimal:
    missing = [
        key
        for key in BRIDGE_KEYS
        if parts.get(key) is None or (isinstance(parts.get(key), str) and not str(parts.get(key)).strip())
    ]
    if missing:
        raise CalcGap(",".join(missing))
    total = (
        D(parts["prior"])
        - D(parts["ceased"])
        + D(parts["price"])
        + D(parts["volume"])
        + D(parts["new_demand"])
        + D(parts["headcount"])
        + D(parts["fx"])
    )
    return total


def logged(method: str, inputs: dict, output: Decimal, currency: str = "RUB") -> tuple[Decimal, dict]:
    return output, log_entry(method, inputs, money(output), currency)
