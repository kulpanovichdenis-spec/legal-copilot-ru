from collections import defaultdict
from .i18n import tr_status

def applicable_requirements(catalog, active_checks, phases=None):
    active=set(active_checks); out=[]
    phases=set(phases or ["initial","conditional","external","closing","derived"])
    for req in catalog.get("requirements",[]):
        phase=req.get("request_phase","initial")
        if phase not in phases:
            continue
        activation=req.get("activation_checks",req.get("mapped_checks",[]))
        if activation and active.intersection(activation):
            out.append(req)
    return out

def _group(requirements, statuses, include_satisfied=False):
    groups=defaultdict(list)
    for req in requirements:
        st=statuses.get(req["id"],"not_requested")
        if not include_satisfied and st in {"satisfied","external_source","not_applicable"}:
            continue
        groups[req.get("requested_from","seller")].append((req,st))
    return groups

def render_full_generic_request(catalog):
    lines=["# Полный общий запрос документов для DD","","Условные пункты должны быть отфильтрованы после определения структуры сделки.",""]
    groups=_group([r for r in catalog.get("requirements",[]) if r.get("request_phase") not in {"external","closing","derived","extension_replaced"}],{},True)
    for recipient,items in groups.items():
        if recipient in {"external_check","system_derived"}: continue
        lines += [f"## {recipient}",""]
        for req,_ in items:
            prefix="[Если применимо] " if req.get("request_phase")=="conditional" else ""
            lines.append(f"- [{req['id']}] {prefix}{req.get('request_text','')}")
        lines.append("")
    return "\n".join(lines)

def render_initial_request(requirements, statuses=None):
    statuses=statuses or {}; groups=_group(requirements,statuses)
    lines=["# Первоначальный запрос документов для DD",""]
    for recipient,items in groups.items():
        if recipient in {"external_check","system_derived"}: continue
        lines += [f"## {recipient}",""]
        seen=set()
        for req,_ in items:
            txt=req.get("request_text","").strip()
            if txt and txt not in seen:
                prefix="[Если применимо] " if req.get("request_phase")=="conditional" else ""
                lines.append(f"- [{req['id']}] {prefix}{txt}"); seen.add(txt)
        lines.append("")
    return "\n".join(lines)

def render_external_workplan(requirements, statuses=None):
    statuses=statuses or {}; lines=["# План независимых внешних проверок DD",""]
    for req in requirements:
        st=statuses.get(req['id'],'not_requested')
        if (req.get("external_verification") or req.get("request_phase")=="external") and st not in {"satisfied","external_source","not_applicable"}:
            lines.append(f"- [{req['id']}] {req['title']} — {req.get('gap_text') or req.get('request_text','')}")
    return "\n".join(lines)+"\n"

def render_gap_request(requirements, statuses):
    relevant={"not_requested","requested","received","partially_satisfied","invalid","outdated","unavailable"}
    lines=["# Дополнительный запрос по недостающим материалам DD",""]
    for req in requirements:
        st=statuses.get(req["id"],"not_requested")
        if st in relevant and req.get("requested_from") not in {"external_check","system_derived"}:
            lines.append(f"- [{req['id']}] **{tr_status(st)}** — {req.get('gap_text') or req.get('request_text','')}")
    return "\n".join(lines)+"\n"
