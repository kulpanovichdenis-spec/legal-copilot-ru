"""ROI only from numbers the caller actually passed. Missing inputs stay missing."""
from __future__ import annotations

from decimal import Decimal

from capacity import CalcGap

TRACKED = ("hours_saved", "rate", "cost", "cycle_time_before", "cycle_time_after")


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def roi_summary(inputs: dict) -> dict:
    if inputs is None:
        raise CalcGap("inputs")
    missing = [key for key in TRACKED if inputs.get(key) is None]
    result: dict = {key: None for key in TRACKED}
    result["labor_value"] = None
    result["net"] = None
    result["cycle_time_delta"] = None
    result["missing"] = missing
    for key in TRACKED:
        if inputs.get(key) is not None:
            result[key] = str(_decimal(inputs[key]))
    if inputs.get("hours_saved") is not None and inputs.get("rate") is not None:
        result["labor_value"] = str(_decimal(inputs["hours_saved"]) * _decimal(inputs["rate"]))
    if result["labor_value"] is not None and inputs.get("cost") is not None:
        result["net"] = str(_decimal(result["labor_value"]) - _decimal(inputs["cost"]))
    if inputs.get("cycle_time_before") is not None and inputs.get("cycle_time_after") is not None:
        result["cycle_time_delta"] = str(
            _decimal(inputs["cycle_time_after"]) - _decimal(inputs["cycle_time_before"])
        )
    return result
