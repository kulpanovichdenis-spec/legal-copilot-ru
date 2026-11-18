# -*- coding: utf-8 -*-
"""Сборка результата competence по одной позиции каталога для одного общества.

Правовых выводов не делает: собирает привязанные правила, допущения и давность проверок норм
и классифицирует состояние данных. Толкование исключений и живая проверка норм — у агента
(skills/corporate-governance/SKILL.md).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402
import gov_views as views  # noqa: E402

STATUSES = ("BLOCKED", "NEEDS_FRESHNESS", "NEEDS_REVIEW", "ASSUMPTION", "RESOLVED")  # от худшего
REVIEW_CLASSES = frozenset({"CONFLICT", "NEEDS_HUMAN_REVIEW"})
STALE_DAYS = 30
CATALOG_FIELDS = ("decision_id", "title", "organs_by_law", "majority_by_law", "confirmation",
                  "sole_member", "norm_cards", "topics", "verified_at")
VERIFICATION_LABEL = {"verified": "подтверждено", "candidate": "кандидат"}


def worst(statuses: list[str]) -> str:
    return min(statuses, key=STATUSES.index) if statuses else "RESOLVED"


def _rule_entry(rule: dict, by_id: dict) -> dict:
    prov = rule.get("provenance") or {}
    return {
        "rule_id": rule["rule_id"], "layer": rule.get("layer"), "topic": rule.get("topic"),
        "subject": rule.get("subject"), "value": views.value_text(rule.get("value")),
        "classification": list(rule.get("classification") or []),
        "verification": rule.get("verification"), "needs_review": bool(rule.get("needs_review")),
        "source_id": prov.get("source_id"),
        "source_status": (by_id.get(prov.get("source_id")) or {}).get("status"),
        "locator": views.locator(prov), "quote": prov.get("quote", ""),
        "law_ref": rule.get("law_ref"), "freshness": rule.get("freshness"),
    }


def _stale_norms(decision: dict, tagged: list[dict], today: dt.date, days: int) -> list[dict]:
    by_rule = {r["rule_id"]: r for r in tagged}
    stale = []
    for item in views.find_stale(tagged, today, days):
        law = by_rule[item["rule_id"]].get("law_ref") or {}
        stale.append({"rule_id": item["rule_id"], "card": law.get("card"), "article": law.get("article"),
                      "reason": item["reason"]})
    checked = schema.to_date(decision.get("verified_at"))
    age = (today - checked).days if checked else None
    if age is None or age > days:
        reason = ("позиция каталога не проверена" if age is None
                  else f"проверка позиции каталога старше {days} дн. (возраст: {age})")
        for ref in decision["norm_cards"]:
            stale.append({"catalog": decision["decision_id"], "card": ref["card"],
                          "article": ref["article"], "reason": reason})
    return stale


def assemble(decision: dict, catalog: dict, rules: list[dict], sources: list[dict],
             assumptions: list[dict], *, slug: str, today: dt.date, days: int = STALE_DAYS) -> dict:
    did = decision["decision_id"]
    by_id = {s["source_id"]: s for s in sources}
    tagged = sorted((r for r in rules if did in (r.get("decisions") or [])), key=lambda r: r["rule_id"])
    charters = [s for s in sources if s.get("kind") == "charter"]
    current = [s for s in charters if s.get("status") == "current"]
    topics = set(decision["topics"])
    open_assumptions = [a for a in assumptions
                        if a.get("status", "open") != "resolved" and a.get("topic") in topics]
    stale = _stale_norms(decision, tagged, today, days)
    untagged = sorted(r["rule_id"] for r in views.active_rules(rules)
                      if not r.get("decisions") and r.get("topic") in topics)
    notes = [f"{r['rule_id']}: класс POTENTIALLY_OUTDATED — положение может быть устаревшим"
             for r in tagged if "POTENTIALLY_OUTDATED" in (r.get("classification") or [])]
    reasons: dict[str, list[str]] = {status: [] for status in STATUSES}

    if not current:
        reasons["BLOCKED"].append("нет устава со статусом current (проверьте check-edition)")
    if not catalog.get("approved_by"):
        reasons["NEEDS_REVIEW"].append("каталог решений не подтверждён юристом")
    for rule in tagged:
        rid = rule["rule_id"]
        source = by_id.get((rule.get("provenance") or {}).get("source_id")) or {}
        if source.get("status") == "superseded" or rule.get("needs_review"):
            reasons["BLOCKED"].append(f"{rid}: источник заменён новой редакцией, правило на пересмотре")
        fresh = rule.get("freshness") or {}
        if fresh.get("status") in ("changed", "failed"):
            reasons["BLOCKED"].append(
                f"{rid}: проверка нормы {fresh['status']}: {fresh.get('required_action') or 'пересмотреть правило'}")
        if rule.get("verification") != "verified":
            reasons["NEEDS_REVIEW"].append(f"{rid}: кандидат, не подтверждён юристом")
        flagged = REVIEW_CLASSES.intersection(rule.get("classification") or [])
        if flagged:
            reasons["NEEDS_REVIEW"].append(f"{rid}: класс {', '.join(sorted(flagged))}")
    for item in stale:
        label = item.get("rule_id") or f"каталог {item['catalog']}"
        reasons["NEEDS_FRESHNESS"].append(f"{label}: {item['card']} {item['article']}: {item['reason']}")
    for a in open_assumptions:
        reasons["ASSUMPTION"].append(f"{a['assumption_id']}: {a.get('missing_data')}")
    if untagged:
        reasons["NEEDS_REVIEW"].append(
            f"в темах позиции есть правила без привязки: {', '.join(untagged)}; "
            "разметка не завершена, молчание устава не установлено")
    if not tagged:
        reasons["ASSUMPTION"].append(
            "привязанных правил нет; норма закона по умолчанию — см. каталог; "
            "вывод о молчании устава — за юристом")

    status = next((s for s in STATUSES[:-1] if reasons[s]), "RESOLVED")
    source = (current or charters or [None])[0]
    return {
        "entity": slug, "decision": did, "as_of": today.isoformat(),
        "catalog": {k: decision.get(k) for k in CATALOG_FIELDS},
        "charter_rules": [_rule_entry(r, by_id) for r in tagged],
        "assumptions": open_assumptions,
        "stale_norms": stale,
        "charter_silent": not tagged,
        "untagged_in_topics": untagged,
        "notes": notes,
        "source": ({k: source.get(k) for k in ("source_id", "title", "status")} if source else None),
        "status": status,
        "reasons": [text for s in STATUSES for text in reasons[s]],
    }


def render_md(payload: dict) -> str:
    lines = [f"# Компетенция: {payload['entity']} на {payload['as_of']}: {payload['status']}"]
    for res in payload["results"]:
        cat = res["catalog"]
        lines += ["", f"## {cat['title']} ({res['decision']}): {res['status']}",
                  f"- По закону: {cat['organs_by_law']}; большинство: {cat['majority_by_law']}; "
                  f"подтверждение: {cat['confirmation']}",
                  f"- Единственный участник: {cat['sole_member']}"]
        if res["charter_silent"]:
            lines.append("- Привязанных правил нет (вывод о молчании устава — за юристом)")
        if res.get("untagged_in_topics", []):
            lines.append(f"- Правила без привязки в темах позиции: {', '.join(res.get('untagged_in_topics', []))}")
        lines += [f"- Оговорка: {note}" for note in res.get("notes", [])]
        for r in res["charter_rules"]:
            label = VERIFICATION_LABEL.get(r["verification"], r["verification"])
            lines.append(f"- {r['rule_id']}, {r['locator']}: {r['subject']}: {r['value']} [{label}]")
        lines += [f"- {reason}" for reason in res["reasons"]]
    return "\n".join(lines)
