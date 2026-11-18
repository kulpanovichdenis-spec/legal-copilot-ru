from pathlib import Path
from .config import load_yaml
from .catalogs import merged_evidence_catalog
from .requests import applicable_requirements
from .utils import read_json

CLOSED_EVIDENCE={"satisfied","external_source","not_applicable"}

def _add(out, capability, reason, priority="normal", related=None):
    key=(capability,reason)
    if any((x["capability"],x["reason"])==key for x in out): return
    out.append({"capability":capability,"priority":priority,"reason":reason,"related":related or []})

def plan_next(skill_root, project_root):
    skill_root=Path(skill_root); project_root=Path(project_root)
    project=load_yaml(project_root/"project.yaml")
    out=[]
    active=project.get("active_checks") or []
    intake=project.get("intake") or {}

    if not active:
        _add(out,"CAP-SCOPE","Coverage obligations have not been routed from current transaction state.","high")

    dr=(project.get("dataroom") or {}).get("mode","none")
    if dr=="local" and (project_root/"dataroom").exists():
        files=[p for p in (project_root/"dataroom").rglob("*") if p.is_file() and p.name!="manifest.json"]
        if files:
            _add(out,"CAP-INVENTORY",f"Local dataroom contains {len(files)} source item(s).","normal")

    cat=merged_evidence_catalog(skill_root,project.get("active_extensions",[]))
    reqs=applicable_requirements(cat,active,phases=["initial","conditional","external","closing","derived"])
    ev={x.get("requirement_id",x.get("id")):x for x in (read_json(project_root/"state/evidence.json",[]) or [])}
    seller_open=[]; external_open=[]
    for req in reqs:
        st=(ev.get(req["id"]) or {}).get("status","not_requested")
        if st in CLOSED_EVIDENCE: continue
        if req.get("external_verification") or req.get("request_phase")=="external" or req.get("requested_from")=="external_check": external_open.append(req["id"])
        elif req.get("requested_from")!="system_derived": seller_open.append(req["id"])
    if seller_open:
        _add(out,"CAP-REQUEST",f"{len(seller_open)} applicable evidence sufficiency contract(s) remain unresolved and can be requested/probed.","normal",seller_open[:20])
    if external_open:
        _add(out,"CAP-EXTERNAL",f"{len(external_open)} independent external verification task(s) remain open.","high",external_open[:20])

    q=read_json(project_root/"state/work-queue.json",[]) or []
    queued=[x for x in q if x.get("status")=="queued"]
    if any(x.get("type")=="classify_document" for x in queued):
        _add(out,"CAP-CLASSIFY","New/changed source items are waiting for content-based classification.","normal")
    if any(x.get("type") in {"extract_facts","deep_review"} for x in queued):
        _add(out,"CAP-EXTRACT","Queued source items can establish unresolved material facts.","normal")

    facts=read_json(project_root/"state/facts.json",[]) or []
    if any(x.get("state")=="conflict_detected" for x in facts):
        _add(out,"CAP-VALIDATE","Material fact conflicts are present.","high")
        _add(out,"CAP-CRITIC","Conflict requires independent challenge before final reliance.","high")
    pending_facts=[x for x in facts if (x.get("human_review") or {}).get("status") in {None,"pending","reconfirmation_required"} and x.get("material",True)]
    if pending_facts:
        _add(out,"CAP-HUMAN",f"{len(pending_facts)} material fact(s) await human review/reconfirmation.","high",[x.get("fact_id") for x in pending_facts[:20]])

    checks=read_json(project_root/"state/checks.json",[]) or []
    check_by={x.get("id"):x for x in checks}
    unresolved_checks=[cid for cid in active if not (check_by.get(cid) or {}).get("agent_assessment")]
    if unresolved_checks:
        _add(out,"CAP-CHECK",f"{len(unresolved_checks)} active coverage obligation(s) have no proposed resolution yet.","normal",unresolved_checks[:20])
    material_issues=[x for x in checks if (x.get("agent_assessment") or {}).get("status") in {"issue","cannot_conclude","external_review_required"}]
    if material_issues:
        _add(out,"CAP-CRITIC","Material adverse/open assessments exist and may need challenge/omission review.","high",[x.get("id") for x in material_issues[:20]])
    pending_checks=[x for x in checks if (x.get("agent_assessment") or {}).get("status") and (x.get("human_review") or {}).get("status") in {None,"pending","reconfirmation_required"}]
    if pending_checks:
        _add(out,"CAP-HUMAN",f"{len(pending_checks)} proposed coverage conclusion(s) await human confirmation.","high",[x.get("id") for x in pending_checks[:20]])

    decisions=read_json(project_root/"state/decisions.json",[]) or []
    open_dec=[x for x in decisions if (x.get("human_decision") or {}).get("status") not in {"confirmed","modified"}]
    if open_dec:
        _add(out,"CAP-DECIDE",f"{len(open_dec)} contract decision(s) remain human-controlled and unresolved.","high",[x.get("decision_id") for x in open_dec[:20]])

    signed=root_signed=project_root/"signed"
    signed_files=[p for p in signed.rglob("*") if p.is_file()] if signed.exists() else []
    if signed_files:
        _add(out,"CAP-RECONCILE",f"{len(signed_files)} signed document(s) available; reconcile against prior deal state.","high")

    # Rendering is always possible but low priority; presentation never blocks analysis.
    _add(out,"CAP-RENDER","Refresh the human review surface when useful; rendering is presentation, not a reasoning dependency.","low")

    order={"high":0,"normal":1,"low":2}
    out.sort(key=lambda x:(order.get(x["priority"],9),x["capability"],x["reason"]))
    return {"project_id":project.get("project_id"),"mode":"state_driven","next_capabilities":out}
