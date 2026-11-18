VALID={"not_requested","requested","received","partially_satisfied","satisfied","invalid","outdated","not_applicable","unavailable","external_source"}

def can_support_clear(status):
    return status in {"satisfied","external_source","not_applicable"}

def check_evidence_gate(requirement_statuses):
    blocking={k:v for k,v in requirement_statuses.items() if not can_support_clear(v)}
    return {"can_be_clear":not blocking,"blocking_requirements":blocking}
