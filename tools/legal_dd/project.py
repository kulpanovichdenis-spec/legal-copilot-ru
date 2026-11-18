from __future__ import annotations
from pathlib import Path
from datetime import date
import secrets
from .utils import utc_now, slug, write_json
from .config import dump_yaml

def make_project_id(name="dd-project"):
    return f"{slug(name)[:40]}-{secrets.token_hex(3)}"

def _folder_label(name: str) -> str:
    value = " ".join(str(name).split()).strip()
    for char in '<>:"/\\|?*':
        value = value.replace(char, "-")
    value = value.strip(" .-")
    return value[:80] or "Legal DD"


def init_project(workflow_root, name="DD Project", project_id=None, dataroom_mode="none", case_dir=None, created_date=None):
    workflow_root = Path(workflow_root)
    project_id = project_id or make_project_id(name)
    if case_dir:
        case_path = Path(case_dir)
        if case_path.is_absolute():
            raise ValueError("case_dir must be relative to workflow root")
        case_root = workflow_root / case_path
    else:
        day = created_date or date.today().isoformat().replace("-", ".")
        case_root = workflow_root / f"{day} {_folder_label(name)}"
    root = case_root / "dd-state"
    if root.exists():
        raise FileExistsError(f"DD project state already exists: {root}")
    dirs = ["state","requests","html","drafts/term-sheet","drafts/agreements","drafts/schedules","drafts/disclosure","signed","roadmap","logs","connector","secrets"]
    if dataroom_mode == "local":
        dirs += ["dataroom/inbox","dataroom/dropzones/contracts","dataroom/dropzones/corporate","dataroom/dropzones/ip","dataroom/dropzones/regulatory","dataroom/dropzones/manufacturing","dataroom/dropzones/litigation","dataroom/dropzones/approvals"]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / ".gitignore").write_text("secrets/\n*.env\n*.token\nhtml/.cache/\n", encoding="utf-8")
    (root / "secrets/dataroom.env.example").write_text("DATAROOM_API_TOKEN=\nDATAROOM_MCP_SECRET=\n", encoding="utf-8")
    project = {"project_id":project_id,"name":name,"status":"intake","created_at":utc_now(),"profile_overrides":{},"intake":{},"active_checks":[],"active_extensions":[],"dataroom":{"mode":dataroom_mode}}
    dump_yaml(root / "project.yaml", project)
    for name in ["assets","parties","evidence","facts","checks","findings","decisions","review-queue","document-families","work-queue"]:
        write_json(root / "state" / f"{name}.json", [])
    write_json(root / "state/contract-inputs.json", {})
    return root
