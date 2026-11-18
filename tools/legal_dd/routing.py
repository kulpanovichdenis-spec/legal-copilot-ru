from __future__ import annotations

def _get(data, dotted):
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

def _predicate(pred, data):
    actual = _get(data, pred["field"])
    op = pred["op"]
    expected = pred.get("value")
    if op == "eq": return actual == expected
    if op == "neq": return actual != expected
    if op == "in": return actual in (expected or [])
    if op == "contains": return isinstance(actual, (list, tuple, set, str)) and expected in actual
    if op == "intersects": return bool(set(actual or []) & set(expected or []))
    if op == "not_empty": return actual not in (None, "", [], {}, ())
    if op == "neq_field": return actual != _get(data, expected)
    vals = (actual or {}).values() if isinstance(actual, dict) else (actual or [])
    if op == "has_legal_entity":
        return any(isinstance(v, dict) and v.get("entity_type") == "legal_entity" for v in vals) == bool(expected)
    if op == "has_representative_signer":
        return any(isinstance(v, dict) and v.get("signer_role") == "representative" for v in vals) == bool(expected)
    if op == "has_foreign_investor_or_control":
        return any(isinstance(v, dict) and v.get("foreign_control") is True for v in vals) == bool(expected)
    if op == "has_state_or_public_element":
        return any(isinstance(v, dict) and v.get("state_or_public") is True for v in vals) == bool(expected)
    raise ValueError(f"Unsupported op: {op}")

def evaluate(condition, data):
    if condition.get("always") is True:
        return True
    if "all" in condition:
        return all(evaluate(x, data) if "field" not in x else _predicate(x, data) for x in condition["all"])
    if "any" in condition:
        return any(evaluate(x, data) if "field" not in x else _predicate(x, data) for x in condition["any"])
    if "field" in condition:
        return _predicate(condition, data)
    return False

# BL-046: юрисдикция пишется как угодно («РФ», «Россия», «Russian Federation»), а правила ждут код.
JURISDICTION_ALIASES = {
    "ru": "RU", "rf": "RU", "рф": "RU", "россия": "RU", "russia": "RU",
    "russian federation": "RU", "российская федерация": "RU",
}
UNKNOWN = (None, "", "unknown", "неизвестно", [], ["unknown"])
# Поля, без которых маршрут неполон; при `unknown` зависящие проверки включаются с запасом.
ROUTING_INPUTS = ("transaction_type", "jurisdictions", "foreign_elements", "assets_in_scope")


def normalize_jurisdictions(value):
    if value in UNKNOWN:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    out = []
    for item in items:
        key = str(item).strip()
        code = JURISDICTION_ALIASES.get(key.lower(), key.upper() if len(key) <= 3 else key)
        if code and code.lower() != "unknown" and code not in out:
            out.append(code)
    return out


def unresolved_routing_inputs(intake):
    return [f for f in ROUTING_INPUTS if intake.get(f) in UNKNOWN]


def derive_flags(intake):
    data = dict(intake)
    data["jurisdictions"] = normalize_jurisdictions(intake.get("jurisdictions"))
    data["_derived"] = {
        "jurisdictions_unknown": not data["jurisdictions"],
        "foreign_elements_unknown": intake.get("foreign_elements") not in ("yes", "no"),
        "unresolved_routing_inputs": unresolved_routing_inputs(intake),
        "structure_defined": intake.get("transaction_type") not in (None, "unknown") and bool(intake.get("assets_in_scope")),
        "registrable_assets": bool(set(intake.get("assets_in_scope") or []) & {"registration_rights","trademarks","patents","domains","shares_interests"}),
    }
    return data

def route(navigator, intake):
    data = derive_flags(intake)
    active, extensions, matched = [], [], []
    for rule in navigator.get("routing_rules", []):
        if evaluate(rule["when"], data):
            matched.append(rule["id"])
            active.extend(rule.get("activate_checks", []))
            if rule.get("activate_extension"):
                extensions.append(rule["activate_extension"])
    return {
        "active_checks": list(dict.fromkeys(active)),
        "active_extensions": list(dict.fromkeys(extensions)),
        "matched_rules": matched,
        "derived": data["_derived"],
        "unresolved_routing_inputs": data["_derived"]["unresolved_routing_inputs"],
    }
