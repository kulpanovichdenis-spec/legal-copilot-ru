"""Shared types for the legal budget run. Amounts are decimal strings, never guessed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

GOALS = ("create", "review", "cut", "reforecast")
STAGE_STATUSES = (
    "not_started",
    "in_progress",
    "waiting_for_data",
    "draft_complete",
    "challenged",
    "ready",
    "not_applicable",
)
CERTAINTY = ("high", "medium", "low")
NORMALIZE_TAGS = (
    "recurring",
    "one_off",
    "timing_distortion",
    "late_invoice",
    "accrual_reversal",
    "fx_effect",
    "allocation_reclass",
    "extraordinary_matter",
    "unknown",
)
LEVERS = (
    "mandatory",
    "committed",
    "risk_critical",
    "business_enabling",
    "maintain_capability",
    "deferrable",
    "discretionary",
)
VARIANCE_DRIVERS = (
    "timing",
    "price",
    "volume",
    "mix",
    "scope",
    "new_event",
    "allocation",
    "prior_estimate_error",
    "unknown",
)
BRIDGE_KEYS = ("prior", "ceased", "price", "volume", "new_demand", "headcount", "fx")


class BudgetError(Exception):
    pass


class CalcGap(BudgetError):
    def __init__(self, missing: str):
        super().__init__(missing)
        self.missing = missing


class DoubleCountError(BudgetError):
    pass


class ScenarioError(BudgetError):
    pass


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    where: str
    message: str


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    rule: str
    affected_refs: tuple[str, ...]
    finding: str
    why_it_matters: str
    recommended_action: str
    blocking: bool
    status: str = "open"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "rule": self.rule,
            "affected_refs": list(self.affected_refs),
            "finding": self.finding,
            "why_it_matters": self.why_it_matters,
            "recommended_action": self.recommended_action,
            "blocking": self.blocking,
            "status": self.status,
        }


def D(value) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def log_entry(method: str, inputs: dict, output, currency: str = "RUB") -> dict:
    return {
        "id": f"CALC-{datetime.now(timezone.utc).strftime('%H%M%S%f')}",
        "method": method,
        "input_refs": list(inputs),
        "input_values": {key: str(val) for key, val in inputs.items()},
        "output_value": str(output),
        "currency": currency,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
