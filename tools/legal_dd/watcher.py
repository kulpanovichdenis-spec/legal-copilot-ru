from __future__ import annotations
from pathlib import Path
import time, uuid
from .dataroom import LocalDataroomAdapter
from .utils import read_json, write_json, utc_now
from .audit import append_event

def _work_id():
    return "WORK-" + uuid.uuid4().hex[:10]

def queue_dataroom_updates(project_root):
    project_root=Path(project_root)
    adapter=LocalDataroomAdapter(project_root/"dataroom")
    updates=adapter.get_updates()
    queue=read_json(project_root/"state/work-queue.json",[]) or []
    known={(x.get("type"),x.get("source_item_id"),x.get("status")) for x in queue}
    added=0
    for kind in ("added","changed"):
        for item in updates[kind]:
            key=("classify_document",item["id"],"queued")
            if key in known:
                continue
            queue.append({
                "work_id":_work_id(),"type":"classify_document","project_id":project_root.name,
                "source_item_id":item["id"],"document_id":None,"affected_checks":[],
                "affected_evidence_requirements":[],"extractor_ids":[],"status":"queued",
                "created_at":utc_now(),"updated_at":utc_now(),"reason":f"dataroom_{kind}"
            })
            added+=1
    write_json(project_root/"state/work-queue.json",queue)
    if added:
        append_event(project_root,"dataroom_work_queued",source="watcher",count=added)
    return {"queued":added,"updates":updates}

def watch(project_root, interval=60):
    while True:
        queue_dataroom_updates(project_root)
        time.sleep(max(5,int(interval)))
