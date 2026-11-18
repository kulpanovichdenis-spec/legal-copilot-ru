#!/usr/bin/env python3
"""Acceptance-проверки по режимам (ТЗ §3, §29–31). Регистрируются в validate.MODE_CHECKS."""
from __future__ import annotations

import re

import bc_model as M
from bc_model import Issue

OBSERVABLE_RE = re.compile(
    r"(уме|определ|провер|отлич|распозна|заполн|согласов|эскалир|обрат|выбр|сравн|назва|назов|"
    r"составл|оцен|примен|найт|найд|перечисл|отказ|оформ|запрос)", re.IGNORECASE)
VAGUE_RE = re.compile(r"(рассказать|ознакомить|познакомить|знать о|иметь представление)", re.IGNORECASE)


def _e(code, where, message):
    return Issue("error", code, where, message)


def _w(code, where, message):
    return Issue("warn", code, where, message)


def _section(idx: dict, name: str) -> list[dict]:
    return [v for v in idx.values() if v["_section"] == name]


def check_training(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    objectives = model["objective"]["learning_objectives"]
    if not objectives:
        out.append(_e("T01", "objective.learning_objectives", "нет learning objectives"))
    for n, obj in enumerate(objectives):
        where = f"objective.learning_objectives[{n}]"
        if not OBSERVABLE_RE.search(obj):
            out.append(_e("T02", where, f"цель не выражена наблюдаемым действием: «{obj}»"))
        elif VAGUE_RE.search(obj):
            out.append(_w("T02", where, f"размытая формулировка цели: «{obj}»"))
    escalation = _section(idx, "escalation_points")
    if not escalation:
        out.append(_e("T03", "content.escalation_points", "не определена точка эскалации в Legal"))
    for e in escalation:
        if not e.get("when"):
            out.append(_e("T03", e["id"], "у точки эскалации нет условия «когда»"))
    main = M.main_storyline(model)
    if main and main[-1]["content_block"] not in ("checklist", "required_action"):
        out.append(_e("T04", f"storyline[{main[-1].get('order')}]", "финал обучения — checklist / действия"))
    kinds = {i.get("kind", "case") for i in _section(idx, "internal_examples")}
    if not {"wrong", "better"} <= kinds:
        out.append(_w("T05", "content.internal_examples", "нет пары «как неправильно / как лучше»"))
    if not (kinds & {"case"} or _section(idx, "cases")):
        out.append(_w("T06", "content", "нет реальной рабочей ситуации (кейса)"))
    return out


def check_report(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    if not _section(idx, "impacts"):
        out.append(_e("R01", "content.impacts", "отчёт без бизнес-эффекта (хотя бы qualitative)"))
    main = M.main_storyline(model)
    if main:
        first_refs = [idx[r] for r in main[0]["evidence_refs"] if r in idx]
        if any(r["_section"] == "metrics" and r.get("kind") == "activity" for r in first_refs):
            out.append(_e("R02", f"storyline[{main[0].get('order')}]",
                          "отчёт начинается с количества действий, а не с результата"))
    if not _section(idx, "risks"):
        out.append(_e("R03", "content.risks", "нет нерешённых рисков / открытых вопросов"))
    if not _section(idx, "next_steps"):
        out.append(_e("R04", "content.next_steps", "нет следующих шагов"))
    return out


def check_recommendation(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    if not model["objective"].get("required_decision"):
        out.append(_e("D01", "objective.required_decision", "не сформулировано требуемое решение"))
    options = _section(idx, "options")
    if len(options) < 2:
        out.append(_e("D02", "content.options", "нужно минимум два реально различающихся варианта"))
    if len([o for o in options if o.get("recommended")]) != 1:
        out.append(_e("D03", "content.options", "должен быть ровно один рекомендуемый вариант"))
    for o in options:
        if not o.get("cons"):
            out.append(_e("D04", o["id"], "у варианта не показан trade-off (cons)"))
    if options and not any(o.get("fallback") for o in options):
        out.append(_w("D05", "content.options", "нет fallback-варианта"))
    main = [s for s in M.main_storyline(model) if s["title_kind"] == "assertion"]
    if main and main[0]["content_block"] not in ("recommendation", "decision"):
        out.append(_e("D06", f"storyline[{main[0].get('order')}]", "рекомендация должна идти первой"))
    return out


def check_change(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    ch = model["change"]
    for key in ("current", "new", "effective_date", "owner"):
        if not ch.get(key):
            out.append(_e("G01", f"change.{key}", "не заполнено"))
    if not ch.get("affected_roles"):
        out.append(_e("G02", "change.affected_roles", "не определены затронутые роли"))
    for key in ("transition", "enforcement"):
        if not ch.get(key):
            out.append(_w("G03", f"change.{key}", "не описано"))
    if not _section(idx, "faq") and not _section(idx, "escalation_points"):
        out.append(_w("G04", "content", "нет FAQ и эскалации"))
    return out


def check_incident(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    facts = _section(idx, "facts")
    if not facts:
        out.append(_e("I01", "content.facts", "нет фактов"))
    for f in facts:
        if f.get("status") not in M.FACT_STATUS:
            out.append(_e("I02", f["id"], "у факта инцидента не указан статус verified / unverified"))
    inc = model["incident"]
    for key in ("status", "next_update"):
        if not inc.get(key):
            out.append(_e("I03", f"incident.{key}", "не заполнено"))
    if not inc.get("decision_makers"):
        out.append(_w("I04", "incident.decision_makers", "не определены лица, принимающие решения"))
    for s in model["storyline"]:
        refs = [idx[r] for r in s["evidence_refs"] if r in idx]
        verified = any(r["_section"] == "facts" and r.get("status") == "verified"
                       and M.claim_type_of(r) == "fact" for r in refs)
        unverified = any(M.claim_type_of(r) == "assumption" or r.get("status") == "unverified" for r in refs)
        if verified and unverified:
            out.append(_e("I05", f"storyline[{s.get('order')}]",
                          "в одном блоке смешаны подтверждённые факты и гипотезы"))
    for a in _section(idx, "actions"):
        if not a.get("when"):
            out.append(_e("I06", a["id"], "в инциденте у действия обязателен срок"))
    return out


def check_briefing(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    blocks = {s["content_block"] for s in M.main_storyline(model)}
    if model["project"].get("subtype") == "regulatory" and not blocks & {"required_action", "checklist"}:
        out.append(_e("U01", "storyline", "regulatory update без блока «что делать»"))
    if not blocks & {"business_consequence", "key_message"}:
        out.append(_w("U02", "storyline", "не показано, почему это важно бизнесу"))
    return out


REGISTRY = {
    "TRAINING": check_training,
    "REPORT": check_report,
    "RECOMMENDATION": check_recommendation,
    "CHANGE": check_change,
    "INCIDENT": check_incident,
    "BRIEFING": check_briefing,
}
