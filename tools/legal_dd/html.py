from __future__ import annotations
from html import escape
from pathlib import Path
from .utils import utc_now
from .i18n import tr_status, tr_value, tr_field, tr_review_item

def _badge(text, cls="neutral"):
    return f'<span class="badge {cls}">{escape(str(text))}</span>'

def _title(item):
    return item.get("title_ru") or item.get("title") or item.get("id","")

def render_report(project, checks, evidence, findings, facts, assets=None, review_queue=None, decisions=None, contract_inputs=None):
    assets = assets or []
    review_queue = review_queue or []
    decisions = decisions or []
    contract_inputs = contract_inputs or {}
    evidence_by_id = {x.get("requirement_id", x.get("id")): x for x in evidence}
    intake=project.get("intake") or {}
    jurisdictions=", ".join(intake.get("jurisdictions") or []) or "—"
    transaction_type=tr_value(intake.get("transaction_type"))
    dataroom_mode=tr_value((project.get("dataroom") or {}).get("mode","—"))
    extensions=", ".join(project.get("active_extensions") or []) or "—"
    counts = {"confirmed":0,"pending":0,"issue":0}
    check_cards=[]
    for check in checks:
        human=(check.get("human_review") or {}).get("status","pending")
        agent=(check.get("agent_assessment") or {}).get("status","not_started")
        counts["confirmed" if human in {"confirmed","modified"} else "pending"] += 1
        if agent == "issue": counts["issue"] += 1
        reqs=check.get("evidence_requirements",[])
        missing=[r for r in reqs if (evidence_by_id.get(r) or {}).get("status") not in {"satisfied","external_source","not_applicable"}]
        conclusion=escape((check.get("agent_assessment") or {}).get("conclusion","") or "—")
        check_cards.append(
            '<details class="card"><summary><b>{}</b> {} {} {}</summary>'
            '<div class="body"><p><b>Предварительное разрешение области:</b> {}</p>'
            '<p><b>Требования к доказательствам:</b> {}</p><p><b>Не закрыто / открытые вопросы:</b> {}</p></div></details>'.format(
                escape(check.get("id","")), escape(_title(check)),
                _badge(tr_status(agent), "issue" if agent=="issue" else "ok" if agent=="clear" else "neutral"),
                _badge(tr_status(human),"human"), conclusion,
                escape(", ".join(reqs)), escape(", ".join(missing) or "—")
            )
        )
    evrows=[]
    for item in evidence:
        evrows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(item.get("requirement_id",item.get("id",""))), escape(item.get("title_ru") or item.get("title","") or item.get("requirement_id","")),
            escape(tr_status(item.get("status",""))), escape(", ".join(item.get("documents",[])) or "—"), escape(item.get("missing","") or "—")))
    factrows=[]
    for fact in facts:
        loc=fact.get("location") or {}
        where=" / ".join(str(loc.get(k)) for k in ["document_id","page","section","paragraph","sheet","cell","api_field"] if loc.get(k) not in (None,""))
        factrows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><q>{}</q><br><small>{}</small></td><td>{}</td></tr>".format(
            escape(fact.get("fact_id","")), escape(tr_field(fact.get("field_id",""))), escape(tr_status(fact.get("state",""))),
            escape(tr_value(fact.get("normalized_value",""))), escape(fact.get("quote") or ""), escape(where),
            escape(tr_status((fact.get("human_review") or {}).get("status","pending")))))
    decisionrows=[]
    for decision in decisions:
        hd=decision.get("human_decision") or {}
        decisionrows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(decision.get("decision_id","")), escape(decision.get("topic_ru") or decision.get("topic","")),
            escape(tr_value(hd.get("selected_option") or decision.get("agent_proposal") or "")), escape(tr_status(hd.get("status","pending")))))
    package=(contract_inputs.get("suggested_document_package") or contract_inputs.get("contract_decisions") or [])
    package_html="<ul>"+"".join(f"<li>{escape(tr_value(x))}</li>" for x in package)+"</ul>" if package else "<p>—</p>"
    findingrows=[]
    for finding in findings:
        findingrows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(finding.get("id","")), escape(finding.get("check_id","")), escape(finding.get("summary_ru") or finding.get("summary","") or "—"),
            escape(tr_status(finding.get("severity",""))), escape(tr_status((finding.get("human_review") or {}).get("status","pending")))))
    assetrows="".join("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        escape(a.get("asset_id","")), escape(tr_value(a.get("asset_type",""))), escape(a.get("name_ru") or a.get("name","")),
        escape(a.get("jurisdiction","")), escape(a.get("holder_ru") or a.get("holder",""))) for a in assets)
    style="""body{font-family:Arial,sans-serif;margin:0;background:#f5f6f8;color:#1f2937}.wrap{max-width:1250px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.kpi,.card,section{background:white;border:1px solid #e5e7eb;border-radius:10px}.kpi{padding:16px}.kpi b{font-size:28px}.meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.meta div{background:#fff;padding:10px;border:1px solid #e5e7eb;border-radius:8px}.label{font-size:12px;color:#6b7280;text-transform:uppercase}.card{margin:8px 0;padding:0}.card summary{cursor:pointer;padding:14px}.body{padding:0 14px 14px}.badge{display:inline-block;padding:3px 7px;border-radius:12px;background:#e5e7eb;font-size:12px}.badge.issue{background:#fee2e2}.badge.ok{background:#dcfce7}.badge.human{background:#dbeafe}section{padding:18px;margin:18px 0}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:8px;text-align:left;vertical-align:top}small{color:#6b7280}q{font-size:13px}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}}"""
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{title}</title><style>{style}</style></head><body><div class="wrap"><h1>{title}</h1><p>{pid} · {status} · сформировано {rendered}</p><div class="meta"><div><span class="label">Тип сделки</span><br>{transaction_type}</div><div><span class="label">Юрисдикции</span><br>{jurisdictions}</div><div><span class="label">Data room</span><br>{dataroom_mode}</div><div><span class="label">Расширения</span><br>{extensions}</div></div><div class="grid" style="margin-top:12px"><div class="kpi"><b>{total}</b><br>Активных областей DD</div><div class="kpi"><b>{confirmed}</b><br>Подтверждено человеком</div><div class="kpi"><b>{pending}</b><br>Ожидает проверки</div><div class="kpi"><b>{issues}</b><br>Вопросов, выявленных агентом</div></div><section><h2>Периметр сделки / Активы</h2><table><tr><th>ID</th><th>Тип</th><th>Наименование</th><th>Юрисдикция</th><th>Правообладатель / держатель</th></tr>{assetrows}</table></section><section><h2>Покрытие доказательствами</h2><table><tr><th>ID</th><th>Что требуется подтвердить</th><th>Статус</th><th>Документы</th><th>Не хватает</th></tr>{evrows}</table></section><section><h2>Покрытие DD / обязательства проверки</h2>{checks}</section><section><h2>Факты для подтверждения человеком</h2><table><tr><th>Факт</th><th>Поле</th><th>Статус</th><th>Значение</th><th>Источник и точное место</th><th>Проверка человеком</th></tr>{factrows}</table></section><section><h2>Выявленные вопросы</h2><table><tr><th>ID</th><th>Проверка</th><th>Описание</th><th>Существенность</th><th>Проверка человеком</th></tr>{findingrows}</table></section><section><h2>Подготовка сделочной документации</h2><h3>Предлагаемый пакет документов</h3>{package}<h3>Решения по структуре договора</h3><table><tr><th>ID</th><th>Вопрос</th><th>Выбранный / предложенный вариант</th><th>Проверка человеком</th></tr>{decisionrows}</table></section><section><h2>Очередь на проверку</h2><pre>{review}</pre></section></div></body></html>""".format(
        title=escape(project.get("name_ru") or project.get("name","DD-проект")), style=style, pid=escape(project.get("project_id","")),
        status=escape(tr_status(project.get("status",""))), rendered=escape(utc_now()), transaction_type=escape(transaction_type), jurisdictions=escape(jurisdictions), dataroom_mode=escape(dataroom_mode), extensions=escape(extensions), total=len(checks), confirmed=counts["confirmed"],
        pending=counts["pending"], issues=counts["issue"], assetrows=assetrows, evrows="".join(evrows), checks="".join(check_cards),
        factrows="".join(factrows), findingrows="".join(findingrows), package=package_html, decisionrows="".join(decisionrows), review=escape("\n".join(tr_review_item(x) for x in review_queue) or "—"))

def write_report(path, *args, **kwargs):
    p=Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_report(*args, **kwargs), encoding="utf-8")
    return p
