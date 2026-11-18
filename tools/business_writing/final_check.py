"""Validate a business_writing.v1 manifest without changing source files.

This is a structural pre-review check. It does not validate legal correctness, facts,
source authority or the rendered document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MODES = {
    "SHORT_ANSWER",
    "BUSINESS_EMAIL",
    "LEGAL_MEMO",
    "BOARD_NOTE",
    "LEGAL_DIGEST",
    "RISK_NOTE",
    "EDIT_EXISTING_TEXT",
}
UNCERTAINTY_TYPES = {
    "MISSING_FACT",
    "UNVERIFIED_SOURCE",
    "LEGAL_AMBIGUITY",
    "PREDICTIVE",
}
BUSINESS_TREATMENTS = {
    "BRANCH",
    "ASSUMPTION",
    "OPEN_QUESTION",
    "SOURCE_STATUS",
    "COMPETING_INTERPRETATIONS",
    "RISK_BASIS",
    "RESOLVED",
}
TREATMENTS_BY_UNCERTAINTY = {
    "MISSING_FACT": {"BRANCH", "ASSUMPTION", "OPEN_QUESTION"},
    "UNVERIFIED_SOURCE": {"SOURCE_STATUS"},
    "LEGAL_AMBIGUITY": {"COMPETING_INTERPRETATIONS"},
    "PREDICTIVE": {"RISK_BASIS"},
}
EVIDENCE_STATUSES = {"VERIFIED", "MARKED", "UNKNOWN"}
TRACE_STATUSES = {
    "OPEN",
    "PENDING_FACT",
    "PENDING_VERIFICATION",
    "LEGAL_AMBIGUITY",
    "PREDICTIVE",
}
TRACE_STATUS_BY_UNCERTAINTY = {
    "MISSING_FACT": "PENDING_FACT",
    "UNVERIFIED_SOURCE": "PENDING_VERIFICATION",
    "LEGAL_AMBIGUITY": "LEGAL_AMBIGUITY",
    "PREDICTIVE": "PREDICTIVE",
}
PLACEHOLDER_VALUES = {
    "-",
    "—",
    "n/a",
    "na",
    "none",
    "null",
    "tbd",
    "unknown",
    "неизвестно",
    "нет",
}
MARKER_RE = re.compile(
    r"^\[(?:ПРОВЕРИТЬ|СВЕРИТЬ|ВОПРОС|СТРАТЕГИЧЕСКОЕ|ДОПУЩЕНИЕ|ПРИМЕНЯЕТСЯ)\b[^\]]*\]$"
)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    path: str
    message: str


class ManifestError(ValueError):
    """Raised when the manifest cannot be checked safely."""


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestError(f"{path} must be an array")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestError(f"{path} must be a boolean")
    return value


def _text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{path} must be a string")
    if not allow_empty and not value.strip():
        raise ManifestError(f"{path} must not be empty")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{path} must be a number")
    return float(value)


def _text_list(value: Any, path: str) -> list[str]:
    items = _list(value, path)
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(items)]


def _meaningful_text(value: Any, path: str) -> str:
    text = _text(value, path)
    if text.strip().casefold() in PLACEHOLDER_VALUES:
        raise ManifestError(f"{path} must contain a real value, not a placeholder")
    return text


def _meaningful_text_list(value: Any, path: str) -> list[str]:
    items = _list(value, path)
    return [_meaningful_text(item, f"{path}[{index}]") for index, item in enumerate(items)]


def _finding(code: str, path: str, message: str, severity: str = "ERROR") -> Finding:
    return Finding(code=code, severity=severity, path=path, message=message)


def check_manifest(raw: Any) -> dict[str, Any]:
    data = _mapping(raw, "$")
    if data.get("schema") != "business_writing.v1":
        raise ManifestError("$.schema must equal business_writing.v1")

    mode = _text(data.get("mode"), "$.mode")
    if mode not in MODES:
        raise ManifestError(f"$.mode must be one of {sorted(MODES)}")
    _text(data.get("audience"), "$.audience")

    findings: list[Finding] = []
    answer = _mapping(data.get("answer"), "$.answer")
    present = _bool(answer.get("present"), "$.answer.present")
    answer_text = _text(answer.get("text"), "$.answer.text", allow_empty=True)
    location = _number(answer.get("location_percent"), "$.answer.location_percent")
    decisive_unknown = _bool(
        answer.get("decisive_fact_unknown"), "$.answer.decisive_fact_unknown"
    )
    branched = _bool(
        answer.get("branches_or_precise_question"),
        "$.answer.branches_or_precise_question",
    )
    if not 0 <= location <= 100:
        raise ManifestError("$.answer.location_percent must be between 0 and 100")
    if not present:
        findings.append(_finding("ANSWER_MISSING", "$.answer", "No answer or precise dependency is stated."))
    elif location > 15:
        findings.append(
            _finding(
                "ANSWER_TOO_LATE",
                "$.answer.location_percent",
                "The answer or precise dependency starts after the first 15% of the text.",
            )
        )
    elif not answer_text.strip():
        findings.append(
            _finding(
                "ANSWER_TEXT_EMPTY",
                "$.answer.text",
                "The manifest declares an answer but does not include its actual text.",
            )
        )
    if decisive_unknown and not branched:
        findings.append(
            _finding(
                "DECISIVE_GAP_UNBRANCHED",
                "$.answer",
                "A decisive unknown fact has no branches or precise open question.",
            )
        )

    uncertainties = _list(data.get("uncertainties"), "$.uncertainties")
    unresolved_uncertainty = False
    unresolved_decisive = False
    for index, item in enumerate(uncertainties):
        path = f"$.uncertainties[{index}]"
        entry = _mapping(item, path)
        kind = _text(entry.get("type"), path + ".type")
        if kind not in UNCERTAINTY_TYPES:
            raise ManifestError(f"{path}.type must be one of {sorted(UNCERTAINTY_TYPES)}")
        resolved = _bool(entry.get("resolved"), path + ".resolved")
        visible = _bool(
            entry.get("visible_in_lawyer_version"), path + ".visible_in_lawyer_version"
        )
        treatment = _text(entry.get("business_treatment"), path + ".business_treatment")
        if treatment not in BUSINESS_TREATMENTS:
            raise ManifestError(
                f"{path}.business_treatment must be one of {sorted(BUSINESS_TREATMENTS)}"
            )
        decisive = _bool(entry.get("decisive"), path + ".decisive")
        if not resolved:
            unresolved_uncertainty = True
            unresolved_decisive = unresolved_decisive or decisive
            trace = _mapping(entry.get("trace"), path + ".trace")
            marker = _meaningful_text(trace.get("marker"), path + ".trace.marker")
            if not MARKER_RE.fullmatch(marker.strip()):
                raise ManifestError(
                    f"{path}.trace.marker must be a bracketed project marker"
                )
            trace_status = _text(trace.get("status"), path + ".trace.status")
            if trace_status not in TRACE_STATUSES:
                raise ManifestError(
                    f"{path}.trace.status must be one of {sorted(TRACE_STATUSES)}"
                )
            expected_status = TRACE_STATUS_BY_UNCERTAINTY[kind]
            if trace_status != expected_status:
                findings.append(
                    _finding(
                        "UNCERTAINTY_TRACE_STATUS_MISMATCH",
                        path + ".trace.status",
                        f"{kind} requires trace status {expected_status}, not {trace_status}.",
                    )
                )
            _meaningful_text(trace.get("handoff"), path + ".trace.handoff")
            source_refs = _meaningful_text_list(
                trace.get("source_refs"), path + ".trace.source_refs"
            )
            locators = _meaningful_text_list(
                trace.get("locators"), path + ".trace.locators"
            )
            if len(source_refs) != len(locators):
                raise ManifestError(
                    f"{path}.trace.source_refs and locators must have equal length"
                )
            if kind != "MISSING_FACT" and not source_refs:
                findings.append(
                    _finding(
                        "UNCERTAINTY_TRACE_INCOMPLETE",
                        path + ".trace",
                        f"{kind} requires at least one source ref and locator in the lawyer trace.",
                    )
                )
            if not visible:
                findings.append(
                    _finding(
                        "UNCERTAINTY_TRACE_HIDDEN",
                        path,
                        "An unresolved uncertainty is not visible in the lawyer/support version.",
                    )
                )
            if treatment == "RESOLVED":
                findings.append(
                    _finding(
                        "UNCERTAINTY_TREATMENT_INVALID",
                        path + ".business_treatment",
                        "An unresolved uncertainty cannot use RESOLVED treatment.",
                    )
                )
            elif treatment not in TREATMENTS_BY_UNCERTAINTY[kind]:
                findings.append(
                    _finding(
                        "UNCERTAINTY_TYPE_TREATMENT_MISMATCH",
                        path + ".business_treatment",
                        f"{kind} cannot be represented as {treatment}.",
                    )
                )
            if decisive and treatment not in {"BRANCH", "OPEN_QUESTION"}:
                findings.append(
                    _finding(
                        "DECISIVE_UNCERTAINTY_NOT_EXPLICIT",
                        path + ".business_treatment",
                        "A decisive uncertainty requires a branch or precise open question.",
                    )
                )
        elif treatment != "RESOLVED":
            findings.append(
                _finding(
                    "RESOLVED_UNCERTAINTY_STILL_EXPOSED",
                    path + ".business_treatment",
                    "Resolved uncertainty should use RESOLVED treatment.",
                    "WARNING",
                )
            )

    if decisive_unknown and not unresolved_decisive:
        findings.append(
            _finding(
                "DECISIVE_GAP_NOT_IN_INVENTORY",
                "$.uncertainties",
                "The answer reports a decisive gap that is absent from the uncertainty inventory.",
            )
        )
    if unresolved_decisive and not decisive_unknown:
        findings.append(
            _finding(
                "ANSWER_GAP_MISMATCH",
                "$.answer.decisive_fact_unknown",
                "The uncertainty inventory contains a decisive gap not reflected in the answer block.",
            )
        )

    actions = _list(data.get("actions"), "$.actions")
    for index, item in enumerate(actions):
        path = f"$.actions[{index}]"
        entry = _mapping(item, path)
        _text(entry.get("text"), path + ".text")
        required = _bool(entry.get("required"), path + ".required")
        owner = entry.get("owner")
        if owner is not None:
            _text(owner, path + ".owner")
        next_step = _bool(entry.get("explicit_next_step"), path + ".explicit_next_step")
        legal_condition = _bool(entry.get("legal_condition"), path + ".legal_condition")
        if required and not legal_condition and not owner and not next_step:
            findings.append(
                _finding(
                    "ACTION_UNOWNED",
                    path,
                    "A required action has neither an owner nor an explicit next step.",
                )
            )

    risks = _list(data.get("risks"), "$.risks")
    if mode == "RISK_NOTE" and not risks:
        findings.append(_finding("RISK_NOTE_EMPTY", "$.risks", "RISK_NOTE requires at least one risk."))
    for index, item in enumerate(risks):
        path = f"$.risks[{index}]"
        entry = _mapping(item, path)
        material = _bool(entry.get("material"), path + ".material")
        trigger = entry.get("trigger")
        consequence = entry.get("consequence")
        if trigger is not None:
            _text(trigger, path + ".trigger")
        if consequence is not None:
            _text(consequence, path + ".consequence")
        evidence_status = _text(entry.get("evidence_status"), path + ".evidence_status")
        if evidence_status not in EVIDENCE_STATUSES:
            raise ManifestError(f"{path}.evidence_status must be one of {sorted(EVIDENCE_STATUSES)}")
        uncertainty_visible = _bool(
            entry.get("uncertainty_visible"), path + ".uncertainty_visible"
        )
        mitigation = entry.get("mitigation")
        if mitigation is not None:
            _text(mitigation, path + ".mitigation")
        if material and (not trigger or not consequence):
            findings.append(
                _finding(
                    "MATERIAL_RISK_CHAIN_INCOMPLETE",
                    path,
                    "A material risk requires both trigger and consequence.",
                )
            )
        if evidence_status != "VERIFIED" and not uncertainty_visible:
            findings.append(
                _finding(
                    "RISK_SUPPORT_HIDDEN",
                    path,
                    "Unverified risk support is not visible as uncertainty.",
                )
            )
        if mode == "RISK_NOTE" and material and not mitigation:
            findings.append(
                _finding(
                    "RISK_MITIGATION_MISSING",
                    path + ".mitigation",
                    "A material RISK_NOTE item requires mitigation or a lawful alternative.",
                )
            )

    recommendations = _list(data.get("recommendations"), "$.recommendations")
    if mode == "BOARD_NOTE" and not recommendations:
        findings.append(
            _finding("BOARD_RECOMMENDATION_MISSING", "$.recommendations", "BOARD_NOTE requires a recommendation.")
        )
    if mode == "RISK_NOTE" and not recommendations:
        findings.append(
            _finding(
                "LAWFUL_COURSE_MISSING",
                "$.recommendations",
                "RISK_NOTE requires a recommended lawful course.",
            )
        )
    for index, item in enumerate(recommendations):
        path = f"$.recommendations[{index}]"
        entry = _mapping(item, path)
        _text(entry.get("text"), path + ".text")
        lawful = _bool(entry.get("lawful"), path + ".lawful")
        depends = _bool(
            entry.get("depends_on_unverified_decisive_fact"),
            path + ".depends_on_unverified_decisive_fact",
        )
        if not lawful:
            findings.append(
                _finding(
                    "UNLAWFUL_RECOMMENDATION",
                    path,
                    "Non-compliance is framed as a recommendation rather than a separate consequence.",
                )
            )
        if depends:
            findings.append(
                _finding(
                    "RECOMMENDATION_ON_DECISIVE_GAP",
                    path,
                    "A recommendation depends on an unverified decisive fact.",
                )
            )

    source_status = _mapping(data.get("source_status"), "$.source_status")
    trace_preserved = _bool(
        source_status.get("lawyer_trace_preserved"),
        "$.source_status.lawyer_trace_preserved",
    )
    diary = _bool(
        source_status.get("main_reasoning_contains_research_diary"),
        "$.source_status.main_reasoning_contains_research_diary",
    )
    gaps_inventoried = _bool(
        source_status.get("material_gaps_inventoried"),
        "$.source_status.material_gaps_inventoried",
    )
    if not gaps_inventoried:
        findings.append(
            _finding(
                "GAP_INVENTORY_INCOMPLETE",
                "$.source_status.material_gaps_inventoried",
                "Material gaps were not affirmatively inventoried before the reader-facing check.",
            )
        )
    if not trace_preserved:
        findings.append(
            _finding(
                "TRACE_NOT_PRESERVED",
                "$.source_status.lawyer_trace_preserved",
                "Unresolved gaps exist but the lawyer/support trace is not preserved.",
            )
        )
    if diary:
        findings.append(
            _finding(
                "RESEARCH_DIARY_IN_MAIN",
                "$.source_status.main_reasoning_contains_research_diary",
                "Research process is narrated in the main reader-facing reasoning.",
            )
        )

    quality = _mapping(data.get("quality"), "$.quality")
    quality_codes = {
        "duplicate_propositions": "DUPLICATE_PROPOSITIONS",
        "ceremonial_opening": "CEREMONIAL_OPENING",
        "remote_sanctions_padding": "REMOTE_SANCTIONS_PADDING",
        "weak_source_detour": "WEAK_SOURCE_DETOUR",
        "internal_markers_in_business_copy": "INTERNAL_MARKERS_IN_BUSINESS_COPY",
    }
    for field, code in quality_codes.items():
        if _bool(quality.get(field), "$.quality." + field):
            findings.append(_finding(code, "$.quality." + field, field.replace("_", " ") + " detected."))

    mode_requirements = _mapping(data.get("mode_requirements"), "$.mode_requirements")
    mode_flags = {
        "SHORT_ANSWER": ["background_section_absent"],
        "BUSINESS_EMAIL": [
            "subject_states_decision_or_effect",
            "close_is_action_or_question",
        ],
        "LEGAL_MEMO": ["analysis_by_issue", "source_status_block_present"],
        "BOARD_NOTE": ["decision_requested_present"],
        "LEGAL_DIGEST": [
            "effect_headline_present",
            "scope_present",
            "date_or_status_present",
        ],
        "RISK_NOTE": ["residual_risk_present"],
        "EDIT_EXISTING_TEXT": ["paragraph_jobs_classified"],
    }
    for field in mode_flags[mode]:
        if not _bool(mode_requirements.get(field), "$.mode_requirements." + field):
            findings.append(
                _finding(
                    "MODE_REQUIREMENT_MISSING",
                    "$.mode_requirements." + field,
                    f"{mode} requires {field}.",
                )
            )

    error_codes = {finding.code for finding in findings if finding.severity == "ERROR"}
    if error_codes & {
        "UNLAWFUL_RECOMMENDATION",
        "TRACE_NOT_PRESERVED",
        "UNCERTAINTY_TRACE_HIDDEN",
        "UNCERTAINTY_TRACE_INCOMPLETE",
        "GAP_INVENTORY_INCOMPLETE",
    }:
        outcome = "HANDOFF_REQUIRED"
    elif error_codes & {
        "DECISIVE_GAP_UNBRANCHED",
        "DECISIVE_UNCERTAINTY_NOT_EXPLICIT",
        "DECISIVE_GAP_NOT_IN_INVENTORY",
        "ANSWER_GAP_MISMATCH",
        "RECOMMENDATION_ON_DECISIVE_GAP",
    }:
        outcome = "BLOCKED_DECISIVE_GAP"
    elif error_codes:
        outcome = "NEEDS_REVISION"
    else:
        outcome = "READY_FOR_REVIEW"

    return {
        "schema": "business_writing_check.v1",
        "outcome": outcome,
        "mode": mode,
        "findings": [asdict(finding) for finding in findings],
        "limitations": [
            "This check does not validate law, facts, source authority, rendered text or business merits.",
            "READY_FOR_REVIEW does not replace profile skill gates or human legal review.",
        ],
    }


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check_manifest(_load(args.manifest))
    except ManifestError as exc:
        print(json.dumps({"schema": "business_writing_check.v1", "outcome": "INVALID_MANIFEST", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["outcome"] == "READY_FOR_REVIEW" else 1


if __name__ == "__main__":
    sys.exit(main())
