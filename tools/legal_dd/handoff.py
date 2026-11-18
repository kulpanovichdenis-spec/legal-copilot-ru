def build_contract_inputs(findings, decisions):
    confirmed={x.get("id"):x for x in findings if (x.get("human_review") or {}).get("status") in {"confirmed","modified"}}
    result=[]
    for decision in decisions:
        human=(decision.get("human_decision") or {})
        if human.get("status") not in {"confirmed","modified"}:
            continue
        refs=[confirmed[x] for x in decision.get("source_findings",[]) if x in confirmed]
        result.append({
            "decision_id":decision.get("decision_id"),
            "topic":decision.get("topic"),
            "selected_option":human.get("selected_option"),
            "source_findings":[x.get("id") for x in refs],
            "contract_effect":decision.get("contract_effect",{}),
        })
    return {"contract_decisions":result}

def build_roadmap_payload(project, signed_documents, obligations):
    return {"project_id":project.get("project_id"),"signed_documents":signed_documents,"obligations":obligations,"source":"legal-dd-navigator"}
