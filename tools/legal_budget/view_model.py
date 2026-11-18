"""One canonical view. Workbook, HTML and the CFO note read this and do not recalculate."""
from __future__ import annotations

from decimal import Decimal

from lb_local import load

_calculate = load("calculate")
annual_amount = _calculate.annual_amount
bridge = _calculate.bridge
_model = load("model")
D = _model.D
money = _model.money

BRIDGE_LABELS = (
    ("prior", "Прошлый период"),
    ("ceased", "минус прекращённое"),
    ("price", "цена и ставки"),
    ("volume", "объём"),
    ("new_demand", "новый спрос"),
    ("headcount", "штат"),
    ("fx", "валюта и аллокация"),
)


def _line_annual(line: dict) -> str:
    monthly = line.get("monthly_amounts") or {}
    if monthly:
        return money(annual_amount(monthly))
    if line.get("annual_amount") not in (None, ""):
        return money(D(line["annual_amount"]))
    return ""


def build_view_model(bundle: dict) -> dict:
    state = bundle.get("state") or {}
    context = bundle.get("context") or {}
    lines = []
    total = D("0")
    total_complete = True
    by_category: dict[str, Decimal] = {}
    monthly_total: dict[str, Decimal] = {}
    for line in state.get("lines") or []:
        annual = _line_annual(line)
        if not annual:
            total_complete = False
        if annual:
            total += D(annual)
            category = line.get("category") or "без категории"
            by_category[category] = by_category.get(category, D("0")) + D(annual)
        for month, value in (line.get("monthly_amounts") or {}).items():
            monthly_total[month] = monthly_total.get(month, D("0")) + D(value)
        lines.append({**line, "annual_amount": annual})
    parts = state.get("bridge")
    bridge_total = money(bridge(parts)) if parts else None
    overlay = state.get("scenario_overlay") or {}
    return {
        "run_id": context.get("run_id") or state.get("run_id"),
        "currency": context.get("reporting_currency") or "",
        "period": context.get("budget_period") or {},
        "total": money(total),
        "total_complete": total_complete,
        "categories": {key: money(value) for key, value in by_category.items()},
        "monthly": {key: money(value) for key, value in sorted(monthly_total.items())},
        "lines": lines,
        "bridge_total": bridge_total,
        "bridge_rows": [
            {"key": key, "label": label, "amount": money(D(parts[key]))}
            for key, label in BRIDGE_LABELS
            if parts and parts.get(key) is not None
        ],
        "bridge": parts or {},
        "scenario_saving": overlay.get("saving_total"),
        "scenario_lines": overlay.get("lines") or [],
        "assumptions": bundle.get("assumptions") or [],
        "open_issues": bundle.get("open_issues") or [],
        "findings": bundle.get("findings") or [],
        "draft": True,
    }
