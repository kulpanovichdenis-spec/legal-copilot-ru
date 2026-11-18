#!/usr/bin/env python3
"""Общие форматтеры для трёх рендереров: один и тот же текст во всех форматах."""
from __future__ import annotations

import re

import bc_model as M

DRAFT_LABEL = "ЧЕРНОВИК — требует проверки юристом"
VALUE_LABELS = {
    "actual": "фактический результат",
    "estimated": "расчётная оценка",
    "exposure": "потенциальный риск (не экономия)",
    "qualitative": "качественный эффект",
}
SOURCE_TYPE_LABELS = {
    "primary_law": "НПА / официальный источник",
    "court_or_regulator": "решение суда / регулятора",
    "internal_policy": "внутренний документ",
    "reported": "сообщено юристом / бизнесом",
    "secondary_reliable": "вторичный правовой источник",
    "commentary": "комментарий / пресса",
}
MODE_LABELS = {
    "BRIEFING": "Брифинг",
    "REPORT": "Отчёт",
    "RECOMMENDATION": "Рекомендация",
    "TRAINING": "Обучение",
    "CHANGE": "Изменение порядка",
    "INCIDENT": "Инцидент",
}
UNIT_LABELS = {"RUB": "руб.", "USD": "долл. США", "EUR": "евро"}


def fmt_number(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    units = ((1_000_000_000, "млрд"), (1_000_000, "млн"), (1_000, "тыс."))
    for n, (div, suffix) in enumerate(units):
        if abs(value) < div:
            continue
        rounded = round(value / div, 1)
        if abs(rounded) >= 1000 and n > 0:
            div, suffix = units[n - 1]
            rounded = round(value / div, 1)
        s = f"{rounded:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{s} {suffix}"
    return f"{value:g}".replace(".", ",")


def fmt_value(impact: dict) -> str:
    cls = impact.get("value_class")
    value = impact.get("value")
    if value is None:
        return VALUE_LABELS.get(cls, "")
    unit = UNIT_LABELS.get(impact.get("unit"), impact.get("unit") or "")
    base = f"{fmt_number(value)} {unit}".strip()
    if cls == "exposure":
        return f"Потенциальная экспозиция до {base}"
    if cls == "estimated":
        return f"Оценка: {base}"
    return base


def item_display_text(item: dict) -> str:
    section = item.get("_section")
    if section in ("actions", "next_steps"):
        tail = ", ".join(x for x in (item.get("who"), item.get("when")) if x)
        text = f"{item.get('what', '')} — {tail}" if tail else item.get("what", "")
    elif section == "escalation_points":
        text = f"{item.get('when', '')} → {item.get('contact', '')}"
    elif section == "options":
        text = item.get("title", "")
    elif section == "impacts":
        text = f"{item.get('label') or item.get('type')}: {fmt_value(item)}"
    elif section == "metrics":
        text = f"{item.get('label', '')}: {fmt_number(item.get('value'))} {item.get('unit') or ''}".strip()
    elif section == "faq":
        text = item.get("q", "")
    elif section == "decision_nodes":
        text = item.get("question", "")
    elif section == "timeline":
        text = f"{item.get('date', '')} — {item.get('text', '')}"
    else:
        text = item.get("text", "")
    if M.claim_type_of(item) == "assumption":
        return f"[ДОПУЩЕНИЕ] {text}"
    if item.get("status") == "unverified":
        return f"[НЕ ПОДТВЕРЖДЕНО] {text}"
    if item.get("_calibrated_weak_source"):
        return f"[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ] {text}"
    return text


def body_lines(model: dict, story: dict, items: list[dict]) -> list[str]:
    """Единое правило тела блока для всех трёх рендереров (fix-wave F2).

    key_message + visual_hint == "text" -> вершина пирамиды Минто (minto.supporting_arguments),
    без этого текста нет причины показывать evidence отдельно. Любое другое сочетание
    (другой visual_hint у key_message, любой другой content_block) -> обычное тело,
    т.е. item_display_text каждого элемента, переданного вызывающей стороной (уже
    отфильтрованного ею при необходимости, например от правовых claim_type).
    """
    if story.get("content_block") == "key_message" and story.get("visual_hint") == "text":
        return list(model["minto"].get("supporting_arguments") or [])
    return [item_display_text(i) for i in items]


def refs_items(model: dict, idx: dict, story: dict) -> list[dict]:
    return [idx[r] for r in story.get("evidence_refs") or [] if r in idx]


def item_sources(model: dict, item: dict) -> list[dict]:
    by_id = {s["id"]: s for s in model["sources"]}
    return [by_id[r] for r in item.get("source_refs") or [] if r in by_id]


def source_line(src: dict) -> str:
    parts = [src.get("title", ""), src.get("reference", "")]
    meta = SOURCE_TYPE_LABELS.get(src.get("type"), src.get("type", ""))
    if src.get("checked_at"):
        meta += f"; сверено {src['checked_at']}"
    return f"{', '.join(p for p in parts if p)} ({meta})"


def slugify(title: str) -> str:
    words = re.findall(r"\w+", title or "")
    return "_".join(words)[:80] or "communication"
