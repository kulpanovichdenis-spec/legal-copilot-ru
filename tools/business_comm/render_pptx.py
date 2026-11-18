#!/usr/bin/env python3
"""PPTX-рендерер content model (ТЗ §18): один слайд = одна мысль, заголовок = вывод.

Правовая база и источники — в notes и приложении, не на слайде.
С корпоративным шаблоном берутся только его layouts; слайды и notes шаблона удаляются.
Роль layout (title/content/section) берётся из `<template>.layouts.yaml` рядом
с шаблоном, если он есть; иначе подбирается эвристикой по типам плейсхолдеров.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

import bc_model as M
import textfmt as T
from bc_model import Issue
from validate import DEBRIS_RE, FINAL_RE

INK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)
ACCENT = RGBColor(0x1D, 0x4E, 0xD8)
BAD = RGBColor(0xB9, 0x1C, 0x1C)
GOOD = RGBColor(0x15, 0x80, 0x3D)
LIGHT = RGBColor(0xF3, 0xF4, 0xF6)
WIDE_W, WIDE_H = Inches(13.333), Inches(7.5)
MAX_FLOW_STEPS = 6
# Заголовки content model — полные фразы-выводы (часто 60-80+ знаков), а не короткие
# лейблы. У части корпоративных layouts (напр. «Заголовок слева логотип внизу справа»)
# внутри рамки TITLE-плейсхолдера есть декоративная полоса; на длинных заголовках 24pt
# переносится на 2 строки, и вторая строка попадает на полосу. 18pt bold держит две
# строки в пределах верхней части зоны заголовка над полосой почти для любых заголовков
# из фикстур (макс. 81 знак) — см. task-14-report.md, «Визуальная проверка».
TEMPLATE_TITLE_PT = 18
LEGAL_CLAIMS = {"legal_rule", "legal_interpretation"}
CONTENT_HEIGHT_FRACTION = 0.45  # порог «контентный» vs «раздел» для эвристики layouts
LAYOUT_ROLES = ("title", "content", "section")


def _drop_all_slides(prs) -> None:
    id_list = prs.slides._sldIdLst
    for sld_id in list(id_list):
        prs.part.drop_rel(sld_id.rId)
        id_list.remove(sld_id)


def _ph_types(layout) -> set:
    return {ph.placeholder_format.type for ph in layout.placeholders}


def _layout_map_path(template: Path) -> Path:
    return template.with_name(f"{template.stem}.layouts.yaml")


def _load_layout_map(template: Path | None) -> dict:
    """Сайдкар `<template>.layouts.yaml` (ключи title/content/section = имена layouts)."""
    if template is None:
        return {}
    path = _layout_map_path(template)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _title_layout(prs):
    for layout in prs.slide_layouts:
        if PP_PLACEHOLDER.CENTER_TITLE in _ph_types(layout):
            return layout
    return prs.slide_layouts[0]


def _content_layout(prs):
    # (а) «Title Only» — TITLE без BODY/OBJECT/CENTER_TITLE/SUBTITLE/PICTURE.
    for layout in prs.slide_layouts:
        types = _ph_types(layout)
        if PP_PLACEHOLDER.TITLE in types and not types & {
                PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.CENTER_TITLE,
                PP_PLACEHOLDER.SUBTITLE, PP_PLACEHOLDER.PICTURE}:
            return layout
    # (б) TITLE + ровно один OBJECT/BODY высотой ≥45% высоты слайда, без PICTURE.
    threshold = prs.slide_height * CONTENT_HEIGHT_FRACTION
    for layout in prs.slide_layouts:
        types = _ph_types(layout)
        if PP_PLACEHOLDER.TITLE not in types or PP_PLACEHOLDER.PICTURE in types:
            continue
        content_phs = [ph for ph in layout.placeholders
                       if ph.placeholder_format.type in (PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.BODY)]
        if len(content_phs) == 1 and content_phs[0].height and content_phs[0].height >= threshold:
            return layout
    # (в) текущий fallback.
    return prs.slide_layouts[min(5, len(prs.slide_layouts) - 1)]


def _section_layout(prs, content_layout):
    threshold = prs.slide_height * CONTENT_HEIGHT_FRACTION
    for layout in prs.slide_layouts:
        types = _ph_types(layout)
        if PP_PLACEHOLDER.TITLE not in types or PP_PLACEHOLDER.PICTURE in types:
            continue
        bodies = [ph for ph in layout.placeholders if ph.placeholder_format.type == PP_PLACEHOLDER.BODY]
        if any(ph.height and ph.height < threshold for ph in bodies):
            return layout
    return content_layout


def _resolve_layouts(prs, template: Path | None) -> dict:
    """Роль (title/content/section) -> slide layout: из сайдкара, иначе эвристикой."""
    by_name = {layout.name: layout for layout in prs.slide_layouts}
    mapping = _load_layout_map(template)
    layouts: dict[str, object] = {}
    for role in LAYOUT_ROLES:
        name = mapping.get(role)
        if name is None:
            continue
        if name not in by_name:
            raise ValueError(
                f"layouts.yaml: layout {name!r} для роли {role!r} не найден в шаблоне; "
                f"доступные layouts: {sorted(by_name)}")
        layouts[role] = by_name[name]
    layouts.setdefault("title", _title_layout(prs))
    layouts.setdefault("content", _content_layout(prs))
    layouts.setdefault("section", _section_layout(prs, layouts["content"]))
    return layouts


def _drop_empty_placeholders(slide) -> None:
    for ph in list(slide.placeholders):
        if not ph.has_text_frame or not ph.text_frame.text.strip():
            ph._element.getparent().remove(ph._element)


def _style_text(tf, size: int, color: RGBColor = INK, bold: bool = False, align=None) -> None:
    for p in tf.paragraphs:
        if align is not None:
            p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color


def _lines(tf, lines: list[str], size: int = 18, color: RGBColor = INK, bold: bool = False) -> None:
    tf.word_wrap = True
    tf.text = lines[0] if lines else ""
    for line in lines[1:]:
        tf.add_paragraph().text = line
    _style_text(tf, size, color, bold)


def _box(slide, left, top, width, height, lines, size=18, color=INK, bold=False, fill=None, shape=None):
    if shape is None:
        sh = slide.shapes.add_textbox(left, top, width, height)
    else:
        sh = slide.shapes.add_shape(shape, left, top, width, height)
        if fill is not None:
            sh.fill.solid()
            sh.fill.fore_color.rgb = fill
        sh.line.color.rgb = LIGHT
    _lines(sh.text_frame, lines, size, color, bold)
    sh.text_frame.vertical_anchor = MSO_ANCHOR.TOP
    return sh


def _texts(items: list[dict]) -> list[str]:
    return [T.item_display_text(i) for i in items]


def v_text(slide, box, model, idx, story, items):
    l, t, w, h = box
    visible = [i for i in items if M.claim_type_of(i) not in LEGAL_CLAIMS] or items
    lines = T.body_lines(model, story, visible)
    _box(slide, l, t, w, h, [f"• {x}" for x in lines] or [""], size=20)


def v_checklist(slide, box, model, idx, story, items):
    l, t, w, h = box
    _box(slide, l, t, w, h, [f"☐ {x}" for x in _texts(items)], size=20)


def v_flow(slide, box, model, idx, story, items):
    if not 2 <= len(items) <= MAX_FLOW_STEPS:
        return v_text(slide, box, model, idx, story, items)
    l, t, w, h = box
    gap = Inches(0.3)
    step_w = int((w - gap * (len(items) - 1)) / len(items))
    for n, item in enumerate(items):
        left = l + n * (step_w + gap)
        _box(slide, left, t + Inches(0.5), step_w, Inches(2.2), [f"{n + 1}. {T.item_display_text(item)}"],
             size=16, fill=LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        if n:
            slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, left - gap, t + Inches(1.6), left, t + Inches(1.6))


def v_timeline(slide, box, model, idx, story, items):
    dated = sorted([i for i in items if i.get("date")], key=lambda i: str(i["date"]))
    if not dated:
        return v_text(slide, box, model, idx, story, items)
    l, t, w, h = box
    y = t + Inches(1.8)
    slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, l, y, l + w, y).line.color.rgb = MUTED
    slot = int(w / len(dated))
    for n, item in enumerate(dated):
        cx = l + slot * n + int(slot / 2)
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, cx - Inches(0.12), y - Inches(0.12), Inches(0.24), Inches(0.24))
        dot.fill.solid()
        dot.fill.fore_color.rgb = ACCENT
        dot.line.color.rgb = ACCENT
        _box(slide, cx - int(slot / 2), y - Inches(0.9), slot, Inches(0.6), [str(item["date"])], size=16, bold=True)
        _box(slide, cx - int(slot / 2), y + Inches(0.3), slot, Inches(1.6), [item.get("text", "")], size=14)


def v_side_by_side(slide, box, model, idx, story, items):
    l, t, w, h = box
    wrong = [i.get("text", "") for i in items if i.get("kind") == "wrong"]
    better = [i.get("text", "") for i in items if i.get("kind") == "better"]
    left_title, right_title = "Как делаем сейчас", "Как лучше"
    if not (wrong or better) and model["change"]:
        wrong, better = [model["change"].get("current", "")], [model["change"].get("new", "")]
        left_title, right_title = "Было", "Стало"
    half = int((w - Inches(0.4)) / 2)
    _box(slide, l, t, half, Inches(0.6), [left_title], size=20, color=BAD, bold=True)
    _box(slide, l, t + Inches(0.7), half, h - Inches(0.7), wrong or [""], size=18, fill=LIGHT,
         shape=MSO_SHAPE.RECTANGLE)
    _box(slide, l + half + Inches(0.4), t, half, Inches(0.6), [right_title], size=20, color=GOOD, bold=True)
    _box(slide, l + half + Inches(0.4), t + Inches(0.7), half, h - Inches(0.7), better or [""], size=18,
         fill=LIGHT, shape=MSO_SHAPE.RECTANGLE)


def _table(slide, box, header: list[str], rows: list[list[str]], size: int = 14):
    l, t, w, h = box
    shape = slide.shapes.add_table(len(rows) + 1, len(header), l, t, w, min(h, Inches(0.6) * (len(rows) + 1)))
    table = shape.table
    for c, text in enumerate(header):
        table.cell(0, c).text = text
    for r, row in enumerate(rows, 1):
        for c, text in enumerate(row):
            table.cell(r, c).text = str(text or "")
    for row in table.rows:
        for cell in row.cells:
            _style_text(cell.text_frame, size)


def v_comparison(slide, box, model, idx, story, items):
    options = [i for i in items if i["_section"] == "options"]
    if not options:
        return v_text(slide, box, model, idx, story, items)
    _table(slide, box, ["Вариант", "Плюсы", "Минусы", "Риск"],
           [[("★ " if o.get("recommended") else "") + o.get("title", ""), "; ".join(o.get("pros") or []),
             "; ".join(o.get("cons") or []), o.get("risk", "")] for o in options])


def v_risk_matrix(slide, box, model, idx, story, items):
    risks = [i for i in items if i["_section"] == "risks"]
    if not risks:
        return v_text(slide, box, model, idx, story, items)
    _table(slide, box, ["Риск", "Уровень"], [[r.get("text", ""), r.get("level", "")] for r in risks])


def v_metric(slide, box, model, idx, story, items):
    tiles = [i for i in items if i["_section"] in ("impacts", "metrics")]
    if not tiles:
        return v_text(slide, box, model, idx, story, items)
    l, t, w, h = box
    gap = Inches(0.3)
    tile_w = int((w - gap * (len(tiles) - 1)) / len(tiles))
    for n, item in enumerate(tiles):
        left = l + n * (tile_w + gap)
        if item["_section"] == "impacts":
            value, label = T.fmt_value(item), item.get("label") or item.get("type")
            kind = T.VALUE_LABELS.get(item.get("value_class"), "")
        else:
            value, label, kind = T.fmt_number(item.get("value")), item.get("label", ""), ""
        _box(slide, left, t + Inches(0.3), tile_w, Inches(1.6), [value], size=28, color=ACCENT, bold=True,
             fill=LIGHT, shape=MSO_SHAPE.RECTANGLE)
        _box(slide, left, t + Inches(2.0), tile_w, Inches(1.2), [label, kind] if kind else [label], size=16)


def v_chart(slide, box, model, idx, story, items):
    numeric = [i for i in items if i["_section"] in ("impacts", "metrics") and isinstance(i.get("value"), (int, float))]
    if len(numeric) < 2:
        return v_metric(slide, box, model, idx, story, items)
    data = CategoryChartData()
    data.categories = [i.get("label") or i.get("id") for i in numeric]
    data.add_series("Значение", [i["value"] for i in numeric])
    l, t, w, h = box
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, l, t, w, h, data)


def v_decision_tree(slide, box, model, idx, story, items):
    nodes = [i for i in items if i["_section"] == "decision_nodes"]
    if not nodes:
        return v_text(slide, box, model, idx, story, items)
    l, t, w, h = box
    row_h = int(h / len(nodes))
    for n, node in enumerate(nodes):
        top = t + n * row_h
        _box(slide, l, top, int(w * 0.45), Inches(1.0), [node.get("question", "")], size=18, fill=LIGHT,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        _box(slide, l + int(w * 0.5), top, int(w * 0.5), Inches(1.0),
             [f"Да → {node.get('if_yes', '')}", f"Нет → {node.get('if_no', '')}"], size=16)


def v_annotated_document(slide, box, model, idx, story, items):
    with_image = [i for i in items if i.get("image") and Path(i["image"]).exists()]
    if not with_image:
        return v_text(slide, box, model, idx, story, items)
    l, t, w, h = box
    doc = with_image[0]
    slide.shapes.add_picture(str(doc["image"]), l, t, height=h)
    _box(slide, l + int(w * 0.6), t, int(w * 0.4), h,
         [f"{n}. {a}" for n, a in enumerate(doc.get("annotations") or [], 1)] or [doc.get("text", "")], size=16)


VISUALS: dict[str, Callable] = {
    "text": v_text, "hierarchy": v_text, "checklist": v_checklist, "flow": v_flow, "timeline": v_timeline,
    "side_by_side": v_side_by_side, "comparison": v_comparison, "risk_matrix": v_risk_matrix,
    "metric": v_metric, "chart": v_chart, "decision_tree": v_decision_tree,
    "annotated_document": v_annotated_document,
}


def _notes(model: dict, story: dict, items: list[dict]) -> str:
    parts: list[str] = []
    if story.get("talk_track"):
        parts.append(f"Текст выступления: {story['talk_track']}")
    support = [i for i in items if M.claim_type_of(i) not in LEGAL_CLAIMS]
    if support:
        # Слайд часто показывает эффекты/варианты разбитыми на элементы визуала
        # (тайлы метрик, таблица сравнения, точки таймлайна) — полный текст каждого
        # элемента (item_display_text) всегда дублируется в notes, чтобы он был
        # доступен человеку и инструментам, читающим текст презентации, независимо
        # от визуального представления на слайде (fix-wave F1, паритет форматов).
        label = "Опора тезиса" if story["content_block"] == "key_message" else "Данные"
        parts.append(f"{label}: " + " | ".join(_texts(support)))
    legal = [i for i in items if M.claim_type_of(i) in LEGAL_CLAIMS]
    if legal:
        parts.append("Правовая база: " + " | ".join(
            T.item_display_text(i) + (f" — {i['detail']}" if i.get("detail") else "") for i in legal))
    details = [i.get("why") or i.get("detail") for i in items
               if M.claim_type_of(i) not in LEGAL_CLAIMS and (i.get("why") or i.get("detail"))]
    if details:
        parts.append("Подробнее: " + " | ".join(details))
    sources = {s["id"]: s for i in items for s in T.item_sources(model, i)}
    if sources:
        parts.append("Источники: " + " | ".join(T.source_line(s) for s in sources.values()))
    return "\n".join(parts)


def _content_slide(prs, title: str, neutral: bool, layout, style_title: bool = True):
    slide = prs.slides.add_slide(layout)
    ttl = slide.shapes.title
    if neutral:
        ttl.left, ttl.top, ttl.width, ttl.height = Inches(0.6), Inches(0.4), prs.slide_width - Inches(1.2), Inches(1.3)
        ttl.text = title
        _style_text(ttl.text_frame, 28, INK, True, PP_ALIGN.LEFT)
    elif style_title:
        # Некоторые корпоративные layouts центрируют TITLE по вертикали внутри рамки
        # (напр. вокруг декоративной полосы под заголовком в контентном layout). При
        # 2-строчном заголовке вторая строка тогда всегда попадает на полосу — рост
        # идёт от центра рамки в обе стороны независимо от размера шрифта. Прижимаем
        # текст к верху рамки, чтобы перенос уходил вниз в чистую зону.
        ttl.text_frame.vertical_anchor = MSO_ANCHOR.TOP
        ttl.text = title
        _style_text(ttl.text_frame, TEMPLATE_TITLE_PT, INK, True, PP_ALIGN.LEFT)
    else:
        # Разделитель («Приложение» на section-layout) не перекрашиваем и не
        # переразмериваем: у layout часто собственный тёмный фон с цветом/размером
        # заголовка, рассчитанным под него (напр. светлый accent на тёмной подложке) —
        # наш INK/TEMPLATE_TITLE_PT для обычного контентного layout там нечитаем.
        ttl.text = title
    box = None
    for ph in slide.placeholders:
        if ph.placeholder_format.type in (PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.BODY):
            box = (ph.left, ph.top, ph.width, ph.height)
            break
    if box is None:
        top = ttl.top + ttl.height + Inches(0.2)
        box = (ttl.left, top, ttl.width, Emu(prs.slide_height - top - Inches(0.5)))
    return slide, box


def render(model: dict, out_path: str | Path, template: str | Path | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    template = template or (model["render"].get("pptx") or {}).get("template")
    neutral = not template
    if neutral:
        prs = Presentation()
        prs.slide_width, prs.slide_height = WIDE_W, WIDE_H
        template_path = None
    else:
        template_path = Path(template)
        prs = Presentation(str(template_path))
        _drop_all_slides(prs)
    layouts = _resolve_layouts(prs, template_path)
    idx = M.index_items(model)
    p = model["project"]

    title_slide = prs.slides.add_slide(layouts["title"])
    title_slide.shapes.title.text = p["title"]
    subtitle = [ph for ph in title_slide.placeholders
                if ph.placeholder_format.type == PP_PLACEHOLDER.SUBTITLE]
    sub_lines = [f"{T.MODE_LABELS[p['mode']]} · {p['audience']}", T.DRAFT_LABEL]
    if neutral:
        # Setting only .left/.width on an inherited placeholder materializes a full
        # xfrm with .top/.height defaulting to 0 (python-pptx quirk) — capture and
        # reapply the original top/height so the box keeps its layout position.
        ttl = title_slide.shapes.title
        top, height = ttl.top, ttl.height
        ttl.left, ttl.top, ttl.width, ttl.height = Inches(0.6), top, WIDE_W - Inches(1.2), height
    if subtitle:
        _lines(subtitle[0].text_frame, sub_lines, size=18, color=MUTED)
        if neutral:
            sub = subtitle[0]
            top, height = sub.top, sub.height
            sub.left, sub.top, sub.width, sub.height = Inches(0.6), top, WIDE_W - Inches(1.2), height
    else:
        _box(title_slide, Inches(0.6), prs.slide_height - Inches(2.0), prs.slide_width - Inches(1.2),
             Inches(1.2), sub_lines, size=18, color=MUTED)
    _drop_empty_placeholders(title_slide)

    for story in M.main_storyline(model):
        slide, box = _content_slide(prs, story["message"], neutral, layouts["content"])
        items = T.refs_items(model, idx, story)
        VISUALS.get(story["visual_hint"], v_text)(slide, box, model, idx, story, items)
        slide.notes_slide.notes_text_frame.text = _notes(model, story, items)
        _drop_empty_placeholders(slide)

    appendix = M.appendix_storyline(model)
    if appendix:
        section, _ = _content_slide(prs, "Приложение", neutral, layouts["section"], style_title=False)
        _drop_empty_placeholders(section)
        for story in appendix:
            slide, box = _content_slide(prs, story["message"], neutral, layouts["content"])
            items = T.refs_items(model, idx, story)
            lines = []
            for i in items:
                lines.append(T.item_display_text(i))
                if i.get("detail"):
                    lines.append(i["detail"])
            _box(slide, *box, lines or [""], size=16)
            slide.notes_slide.notes_text_frame.text = _notes(model, story, items)
            _drop_empty_placeholders(slide)

    if model["sources"]:
        slide, box = _content_slide(prs, "Источники", neutral, layouts["content"])
        _box(slide, *box, [f"{n}. {T.source_line(s)}" for n, s in enumerate(model["sources"], 1)], size=12)
        _drop_empty_placeholders(slide)

    prs.save(out)
    return out


def slide_titles(path: str | Path) -> list[str]:
    prs = Presentation(str(path))
    return [(s.shapes.title.text if s.shapes.title is not None else "") for s in prs.slides]


def slide_notes(path: str | Path) -> list[str]:
    prs = Presentation(str(path))
    return [(s.notes_slide.notes_text_frame.text if s.has_notes_slide else "") for s in prs.slides]


def _shape_text(shape) -> str:
    if shape.has_text_frame:
        return shape.text_frame.text
    if shape.has_table:
        return " ".join(c.text for c in shape.table.iter_cells())
    if shape.has_chart:
        chart = shape.chart
        parts = [str(s.name or "") for s in chart.series]
        try:
            parts += [str(c) for c in chart.plots[0].categories]
        except (IndexError, AttributeError, TypeError):
            pass
        return " ".join(parts)
    return ""


def _slide_text(slide) -> str:
    return " ".join(_shape_text(sh) for sh in slide.shapes)


def inspect_pptx(path: str | Path) -> list[Issue]:
    out: list[Issue] = []
    prs = Presentation(str(path))
    slides = list(prs.slides)
    first_text = _slide_text(slides[0]) if slides else ""
    if T.DRAFT_LABEL not in first_text:
        out.append(Issue("error", "X01", str(path), "нет метки черновика на титульном слайде"))
    for n, slide in enumerate(slides, 1):
        if slide.shapes.title is None or not slide.shapes.title.text.strip():
            out.append(Issue("error", "X04", f"слайд {n}", "нет заголовка"))
        text = _slide_text(slide)
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if DEBRIS_RE.search(text) or DEBRIS_RE.search(notes):
            out.append(Issue("error", "X02", f"слайд {n}", "мусор шаблона в тексте/notes"))
        if FINAL_RE.search(text) or FINAL_RE.search(notes):
            out.append(Issue("error", "X03", f"слайд {n}", "«финальный / готов к показу» в тексте/notes"))
    return out
