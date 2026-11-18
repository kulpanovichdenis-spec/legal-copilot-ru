from pathlib import Path
from .config import load_yaml

from tools.skill_lint.fnm import REQUIRED_DESIGN_FIELDS as _FIELDS, validate_rows

# Один источник правил FNM-таблицы — tools/skill_lint/fnm.py (Т4 ТЗ cfl-gap-closure).
REQUIRED_DESIGN_FIELDS = set(_FIELDS)

def validate_fnm_package(skill_root):
    root=Path(skill_root); errors=[]; warnings=[]
    design=root/"design/fnm-design-table.yaml"
    outcomes=root/"design/outcome-contract.yaml"
    validators=root/"runtime/validators.yaml"
    graph=root/"runtime/capability_graph.yaml"
    for p in [design,outcomes,validators,graph]:
        if not p.exists(): errors.append(f"missing FNM artifact: {p.relative_to(root)}")
    if design.exists():
        data=load_yaml(design)
        errors.extend(validate_rows(data.get("rows",[])))
    for p in (root/"cards/checks").glob("*.yaml"):
        c=load_yaml(p)
        if c.get("role")!="coverage_obligation": errors.append(f"{p.stem} is not coverage_obligation")
        f=c.get("fnm") or {}
        for k in ["purpose","failure_modes","required_invariant","constraint_type","ai_native_implementation","validators"]:
            if not f.get(k): errors.append(f"{p.stem} missing fnm.{k}")
    cat=load_yaml(root/"catalogs/evidence_requirements.yaml")
    for er in cat.get("requirements",[]):
        if er.get("role")!="evidence_sufficiency_contract": errors.append(f"{er.get('id')} not evidence_sufficiency_contract")
        if er.get("evidence_types_are_examples") is not True: errors.append(f"{er.get('id')} evidence types still treated as mandatory list")
    ex=load_yaml(root/"catalogs/extractors.yaml")
    for x in ex.get("extractors",[]):
        if x.get("role")!="extraction_capability": errors.append(f"{x.get('id')} not extraction_capability")
        if (x.get("project_calibration") or {}).get("mode")!="adaptive": errors.append(f"{x.get('id')} calibration not adaptive")
    nav=load_yaml(root/"navigator.yaml")
    if (nav.get("orchestration") or {}).get("no_global_fixed_sequence") is not True: errors.append("navigator still encodes global fixed sequence")
    return {"ok":not errors,"errors":errors,"warnings":warnings}
