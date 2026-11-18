#!/usr/bin/env python3
"""Read-only consistency check for one case-law research issue.

The checker does not search, interpret law, decide relevance, or assign human review
statuses.  It validates the research manifest, derives the admissible counted set and
keeps practice classification separate from research completion.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from .practice_status import PracticeInput, classify
except ImportError:  # pragma: no cover - standalone CLI
    from practice_status import PracticeInput, classify


PASS_ROLES = {"standalone", "supporting", "adverse"}
DIRECTIONS = {"SUPPORT", "OPPOSE", "NEUTRAL"}
AUTHORITIES = {"A1", "A2", "A3", "A4", "B1", "B2", "B3", "X"}
ATTRIBUTIONS = {"HOLDING", "REASONING", "PARTY_POSITION", "SYNTHESIS", "COMMENTARY"}
JUDICIAL_ATTRIBUTIONS = {"HOLDING", "REASONING"}
HISTORY = {"CURRENT", "PARTIALLY_REVERSED", "REVERSED", "UNKNOWN"}
FITS = {"MATCH", "PARTIAL", "NO", "UNKNOWN"}
ANALOGY_MODES = {"DIRECT_LEGAL", "FACTUAL_ARGUMENTATIVE"}
REASONING_LINKS = {"explicit", "strong_implicit", "weak_inference", "background"}
LINEAGE_MODES = {"ORIGINAL", "INDEPENDENT_APPLICATION", "COPY"}
DIVERGENCE_TYPES = {"FACTUAL", "LEGAL", "MIXED", "TEMPORAL", "UNEXPLAINED"}
CHECK_STATUSES = {"DONE", "PENDING", "UNAVAILABLE"}
OPPOSITION_STATUSES = {"FOUND", "NOT_FOUND_IN_TARGETED_SEARCH", "NOT_SEARCHED"}
OUTCOMES = {"READY_FOR_HANDOFF", "CONTINUE_TARGETED", "STOP_WITH_GAPS", "HANDOFF_REQUIRED"}
REQUIRED_CHECKS = {
    "source_opened",
    "later_history",
    "legal_regime_fit",
    "issue_fit",
    "adverse_search",
    "conflicts_assessed",
}
HIGH_AUTHORITY = {"A1": "a1", "A2": "a2", "A4": "a4"}
AUTHORITY_PRIORITY = {"A1": 0, "A2": 1, "A4": 2, "A3": 3, "B1": 4, "B2": 5, "B3": 6}


@dataclass
class CheckResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counted_case_ids: list[str] = field(default_factory=list)
    excluded_cases: dict[str, list[str]] = field(default_factory=dict)
    independent_units: list[dict[str, Any]] = field(default_factory=list)
    derived_practice_input: dict[str, Any] = field(default_factory=dict)
    practice_status: dict[str, Any] = field(default_factory=dict)
    coverage_gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    outcome: str = "CONTINUE_TARGETED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected mapping")
        return {}
    return value


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _enum(value: Any, choices: set[str], path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or value not in choices:
        errors.append(f"{path}: expected one of {sorted(choices)}")
        return False
    return True


def _refs(value: Any, path: str, errors: list[str], *, required: bool = True) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value) or any(not _nonempty(v) for v in value):
        errors.append(f"{path}: expected {'non-empty ' if required else ''}list of non-empty strings")
        return []
    return value


def _case_exclusions(case: dict[str, Any], errors: list[str]) -> list[str]:
    cid = str(case.get("id", "<unknown>"))
    reasons: list[str] = []
    required = ("id", "dispute_id", "issue_ref", "proposition_ref", "direction", "authority", "circuit")
    for key in required:
        if not _nonempty(case.get(key)):
            errors.append(f"cases[{cid}].{key}: required non-empty string")

    direction = case.get("direction")
    if not _enum(direction, DIRECTIONS, f"cases[{cid}].direction", errors):
        reasons.append("invalid_direction")
    if direction == "NEUTRAL":
        reasons.append("neutral_direction")

    authority = case.get("authority")
    if not _enum(authority, AUTHORITIES, f"cases[{cid}].authority", errors):
        reasons.append("invalid_authority")
    if authority == "X":
        reasons.append("refusal_or_non_substantive")

    if case.get("opened") is not True:
        reasons.append("source_not_opened")

    history = _mapping(case.get("history"), f"cases[{cid}].history", errors)
    history_status = history.get("status")
    if not _enum(history_status, HISTORY, f"cases[{cid}].history.status", errors):
        reasons.append("history_invalid")
    elif history_status in {"REVERSED", "UNKNOWN"}:
        reasons.append(f"history_{history_status.lower()}")
    elif history_status == "PARTIALLY_REVERSED":
        if not _nonempty(history.get("surviving_scope")) or history.get("scope_confirmed") is not True:
            reasons.append("partial_history_scope_unconfirmed")
    if isinstance(history_status, str) and history_status in {"CURRENT", "PARTIALLY_REVERSED"}:
        _refs(history.get("source_refs"), f"cases[{cid}].history.source_refs", errors)

    for key in ("legal_regime_fit", "issue_fit"):
        value = case.get(key)
        if not _enum(value, FITS, f"cases[{cid}].{key}", errors):
            reasons.append(f"invalid_{key}")
        elif value != "MATCH":
            reasons.append(f"{key}_{str(value).lower()}")

    analogy_mode = case.get("analogy_mode")
    if not _enum(analogy_mode, ANALOGY_MODES, f"cases[{cid}].analogy_mode", errors):
        reasons.append("invalid_analogy_mode")
    elif analogy_mode == "FACTUAL_ARGUMENTATIVE":
        reasons.append("factual_argument_only")
        _enum(case.get("reasoning_link"), REASONING_LINKS, f"cases[{cid}].reasoning_link", errors)

    attrs = case.get("attributions")
    if not isinstance(attrs, list) or not attrs:
        errors.append(f"cases[{cid}].attributions: non-empty list required")
        reasons.append("no_judicial_attribution")
    else:
        judicial = False
        for i, attr in enumerate(attrs):
            attr = _mapping(attr, f"cases[{cid}].attributions[{i}]", errors)
            role = attr.get("type")
            role_valid = _enum(role, ATTRIBUTIONS, f"cases[{cid}].attributions[{i}].type", errors)
            if not _nonempty(attr.get("locator")):
                errors.append(f"cases[{cid}].attributions[{i}].locator: required")
            judicial = judicial or (role_valid and role in JUDICIAL_ATTRIBUTIONS)
        if not judicial:
            reasons.append("no_judicial_attribution")

    raw_lineage = case.get("citation_lineage")
    lineage = _mapping(raw_lineage, f"cases[{cid}].citation_lineage", errors)
    if not isinstance(raw_lineage, dict):
        reasons.append("invalid_citation_lineage")
    mode = lineage.get("mode")
    if not _enum(mode, LINEAGE_MODES, f"cases[{cid}].citation_lineage.mode", errors):
        reasons.append("invalid_citation_lineage_mode")
    if mode == "COPY" and not _nonempty(lineage.get("root_ref")):
        errors.append(f"cases[{cid}].citation_lineage.root_ref: required for COPY")
    if not _nonempty(lineage.get("explanation")):
        errors.append(f"cases[{cid}].citation_lineage.explanation: required")

    return sorted(set(reasons))


def _base_unit_key(case: dict[str, Any]) -> tuple[str, str, str]:
    return (str(case.get("proposition_ref", "")), str(case.get("issue_ref", "")), str(case.get("dispute_id", "")))


def _canonical_unit_key(
    case: dict[str, Any],
    cases_by_id: dict[str, dict[str, Any]],
    errors: list[str],
    stack: tuple[str, ...] = (),
) -> tuple[str, str, str] | None:
    cid = str(case.get("id", ""))
    lineage = case.get("citation_lineage") or {}
    if lineage.get("mode") != "COPY":
        return _base_unit_key(case)
    root_ref = lineage.get("root_ref")
    if not _nonempty(root_ref) or root_ref not in cases_by_id:
        errors.append(f"cases[{cid}].citation_lineage.root_ref: COPY must reference a case id in this manifest")
        return None
    if cid in stack or root_ref in stack:
        errors.append(f"cases[{cid}].citation_lineage.root_ref: citation lineage cycle")
        return None
    root = cases_by_id[root_ref]
    if root.get("issue_ref") != case.get("issue_ref") or root.get("proposition_ref") != case.get("proposition_ref"):
        errors.append(f"cases[{cid}].citation_lineage.root_ref: root must have the same issue and proposition")
        return None
    return _canonical_unit_key(root, cases_by_id, errors, stack + (cid,))


def _representative(group: list[dict[str, Any]]) -> dict[str, Any]:
    original_or_application = [c for c in group if (c.get("citation_lineage") or {}).get("mode") != "COPY"]
    candidates = original_or_application or group
    return sorted(candidates, key=lambda c: (AUTHORITY_PRIORITY.get(str(c.get("authority")), 99), str(c.get("id"))))[0]


def _derive_practice_input(units: list[dict[str, Any]]) -> dict[str, Any]:
    flags = {"a1": False, "a2": False, "a4": False}
    skes_units = 0
    support_circuits: set[str] = set()
    oppose_circuits: set[str] = set()
    support_decisions = 0
    for unit in units:
        case = unit["representative"]
        direction = case["direction"]
        authority = case["authority"]
        if direction == "SUPPORT":
            support_decisions += 1
            if authority in HIGH_AUTHORITY:
                flags[HIGH_AUTHORITY[authority]] = True
            if authority == "A3":
                skes_units += 1
            if authority == "B1" and case.get("circuit"):
                support_circuits.add(str(case["circuit"]))
        elif direction == "OPPOSE" and authority == "B1" and case.get("circuit"):
            oppose_circuits.add(str(case["circuit"]))
    return {
        **flags,
        "skes": skes_units,
        "circuits_support": len(support_circuits),
        "circuits_oppose": len(oppose_circuits),
        "decisions_support": support_decisions,
    }


def check_manifest(data: Any) -> CheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    root = _mapping(data, "manifest", errors)
    if root.get("version") != "case_law_research.v1":
        errors.append("version: expected case_law_research.v1")

    issue = _mapping(root.get("issue"), "issue", errors)
    proposition = _mapping(root.get("proposition"), "proposition", errors)
    for obj, path in ((issue, "issue"), (proposition, "proposition")):
        if not _nonempty(obj.get("id")) or not _nonempty(obj.get("text")):
            errors.append(f"{path}: id and text are required")
    role = root.get("pass_role")
    _enum(role, PASS_ROLES, "pass_role", errors)
    if not _nonempty(root.get("purpose")):
        errors.append("purpose: required")
    regime = _mapping(root.get("legal_regime"), "legal_regime", errors)
    if not _nonempty(regime.get("description")):
        errors.append("legal_regime.description: required")
    _refs(regime.get("source_refs"), "legal_regime.source_refs", errors)

    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        errors.append("cases: expected list")
        raw_cases = []
    seen_ids: set[str] = set()
    excluded: dict[str, list[str]] = {}
    admissible: list[dict[str, Any]] = []
    for raw in raw_cases:
        case = _mapping(raw, "cases[]", errors)
        cid = str(case.get("id", "<unknown>"))
        if cid in seen_ids:
            errors.append(f"cases[{cid}]: duplicate id")
        seen_ids.add(cid)
        reasons = _case_exclusions(case, errors)
        if case.get("issue_ref") != issue.get("id"):
            reasons.append("different_issue")
        if case.get("proposition_ref") != proposition.get("id"):
            reasons.append("different_proposition")
        if reasons:
            excluded[cid] = sorted(set(reasons))
        else:
            admissible.append(case)

    # One proceeding and one issue are one independent line. COPY resolves to the
    # canonical in-manifest root; independent applications retain their proceedings.
    cases_by_id = {str(case["id"]): case for case in admissible}
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for case in admissible:
        key = _canonical_unit_key(case, cases_by_id, errors)
        if key is None:
            excluded[str(case["id"])] = ["invalid_copy_lineage"]
            continue
        grouped.setdefault(key, []).append(case)
    units: list[dict[str, Any]] = []
    duplicate_ids: dict[tuple[str, str, str], list[str]] = {}
    line_conflicts: list[str] = []
    for key, group in grouped.items():
        directions = {str(c["direction"]) for c in group}
        if len(directions) > 1:
            ids = [str(c["id"]) for c in group]
            line_conflicts.append(f"independent line {key[2]}: conflicting directions in {', '.join(ids)}")
            for case in group:
                excluded[str(case["id"])] = ["same_line_direction_conflict"]
            continue
        representative = _representative(group)
        substantive_group = [c for c in group if (c.get("citation_lineage") or {}).get("mode") != "COPY"] or group
        unit_circuits = sorted({str(c["circuit"]) for c in substantive_group if c.get("authority") == "B1"})
        if len(unit_circuits) > 1:
            line_conflicts.append(f"independent line {key[2]}: multiple cassation circuits {', '.join(unit_circuits)}")
            for case in group:
                excluded[str(case["id"])] = ["same_line_multiple_circuits"]
            continue
        units.append({"key": key, "representative": representative, "cases": group, "substantive_cases": substantive_group})
        if len(group) > 1:
            duplicate_ids[key] = [str(c["id"]) for c in group]
            for case in group:
                if case is not representative:
                    reason = "copy_of_canonical_root" if (case.get("citation_lineage") or {}).get("mode") == "COPY" else "same_independent_line"
                    excluded[str(case["id"])] = [reason]
    if duplicate_ids:
        warnings.append("multiple acts collapsed to one dispute+issue or one copy lineage")

    derived = _derive_practice_input(units)
    declared = root.get("practice_input")
    if declared is not None:
        declared = _mapping(declared, "practice_input", errors)
        for key, expected in derived.items():
            if declared.get(key) != expected:
                errors.append(f"practice_input.{key}: declared {declared.get(key)!r}, derived {expected!r}")
    practice = classify(PracticeInput(**derived)).to_dict()

    conflicts: list[str] = list(line_conflicts)
    by_circuit: dict[str, set[str]] = {}
    for unit in units:
        case = unit["representative"]
        if case.get("authority") == "B1":
            by_circuit.setdefault(str(case.get("circuit")), set()).add(str(case.get("direction")))
    for circuit, directions in sorted(by_circuit.items()):
        if {"SUPPORT", "OPPOSE"}.issubset(directions):
            conflicts.append(f"circuit {circuit}: SUPPORT and OPPOSE")

    coverage = _mapping(root.get("coverage"), "coverage", errors)
    checks = _mapping(coverage.get("checks"), "coverage.checks", errors)
    missing_checks = REQUIRED_CHECKS - set(checks)
    if missing_checks:
        errors.append(f"coverage.checks: missing {', '.join(sorted(missing_checks))}")
    gaps: list[str] = []
    for name in sorted(REQUIRED_CHECKS):
        item = _mapping(checks.get(name), f"coverage.checks.{name}", errors)
        status = item.get("status")
        status_valid = _enum(status, CHECK_STATUSES, f"coverage.checks.{name}.status", errors)
        if not status_valid:
            gaps.append(name)
        elif status != "DONE":
            gaps.append(name)
        if status == "DONE":
            _refs(item.get("evidence_refs"), f"coverage.checks.{name}.evidence_refs", errors)
        if status != "DONE" and not _nonempty(item.get("reason")):
            errors.append(f"coverage.checks.{name}.reason: required when not DONE")

    opposition = _mapping(coverage.get("targeted_opposition"), "coverage.targeted_opposition", errors)
    opposition_status = opposition.get("status")
    if not _enum(opposition_status, OPPOSITION_STATUSES, "coverage.targeted_opposition.status", errors):
        gaps.append("targeted_opposition")
    elif opposition_status == "NOT_SEARCHED":
        gaps.append("targeted_opposition")
    else:
        _refs(opposition.get("search_refs"), "coverage.targeted_opposition.search_refs", errors)
    has_oppose = any(c.get("direction") == "OPPOSE" for c in admissible)
    if has_oppose and opposition_status != "FOUND":
        errors.append("coverage.targeted_opposition.status: OPPOSE case is present, expected FOUND")
        gaps.append("targeted_opposition")

    has_support = any(c.get("direction") == "SUPPORT" for c in admissible)
    synthesis = _mapping(root.get("synthesis", {}), "synthesis", errors)
    divergences = synthesis.get("divergences", [])
    if not isinstance(divergences, list):
        errors.append("synthesis.divergences: expected list")
        divergences = []
    if has_support and has_oppose and not divergences:
        errors.append("synthesis.divergences: required when SUPPORT and OPPOSE are both present")
    limitations: list[str] = []
    for i, raw_divergence in enumerate(divergences):
        div = _mapping(raw_divergence, f"synthesis.divergences[{i}]", errors)
        dtype = div.get("type")
        _enum(dtype, DIVERGENCE_TYPES, f"synthesis.divergences[{i}].type", errors)
        if not _nonempty(div.get("explanation")):
            errors.append(f"synthesis.divergences[{i}].explanation: required")
        case_refs = _refs(div.get("case_refs"), f"synthesis.divergences[{i}].case_refs", errors)
        for case_ref in case_refs:
            if case_ref not in seen_ids:
                errors.append(f"synthesis.divergences[{i}].case_refs: unknown case id {case_ref}")
        if dtype == "FACTUAL":
            _refs(div.get("reasoning_refs"), f"synthesis.divergences[{i}].reasoning_refs", errors)
        if dtype == "TEMPORAL":
            _refs(div.get("regime_refs"), f"synthesis.divergences[{i}].regime_refs", errors)
        if dtype == "UNEXPLAINED":
            if not _nonempty(div.get("limitation")):
                errors.append(f"synthesis.divergences[{i}].limitation: required for UNEXPLAINED")
            else:
                limitations.append(str(div["limitation"]))
                gaps.append("unexplained_divergence")

    unresolved = coverage.get("unresolved_conflicts", [])
    if not isinstance(unresolved, list):
        errors.append("coverage.unresolved_conflicts: expected list")
        unresolved = []
    elif any(not _nonempty(item) for item in unresolved):
        errors.append("coverage.unresolved_conflicts: expected non-empty strings")
    if unresolved or conflicts:
        gaps.append("unresolved_conflicts")

    caller_pending = coverage.get("caller_pending", [])
    if not isinstance(caller_pending, list):
        errors.append("coverage.caller_pending: expected list")
        caller_pending = []
    else:
        for i, item in enumerate(caller_pending):
            item = _mapping(item, f"coverage.caller_pending[{i}]", errors)
            if not _nonempty(item.get("check")) or not _nonempty(item.get("reason")):
                errors.append(f"coverage.caller_pending[{i}]: check and reason are required")
    constraints = _mapping(coverage.get("constraints", {}), "coverage.constraints", errors)
    unavailable = _refs(constraints.get("unavailable", []), "coverage.constraints.unavailable", errors, required=False)
    cap_reached = constraints.get("cap_reached")
    if cap_reached is not None and not isinstance(cap_reached, bool):
        errors.append("coverage.constraints.cap_reached: expected boolean")
    constrained = cap_reached is True or bool(unavailable)

    gaps = sorted(set(gaps))
    if caller_pending:
        outcome = "HANDOFF_REQUIRED"
    elif gaps and constrained:
        outcome = "STOP_WITH_GAPS"
    elif gaps:
        outcome = "CONTINUE_TARGETED"
    else:
        outcome = "READY_FOR_HANDOFF"

    claimed = root.get("claimed_outcome")
    if claimed is not None:
        if not _enum(claimed, OUTCOMES, "claimed_outcome", errors):
            pass
        elif claimed != outcome:
            errors.append(f"claimed_outcome: {claimed} inconsistent with derived {outcome}")

    if practice["established"] and gaps:
        warnings.append("established is only a candidate practice status; coverage remains incomplete")
    if opposition_status == "NOT_FOUND_IN_TARGETED_SEARCH":
        warnings.append("targeted search found no opposition; this does not prove that opposition does not exist")
    if role == "supporting" and opposition_status == "NOT_SEARCHED" and not caller_pending:
        errors.append("supporting pass with NOT_SEARCHED opposition must hand the pending check to caller_pending")

    return CheckResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        counted_case_ids=[str(unit["representative"]["id"]) for unit in units],
        excluded_cases=excluded,
        independent_units=[
            {
                "representative_case_id": str(unit["representative"]["id"]),
                "counted_authority": str(unit["representative"]["authority"]),
                "case_ids": sorted(str(c["id"]) for c in unit["cases"]),
                "copy_case_ids": sorted(
                    str(c["id"]) for c in unit["cases"]
                    if (c.get("citation_lineage") or {}).get("mode") == "COPY"
                ),
                "issue_ref": str(unit["key"][1]),
                "dispute_id": str(unit["key"][2]),
                "authorities": sorted({str(c["authority"]) for c in unit["substantive_cases"]}, key=lambda a: AUTHORITY_PRIORITY.get(a, 99)),
                "circuits": sorted({str(c["circuit"]) for c in unit["substantive_cases"] if c.get("authority") == "B1"}),
            }
            for unit in units
        ],
        derived_practice_input=derived,
        practice_status=practice,
        coverage_gaps=gaps,
        conflicts=conflicts,
        limitations=limitations,
        outcome=outcome,
    )


def load_manifest(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="YAML/JSON manifest for one research issue")
    args = parser.parse_args(argv)
    result = check_manifest(load_manifest(args.manifest))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.valid else 2


if __name__ == "__main__":
    raise SystemExit(run())
