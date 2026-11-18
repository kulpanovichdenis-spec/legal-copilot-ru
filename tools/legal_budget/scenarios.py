"""Scenario overlay. The approved base is copied and never scaled pro-rata."""
from __future__ import annotations

import copy

from lb_local import load

_model = load("model")
LEVERS = _model.LEVERS
D = _model.D
ScenarioError = _model.ScenarioError
money = _model.money


PROTECTED = {"mandatory", "committed", "risk_critical"}


def apply_scenario(base_state: dict, actions: list[dict], decisions: list | None = None) -> dict:
    known = {item.get("id") for item in (decisions or []) if isinstance(item, dict)}
    for action in actions:
        if action.get("type") in {"pro_rata", "scale_all"}:
            raise ScenarioError("равномерная стрижка всех строк запрещена")
        if action.get("classification") not in LEVERS:
            raise ScenarioError("у действия сценария нет классификации рычага")
        if action.get("saving") in (None, ""):
            raise ScenarioError("у действия сценария нет saving")
        if action.get("classification") in PROTECTED and action.get("decision_id") not in known:
            raise ScenarioError("mandatory, committed и risk_critical требуют записанное решение")
    overlay = copy.deepcopy(base_state)
    scenario_lines = []
    for action in actions:
        scenario_lines.append(
            {
                "line_id": action.get("line_id"),
                "classification": action["classification"],
                "saving": money(D(action["saving"])),
                "consequence": action.get("consequence") or "",
                "owner": action.get("owner") or "",
                "confidence": action.get("confidence") or "low",
            }
        )
    overlay["scenario_overlay"] = {
        "actions": copy.deepcopy(actions),
        "lines": scenario_lines,
        "saving_total": money(sum((D(item["saving"]) for item in scenario_lines), D("0"))),
    }
    return overlay


def plan_cut(lines: list[dict], target_percent) -> dict:
    """A percent target is a request, not a method. Lines stay as they are."""
    if target_percent is None:
        raise ScenarioError("нет цели сокращения")
    try:
        D(target_percent)
    except Exception as exc:
        raise ScenarioError("percent должен быть числом") from exc
    return {
        "applied": False,
        "target_percent": str(target_percent),
        "lines": copy.deepcopy(lines),
        "needed": "отдельные рычаги с классификацией и последствием",
    }


REQUIRED_MAKE_VS_BUY = (
    "fully_loaded_cost",
    "steady_workload",
    "capacity",
    "specialisation",
    "demand_variability",
    "supervision_cost",
    "speed",
    "knowledge_retention",
    "independence",
    "strategic_value",
    "risk",
)


def make_vs_buy(external_cost, salary, **factors) -> dict:
    """Equal external spend and salary is not a hire decision."""
    missing = [name for name in REQUIRED_MAKE_VS_BUY if not factors.get(name)]
    return {
        "decision": None,
        "hire": False,
        "external_cost": str(external_cost),
        "salary": str(salary),
        "missing": missing,
    }

