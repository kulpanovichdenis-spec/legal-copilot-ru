"""Structural checks and derived work queues; no legal or evidential adjudication.

Contract: tools/case_analysis/README.md. The validator never modifies matter state.
An accepted record means internally well-formed input, not verified law or proven facts.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

STEP_KINDS = ("request_fact", "request_evidence", "research_law", "compare_bases", "lawyer_decision")
SUFFICIENCY = ("complete", "missing_facts", "structural_failure", "legal_uncertainty", "qualification_uncertainty")
ALLEGATIONS = ("present", "missing", "structural_failure", "legal_uncertainty", "qualification_uncertainty")
RULE_STATUSES = ("UNVERIFIED", "OPENED", "VERIFIED")
TRIGGERS = ("factual_dispute", "missing_support", "source_conflict", "admissibility")
PROOF_STATES = ("strong_support", "incomplete_support", "material_contradiction",
                "counter_evidence_significant", "unavailable_source", "unable_to_assess")
ROUTING = {"missing": {"request_fact"}, "missing_facts": {"request_fact"},
           "legal_uncertainty": {"research_law"}, "qualification_uncertainty": {"compare_bases"},
           "structural_failure": {"compare_bases", "research_law", "lawyer_decision"}}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _index(records):
    return {v["id"]: v for v in _dicts(records) if _text(v.get("id"))}


def validate(data, context):
    """Return diagnostics for arbitrary YAML values; no writes and no status promotion."""
    errors = []
    if not isinstance(data, dict):
        return ["case_structure: ожидается объект"]
    ctx = context if isinstance(context, dict) else {}
    fact_index = {**_index(ctx.get("facts")), **_index(ctx.get("events"))}
    gap_index, positions, issues = (_index(ctx.get(k)) for k in ("gaps", "positions", "issues"))
    ids, elements, bases, claims, responses = {}, {}, {}, {}, {}

    def text(obj, field, where):
        if not _text(obj.get(field)):
            errors.append(f"{where}.{field}: нужна непустая строка")

    def choice(obj, field, allowed, where):
        val = obj.get(field)
        if not isinstance(val, str) or val not in allowed:
            errors.append(f"{where}.{field}: допустимы {allowed}")

    def records(obj, field, where, required=False):
        raw = obj.get(field)
        if not isinstance(raw, list):
            errors.append(f"{where}.{field}: нужен список объектов")
            return []
        if required and not raw:
            errors.append(f"{where}.{field}: пустой обязательный список")
        for n, row in enumerate(raw):
            if not isinstance(row, dict):
                errors.append(f"{where}.{field}[{n}]: ожидается объект")
        return _dicts(raw)

    def register(obj, prefix, where):
        ident = obj.get("id")
        if not isinstance(ident, str) or not re.fullmatch(prefix + r"-\d{3,}", ident):
            errors.append(f"{where}.id: нужен {prefix}-001")
            return None
        if ident in ids:
            errors.append(f"{where}: повтор ID {ident}")
        ids[ident] = obj
        return ident

    def ref(obj, field, index, where):
        value = obj.get(field)
        if not isinstance(value, str) or value not in index:
            errors.append(f"{where}.{field}: неизвестная ссылка {value!r}")
            return None
        return value

    def refs(obj, field, index, where):
        raw = obj.get(field)
        if not isinstance(raw, list):
            errors.append(f"{where}.{field}: нужен список ссылок")
            return []
        out = []
        for value in raw:
            if not isinstance(value, str) or value not in index:
                errors.append(f"{where}.{field}: неизвестная ссылка {value!r}")
            elif value in out:
                errors.append(f"{where}.{field}: повтор ссылки {value}")
            else:
                out.append(value)
        return out

    def rule(obj, field, where):
        value = obj.get(field)
        if not isinstance(value, dict):
            errors.append(f"{where}.{field}: нужен объект text/source/status")
            return
        for key in ("text", "source"):
            text(value, key, f"{where}.{field}")
        choice(value, "status", RULE_STATUSES, f"{where}.{field}")
        # VERIFIED here is a declaration, not the source-verification gate.
        # Runtime method requires the existing claim ledger/provider route independently.

    def steps(obj, where, required=False, allowed=None):
        rows = records(obj, "next_steps", where, required)
        for row in rows:
            choice(row, "kind", STEP_KINDS, where + ".next_steps")
            text(row, "action", where + ".next_steps")
            if "owner" in row:
                text(row, "owner", where + ".next_steps")
        if allowed and not any(r.get("kind") in allowed for r in rows if isinstance(r.get("kind"), str)):
            errors.append(f"{where}: следующий шаг должен включать {sorted(allowed)}")

    objective = data.get("objective")
    if not isinstance(objective, dict):
        errors.append("case_structure.objective: нужен объект")
    else:
        for field in ("legal_outcome", "business_goal", "stage"):
            text(objective, field, "objective")

    covered = set()
    for c in records(data, "claims", "case_structure", True):
        cid = register(c, "R", "claim")
        if cid:
            claims[cid] = c
        cp = ref(c, "position_ref", positions, "claim")
        issue = ref(c, "issue_ref", issues, "claim")
        if issue and issues[issue].get("status") != "confirmed":
            errors.append(f"{cid}: issue не confirmed")
        if cp:
            if positions[cp].get("kind") not in ("claim", "procedural_request"):
                errors.append(f"{cid}: position_ref не требование/процессуальная просьба")
            if positions[cp].get("issue_ref") != issue:
                errors.append(f"{cid}: issue позиции и требования различаются")
            if cp in covered:
                errors.append(f"{cid}: позиция уже разобрана; альтернативы хранить в bases")
            covered.add(cp)
        text(c, "outcome", str(cid))
        for b in records(c, "bases", str(cid), True):
            bid = register(b, "B", "basis")
            if bid:
                bases[bid] = b
            choice(b, "role", ("primary", "alternative", "subsidiary", "exclusive"), str(bid))
            rule(b, "rule", str(bid))
            choice(b, "sufficiency", SUFFICIENCY, str(bid))
            text(b, "assessment", str(bid))
            steps(b, str(bid))
            for e in records(b, "elements", str(bid), True):
                eid = register(e, "E", "element")
                if eid:
                    elements[eid] = (e, b, c)
                text(e, "criterion", str(eid))
                text(e, "assessment", str(eid))
                choice(e, "allegation_status", ALLEGATIONS, str(eid))
                ff, gg = refs(e, "fact_refs", fact_index, str(eid)), refs(e, "gap_refs", gap_index, str(eid))
                state = e.get("allegation_status")
                if state == "present" and not ff:
                    errors.append(f"{eid}: present без факта/события")
                if state == "missing" and not gg:
                    errors.append(f"{eid}: missing без ссылки на пробел")
                if b.get("sufficiency") == "complete" and state != "present":
                    errors.append(f"{bid}: complete несовместим с неполным элементом {eid}")
                steps(e, str(eid), state != "present", ROUTING.get(state) if isinstance(state, str) else None)
            sufficiency = b.get("sufficiency")
            allowed = ROUTING.get(sufficiency) if isinstance(sufficiency, str) else None
            actions = _dicts(b.get("next_steps")) + [s for e in _dicts(b.get("elements")) for s in _dicts(e.get("next_steps"))]
            if allowed and not any(isinstance(s.get("kind"), str) and s["kind"] in allowed for s in actions):
                errors.append(f"{bid}: неразрешённое основание требует следующего шага {sorted(allowed)}")
            if sufficiency == "missing_facts" and not any(e.get("allegation_status") == "missing" for e in _dicts(b.get("elements"))):
                errors.append(f"{bid}: missing_facts без отсутствующего фактического тезиса элемента")

    for exclusion in records(data, "excluded_claims", "case_structure"):
        cp = ref(exclusion, "position_ref", positions, "excluded_claims")
        text(exclusion, "reason", "excluded_claims")
        if cp in covered:
            errors.append(f"{cp}: повтор покрытия/исключения")
        if cp:
            covered.add(cp)
    for cp, p in positions.items():
        issue = p.get("issue_ref")
        if p.get("kind") in ("claim", "procedural_request") and isinstance(issue, str) and issue in issues:
            if issues[issue].get("status") == "confirmed" and cp not in covered:
                errors.append(f"{cp}: требование не разобрано и не исключено с причиной")

    covered_responses = set()
    for r in records(data, "responses", "case_structure"):
        rid = register(r, "D", "response")
        if rid:
            responses[rid] = r
        rp = ref(r, "position_ref", positions, str(rid))
        if rp:
            covered_responses.add(rp)
            ri = positions[rp].get("issue_ref")
            if not isinstance(ri, str) or ri not in issues or issues[ri].get("status") != "confirmed":
                errors.append(f"{rid}: ответ ссылается на неподтверждённый вопрос")
        choice(r, "kind", ("factual_denial", "alternative_facts", "legal_disagreement", "independent_defense", "rhetoric", "supporting_argument"), str(rid))
        choice(r, "state", ("open", "answered", "closed"), str(rid))
        text(r, "assessment", str(rid))
        if not isinstance(r.get("material"), bool):
            errors.append(f"{rid}: material должен быть boolean")
        if r.get("material") is False and r.get("state") != "closed":
            errors.append(f"{rid}: несущественная ветвь должна быть closed")
        steps(r, str(rid), r.get("material") is True and r.get("state") == "open")
    targets = {**claims, **elements, **responses}
    for rid, r in responses.items():
        target = ref(r, "target_ref", targets, rid)
        seen = {rid}
        while isinstance(target, str) and target in responses:
            if target in seen:
                errors.append(f"{rid}: цикл ответов")
                break
            seen.add(target)
            target = responses[target].get("target_ref")
    for cp, p in positions.items():
        issue = p.get("issue_ref")
        if p.get("kind") in ("argument", "defense") and isinstance(issue, str) and issue in issues:
            if issues[issue].get("status") == "confirmed" and cp not in covered_responses:
                errors.append(f"{cp}: заявленный довод не получил оценки существенности/ответа")

    for p in records(data, "proof_issues", "case_structure"):
        pid = register(p, "PF", "proof")
        eid = ref(p, "element_ref", elements, str(pid))
        ff, gg = refs(p, "fact_refs", fact_index, str(pid)), refs(p, "gap_refs", gap_index, str(pid))
        if not ff and not gg:
            errors.append(f"{pid}: нет факта или пробела")
        if eid:
            e, b, _ = elements[eid]
            if b.get("sufficiency") == "structural_failure":
                errors.append(f"{pid}: преждевременный proof для structural_failure основания")
            if any(f not in (e.get("fact_refs") or []) for f in ff) or any(g not in (e.get("gap_refs") or []) for g in gg):
                errors.append(f"{pid}: факты/пробелы не относятся к элементу {eid}")
        choice(p, "trigger", TRIGGERS, str(pid))
        choice(p, "party_position", ("disputed", "agreed", "unknown"), str(pid))
        choice(p, "state", PROOF_STATES, str(pid))
        for field in ("materiality", "problems", "availability", "nonproof_consequence"):
            text(p, field, str(pid))
        rule(p, "burden", str(pid))
        supporting = refs(p, "support_refs", fact_index, str(pid))
        refs(p, "counter_refs", fact_index, str(pid))
        if p.get("state") == "strong_support" and not supporting:
            errors.append(f"{pid}: strong_support без подтверждающего источника")
        if p.get("trigger") == "factual_dispute" and p.get("party_position") != "disputed":
            errors.append(f"{pid}: factual_dispute требует disputed")
        steps(p, str(pid), p.get("state") != "strong_support")
    return errors


def queues(data):
    """Derive tasks, preserving their originating legal/evidence dependency."""
    result = {k: [] for k in STEP_KINDS}
    def add(item, **links):
        for step in _dicts(item.get("next_steps")):
            kind = step.get("kind")
            if isinstance(kind, str) and kind in result:
                result[kind].append({**step, "item_ref": item.get("id"), **links})
    for c in _dicts(data.get("claims")):
        for b in _dicts(c.get("bases")):
            add(b, claim_ref=c.get("id"), issue_ref=c.get("issue_ref"))
            for e in _dicts(b.get("elements")):
                add(e, claim_ref=c.get("id"), basis_ref=b.get("id"), issue_ref=c.get("issue_ref"))
    for r in _dicts(data.get("responses")):
        add(r, target_ref=r.get("target_ref"))
    for p in _dicts(data.get("proof_issues")):
        add(p, element_ref=p.get("element_ref"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    # Imports deferred to avoid a case_docs/structure cycle.
    from tools.case_analysis import case_docs
    try:
        cd = case_docs.load_case(Path(args.case))
        errs = case_docs.validate_analysis(cd)
        if errs:
            print("\n".join(errs))
            return 1
        data = cd["analysis"].get("case_structure")
        print(json.dumps(queues(data) if isinstance(data, dict) else {
            "coverage": "legacy", "warning": "Структура элементов не проверялась"}, ensure_ascii=False, indent=2))
        return 0
    except (case_docs.RenderError, OSError, yaml.YAMLError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
