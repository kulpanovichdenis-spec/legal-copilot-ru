"""State checks that do not rewrite numbers."""
from __future__ import annotations

from lb_local import load

_model = load("model")
GOALS = _model.GOALS
Issue = _model.Issue


def validate_state(bundle: dict) -> list[Issue]:
    issues: list[Issue] = []
    context = bundle.get("context") or {}
    if context.get("goal") not in GOALS:
        issues.append(Issue("error", "bad_goal", "context.goal", "неизвестный режим"))
    if not str(context.get("reporting_currency") or "").strip():
        issues.append(Issue("warn", "no_currency", "context.reporting_currency", "валюта не задана"))
    return issues
