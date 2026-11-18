# -*- coding: utf-8 -*-
"""Сборка .docx «Разбор устава» по профилю «аналитическая заметка» (tools/docx_style).

Модуль отвечает за раскладку данных по разделам; форма (шрифты, таблицы,
подсветка маркеров) — у NoteDoc. Ничего не дописывает от себя: пустой раздел
получает строку «Нет данных», недостающее остаётся маркером.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402
import gov_views as views  # noqa: E402

ROOT = store.ROOT
OVERRIDE_CLASSES = ("CHARTER_OVERRIDE", "CHARTER_OPTION")
ATTENTION_CLASSES = ("CONFLICT", "POTENTIALLY_OUTDATED", "NEEDS_HUMAN_REVIEW")
# подписи разделов профиля (кроме classification: у него свой заголовок «2. Классификация компании»)
FACT_CAPTIONS = {
    "ownership": "Участники и доли",
    "governance_bodies": "Органы управления",
    "appointments": "Назначения",
    "related_entities": "Связанные компании",
    "open_governance_issues": "Открытые вопросы управления",
}


ZWSP = "\u200b"


def _literal(text) -> str:
    """Текст пользователя без срабатывания разметки NoteDoc.

    NoteDoc читает ** как переключатель полужирного и ^<цифры> как надстрочную
    сноску, поэтому дословная цитата теряла бы эти символы. Пробел нулевой ширины
    между звёздочками и после ^ ломает разметку, не меняя видимого текста; после
    его удаления строка равна исходной. Подсветка маркеров в [...] остаётся.
    """
    return re.sub(r"\^(?=\d)", "^" + ZWSP, re.sub(r"\*(?=\*)", "*" + ZWSP, str(text)))


def _literal_row(cells) -> list[str]:
    return [_literal(c) for c in cells]


def _widths(doc, weights: list[float]) -> list[float]:
    total = sum(weights)
    return [round(doc.body_width_cm * w / total, 2) for w in weights]


def _rule_table(doc, rows: list[dict]) -> None:
    if not rows:
        doc.para("Нет данных.")
        return
    header = ["Предмет", "Значение", "Класс", "Закон", "Место", "Статус"]
    body = [_literal_row([r["subject"], r["value"], r["classification"], r["law"] or "—",
                          f"{r['locator']} ({r['rule_id']})", " ".join(r["flags"]) or "подтверждено"])
            for r in rows]
    doc.table(header, body, _widths(doc, [3.2, 3.6, 2.4, 2.4, 3.0, 2.4]))


def _fact_table(doc, facts: list[dict]) -> None:
    rows = [_literal_row([f["key"], views.value_text(f["value"]), views.locator(f["provenance"]),
                          "подтверждено" if f.get("verification") == "verified" else "кандидат"])
            for f in facts]
    doc.table(["Признак", "Значение", "Место в документе", "Статус"], rows,
              _widths(doc, [4.5, 3.5, 5.0, 3.0]))


def _fact_block(doc, facts: list[dict], section: str) -> None:
    """Подпись раздела профиля и таблица его фактов; пустой раздел не выводится."""
    items = [f for f in facts if f["section"] == section]
    if items:
        doc.para(f"**{FACT_CAPTIONS[section]}**", keep_next=True)
        _fact_table(doc, items)


def build_report(entity: store.Entity, out_path: str, *, title: str = "Разбор устава") -> str:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.docx_style.profiles import NoteDoc  # noqa: PLC0415

    profile = entity.load_profile()
    sources = entity.load_sources()["sources"]
    rules = entity.load_rules()["rules"]
    by_id = {s["source_id"]: s for s in sources}
    name = profile.get("name", entity.slug)

    doc = NoteDoc()
    doc.header(f"{title}: {_literal(name)}")
    doc.title(title, _literal(name), f"Черновик от {store.today()}. Проверяется юристом, ничего не финализировано")

    doc.heading("1. Реквизиты и статус редакции")
    banner = views.charter_banner(sources)
    if banner:
        doc.para(banner)
    if sources:
        rows = [_literal_row([s["source_id"], s["title"], s["kind"], str(s.get("edition_date") or "—"),
                              s["status"], str(s.get("current_basis") or "—")]) for s in sources]
        doc.table(["№", "Документ", "Вид", "Редакция", "Статус", "Чем подтверждена актуальность"],
                  rows, _widths(doc, [1.2, 4.4, 2.6, 2.4, 2.0, 4.4]))
    else:
        doc.para("Нет данных.")

    doc.heading("2. Классификация компании")
    facts = [f for f in profile["facts"] if not f.get("needs_review")]
    facts_review = [f for f in profile["facts"] if f.get("needs_review")]
    classification = [f for f in facts if f["section"] == "classification"]
    classification_review = [f for f in facts_review if f["section"] == "classification"]
    if classification:
        _fact_table(doc, classification)
    elif classification_review:
        doc.para("Классификация компании: актуальных данных нет — прежние помечены на пересмотр "
                 "(источник заменён новой редакцией), см. раздел 9 «Факты на пересмотр» "
                 "[ПРОВЕРИТЬ ФАКТ].")
    else:
        doc.para("Нет данных: классификация компании не установлена [ПРОВЕРИТЬ ФАКТ].")
    for section in schema.FACT_SECTIONS:
        if section not in ("classification", "open_governance_issues"):
            _fact_block(doc, facts, section)

    numbered = [("competence", "3."), ("voting", "4."), ("meetings", "5."),
                ("confirmation", "6."), ("other", "7.")]
    for view, number in numbered:
        doc.heading(f"{number} {views.VIEWS[view][0]}")
        _rule_table(doc, views.build_rows(rules, by_id, view))

    doc.heading("8. Отклонения от закона (устав-override и использованные опции)")
    override = [views.rule_row(r, by_id) for r in views.active_rules(rules)
                if any(c in OVERRIDE_CLASSES for c in r["classification"])]
    _rule_table(doc, override)

    doc.heading("9. Конфликты, пробелы, устаревшее: на решение юриста")
    attention = [views.rule_row(r, by_id) for r in views.active_rules(rules)
                 if any(c in ATTENTION_CLASSES for c in r["classification"])]
    candidates = views.find_inconsistencies(rules)
    review = views.review_rows(rules, by_id)
    # «Нет данных.» только когда пусты все четыре подблока раздела; иначе печатаются непустые
    # (пустая attention-таблица раньше печатала «Нет данных.» безусловно, даже если ниже были данные)
    if attention or candidates or review or facts_review:
        if attention:
            _rule_table(doc, attention)
    else:
        doc.para("Нет данных.")
    _fact_block(doc, facts, "open_governance_issues")
    if candidates:
        doc.para("**Кандидаты на внутреннее противоречие** (лид, не вывод):")
        for item in candidates:
            variants = "; ".join(f"{r['rule_id']} ({r['locator']}): {r['value']}" for r in item["rules"])
            doc.bullet(_literal(f"{item['topic']} / {item['subject']}: {variants}"))
    if review:
        doc.para("**Требуют пересмотра** (источник заменён новой редакцией):")
        _rule_table(doc, review)
    if facts_review:
        doc.para("**Факты на пересмотр** (источник заменён новой редакцией):")
        _fact_table(doc, facts_review)

    doc.heading("10. Допущения и недостающие документы")
    open_items, resolved = views.split_assumptions(profile)
    if open_items:
        rows = [_literal_row([a["assumption_id"], a["topic"], a["missing_data"],
                              a["default_rule_if_no_special_rule"], a["risk"], a["required_verification"]])
                for a in open_items]
        doc.table(["№", "Тема", "Чего не хватает", "Без специального правила", "Риск", "Что проверить"],
                  rows, _widths(doc, [1.2, 2.2, 3.4, 3.6, 2.2, 4.4]))
    elif not resolved:
        doc.para("Нет данных.")
    else:
        doc.para("Открытых допущений нет.")
    for a in resolved:
        doc.para("Снятые допущения: " + _literal(views.resolved_line(a)))

    doc.heading("11. Приложение: реестр правил с provenance")
    if rules:
        rows = [_literal_row([r["rule_id"], r["subject"], views.locator(r["provenance"]),
                              r["provenance"]["quote"]]) for r in rules]
        doc.table(["№", "Предмет", "Место", "Дословная цитата (сверить по скану)"], rows,
                  _widths(doc, [1.2, 3.6, 3.6, 8.6]))
    else:
        doc.para("Нет данных.")
    doc.footer()
    return doc.save(out_path)


REVIEW_STATUS = {"verified": "подтверждено", "candidate": "кандидат"}


def build_decisions_review(entity: store.Entity, catalog: dict, out_path: str) -> str:
    """Привязка правил к каталогу решений — на проверку юристу (черновик)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.docx_style.profiles import NoteDoc  # noqa: PLC0415

    name = entity.load_profile().get("name", entity.slug)
    all_rules = entity.load_rules()["rules"]
    rules = views.active_rules(all_rules)
    title = "Привязка правил к каталогу решений"
    doc = NoteDoc()
    doc.header(f"{title}: {_literal(name)}")
    doc.title(title, _literal(name), f"Черновик от {store.today()}. Проверяется юристом, ничего не финализировано")

    def status_of(r: dict) -> str:
        if r.get("needs_review"):
            return "на пересмотре (редакция заменена)"
        return REVIEW_STATUS.get(r.get("verification"), str(r.get("verification")))

    def rows(items: list[dict]) -> list[list[str]]:
        return [_literal_row([r["rule_id"], views.locator(r["provenance"]), r["subject"],
                              views.value_text(r["value"]), status_of(r)])
                for r in items]

    header = ["№", "Место", "Предмет", "Значение", "Статус"]
    weights = [1.2, 2.6, 4.0, 6.2, 2.0]
    doc.heading("1. Позиции каталога и привязанные правила")
    for item in catalog["decisions"]:
        did = item["decision_id"]
        doc.para(f"**{_literal(item['title'])}** ({did})")
        tagged = [r for r in all_rules if did in (r.get("decisions") or [])]
        if tagged:
            doc.table(header, rows(tagged), _widths(doc, weights))
        else:
            doc.para("Привязанных правил нет. Вывод о молчании устава — за юристом.")
    doc.heading("2. Правила без привязки")
    free = [r for r in rules if not r.get("decisions")]
    if free:
        doc.table(header, rows(free), _widths(doc, weights))
    else:
        doc.para("Нет данных.")
    doc.footer()
    return doc.save(out_path)
