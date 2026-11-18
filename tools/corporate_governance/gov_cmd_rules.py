# -*- coding: utf-8 -*-
"""Команды: add-rule, update-rule, set-freshness, add-fact, update-fact, add-assumption.

Любое изменение содержания уже подтверждённой записи возвращает её в candidate:
подтверждение относится к конкретному содержанию, а не к идентификатору.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402


# ---------- разбор аргументов ----------

def _parse_json(text: str, option: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise store.GovError(f"{option}: невалидный JSON ({exc})") from exc


def _rule_value(args):
    """Значение правила: --value → {"text": ...}; --value-json → как есть."""
    if args.value_json is not None:
        return _parse_json(args.value_json, "--value-json")
    if args.value is not None:
        return {"text": args.value}
    return None


def _fact_value(args):
    """Значение факта: --value → строка как есть; --value-json → как есть (true/false/объект)."""
    if args.value_json is not None:
        return _parse_json(args.value_json, "--value-json")
    return args.value


def _classes(text: str) -> list[str]:
    return [c.strip() for c in text.split(",") if c.strip()]


def _law_ref(card, article):
    if card is None and article is None:
        return None
    if card is None:
        raise store.GovError("--law-article без --law-card: укажите карточку-указатель нормы")
    return {"card": card, "article": article}


def _law_ref_key(law_ref) -> tuple:
    """Норма, на которую указывает law_ref: (карточка, статья); отсутствие ключа = пусто."""
    ref = law_ref if isinstance(law_ref, dict) else {}
    return ref.get("card"), ref.get("article")


def _add_provenance_args(parser, *, required: bool) -> None:
    parser.add_argument("--source-id", required=required)
    parser.add_argument("--page", type=int, required=required)
    parser.add_argument("--clause", required=required, help="номер пункта документа")
    parser.add_argument("--quote", required=required, help="дословная цитата (с листа или скана)")
    # default=None (не "agent"): update-rule/update-fact должны различать «флаг не передан»
    # (оставить как было) от «передан явно» (T5.1); add-rule/add-fact подставляют "agent" сами в _provenance
    parser.add_argument("--extracted-by", default=None)


def _add_value_args(parser) -> None:
    parser.add_argument("--value", help="значение текстом")
    parser.add_argument("--value-json", help="значение в JSON (число, true/false, объект)")


def _provenance(args) -> dict:
    return {"source_id": args.source_id, "page": args.page, "clause": args.clause,
            "quote": args.quote, "extracted_by": args.extracted_by or "agent",
            "extracted_at": store.today()}


def _find(items: list[dict], key: str, value: str, what: str) -> dict:
    for item in items:
        if item.get(key) == value:
            return item
    raise store.GovError(f"{what} не найден: {value}")


def _reset_verification(record: dict) -> bool:
    if record.get("verification") == "verified":
        record["verification"] = "candidate"
        record["verified_by"] = None
        record["verified_at"] = None
        return True
    return False


def _update_provenance(record: dict, args) -> list[str]:
    changed = []
    prov = record["provenance"]
    quote_affecting = False
    for arg_name, key in (("source_id", "source_id"), ("page", "page"),
                          ("clause", "clause"), ("quote", "quote")):
        value = getattr(args, arg_name)
        if value is not None:
            prov[key] = value
            changed.append(f"provenance.{key}")
            quote_affecting = True
    # T5.1: --extracted-by пробрасывается в provenance только когда передан явно —
    # иначе update-rule/update-fact молча стирали бы, кто на самом деле извлёк запись
    if args.extracted_by is not None:
        prov["extracted_by"] = args.extracted_by
        changed.append("provenance.extracted_by")
    if quote_affecting:
        prov.pop("quote_check", None)  # цитату нужно сверить заново
        prov["extracted_at"] = store.today()
    return changed


# ---------- правила ----------

def cmd_add_rule(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_rules()
    value = _rule_value(args)
    rule = {
        "rule_id": store.next_id("R", data["rules"], "rule_id"),
        "layer": args.layer, "topic": args.topic, "subject": args.subject,
        "value": value, "classification": _classes(args.classification),
        "law_ref": _law_ref(args.law_card, args.law_article),
        "freshness": None, "provenance": _provenance(args),
        "verification": "candidate", "verified_by": None, "verified_at": None,
    }
    errors = schema.validate_rule(rule, entity.sources_by_id())
    if errors:
        raise store.GovError("; ".join(errors))
    data["rules"].append(rule)
    rev = entity.save_rules(data)
    entity.audit("add-rule", rule["rule_id"], actor=args.actor, new=rule,
                 source=args.source_id, rev=rev)
    print(f"OK: {rule['rule_id']} [{rule['topic']}] {rule['subject']} (кандидат)")
    return 0


def cmd_update_rule(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_rules()
    rule = _find(data["rules"], "rule_id", args.rule_id, "правило")
    before = copy.deepcopy(rule)
    changed: list[str] = []
    freshness_cleared = False
    if args.subject is not None:
        rule["subject"] = args.subject
        changed.append("subject")
    value = _rule_value(args)
    if value is not None:
        rule["value"] = value
        changed.append("value")
    if args.classification is not None:
        rule["classification"] = _classes(args.classification)
        changed.append("classification")
    if args.law_card is not None or args.law_article is not None:
        current = rule.get("law_ref") or {}
        card = args.law_card if args.law_card is not None else current.get("card")
        article = args.law_article if args.law_article is not None else current.get("article")
        rule["law_ref"] = _law_ref(card, article)
        changed.append("law_ref")
        # Legal Freshness Check — результат открытия одной конкретной нормы: при смене нормы он неприменим
        if _law_ref_key(rule["law_ref"]) != _law_ref_key(before.get("law_ref")) and rule.get("freshness"):
            rule["freshness"] = None
            changed.append("freshness")
            freshness_cleared = True
    changed += _update_provenance(rule, args)
    if not changed:
        raise store.GovError("нечего обновлять: не указано ни одного поля")
    downgraded = _reset_verification(rule)
    errors = schema.validate_rule(rule, entity.sources_by_id())
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_rules(data)
    audited = ("subject", "value", "classification", "law_ref", "freshness", "provenance", "verification")
    entity.audit("update-rule", rule["rule_id"], actor=args.actor,
                 old={k: before.get(k) for k in audited}, new={k: rule.get(k) for k in audited}, rev=rev)
    note = " (подтверждение снято: правило снова кандидат)" if downgraded else ""
    if freshness_cleared:
        note += " (freshness сброшен: норма изменилась, нужна новая проверка)"
    print(f"OK: {rule['rule_id']} обновлено: {', '.join(changed)}{note}")
    return 0


def cmd_set_freshness(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_rules()
    rule = _find(data["rules"], "rule_id", args.rule_id, "правило")
    if not rule.get("law_ref"):
        raise store.GovError(
            f"{rule['rule_id']}: у правила нет law_ref; сначала update-rule --law-card <карточка>")
    fresh = {
        "status": args.status,
        "checked_at": args.checked_at or store.today(),
        "checked_source": args.checked_source,
        "edition": args.edition,
        "differences_from_local_playbook": args.differences,
        "required_action": args.required_action,
    }
    errors = schema.validate_freshness(fresh)
    if errors:
        raise store.GovError("; ".join(errors))
    old = rule.get("freshness")
    rule["freshness"] = fresh
    downgraded = False
    if args.status != "verified":
        downgraded = _reset_verification(rule)
    rev = entity.save_rules(data)
    entity.audit("set-freshness", rule["rule_id"], actor=args.actor, old=old, new=fresh, rev=rev)
    note = " (подтверждение снято: правило снова кандидат)" if downgraded else ""
    print(f"OK: {rule['rule_id']} freshness={args.status}{note}")
    return 0


# ---------- факты профиля ----------

def cmd_add_fact(args) -> int:
    entity = store.entity_from_args(args)
    profile = entity.load_profile()
    if args.section == "classification" and any(
        f["section"] == "classification" and f["key"] == args.key and not f.get("needs_review")
        for f in profile["facts"]
    ):
        raise store.GovError(
            f"поле классификации {args.key!r} уже задано; используйте update-fact")
    fact = {
        "fact_id": store.next_id("F", profile["facts"], "fact_id"),
        "section": args.section, "key": args.key, "value": _fact_value(args),
        "provenance": _provenance(args),
        "verification": "candidate", "verified_by": None, "verified_at": None,
    }
    errors = schema.validate_fact(fact, entity.sources_by_id())
    if errors:
        raise store.GovError("; ".join(errors))
    profile["facts"].append(fact)
    rev = entity.save_profile(profile)
    entity.audit("add-fact", fact["fact_id"], actor=args.actor, new=fact,
                 source=args.source_id, rev=rev)
    print(f"OK: {fact['fact_id']} [{fact['section']}] {fact['key']} (кандидат)")
    return 0


def cmd_update_fact(args) -> int:
    entity = store.entity_from_args(args)
    profile = entity.load_profile()
    fact = _find(profile["facts"], "fact_id", args.fact_id, "факт")
    before = copy.deepcopy(fact)
    changed: list[str] = []
    if args.value is not None or args.value_json is not None:
        fact["value"] = _fact_value(args)
        changed.append("value")
    changed += _update_provenance(fact, args)
    if not changed:
        raise store.GovError("нечего обновлять: не указано ни одного поля")
    downgraded = _reset_verification(fact)
    errors = schema.validate_fact(fact, entity.sources_by_id())
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_profile(profile)
    entity.audit("update-fact", fact["fact_id"], actor=args.actor,
                 old={k: before.get(k) for k in ("value", "provenance", "verification")},
                 new={k: fact.get(k) for k in ("value", "provenance", "verification")}, rev=rev)
    note = " (подтверждение снято: факт снова кандидат)" if downgraded else ""
    print(f"OK: {fact['fact_id']} обновлён: {', '.join(changed)}{note}")
    return 0


def cmd_add_assumption(args) -> int:
    entity = store.entity_from_args(args)
    profile = entity.load_profile()
    item = {
        "assumption_id": store.next_id("A", profile["assumptions"], "assumption_id"),
        "topic": args.topic,
        "missing_data": args.missing_data,
        "default_rule_if_no_special_rule": args.default_rule,
        "risk": args.risk,
        "required_verification": args.required_verification,
        "law_ref": _law_ref(args.law_card, args.law_article),
        "status": "open",
        "created_at": store.today(),
    }
    errors = schema.validate_assumption(item)
    if errors:
        raise store.GovError("; ".join(errors))
    profile["assumptions"].append(item)
    rev = entity.save_profile(profile)
    entity.audit("add-assumption", item["assumption_id"], actor=args.actor, new=item, rev=rev)
    print(f"OK: {item['assumption_id']} [{item['topic']}] допущение зафиксировано (стандартное правило не подставлено)")
    return 0


def cmd_resolve_assumption(args) -> int:
    """Недостающее получено: допущение не удаляется, а снимается с основанием (история в профиле и аудите)."""
    entity = store.entity_from_args(args)
    profile = entity.load_profile()
    item = next((a for a in profile["assumptions"] if a.get("assumption_id") == args.assumption_id), None)
    if item is None:
        raise store.GovError(f"допущение {args.assumption_id} не найдено")
    if item.get("status") == "resolved":
        raise store.GovError(f"{args.assumption_id} уже снято ({item.get('resolved_basis')})")
    basis = (args.basis or "").strip()
    if not basis:
        raise store.GovError("--basis пуст: укажите, чем снято допущение (какой документ получен)")
    if args.source_id and args.source_id not in entity.sources_by_id():
        raise store.GovError(f"источник {args.source_id} не зарегистрирован")
    old = {"status": item.get("status", "open")}
    item.update(status="resolved", resolved_basis=basis, resolved_by_source=args.source_id or None,
                resolved_at=store.today())
    errors = schema.validate_assumption(item)
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_profile(profile)
    entity.audit("resolve-assumption", item["assumption_id"], actor=args.actor, old=old,
                 new={"status": "resolved", "resolved_basis": basis, "resolved_by_source": item["resolved_by_source"]},
                 source=args.source_id, rev=rev)
    print(f"OK: {item['assumption_id']} снято: {basis}")
    return 0


def register(sub) -> None:
    common = store.common_parser()

    p = sub.add_parser("add-rule", parents=[common],
                       help="внести правило из документа (кандидат, с provenance)")
    p.add_argument("--layer", default="charter", choices=schema.LAYERS)
    p.add_argument("--topic", required=True, choices=schema.TOPICS)
    p.add_argument("--subject", required=True, help="предмет правила")
    _add_value_args(p)
    p.add_argument("--classification", required=True,
                   help="классы через запятую: " + ", ".join(schema.CLASSIFICATIONS))
    p.add_argument("--law-card", help="карточка-указатель нормы, например llc/notice")
    p.add_argument("--law-article", help="статья и пункт, открытые живым маршрутом")
    _add_provenance_args(p, required=True)
    p.set_defaults(func=cmd_add_rule)

    p = sub.add_parser("update-rule", parents=[common],
                       help="изменить правило; подтверждённое возвращается в кандидаты")
    p.add_argument("--rule-id", required=True)
    p.add_argument("--subject")
    _add_value_args(p)
    p.add_argument("--classification")
    p.add_argument("--law-card")
    p.add_argument("--law-article")
    _add_provenance_args(p, required=False)
    p.set_defaults(func=cmd_update_rule)

    p = sub.add_parser("set-freshness", parents=[common],
                       help="записать результат Legal Freshness Check по правилу")
    p.add_argument("--rule-id", required=True)
    p.add_argument("--status", required=True, choices=schema.FRESHNESS_STATUSES)
    p.add_argument("--checked-source", default="pravo-gov-ru")
    p.add_argument("--edition", help="редакция и дата открытого текста нормы")
    p.add_argument("--checked-at", help="дата проверки YYYY-MM-DD (по умолчанию сегодня)")
    p.add_argument("--differences", help="чем живой текст отличается от карточки-указателя")
    p.add_argument("--required-action", help="что сделать (обязательно при changed/uncertain/failed)")
    p.set_defaults(func=cmd_set_freshness)

    p = sub.add_parser("add-fact", parents=[common],
                       help="внести факт профиля компании (кандидат, с provenance)")
    p.add_argument("--section", required=True, choices=schema.FACT_SECTIONS)
    p.add_argument("--key", required=True)
    _add_value_args(p)
    _add_provenance_args(p, required=True)
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("update-fact", parents=[common],
                       help="изменить факт; подтверждённый возвращается в кандидаты")
    p.add_argument("--fact-id", required=True)
    _add_value_args(p)
    _add_provenance_args(p, required=False)
    p.set_defaults(func=cmd_update_fact)

    p = sub.add_parser("add-assumption", parents=[common],
                       help="зафиксировать допущение вместо молчаливого стандартного правила (§24)")
    # I5: помимо 16 тем правил допущение принимает ещё "classification" — для молчащего поля
    # классификации компании (issuer_status и т. п.), для которого в документе нет вообще никакой
    # опоры (значит, нет цитаты для add-fact); add-rule/update-rule эту тему не принимают.
    p.add_argument("--topic", required=True, choices=schema.ASSUMPTION_TOPICS)
    p.add_argument("--missing-data", required=True, help="чего не хватает")
    p.add_argument("--default-rule", required=True,
                   help="что действует, если специального правила нет")
    p.add_argument("--risk", required=True)
    p.add_argument("--required-verification", required=True, help="что запросить или проверить")
    p.add_argument("--law-card")
    p.add_argument("--law-article")
    p.set_defaults(func=cmd_add_assumption)

    p = sub.add_parser("resolve-assumption", parents=[common],
                       help="снять допущение: недостающий документ получен (запись остаётся с основанием)")
    p.add_argument("--assumption-id", required=True)
    p.add_argument("--basis", required=True, help="чем снято: какой документ получен и что из него следует")
    p.add_argument("--source-id", help="источник, которым снято допущение (если зарегистрирован)")
    p.set_defaults(func=cmd_resolve_assumption)
