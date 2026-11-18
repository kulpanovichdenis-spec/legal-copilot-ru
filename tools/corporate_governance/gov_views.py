# -*- coding: utf-8 -*-
"""Проекции и проверки над правилами: матрицы, кандидаты противоречий, устаревшие проверки.

Матрицы компетенции, голосования, собраний и подтверждения не хранятся:
они вычисляются из правил (ТЗ §27, «один источник истины»). Каждая строка
ведёт к правилу и его цитате по rule_id. Модуль детерминированный и не делает
правовых выводов: «кандидат» здесь лид для юриста, а не установленное
противоречие.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402

# view -> (заголовок, темы таксономии)
VIEWS = {
    "competence": ("Матрица компетенции",
                   ("competence", "executive_body", "transactions", "capital_shares",
                    "profit", "audit_body")),
    "voting": ("Матрица голосования", ("quorum", "threshold", "voting_procedure")),
    "meetings": ("Правила собраний", ("convening", "notice", "agenda")),
    "confirmation": ("Подтверждение решений и решения единственного участника",
                     ("confirmation", "sole_member")),
    "other": ("Прочие правила", ("info_rights", "representation")),
}
TOPIC_TO_VIEW = {topic: view for view, (_, topics) in VIEWS.items() for topic in topics}

MARK_EDITION = "[ПРОВЕРИТЬ АКТУАЛЬНОСТЬ РЕДАКЦИИ]"
MARK_NORM = "[ПРОВЕРИТЬ НОРМУ]"
MARK_SOURCE = "[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]"


# ---------- форматирование ----------

def value_text(value) -> str:
    """Короткое текстовое представление значения правила или факта.

    I6: словарь с ключом "text" раньше отдавал только его, молча отбрасывая остальные ключи —
    вместе с ними терялись маркеры вроде [ПРОВЕРИТЬ СРОК], записанные в соседнем ключе (например
    term_rule). Теперь "text" печатается первым, а остальные ключи (кроме пустых None — иначе
    у каждого необязательного и просто не заданного поля была бы шумная "; foo: None")
    дописываются тем же форматом "; key: value", что и раньше для словаря без "text".
    """
    if isinstance(value, dict):
        if value.get("text"):
            rest = "; ".join(f"{k}: {v}" for k, v in value.items() if k != "text" and v is not None)
            return f"{value['text']}; {rest}" if rest else str(value["text"])
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(value_text(v) for v in value)
    return str(value)


def locator(prov: dict) -> str:
    return f"{prov.get('source_id')}, стр. {prov.get('page')}, п. {prov.get('clause')}"


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


# ---------- строки матриц ----------

def rule_flags(rule: dict, sources_by_id: dict) -> list[str]:
    flags: list[str] = []
    if rule.get("verification") != "verified":
        flags.append("кандидат")
    prov = rule.get("provenance") or {}
    src = sources_by_id.get(prov.get("source_id")) or {}
    if src.get("status") != "current":
        flags.append(MARK_EDITION)
    fresh = rule.get("freshness")
    if schema.needs_law(rule):
        if not fresh or fresh.get("status") != "verified":
            flags.append(MARK_NORM)
    elif isinstance(fresh, dict) and fresh.get("status") != "verified":
        # I3: реклассификация не убирает leftover freshness-блок прежней (закон-зависимой)
        # классификации — если он так и не подтверждён, правило всё ещё требует проверки нормы
        flags.append(MARK_NORM)
    if (prov.get("quote_check") or {}).get("status") == "not_found":
        flags.append(MARK_SOURCE)
    return flags


def rule_row(rule: dict, sources_by_id: dict) -> dict:
    law = rule.get("law_ref") or {}
    law_text = law.get("card", "")
    if law.get("article"):
        law_text = f"{law_text}: {law['article']}"
    return {
        "rule_id": rule["rule_id"],
        "topic": rule["topic"],
        "layer": rule["layer"],
        "subject": rule["subject"],
        "value": value_text(rule["value"]),
        "classification": ", ".join(rule["classification"]),
        "law": law_text,
        "locator": locator(rule["provenance"]),
        "quote": (rule["provenance"] or {}).get("quote", ""),
        "flags": rule_flags(rule, sources_by_id),
    }


def active_rules(rules: list[dict]) -> list[dict]:
    return [r for r in rules if not r.get("needs_review")]


def build_rows(rules: list[dict], sources_by_id: dict, view: str) -> list[dict]:
    topics = VIEWS[view][1]
    picked = [r for r in active_rules(rules) if r["topic"] in topics]
    picked.sort(key=lambda r: (topics.index(r["topic"]), r["rule_id"]))
    return [rule_row(r, sources_by_id) for r in picked]


def review_rows(rules: list[dict], sources_by_id: dict) -> list[dict]:
    return [rule_row(r, sources_by_id) for r in rules if r.get("needs_review")]


def review_facts(profile: dict) -> list[dict]:
    """Факты профиля, помеченные needs_review (источник заменён новой редакцией).

    Отдельно от активных фактов render_profile: needs_review-факты не попадают в рабочие
    разделы профиля молча, но должны оставаться видимыми юристу — см. render_review_facts.
    """
    return [f for f in profile.get("facts", []) if f.get("needs_review")]


def split_assumptions(profile: dict) -> tuple[list[dict], list[dict]]:
    """(открытые, снятые) допущения: снятые не должны выглядеть как всё ещё недостающие документы."""
    items = profile.get("assumptions", [])
    return ([a for a in items if a.get("status", "open") != "resolved"],
            [a for a in items if a.get("status") == "resolved"])


def resolved_line(a: dict) -> str:
    source = f", {a['resolved_by_source']}" if a.get("resolved_by_source") else ""
    return (f"{a['assumption_id']} [{a['topic']}] ({a['missing_data']}): снято {a.get('resolved_at')} — "
            f"{a.get('resolved_basis')}{source}")


def render_review_facts(facts: list[dict]) -> str:
    if not facts:
        return ""
    lines = ["## Факты на пересмотр (источник заменён новой редакцией)", ""]
    for f in facts:
        mark = "" if f.get("verification") == "verified" else " (кандидат)"
        lines.append(f"- [{f.get('section')}] {f['key']}: {value_text(f['value'])} — "
                     f"{locator(f['provenance'])}{mark} ({f['fact_id']})")
    return "\n".join(lines) + "\n"


# ---------- проверки ----------

def find_inconsistencies(rules: list[dict]) -> list[dict]:
    """Кандидаты: одна тема и предмет, но разные значения в разных пунктах."""
    groups: dict[tuple, list[dict]] = {}
    for rule in active_rules(rules):
        key = (rule["topic"], " ".join(str(rule["subject"]).casefold().split()))
        groups.setdefault(key, []).append(rule)
    found = []
    for (topic, subject), items in sorted(groups.items()):
        variants = {json.dumps(i["value"], sort_keys=True, ensure_ascii=False) for i in items}
        if len(variants) > 1:
            found.append({
                "topic": topic,
                "subject": subject,
                "rules": [{"rule_id": i["rule_id"], "layer": i["layer"],
                           "locator": locator(i["provenance"]), "value": value_text(i["value"])}
                          for i in items],
            })
    return found


def find_stale(rules: list[dict], today: dt.date, days: int) -> list[dict]:
    """Правила, зависящие от закона, без проверки, с не-verified или устаревшей проверкой.

    Правило, у которого freshness-блок остался от прежней (закон-зависимой) классификации
    и так и не подтверждён, попадает в список и после реклассификации: иначе update-rule
    --classification тихо прятал бы непройденную проверку нормы от stale (I3).
    """
    stale = []
    for rule in active_rules(rules):
        fresh = rule.get("freshness")
        if not schema.needs_law(rule):
            if isinstance(fresh, dict) and fresh.get("status") != "verified":
                stale.append({"rule_id": rule["rule_id"],
                              "reason": f"freshness.status={fresh.get('status')}: {fresh.get('required_action')}"})
            continue
        reason = None
        if not fresh:
            reason = "нет проверки актуальности нормы"
        elif fresh.get("status") != "verified":
            reason = f"freshness.status={fresh.get('status')}: {fresh.get('required_action')}"
        else:
            checked = schema.to_date(fresh.get("checked_at"))
            age = (today - checked).days if checked else None
            if age is None or age > days:
                reason = f"проверка старше {days} дн. (возраст: {age})"
        if reason:
            stale.append({"rule_id": rule["rule_id"], "reason": reason})
    return stale


def charter_banner(sources: list[dict]) -> str | None:
    """Предупреждение, если применимая редакция устава не подтверждена."""
    charters = [s for s in sources if s.get("kind") == "charter"]
    if any(s.get("status") == "current" for s in charters):
        return None
    if not charters:
        return (f"{MARK_EDITION} Устав не зарегистрирован в источниках: применимые правила "
                "определить нельзя (ТЗ §34).")
    return (f"{MARK_EDITION} Применимая редакция устава не подтверждена: нет источника "
            "вида charter со статусом current (нужна выписка ЕГРЮЛ).")


# ---------- markdown ----------

def render_table(rows: list[dict]) -> str:
    if not rows:
        return "Нет данных.\n"
    head = "| Предмет | Значение | Класс | Основание (закон) | Место в документе | Статус |\n"
    head += "|---|---|---|---|---|---|\n"
    body = "".join(
        f"| {_cell(r['subject'])} | {_cell(r['value'])} | {_cell(r['classification'])} "
        f"| {_cell(r['law'])} | {_cell(r['locator'])} ({r['rule_id']}) "
        f"| {_cell(' '.join(r['flags']) or 'подтверждено')} |\n"
        for r in rows
    )
    return head + body


def render_view(view: str, rules: list[dict], sources_by_id: dict) -> str:
    title = VIEWS[view][0]
    return f"## {title}\n\n{render_table(build_rows(rules, sources_by_id, view))}\n"


def render_profile(profile: dict) -> str:
    lines = [f"## Профиль компании: {profile.get('name', '')}", ""]
    facts = [f for f in profile.get("facts", []) if not f.get("needs_review")]
    for section in schema.FACT_SECTIONS:
        items = [f for f in facts if f["section"] == section]
        if not items:
            continue
        lines.append(f"### {section}")
        for f in items:
            mark = "" if f.get("verification") == "verified" else " (кандидат)"
            lines.append(f"- {f['key']}: {value_text(f['value'])} — {locator(f['provenance'])}{mark} ({f['fact_id']})")
        lines.append("")
    open_items, resolved = split_assumptions(profile)
    if open_items:
        lines.append("### Допущения (нет данных, стандартное правило не подставлено молча)")
        for a in open_items:
            lines.append(
                f"- {a['assumption_id']} [{a['topic']}]: нет {a['missing_data']}; "
                f"без специального правила действует: {a['default_rule_if_no_special_rule']}; "
                f"риск: {a['risk']}; проверить: {a['required_verification']}")
        lines.append("")
    if resolved:
        lines.append("### Снятые допущения (недостающее получено)")
        lines.extend(f"- {resolved_line(a)}" for a in resolved)
        lines.append("")
    return "\n".join(lines) + "\n"


def render_inconsistencies(found: list[dict]) -> str:
    if not found:
        return "## Кандидаты на противоречие\n\nНе найдены.\n"
    lines = ["## Кандидаты на противоречие (лид для юриста, не вывод)", ""]
    for item in found:
        lines.append(f"- {item['topic']} / {item['subject']}:")
        for r in item["rules"]:
            lines.append(f"  - {r['rule_id']} ({r['layer']}, {r['locator']}): {r['value']}")
    return "\n".join(lines) + "\n"


def render_full(profile: dict, rules: list[dict], sources: list[dict]) -> str:
    by_id = {s["source_id"]: s for s in sources}
    parts = [f"# Разбор: {profile.get('name', '')}\n"]
    banner = charter_banner(sources)
    if banner:
        parts.append(banner + "\n")
    for view in VIEWS:
        parts.append(render_view(view, rules, by_id))
    review = review_rows(rules, by_id)
    if review:
        parts.append("## Требуют пересмотра (источник заменён новой редакцией)\n\n"
                     + render_table(review) + "\n")
    facts_review_md = render_review_facts(review_facts(profile))
    if facts_review_md:
        parts.append(facts_review_md)
    parts.append(render_inconsistencies(find_inconsistencies(rules)))
    parts.append(render_profile(profile))
    return "\n".join(parts)
