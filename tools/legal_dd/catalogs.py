from pathlib import Path
from .config import load_yaml

def extension_config(skill_root, extension_id):
    nav=load_yaml(Path(skill_root)/"navigator.yaml")
    rel=(nav.get("extensions") or {}).get(extension_id)
    if not rel:
        return None
    return load_yaml(Path(skill_root)/rel)

def active_checks_with_extensions(skill_root, core_checks, extensions):
    result=list(core_checks)
    for ext_id in extensions:
        cfg=extension_config(skill_root,ext_id)
        if cfg:
            result.extend(cfg.get("checks",[]))
    return list(dict.fromkeys(result))

def load_evidence_catalogs(skill_root, extensions=None):
    root=Path(skill_root)
    catalogs=[load_yaml(root/"catalogs/evidence_requirements.yaml")]
    for ext_id in extensions or []:
        cfg=extension_config(root,ext_id)
        if cfg and cfg.get("evidence_catalog"):
            catalogs.append(load_yaml(root/cfg["evidence_catalog"]))
    return catalogs

def merged_evidence_catalog(skill_root, extensions=None):
    reqs=[]
    for cat in load_evidence_catalogs(skill_root,extensions):
        reqs.extend(cat.get("requirements",[]))
    return {"requirements":reqs}

def check_card(skill_root, check_id, extensions=None):
    root=Path(skill_root)
    p=root/"cards/checks"/f"{check_id}.yaml"
    if p.exists(): return load_yaml(p)
    for ext_id in extensions or []:
        cfg=extension_config(root,ext_id)
        if not cfg: continue
        p=root/"extensions"/ext_id/"cards"/f"{check_id}.yaml"
        if p.exists(): return load_yaml(p)
    return {"id":check_id,"title":check_id,"evidence_requirements":[]}
