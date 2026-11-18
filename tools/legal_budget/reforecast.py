"""Reforecast from an approved baseline. Actual and accrual of the same invoice cannot both count."""
from __future__ import annotations

from lb_local import load

_calculate = load("calculate")
eac = _calculate.eac
variance = _calculate.variance
_model = load("model")
D = _model.D
money = _model.money


def reforecast_view(
    *,
    approved_total,
    phased_to_date,
    actual_total,
    accrual_total,
    etc_total,
    actual_invoices=None,
    accrual_invoices=None,
    driver: str | None = None,
) -> dict:
    eac_total = eac(
        actual_total,
        accrual_total,
        etc_total,
        actual_invoices=actual_invoices,
        accrual_invoices=accrual_invoices,
    )
    classified = variance(phased_to_date, actual_total, eac_total, driver)
    return {
        "approved": money(D(approved_total)),
        "phased_to_date": money(D(phased_to_date)),
        "actual": money(D(actual_total)),
        "accrual": money(D(accrual_total)),
        "etc": money(D(etc_total)),
        "eac": money(eac_total),
        "actual_vs_phased": classified["actual_vs_budget"],
        "eac_vs_approved": money(eac_total - D(approved_total)),
        "driver": classified["driver"],
        "timing": classified["timing"],
        "permanent": classified["permanent"],
    }
