from __future__ import annotations
import argparse, json
from pathlib import Path
from .config import load_yaml, dump_yaml
from .project import init_project
from .routing import route
from .dataroom import LocalDataroomAdapter
from .requests import applicable_requirements, render_full_generic_request, render_initial_request, render_gap_request, render_external_workplan
from .html import write_report
from .utils import read_json, write_json
from .drafting import suggest_document_package
from .catalogs import active_checks_with_extensions, merged_evidence_catalog, check_card
from .doctor import validate_package, validate_project
from .watcher import queue_dataroom_updates, watch
from .review import review_fact, review_check
from .planner import plan_next
from .docx import markdown_to_docx, render_dd_report

def resource_root_from_here():
    return Path(__file__).resolve().parent / "resources"

def cmd_init(a):
    print(init_project(a.workflow, a.name, a.project_id, a.dataroom, a.case_dir))

def cmd_route(a):
    root=resource_root_from_here(); nav=load_yaml(root/"navigator.yaml"); proj=load_yaml(a.project/"project.yaml")
    result=route(nav,proj.get("intake",{}))
    result["active_checks"]=active_checks_with_extensions(root,result.get("active_checks",[]),result.get("active_extensions",[]))
    proj.update(result); proj["status"]="dataroom_setup"; dump_yaml(a.project/"project.yaml",proj)
    print(json.dumps(result,ensure_ascii=False,indent=2))

def cmd_inventory(a):
    print(json.dumps(LocalDataroomAdapter(a.project/"dataroom").get_updates(),ensure_ascii=False,indent=2))

def cmd_request(a):
    root=resource_root_from_here(); proj=load_yaml(a.project/"project.yaml"); cat=merged_evidence_catalog(root,proj.get("active_extensions",[]))
    states={x.get("requirement_id"):x.get("status") for x in (read_json(a.project/"state/evidence.json",[]) or [])}
    if a.kind=="full":
        text=render_full_generic_request(cat); filename="full-generic-request.md"
    elif a.kind=="external":
        reqs=applicable_requirements(cat,proj.get("active_checks",[]),phases=["initial","conditional","external"])
        text=render_external_workplan(reqs,states); filename="external-workplan.md"
    elif a.kind=="gap":
        reqs=applicable_requirements(cat,proj.get("active_checks",[]),phases=["initial","conditional"])
        text=render_gap_request(reqs,states); filename="gap-request.md"
    else:
        reqs=applicable_requirements(cat,proj.get("active_checks",[]),phases=["initial","conditional"])
        text=render_initial_request(reqs,states); filename="initial-request.md"
    target=a.project/"requests"/filename
    target.write_text(text,encoding="utf-8")
    docx_target=target.with_suffix(".docx")
    markdown_to_docx(text,docx_target,"Запрос документов для DD")
    print(json.dumps({"technical_markdown":str(target),"human_docx":str(docx_target)},ensure_ascii=False,indent=2))

def cmd_render(a):
    root=resource_root_from_here(); proj=load_yaml(a.project/"project.yaml"); states=read_json(a.project/"state/checks.json",[]) or []
    cards=[]
    for cid in proj.get("active_checks",[]):
        card=check_card(root,cid,proj.get("active_extensions",[]))
        current=next((x for x in states if x.get("id")==cid),{})
        card.update(current); cards.append(card)
    evidence=read_json(a.project/"state/evidence.json",[]) or []
    findings=read_json(a.project/"state/findings.json",[]) or []
    facts=read_json(a.project/"state/facts.json",[]) or []
    assets=read_json(a.project/"state/assets.json",[]) or []
    queue=read_json(a.project/"state/review-queue.json",[]) or []
    decisions=read_json(a.project/"state/decisions.json",[]) or []
    contract_inputs=read_json(a.project/"state/contract-inputs.json",{}) or {}
    html_path=write_report(a.project/"html/index.html",proj,cards,evidence,findings,facts,assets,queue,decisions,contract_inputs)
    docx_path=render_dd_report(a.project/"reports/dd-review.docx",proj,cards,evidence,findings,facts,decisions,contract_inputs)
    print(json.dumps({"human_docx":str(docx_path),"technical_html":str(html_path)},ensure_ascii=False,indent=2))

