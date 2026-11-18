"""Submission gate. The script never marks a budget ready_for_submission by itself."""
from __future__ import annotations

from pathlib import Path

from lb_local import load

challenge = load("challenge").challenge
load_json = load("state").load_json


def quality_gate(folder: Path) -> dict:
    folder = Path(folder)
    context = load_json(folder / "state" / "budget_context.json")
    state = load_json(folder / "state" / "budget_state.json")
    findings = [item.as_dict() for item in challenge(state, context)]
    blocking = [item["id"] for item in findings if item["blocking"]]
    decisions = load_json(folder / "state" / "decisions.json")
    accepted = any(isinstance(item, dict) and item.get("kind") == "acceptance" for item in decisions)
    checks = {
        "currency": bool(context.get("reporting_currency")),
        "period": bool((context.get("budget_period") or {}).get("start")),
        "no_blocking_findings": not blocking,
        "user_acceptance_recorded": accepted,
    }
    return {
        "ready_for_submission": False,
        "checks": checks,
        "blocking_findings": blocking,
        "finding_count": len(findings),
    }
