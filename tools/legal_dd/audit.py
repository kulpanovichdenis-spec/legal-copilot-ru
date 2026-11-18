from pathlib import Path
import json
from .utils import utc_now

def append_event(project_root, event, actor="agent", **payload):
    record={"timestamp":utc_now(),"event":event,"actor":actor,**payload}
    p=Path(project_root)/"logs/audit.jsonl"
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,ensure_ascii=False)+"\n")
    return record
