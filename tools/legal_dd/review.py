from pathlib import Path
from .state import load_state, save_state
from .audit import append_event
from .utils import utc_now

HUMAN_STATUSES={"confirmed","modified","rejected"}

def review_fact(project_root, fact_id, status, value=None, comment=None, reviewer="human"):
    if status not in HUMAN_STATUSES: raise ValueError(status)
    facts=load_state(project_root,"facts")
    for f in facts:
        if f.get("fact_id")==fact_id:
            old={"state":f.get("state"),"normalized_value":f.get("normalized_value"),"human_review":dict(f.get("human_review") or {})}
            if status=="modified" and value is not None:
                f["normalized_value"]=value
            f["human_review"]={"status":status,"reviewed_by":reviewer,"reviewed_at":utc_now(),"comment":comment}
            save_state(project_root,"facts",facts)
            append_event(project_root,"fact_reviewed",actor=reviewer,fact_id=fact_id,old=old,new=f["human_review"],new_value=f.get("normalized_value"))
            return f
    raise KeyError(fact_id)

def review_check(project_root, check_id, status, final_status=None, comment=None, reviewer="human"):
    if status not in HUMAN_STATUSES: raise ValueError(status)
    checks=load_state(project_root,"checks")
    for c in checks:
        if c.get("id")==check_id:
            old={"human_review":dict(c.get("human_review") or {}),"final_status":c.get("final_status")}
            c["human_review"]={"status":status,"reviewed_by":reviewer,"reviewed_at":utc_now(),"comment":comment}
            if status in {"confirmed","modified"} and final_status:
                c["final_status"]=final_status
            elif status=="rejected":
                c.pop("final_status",None)
            save_state(project_root,"checks",checks)
            append_event(project_root,"check_reviewed",actor=reviewer,check_id=check_id,old=old,new=c.get("human_review"),final_status=c.get("final_status"))
            return c
    raise KeyError(check_id)
