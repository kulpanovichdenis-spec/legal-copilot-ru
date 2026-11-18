#!/usr/bin/env python3
"""DOCX-рендерер content model (ТЗ §19): memo для бизнеса или одностраничная памятка.

Не legal memo: сначала вывод и эффект, правовая база — в приложении.
Сборка по references/docx-generation.md (Times New Roman + eastAsia).
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import bc_model as M
import textfmt as T
from bc_model import Issue
from validate import DEBRIS_RE, FINAL_RE

FONT = "Times New Roman"
SIZE = Pt(12)


def _fonts(rpr_owner, font: str = FONT) -> None:
    rpr = rpr_owner.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), font)


def _setup(doc: Document) -> None:
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin, sec.right_margin = Cm(3.0), Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(2.0), Cm(2.0)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "List Bullet", "List Number"):
        style = doc.styles[name]
        style.font.name = FONT
        style.font.color.rgb = RGBColor(0, 0, 0)
        _fonts(style.element)
    doc.styles["Normal"].font.size = SIZE
    doc.styles["Normal"].paragraph_format.line_spacing = 1.15
    doc.styles["Title"].font.size = Pt(16)
    doc.styles["Heading 1"].font.size = Pt(14)
    doc.styles["Heading 2"].font.size = Pt(12)
    header = sec.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = header.add_run(T.DRAFT_LABEL)
    run.italic = True
    run.font.size = Pt(9)
    _fonts(run._element)


def _para(doc, text: str, *, bold: bool = False, italic: bool = False, style: str | None = None):
    p = doc.add_paragraph(style=style)
    run = p.add_run(text)
    run.bold, run.italic = bold, italic
    _fonts(run._element)
    return p


def _heading(doc, text: str, level: int = 1) -> None:
    h = doc.add_heading(level=level)
    run = h.add_run(text)
    _fonts(run._element)


def _bullets(doc, lines: list[str]) -> None:
    for line in lines:
        if line:
            _para(doc, line, style="List Bullet")


def _table(doc, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, header):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        _fonts(run._element)
    for row in rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, row):
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(text or ""))
            _fonts(run._element)
    doc.add_paragraph()


def _section(idx: dict, name: str) -> list[dict]:
    return [v for v in idx.values() if v["_section"] == name]


def _with_sources(model: dict, item: dict) -> str:
    srcs = T.item_sources(model, item)
    text = T.item_display_text(item)
    if srcs:
        text += " (" + "; ".join(s.get("title", "") for s in srcs) + ")"
    return text


def _memo(doc, model: dict, idx: dict) -> None:
    p, o, mi = model["project"], model["objective"], model["minto"]
    _heading(doc, "Кратко")
    _para(doc, mi["answer"], bold=True)
    _bullets(doc, mi["supporting_arguments"])
    if o.get("required_decision"):
        _para(doc, f"Требуемое решение: {o['required_decision']}", bold=True)

    if p["mode"] == "CHANGE" and model["change"]:
        ch = model["change"]
        _heading(doc, "Что меняется")
        _table(doc, ["Было", "Стало"], [[ch.get("current", ""), ch.get("new", "")]])
        _bullets(doc, [
            f"Дата вступления: {ch['effective_date']}" if ch.get("effective_date") else "",
            f"Кого касается: {', '.join(ch.get('affected_roles') or [])}" if ch.get("affected_roles") else "",
            f"Владелец процесса: {ch['owner']}" if ch.get("owner") else "",
            f"Переходный период: {ch['transition']}" if ch.get("transition") else "",
            f"Контроль исполнения: {ch['enforcement']}" if ch.get("enforcement") else "",
        ])
    if p["mode"] == "INCIDENT" and model["incident"]:
        inc = model["incident"]
        _heading(doc, "Текущий статус")
        _bullets(doc, [
            inc.get("status", ""),
            f"Следующее обновление: {inc['next_update']}" if inc.get("next_update") else "",
            f"Принимают решения: {', '.join(inc.get('decision_makers') or [])}" if inc.get("decision_makers") else "",
            f"Сроки уведомлений: {inc['notification_deadlines']}" if inc.get("notification_deadlines") else "",
        ])

    _heading(doc, "Контекст")
    _para(doc, mi["situation"])
    _para(doc, mi["complication"])
    _bullets(doc, [_with_sources(model, i) for i in _section(idx, "business_context")])

    _heading(doc, "Главные выводы")
    for story in M.main_storyline(model):
        if story["title_kind"] != "assertion":
            continue
        _heading(doc, story["message"], level=2)
        items = T.refs_items(model, idx, story)
        options = [i for i in items if i["_section"] == "options"]
        if options:
            _table(doc, ["Вариант", "Плюсы", "Минусы", "Риск"],
                   [[(("★ " if op.get("recommended") else "") + op.get("title", "")),
                     "; ".join(op.get("pros") or []), "; ".join(op.get("cons") or []), op.get("risk", "")]
                    for op in options])
        if story["content_block"] == "key_message" and story["visual_hint"] == "text":
            # Единое правило fix-wave F2: key_message + hint "text" -> вершина пирамиды
            # Минто (supporting_arguments), как в PPTX/HTML, а не evidence-элементы.
            _bullets(doc, T.body_lines(model, story, items))
        else:
            _bullets(doc, [_with_sources(model, i) for i in items if i["_section"] != "options"])

    impacts = _section(idx, "impacts")
    if impacts:
        _heading(doc, "Эффект для бизнеса")
        by_id = {s["id"]: s for s in model["sources"]}
        _table(doc, ["Эффект", "Значение", "Тип", "Метод", "Источник"],
               [[imp.get("label") or imp.get("type"), T.fmt_value(imp),
                 T.VALUE_LABELS.get(imp.get("value_class"), ""), imp.get("method", ""),
                 "; ".join(by_id[r].get("title", "") for r in imp.get("source_refs") or [] if r in by_id)]
                for imp in impacts])

    facts = _section(idx, "facts") + _section(idx, "timeline") + _section(idx, "cases")
    if facts:
        _heading(doc, "Ключевые доказательства")
        if p["mode"] == "INCIDENT":
            verified = [f for f in facts if f.get("status") == "verified" and M.claim_type_of(f) != "assumption"]
            other = [f for f in facts if f not in verified]
            _heading(doc, "Подтверждено", level=2)
            _bullets(doc, [_with_sources(model, f) for f in verified])
            _heading(doc, "Не подтверждено", level=2)
            _bullets(doc, [_with_sources(model, f) for f in other])
        else:
            _bullets(doc, [_with_sources(model, f) for f in facts])

    risks = [T.item_display_text(r) for r in _section(idx, "risks")]
    risks += list(model["quality"]["open_questions"])
    risks += [f"Допущение: {a}" for a in model["quality"]["assumptions"]]
    if risks:
        _heading(doc, "Риски и открытые вопросы")
        _bullets(doc, risks)

    actions = _section(idx, "actions")
    if actions:
        _heading(doc, "Что требуется")
        _table(doc, ["Что", "Кто", "Когда"], [[a.get("what", ""), a.get("who", ""), a.get("when", "")] for a in actions])

    next_steps = _section(idx, "next_steps")
    if next_steps:
        _heading(doc, "Следующие шаги")
        _bullets(doc, [T.item_display_text(n) for n in next_steps])

    escalation = _section(idx, "escalation_points")
    if escalation:
        _heading(doc, "Когда обращаться в Legal")
        _bullets(doc, [T.item_display_text(e) for e in escalation])

    faq = _section(idx, "faq")
    if faq:
        _heading(doc, "Частые вопросы")
        for q in faq:
            _para(doc, q.get("q", ""), bold=True)
            _para(doc, q.get("a", ""))

    legal = _section(idx, "legal_rules") + _section(idx, "interpretations")
    if legal or M.appendix_storyline(model):
        _heading(doc, "Приложение. Правовая база")
        for story in M.appendix_storyline(model):
            _heading(doc, story["message"], level=2)
        for item in legal:
            _para(doc, _with_sources(model, item))
            if item.get("detail"):
                _para(doc, item["detail"], italic=True)


def _one_pager(doc, model: dict, idx: dict) -> None:
    _para(doc, model["minto"]["answer"], bold=True)
    blocks = [
        ("Когда это касается вас", [T.item_display_text(i) for i in _section(idx, "triggers")]),
        ("Проверьте", [T.item_display_text(i) for i in _section(idx, "checks")]),
        ("Сделайте", [T.item_display_text(i) for i in _section(idx, "actions")]),
        ("Не делайте", [i.get("text", "") for i in _section(idx, "internal_examples") if i.get("kind") == "wrong"]),
        ("Обратитесь в Legal", [T.item_display_text(i) for i in _section(idx, "escalation_points")]),
    ]
    for heading, lines in blocks:
        _heading(doc, heading)
        _bullets(doc, lines or ["[ЗАПОЛНИТЬ]"])


def _sources_block(doc, model: dict) -> None:
    if not model["sources"]:
        return
    _heading(doc, "Источники")
    for n, src in enumerate(model["sources"], 1):
        _para(doc, f"{n}. {T.source_line(src)}")


def render(model: dict, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    idx = M.index_items(model)
    doc = Document()
    _setup(doc)
    title = doc.add_heading(level=0)
    _fonts(title.add_run(model["project"]["title"])._element)
    _para(doc, f"{T.MODE_LABELS[model['project']['mode']]} · для: {model['project']['audience']}"
               f" · подготовлено: {model['project'].get('prepared_at', '')}", italic=True)
    variant = (model["render"].get("docx") or {}).get("variant") or "memo"
    if variant == "one_pager":
        _one_pager(doc, model, idx)
    else:
        _memo(doc, model, idx)
    _sources_block(doc, model)
    doc.save(out)
    return out


def docx_text(path: str | Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts += [c.text for c in row.cells]
    for sec in doc.sections:
        parts += [p.text for p in sec.header.paragraphs]
    return "\n".join(parts)


def inspect_docx(path: str | Path) -> list[Issue]:
    out: list[Issue] = []
    doc = Document(str(path))
    header = "\n".join(p.text for s in doc.sections for p in s.header.paragraphs)
    if T.DRAFT_LABEL not in header:
        out.append(Issue("error", "X01", str(path), "нет метки черновика в колонтитуле"))
    text = docx_text(path)
    if DEBRIS_RE.search(text):
        out.append(Issue("error", "X02", str(path), "мусор шаблона в тексте"))
    if FINAL_RE.search(text):
        out.append(Issue("error", "X03", str(path), "«финальный / готов к показу» в тексте"))
    return out
