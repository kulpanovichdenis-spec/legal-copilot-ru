from pathlib import Path
from .config import load_yaml
from .utils import read_json
from .catalogs import extension_config
from .evidence import can_support_clear
from .fnm import validate_fnm_package

def validate_package(skill_root):
    root=Path(skill_root); errors=[]; warnings=[]
    core_cards={p.stem:load_yaml(p) for p in (root/"cards/checks").glob("*.yaml")}
    all_cards=dict(core_cards)
    nav=load_yaml(root/"navigator.yaml")
    extension_ids=list((nav.get("extensions") or {}).keys())
    ext_catalogs=[]; ext_extractors=[]
    for ext_id in extension_ids:
        cfg=extension_config(root,ext_id)
        if not cfg: continue
        for cid in cfg.get("checks",[]):
            p=root/"extensions"/ext_id/"cards"/f"{cid}.yaml"
            if not p.exists(): errors.append(f"missing extension check card: {ext_id}/{cid}")
            else: all_cards[cid]=load_yaml(p)
        if cfg.get("evidence_catalog"): ext_catalogs.extend(load_yaml(root/cfg["evidence_catalog"]).get("requirements",[]))
        if cfg.get("extractor_catalog"): ext_extractors.extend(load_yaml(root/cfg["extractor_catalog"]).get("extractors",[]))
    evidence=load_yaml(root/"catalogs/evidence_requirements.yaml").get("requirements",[])+ext_catalogs
    er_ids={x["id"] for x in evidence}; check_ids=set(all_cards)
    extractors=load_yaml(root/"catalogs/extractors.yaml").get("extractors",[])+ext_extractors
    ext_ids={x["id"] for x in extractors}
    for er in evidence:
        for cid in er.get("mapped_checks",[]):
            if cid not in check_ids: errors.append(f"{er['id']} maps to missing check {cid}")
        for xid in er.get("extractor_ids",[]):
            if xid not in ext_ids: errors.append(f"{er['id']} maps to missing extractor {xid}")
    for cid,card in all_cards.items():
        for erid in card.get("evidence_requirements",[]):
            if erid not in er_ids: errors.append(f"{cid} references missing Evidence Requirement {erid}")
    for ex in extractors:
        for cid in ex.get("mapped_checks",[]):
            if cid not in check_ids: errors.append(f"{ex['id']} maps to missing check {cid}")
    if len(core_cards)!=57: errors.append(f"expected 57 core check cards, found {len(core_cards)}")
    if not (root/"templates/project/.gitignore").exists(): warnings.append("project .gitignore template missing")
    fnm=validate_fnm_package(root)
    errors.extend(fnm.get("errors",[])); warnings.extend(fnm.get("warnings",[]))
    return {"ok":not errors,"errors":errors,"warnings":warnings,"counts":{"core_checks":len(core_cards),"all_checks":len(all_cards),"evidence_requirements":len(evidence),"extractors":len(extractors)}}

def _quote_check(project_root, fact, loc):
    """Т3: цитата ответа сверяется с документом локального data room; иначе None (не проверить)."""
    doc_id=loc.get("document_id"); quote=fact.get("quote")
    if not doc_id or not quote: return None
    path=Path(project_root)/"dataroom"/doc_id
    if not path.is_file(): return None
    from tools.evidence_anchor.anchor import check
    where=" ".join(str(loc.get(k)) for k in ("section","paragraph") if loc.get(k) not in (None,""))
    return check(path, quote, where or None)["quote_check"]

def validate_project(project_root):
    p=Path(project_root); errors=[]; warnings=[]
    if (p/"project.yaml").exists():  # VAL-ROUTING-INPUTS (BL-046)
        from .routing import unresolved_routing_inputs
        for field in unresolved_routing_inputs((load_yaml(p/"project.yaml") or {}).get("intake") or {}):
            warnings.append(f"routing input unresolved: {field} — dependent checks activated conservatively; ask the lawyer")
    facts=read_json(p/"state/facts.json",[]) or []
    evidence={x.get("requirement_id"):x for x in (read_json(p/"state/evidence.json",[]) or [])}
    checks=read_json(p/"state/checks.json",[]) or []
    for f in facts:
        if f.get("state")=="answered":
            if not f.get("quote"): errors.append(f"answered fact {f.get('fact_id')} has no quote")
            loc=f.get("location") or {}
            if not any(v not in (None,"") for k,v in loc.items() if k!="document_id"): errors.append(f"answered fact {f.get('fact_id')} has no exact locator")
            qc=_quote_check(p,f,loc)
            if qc=="mismatch": errors.append(f"answered fact {f.get('fact_id')}: quote not found in {loc.get('document_id')}")
            elif qc in ("ocr_fuzzy","location_mismatch"): warnings.append(f"answered fact {f.get('fact_id')}: quote {qc} in {loc.get('document_id')}")
    for c in checks:
        agent=(c.get("agent_assessment") or {}).get("status")
        if agent=="clear":
            for erid in c.get("evidence_requirements",[]):
                st=(evidence.get(erid) or {}).get("status")
                if not can_support_clear(st): errors.append(f"clear check {c.get('id')} blocked by {erid}={st}")
        if c.get("final_status") and (c.get("human_review") or {}).get("status") not in {"confirmed","modified"}:
            errors.append(f"final status on {c.get('id')} without human confirmation")
    return {"ok":not errors,"errors":errors,"warnings":warnings}
