#!/usr/bin/env python3
"""Read-only validation of a procedural argument manifest.

The checker validates explicit traceability supplied by the drafting workflow. It does
not interpret law, decide whether a proposition is true, parse a DOCX for meaning, or
promote source, human-review, or factual statuses.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


SCHEMA = "procedural_argument.v1"
STRUCTURE_MODES = {"CLAIM_BASED", "DEFENSE_BASED", "ERROR_BASED", "FORMAL"}
ARGUMENT_KINDS = {"FACTUAL", "LEGAL", "MIXED"}
PROPOSITION_TYPES = {"FACT", "LEGAL", "MIXED"}
FACT_STATUSES = {"ESTABLISHED", "ALLEGED", "CONTESTED", "UNKNOWN"}
LEGAL_STATUSES = {"VERIFIED", "CANDIDATE", "UNVERIFIED"}
ADVERSE_STATUSES = {"DONE", "HANDOFF", "NOT_REQUIRED", "PENDING"}
CRITIC_STATUSES = {"DONE", "PENDING", "NOT_REQUIRED"}
ERROR_TYPES = {"FACTUAL", "LEGAL", "PROCEDURAL", "MIXED"}
OUTCOMES = {"READY_FOR_RENDER", "BLOCKED_MATERIAL_GAP", "HANDOFF_REQUIRED", "LIMITED_DRAFT"}
SCOPE_KEYS = {
    "claim_refs",
    "element_refs",
    "fact_refs",
    "issue_refs",
    "response_refs",
    "proof_issue_refs",
    "case_law_refs",
    "evidence_refs",
    "authority_refs",
}


@dataclass
class DraftCheckResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    material_gaps: list[str] = field(default_factory=list)
    handoffs: list[str] = field(default_factory=list)
    orphan_evidence: list[str] = field(default_factory=list)
    outcome: str = "BLOCKED_MATERIAL_GAP"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected mapping")
        return {}
    return value


def _list(value: Any, path: str, errors: list[str], *, required: bool = False) -> list[Any]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        errors.append(f"{path}: expected {'non-empty ' if required else ''}list")
        return []
    return value


def _text(value: Any, path: str, errors: list[str], *, required: bool = True) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if required:
        errors.append(f"{path}: required non-empty string")
    return ""


def _enum(value: Any, choices: set[str], path: str, errors: list[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        errors.append(f"{path}: expected one of {sorted(choices)}")
        return ""
    return value


def _refs(value: Any, path: str, errors: list[str], *, required: bool = False) -> list[str]:
    values = _list(value, path, errors, required=required)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        errors.append(f"{path}: expected non-empty string refs")
        return []
    return [item.strip() for item in values]


def _unique(items: list[dict[str, Any]], path: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(items):
        item = _mapping(item, f"{path}[{i}]", errors)
        item_id = _text(item.get("id"), f"{path}[{i}].id", errors)
        if not item_id:
            continue
        if item_id in indexed:
            errors.append(f"{path}[{i}].id: duplicate {item_id}")
        else:
            indexed[item_id] = item
    return indexed


def _check_in_scope(refs: list[str], allowed: set[str], path: str, errors: list[str]) -> None:
    for ref in refs:
        if ref not in allowed:
            errors.append(f"{path}: ref {ref} is outside analysis_scope")


def check_manifest(data: Any) -> DraftCheckResult:
    """Validate a manifest without modifying it and derive the pre-render outcome."""
    original = copy.deepcopy(data)
    errors: list[str] = []
    warnings: list[str] = []
    gaps: list[str] = []
    handoffs: list[str] = []
    orphans: list[str] = []

    root = _mapping(data, "manifest", errors)
    if root.get("schema") != SCHEMA:
        errors.append(f"schema: expected {SCHEMA}")

    document = _mapping(root.get("document"), "document", errors)
    _text(document.get("type"), "document.type", errors)
    _text(document.get("stage"), "document.stage", errors)
    mode = _enum(document.get("structure_mode"), STRUCTURE_MODES, "document.structure_mode", errors)
    requested_outcomes = _refs(
        document.get("requested_outcomes"),
        "document.requested_outcomes",
        errors,
        required=mode != "FORMAL",
    )

    scope = _mapping(root.get("analysis_scope"), "analysis_scope", errors)
    unknown_scope = sorted(set(scope) - SCOPE_KEYS)
    if unknown_scope:
        warnings.append(f"analysis_scope: unrecognized keys {unknown_scope}")
    allowed: dict[str, set[str]] = {}
    for key in SCOPE_KEYS:
        allowed[key] = set(_refs(scope.get(key, []), f"analysis_scope.{key}", errors))

    raw_props = _list(root.get("material_propositions"), "material_propositions", errors)
    props = _unique(raw_props, "material_propositions", errors)
    visible_markers: dict[str, str] = {}
    proposition_types: dict[str, str] = {}
    proposition_analysis_refs: dict[str, set[str]] = {}
    proposition_fact_refs: dict[str, set[str]] = {}
    proposition_source_refs: dict[str, set[str]] = {}
    proposition_authority_refs: dict[str, set[str]] = {}
    for prop_id, prop in props.items():
        prefix = f"material_propositions[{prop_id}]"
        prop_type = _enum(prop.get("type"), PROPOSITION_TYPES, f"{prefix}.type", errors)
        proposition_types[prop_id] = prop_type
        _text(prop.get("text"), f"{prefix}.text", errors)
        material = prop.get("material") is True
        if isinstance(prop.get("marker"), str) and prop.get("marker", "").strip():
            visible_markers[prop_id] = prop["marker"].strip()
        if not isinstance(prop.get("material"), bool):
            errors.append(f"{prefix}.material: expected boolean")
        analysis_refs = _refs(prop.get("analysis_refs"), f"{prefix}.analysis_refs", errors, required=material)
        proposition_analysis_refs[prop_id] = set(analysis_refs)
        allowed_analysis = set().union(
            allowed["claim_refs"],
            allowed["element_refs"],
            allowed["fact_refs"],
            allowed["issue_refs"],
            allowed["response_refs"],
            allowed["proof_issue_refs"],
        )
        _check_in_scope(analysis_refs, allowed_analysis, f"{prefix}.analysis_refs", errors)

        if prop_type in {"FACT", "MIXED"}:
            fact_status = _enum(prop.get("fact_status"), FACT_STATUSES, f"{prefix}.fact_status", errors)
            source_refs = _refs(prop.get("source_refs"), f"{prefix}.source_refs", errors)
            _check_in_scope(source_refs, allowed["evidence_refs"], f"{prefix}.source_refs", errors)
            fact_analysis_refs = set(analysis_refs) & allowed["fact_refs"]
            proposition_fact_refs[prop_id] = fact_analysis_refs
            proposition_source_refs[prop_id] = set(source_refs)
            if material and not fact_analysis_refs:
                gaps.append(f"{prop_id}: material fact has no approved fact ref")
            if material and not source_refs:
                gaps.append(f"{prop_id}: material fact has no source ref")
            if fact_status in {"ALLEGED", "CONTESTED", "UNKNOWN"}:
                marker = _text(prop.get("marker"), f"{prefix}.marker", errors, required=False)
                if not marker:
                    gaps.append(f"{prop_id}: {fact_status} fact has no visible marker")

        if prop_type in {"LEGAL", "MIXED"}:
            legal_status = _enum(prop.get("legal_status"), LEGAL_STATUSES, f"{prefix}.legal_status", errors)
            authority_refs = _refs(prop.get("authority_refs"), f"{prefix}.authority_refs", errors)
            proposition_authority_refs[prop_id] = set(authority_refs)
            passage_refs = _refs(prop.get("passage_refs"), f"{prefix}.passage_refs", errors)
            _check_in_scope(authority_refs, allowed["authority_refs"], f"{prefix}.authority_refs", errors)
            if material and (not authority_refs or not passage_refs):
                gaps.append(f"{prop_id}: material legal proposition lacks authority or passage")
            if material and not (set(analysis_refs) & allowed["issue_refs"]):
                gaps.append(f"{prop_id}: material legal proposition has no approved issue ref")
            if material and legal_status != "VERIFIED":
                marker = _text(prop.get("marker"), f"{prefix}.marker", errors, required=False)
                if not marker:
                    gaps.append(f"{prop_id}: {legal_status or 'invalid'} legal proposition has no visible marker")
                else:
                    handoffs.append(f"{prop_id}: source verification required")

    raw_args = _list(root.get("arguments"), "arguments", errors, required=mode != "FORMAL")
    arguments = _unique(raw_args, "arguments", errors)
    argument_fact_refs: dict[str, set[str]] = {}
    argument_proposition_refs: dict[str, set[str]] = {}
    argument_rule_refs: dict[str, set[str]] = {}
    for argument_id, argument in arguments.items():
        prefix = f"arguments[{argument_id}]"
        kind = _enum(argument.get("kind"), ARGUMENT_KINDS, f"{prefix}.kind", errors)
        material = argument.get("material") is True
        if isinstance(argument.get("marker"), str) and argument.get("marker", "").strip():
            visible_markers[argument_id] = argument["marker"].strip()
        if not isinstance(argument.get("material"), bool):
            errors.append(f"{prefix}.material: expected boolean")
        heading = _mapping(argument.get("heading"), f"{prefix}.heading", errors)
        if material:
            _text(heading.get("conclusion"), f"{prefix}.heading.conclusion", errors)
            _text(heading.get("principal_reason"), f"{prefix}.heading.principal_reason", errors)
        issue_ref = _text(argument.get("issue_ref"), f"{prefix}.issue_ref", errors, required=material)
        if issue_ref and issue_ref not in allowed["issue_refs"]:
            errors.append(f"{prefix}.issue_ref: ref {issue_ref} is outside analysis_scope")
        _text(argument.get("conclusion"), f"{prefix}.conclusion", errors, required=material)
        _text(argument.get("result"), f"{prefix}.result", errors, required=material)

        proposition_refs = _refs(argument.get("proposition_refs"), f"{prefix}.proposition_refs", errors, required=material)
        argument_proposition_refs[argument_id] = set(proposition_refs)
        linked_props: list[dict[str, Any]] = []
        for ref in proposition_refs:
            if ref not in props:
                errors.append(f"{prefix}.proposition_refs: unknown proposition {ref}")
            else:
                linked_props.append(props[ref])
        material_linked = [prop for prop in linked_props if prop.get("material") is True]
        nonmaterial_linked_refs = [
            ref for ref in proposition_refs if ref in props and props[ref].get("material") is not True
        ]
        if material and nonmaterial_linked_refs:
            gaps.append(
                f"{argument_id}: material argument links nonmaterial propositions "
                + ", ".join(sorted(nonmaterial_linked_refs))
            )
        if material and not material_linked:
            gaps.append(f"{argument_id}: material argument has no material proposition")
        material_linked_refs = [
            ref for ref in proposition_refs if ref in props and props[ref].get("material") is True
        ]
        if material and kind in {"FACTUAL", "MIXED"} and not any(
            proposition_types.get(ref) in {"FACT", "MIXED"} for ref in material_linked_refs
        ):
            gaps.append(f"{argument_id}: material factual argument has no material factual proposition")
        if material and kind in {"LEGAL", "MIXED"} and not any(
            proposition_types.get(ref) in {"LEGAL", "MIXED"} for ref in material_linked_refs
        ):
            gaps.append(f"{argument_id}: material legal argument has no material legal proposition")
        fact_refs = _refs(argument.get("application_fact_refs"), f"{prefix}.application_fact_refs", errors)
        argument_fact_refs[argument_id] = set(fact_refs)
        _check_in_scope(fact_refs, allowed["fact_refs"], f"{prefix}.application_fact_refs", errors)
        rule_refs = _refs(argument.get("rule_refs"), f"{prefix}.rule_refs", errors)
        argument_rule_refs[argument_id] = set(rule_refs)
        _check_in_scope(rule_refs, allowed["authority_refs"], f"{prefix}.rule_refs", errors)
        support_refs = _refs(argument.get("rule_support_refs"), f"{prefix}.rule_support_refs", errors)
        _check_in_scope(support_refs, allowed["case_law_refs"], f"{prefix}.rule_support_refs", errors)
        if material and kind in {"LEGAL", "MIXED"} and not rule_refs:
            gaps.append(f"{argument_id}: material legal argument has no governing rule ref")
        if material and kind in {"FACTUAL", "MIXED"} and not fact_refs:
            gaps.append(f"{argument_id}: material factual application has no approved fact ref")
        linked_fact_refs = set().union(
            *(proposition_fact_refs.get(ref, set()) for ref in proposition_refs)
        ) if proposition_refs else set()
        for fact_ref in sorted(set(fact_refs) - linked_fact_refs):
            gaps.append(f"{argument_id}: application fact {fact_ref} is not grounded by a linked proposition")
        linked_authority_refs = set().union(
            *(proposition_authority_refs.get(ref, set()) for ref in proposition_refs)
        ) if proposition_refs else set()
        for rule_ref in sorted(set(rule_refs) - linked_authority_refs):
            gaps.append(f"{argument_id}: rule {rule_ref} is not grounded by a linked proposition")
        linked_analysis_refs = set().union(
            *(proposition_analysis_refs.get(ref, set()) for ref in proposition_refs)
        ) if proposition_refs else set()
        if material and issue_ref and issue_ref not in linked_analysis_refs:
            gaps.append(f"{argument_id}: issue {issue_ref} is not grounded by a linked proposition")

        contested = argument.get("contested") is True
        if not isinstance(argument.get("contested"), bool):
            errors.append(f"{prefix}.contested: expected boolean")
        adverse_status = _enum(argument.get("adverse_status"), ADVERSE_STATUSES, f"{prefix}.adverse_status", errors)
        counter = _mapping(argument.get("counterargument", {}), f"{prefix}.counterargument", errors)
        if material and adverse_status == "HANDOFF":
            reason = _text(argument.get("handoff_reason"), f"{prefix}.handoff_reason", errors)
            handoffs.append(f"{argument_id}: adverse handoff required{': ' + reason if reason else ''}")
        elif material and adverse_status == "PENDING":
            handoffs.append(f"{argument_id}: adverse review pending")
        elif material and contested:
            if adverse_status == "DONE":
                _text(counter.get("strongest_position"), f"{prefix}.counterargument.strongest_position", errors)
                adverse_refs = _refs(
                    counter.get("adverse_refs"),
                    f"{prefix}.counterargument.adverse_refs",
                    errors,
                    required=True,
                )
                _check_in_scope(
                    adverse_refs,
                    allowed["case_law_refs"],
                    f"{prefix}.counterargument.adverse_refs",
                    errors,
                )
                _text(counter.get("response"), f"{prefix}.counterargument.response", errors)
            elif adverse_status == "NOT_REQUIRED":
                gaps.append(f"{argument_id}: contested material argument lacks completed adverse or handoff")

    raw_analogies = _list(root.get("analogies", []), "analogies", errors)
    analogies = _unique(raw_analogies, "analogies", errors)
    for analogy_id, analogy in analogies.items():
        prefix = f"analogies[{analogy_id}]"
        if isinstance(analogy.get("marker"), str) and analogy.get("marker", "").strip():
            visible_markers[analogy_id] = analogy["marker"].strip()
        argument_ref = _text(analogy.get("argument_ref"), f"{prefix}.argument_ref", errors)
        if argument_ref and argument_ref not in arguments:
            errors.append(f"{prefix}.argument_ref: unknown argument {argument_ref}")
        case_ref = _text(analogy.get("case_ref"), f"{prefix}.case_ref", errors)
        if case_ref and case_ref not in allowed["case_law_refs"]:
            errors.append(f"{prefix}.case_ref: ref {case_ref} is outside analysis_scope")
        for field_name in ("legal_criterion", "reasoning_link", "similarity", "difference", "effect"):
            if not _text(analogy.get(field_name), f"{prefix}.{field_name}", errors, required=False):
                gaps.append(f"{analogy_id}: analogy lacks {field_name}")
        if not _refs(analogy.get("decisive_fact_refs"), f"{prefix}.decisive_fact_refs", errors):
            gaps.append(f"{analogy_id}: analogy lacks decisive fact refs")
        else:
            _check_in_scope(
                _refs(analogy.get("decisive_fact_refs"), f"{prefix}.decisive_fact_refs", []),
                allowed["fact_refs"],
                f"{prefix}.decisive_fact_refs",
                errors,
            )

    raw_errors = _list(root.get("appellate_errors", []), "appellate_errors", errors)
    appellate_errors = _unique(raw_errors, "appellate_errors", errors)
    if mode == "ERROR_BASED" and not appellate_errors:
        gaps.append("ERROR_BASED document has no appellate error map")
    for error_id, error_item in appellate_errors.items():
        prefix = f"appellate_errors[{error_id}]"
        if isinstance(error_item.get("marker"), str) and error_item.get("marker", "").strip():
            visible_markers[error_id] = error_item["marker"].strip()
        argument_ref = _text(error_item.get("argument_ref"), f"{prefix}.argument_ref", errors)
        if argument_ref and argument_ref not in arguments:
            errors.append(f"{prefix}.argument_ref: unknown argument {argument_ref}")
        _enum(error_item.get("error_type"), ERROR_TYPES, f"{prefix}.error_type", errors)
        for field_name in (
            "error_description",
            "challenged_act_locator",
            "materiality",
            "requested_consequence",
        ):
            if not _text(error_item.get(field_name), f"{prefix}.{field_name}", errors, required=False):
                gaps.append(f"{error_id}: appellate error lacks {field_name}")
        governing_refs = _refs(error_item.get("governing_rule_refs"), f"{prefix}.governing_rule_refs", errors)
        _check_in_scope(governing_refs, allowed["authority_refs"], f"{prefix}.governing_rule_refs", errors)
        if not governing_refs:
            gaps.append(f"{error_id}: appellate error lacks governing rule refs")
        if argument_ref in argument_rule_refs:
            for governing_ref in sorted(set(governing_refs) - argument_rule_refs[argument_ref]):
                gaps.append(
                    f"{error_id}: governing rule {governing_ref} is not grounded by linked argument {argument_ref}"
                )
        consequence = error_item.get("requested_consequence")
        if consequence and requested_outcomes and consequence not in requested_outcomes:
            errors.append(f"{prefix}.requested_consequence: must match document.requested_outcomes")
    if mode == "ERROR_BASED":
        covered_arguments = {
            item.get("argument_ref") for item in appellate_errors.values() if isinstance(item.get("argument_ref"), str)
        }
        material_argument_ids = {
            argument_id for argument_id, argument in arguments.items() if argument.get("material") is True
        }
        for argument_id in sorted(material_argument_ids - covered_arguments):
            gaps.append(f"{argument_id}: material appellate argument has no error-map entry")
        covered_outcomes = {
            item.get("requested_consequence")
            for item in appellate_errors.values()
            if isinstance(item.get("requested_consequence"), str)
        }
        for requested_outcome in sorted(set(requested_outcomes) - covered_outcomes):
            gaps.append(f"{requested_outcome}: requested outcome has no error-map support")

    raw_evidence = _list(root.get("evidence_links", []), "evidence_links", errors)
    evidence_links = _unique(raw_evidence, "evidence_links", errors)
    all_proposition_source_refs = set().union(*proposition_source_refs.values()) if proposition_source_refs else set()
    missing_evidence_links = sorted(all_proposition_source_refs - set(evidence_links))
    for evidence_ref in missing_evidence_links:
        gaps.append(f"{evidence_ref}: referenced evidence has no evidence link")
    used_fact_refs: set[str] = set()
    for prop in props.values():
        raw_analysis_refs = prop.get("analysis_refs")
        if isinstance(raw_analysis_refs, list):
            used_fact_refs.update(
                ref for ref in raw_analysis_refs if isinstance(ref, str) and ref in allowed["fact_refs"]
            )
    for argument in arguments.values():
        raw_fact_refs = argument.get("application_fact_refs")
        if isinstance(raw_fact_refs, list):
            used_fact_refs.update(ref for ref in raw_fact_refs if isinstance(ref, str))
    for evidence_id, evidence in evidence_links.items():
        prefix = f"evidence_links[{evidence_id}]"
        if evidence_id not in allowed["evidence_refs"]:
            errors.append(f"{prefix}.id: ref {evidence_id} is outside analysis_scope")
        fact_refs = _refs(evidence.get("fact_refs"), f"{prefix}.fact_refs", errors)
        _text(evidence.get("locator"), f"{prefix}.locator", errors)
        _check_in_scope(fact_refs, allowed["fact_refs"], f"{prefix}.fact_refs", errors)
        if not fact_refs or not any(ref in used_fact_refs for ref in fact_refs):
            orphans.append(evidence_id)
    for prop_id, source_refs in proposition_source_refs.items():
        fact_refs = proposition_fact_refs.get(prop_id, set())
        for source_ref in sorted(source_refs & set(evidence_links)):
            linked_facts = evidence_links[source_ref].get("fact_refs", [])
            linked_fact_set = {ref for ref in linked_facts if isinstance(ref, str)} if isinstance(linked_facts, list) else set()
            if not fact_refs.intersection(linked_fact_set):
                gaps.append(f"{prop_id}: source {source_ref} is not linked to the proposition fact")
    proposition_covered_facts: dict[str, set[str]] = {}
    for prop_id, source_refs in proposition_source_refs.items():
        covered: set[str] = set()
        for source_ref in source_refs & set(evidence_links):
            linked_facts = evidence_links[source_ref].get("fact_refs", [])
            if isinstance(linked_facts, list):
                covered.update(ref for ref in linked_facts if isinstance(ref, str))
        proposition_covered_facts[prop_id] = covered & proposition_fact_refs.get(prop_id, set())
    for argument_id, used_facts in argument_fact_refs.items():
        covered_by_linked_props: set[str] = set()
        for prop_ref in argument_proposition_refs.get(argument_id, set()):
            covered_by_linked_props.update(proposition_covered_facts.get(prop_ref, set()))
        for fact_ref in sorted(used_facts - covered_by_linked_props):
            gaps.append(
                f"{argument_id}: application fact {fact_ref} is not covered by evidence of linked propositions"
            )
    if orphans:
        warnings.append(f"orphan evidence: {sorted(orphans)}")

    critic = _mapping(root.get("critic"), "critic", errors)
    critic_status = _enum(critic.get("status"), CRITIC_STATUSES, "critic.status", errors)
    critic_required = critic.get("required")
    if not isinstance(critic_required, bool):
        errors.append("critic.required: expected boolean")
    if mode != "FORMAL" and critic_required is not True:
        errors.append("critic.required: must be true for non-FORMAL argument manifest")
    if critic_status == "PENDING":
        handoffs.append("substantive critic review pending")
    elif critic_required is True and critic_status != "DONE":
        handoffs.append("substantive critic review required")

    constraints = _mapping(root.get("constraints", {}), "constraints", errors)
    limited = constraints.get("limited_draft_authorized") is True
    if constraints.get("limited_draft_authorized") is not None and not isinstance(
        constraints.get("limited_draft_authorized"), bool
    ):
        errors.append("constraints.limited_draft_authorized: expected boolean")
    if limited and not _text(
        constraints.get("authorization_note"), "constraints.authorization_note", errors, required=False
    ):
        errors.append("constraints.authorization_note: required for LIMITED_DRAFT")
    raw_gap_markers = constraints.get("visible_gap_markers", {})
    gap_markers = _mapping(raw_gap_markers, "constraints.visible_gap_markers", errors)
    for ref, marker in gap_markers.items():
        if not isinstance(ref, str) or not ref.strip() or not isinstance(marker, str) or not marker.strip():
            errors.append("constraints.visible_gap_markers: expected non-empty ref-to-marker mapping")
        else:
            visible_markers[ref.strip()] = marker.strip()
    for flag_name in ("human_decision_pending", "source_verification_pending"):
        if flag_name in constraints and not isinstance(constraints.get(flag_name), bool):
            errors.append(f"constraints.{flag_name}: expected boolean")
    if constraints.get("human_decision_pending") is True:
        handoffs.append("human decision pending")
    if constraints.get("source_verification_pending") is True:
        handoffs.append("source verification pending")

    errors = sorted(set(errors))
    gaps = sorted(set(gaps))
    handoffs = sorted(set(handoffs))
    if limited and gaps:
        gap_refs = {gap.split(":", 1)[0] for gap in gaps}
        missing_markers = sorted(ref for ref in gap_refs if ref not in visible_markers)
        if missing_markers:
            errors.append(
                "constraints.visible_gap_markers: missing visible markers for "
                + ", ".join(missing_markers)
            )
            errors = sorted(set(errors))
    if data != original:
        errors.append("checker mutated input")

    if errors:
        outcome = "BLOCKED_MATERIAL_GAP"
    elif handoffs:
        outcome = "HANDOFF_REQUIRED"
    elif gaps:
        outcome = "LIMITED_DRAFT" if limited else "BLOCKED_MATERIAL_GAP"
    else:
        outcome = "READY_FOR_RENDER"

    return DraftCheckResult(
        valid=not errors,
        errors=errors,
        warnings=sorted(set(warnings)),
        material_gaps=gaps,
        handoffs=handoffs,
        orphan_evidence=sorted(set(orphans)),
        outcome=outcome,
    )


def load_manifest(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return yaml.safe_load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_manifest(load_manifest(args.manifest))
    except (OSError, yaml.YAMLError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.valid and result.outcome in {"READY_FOR_RENDER", "LIMITED_DRAFT"} else 1


if __name__ == "__main__":
    sys.exit(main())