def cmd_drafting(a):
    proj=load_yaml(a.project/"project.yaml")
    package=suggest_document_package(proj)
    payload={"suggested_document_package":package,"status":"proposed","human_confirmation_required":True}
    write_json(a.project/"state/contract-inputs.json",payload)
    print(json.dumps(payload,ensure_ascii=False,indent=2))

def cmd_review_fact(a):
    result=review_fact(a.project,a.fact_id,a.status,a.value,a.comment)
    print(json.dumps(result,ensure_ascii=False,indent=2))

def cmd_review_check(a):
    result=review_check(a.project,a.check_id,a.status,a.final_status,a.comment)
    print(json.dumps(result,ensure_ascii=False,indent=2))

def cmd_watch(a):
    if a.once:
        print(json.dumps(queue_dataroom_updates(a.project),ensure_ascii=False,indent=2))
    else:
        watch(a.project,a.interval)

def cmd_plan(a):
    root=resource_root_from_here()
    print(json.dumps(plan_next(root,a.project),ensure_ascii=False,indent=2))

def cmd_doctor(a):
    root=resource_root_from_here()
    result=validate_project(a.project) if a.project else validate_package(root)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result.get("ok"): raise SystemExit(2)

def main():
    p=argparse.ArgumentParser(prog="legal-dd"); sub=p.add_subparsers(dest="cmd",required=True)
    x=sub.add_parser("init"); x.add_argument("--workflow",type=Path,default=Path("workflow")); x.add_argument("--case-dir",type=Path); x.add_argument("--name",default="DD Project"); x.add_argument("--project-id"); x.add_argument("--dataroom",choices=["local","api","mcp","none"],default="none"); x.set_defaults(func=cmd_init)
    x=sub.add_parser("route"); x.add_argument("project",type=Path); x.set_defaults(func=cmd_route)
    x=sub.add_parser("inventory"); x.add_argument("project",type=Path); x.set_defaults(func=cmd_inventory)
    x=sub.add_parser("request"); x.add_argument("project",type=Path); x.add_argument("--kind",choices=["full","initial","gap","external"],default="initial"); x.set_defaults(func=cmd_request)
    x=sub.add_parser("render"); x.add_argument("project",type=Path); x.set_defaults(func=cmd_render)
    x=sub.add_parser("drafting-package"); x.add_argument("project",type=Path); x.set_defaults(func=cmd_drafting)
    x=sub.add_parser("review-fact"); x.add_argument("project",type=Path); x.add_argument("fact_id"); x.add_argument("--status",choices=["confirmed","modified","rejected"],required=True); x.add_argument("--value"); x.add_argument("--comment"); x.set_defaults(func=cmd_review_fact)
    x=sub.add_parser("review-check"); x.add_argument("project",type=Path); x.add_argument("check_id"); x.add_argument("--status",choices=["confirmed","modified","rejected"],required=True); x.add_argument("--final-status"); x.add_argument("--comment"); x.set_defaults(func=cmd_review_check)
    x=sub.add_parser("watch"); x.add_argument("project",type=Path); x.add_argument("--interval",type=int,default=60); x.add_argument("--once",action="store_true"); x.set_defaults(func=cmd_watch)
    x=sub.add_parser("plan-next"); x.add_argument("project",type=Path); x.set_defaults(func=cmd_plan)
    x=sub.add_parser("doctor"); x.add_argument("--project",type=Path); x.set_defaults(func=cmd_doctor)
    args=p.parse_args(); args.func(args)
if __name__ == "__main__": main()
