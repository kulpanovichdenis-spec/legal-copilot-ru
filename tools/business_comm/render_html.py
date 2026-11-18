#!/usr/bin/env python3
"""HTML-рендерер content model (ТЗ §20): короткое бизнес-объяснение + раскрывающиеся блоки.

Не экспорт PPTX: вывод сверху, «Почему? / Правовая база / Пример / Подробнее» — в <details>,
интерактивный чек-лист, до/после, дерево решений, FAQ, эскалация, источники.
Один файл, без внешних ресурсов (конфиденциально, живёт в workflow/).
"""
from __future__ import annotations

import html as H
import re
from pathlib import Path

import bc_model as M
import textfmt as T
from bc_model import Issue
from validate import DEBRIS_RE, FINAL_RE

LEGAL_CLAIMS = {"legal_rule", "legal_interpretation"}
EXTERNAL_RE = re.compile(r"(<link\b|<script[^>]+src=|src=\"https?:|href=\"https?:[^\"]+\.(css|js)\")", re.IGNORECASE)

CSS = """
:root{--bg:#fbfbfa;--fg:#1f2937;--muted:#6b7280;--card:#fff;--line:#e5e7eb;--accent:#1d4ed8;--bad:#b91c1c;--good:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#111827;--fg:#e5e7eb;--muted:#9ca3af;--card:#1f2937;--line:#374151;--accent:#93c5fd;--bad:#fca5a5;--good:#86efac}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding-block:32px;padding-inline:16px}
.draft{font-size:13px;color:var(--bad);text-transform:uppercase;letter-spacing:.04em}
.meta{color:var(--muted);font-size:14px}
.answer{background:var(--card);border-left:4px solid var(--accent);padding:16px 20px;margin:20px 0;font-size:19px;font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:16px 0}
h1{font-size:28px;line-height:1.25;margin:8px 0}
h2{font-size:19px;line-height:1.35;margin:0 0 10px}
details{border-top:1px solid var(--line);padding-top:8px;margin-top:10px}
summary{cursor:pointer;color:var(--accent);font-weight:600}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:560px){.cols{grid-template-columns:1fr}}
.bad{border-left:4px solid var(--bad);padding-left:10px}.good{border-left:4px solid var(--good);padding-left:10px}
.tiles{display:flex;flex-wrap:wrap;gap:12px}.tile{flex:1 1 200px;border:1px solid var(--line);border-radius:8px;padding:12px}
.tile b{display:block;font-size:22px;color:var(--accent)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
ol.timeline{list-style:none;padding:0;border-left:2px solid var(--line)}ol.timeline li{padding:0 0 10px 14px}
label{display:block;padding:4px 0}
"""


def e(text) -> str:
    return H.escape(str(text if text is not None else ""))


def _ul(lines: list[str]) -> str:
    lines = [x for x in lines if x]
    return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>" if lines else ""


def _details(summary: str, body_html: str) -> str:
    return f"<details><summary>{e(summary)}</summary>{body_html}</details>" if body_html else ""


def _section_items(idx: dict, name: str) -> list[dict]:
    return [v for v in idx.values() if v["_section"] == name]


def _visual(model: dict, story: dict, items: list[dict]) -> str:
    hint = story["visual_hint"]
    visible = [i for i in items if M.claim_type_of(i) not in LEGAL_CLAIMS]
    fallback = lambda: _ul(T.body_lines(model, story, visible or items))  # noqa: E731
    if hint == "checklist":
        return "".join(f'<label><input type="checkbox"> {e(T.item_display_text(i))}</label>' for i in items)
    if hint == "side_by_side":
        wrong = [i.get("text", "") for i in items if i.get("kind") == "wrong"]
        better = [i.get("text", "") for i in items if i.get("kind") == "better"]
        titles = ("Как делаем сейчас", "Как лучше")
        if not (wrong or better) and model["change"]:
            wrong, better, titles = [model["change"].get("current", "")], [model["change"].get("new", "")], ("Было", "Стало")
        return (f'<div class="cols"><div class="bad"><b>{e(titles[0])}</b>{_ul(wrong)}</div>'
                f'<div class="good"><b>{e(titles[1])}</b>{_ul(better)}</div></div>')
    if hint == "timeline":
        dated = sorted([i for i in items if i.get("date")], key=lambda i: str(i["date"]))
        if not dated:
            return fallback()
        return '<ol class="timeline">' + "".join(
            f"<li><b>{e(i['date'])}</b> — {e(i.get('text', ''))}</li>" for i in dated) + "</ol>"
    if hint == "decision_tree":
        nodes = [i for i in items if i["_section"] == "decision_nodes"]
        if not nodes:
            return fallback()
        return "".join(f"<p><b>{e(n.get('question', ''))}</b><br>Да → {e(n.get('if_yes', ''))}"
                       f"<br>Нет → {e(n.get('if_no', ''))}</p>" for n in nodes)
    if hint in ("metric", "chart"):
        tiles = [i for i in items if i["_section"] in ("impacts", "metrics")]
        if not tiles:
            return fallback()
        # Полный текст элемента (label + значение) — одной строкой, чтобы он совпадал
        # с T.item_display_text и был виден без тегов (паритет с DOCX/PPTX, fix-wave F1).
        return '<div class="tiles">' + "".join(
            f'<div class="tile"><b>{e(T.item_display_text(i))}</b>'
            f'<br><span class="meta">{e(T.VALUE_LABELS.get(i.get("value_class"), ""))}</span></div>'
            for i in tiles) + "</div>"
    if hint == "comparison":
        options = [i for i in items if i["_section"] == "options"]
        if not options:
            return fallback()
        rows = "".join(f"<tr><td>{'★ ' if o.get('recommended') else ''}{e(o.get('title', ''))}</td>"
                       f"<td>{e('; '.join(o.get('pros') or []))}</td><td>{e('; '.join(o.get('cons') or []))}</td>"
                       f"<td>{e(o.get('risk', ''))}</td></tr>" for o in options)
        return ('<div class="wrap"><table><tr><th>Вариант</th><th>Плюсы</th><th>Минусы</th><th>Риск</th></tr>'
                f"{rows}</table></div>")
    if hint == "flow":
        return "<ol>" + "".join(f"<li>{e(T.item_display_text(i))}</li>" for i in items) + "</ol>"
    return fallback()


def _story_section(model: dict, idx: dict, story: dict) -> str:
    items = T.refs_items(model, idx, story)
    legal = [i for i in items if M.claim_type_of(i) in LEGAL_CLAIMS]
    why = [i["why"] for i in items if i.get("why")]
    examples = [T.item_display_text(i) for i in items if i["_section"] in ("cases", "internal_examples")
                and i.get("kind", "case") == "case"]
    more = [i["detail"] for i in items if i.get("detail") and M.claim_type_of(i) not in LEGAL_CLAIMS]
    legal_html = "".join(
        f"<p>{e(T.item_display_text(i))}</p>" + (f"<p class='meta'>{e(i['detail'])}</p>" if i.get("detail") else "")
        + "".join(f"<p class='meta'>Источник: {e(T.source_line(s))}</p>" for s in T.item_sources(model, i))
        for i in legal)
    support_html = ""
    if story["content_block"] == "key_message" and story["visual_hint"] == "text":
        # При этом сочетании _visual показывает вершину пирамиды Минто
        # (minto.supporting_arguments), а не evidence_refs (fix-wave F2) — сама
        # evidence при этом не должна пропадать из документа, поэтому раскрывается
        # отдельно (аналог "Опора тезиса" в notes PPTX).
        support = [i for i in items if M.claim_type_of(i) not in LEGAL_CLAIMS]
        if support:
            support_html = _details("Опора тезиса", _ul([T.item_display_text(i) for i in support]))
    return (f"<section><h2>{e(story['message'])}</h2>{_visual(model, story, items)}{support_html}"
            f"{_details('Почему?', _ul(why))}{_details('Правовая база', legal_html)}"
            f"{_details('Пример', _ul(examples) if story['content_block'] not in ('internal_case', 'enforcement_case') else '')}"
            f"{_details('Подробнее', _ul(more))}</section>")


def render(model: dict, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    idx = M.index_items(model)
    p, mi = model["project"], model["minto"]
    parts = [
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(p['title'])}</title><style>{CSS}</style></head><body><main>",
        f'<div class="draft">{e(T.DRAFT_LABEL)}</div><h1>{e(p["title"])}</h1>',
        f'<div class="meta">{e(T.MODE_LABELS[p["mode"]])} · для: {e(p["audience"])} · {e(p.get("prepared_at", ""))}</div>',
        f'<div class="answer">{e(mi["answer"])}</div>',
    ]
    if p["mode"] == "INCIDENT" and model["incident"]:
        inc = model["incident"]
        parts.append(f"<section><h2>Текущий статус</h2>{_ul([inc.get('status', ''), 'Следующее обновление: ' + str(inc.get('next_update', ''))])}</section>")
    for story in M.main_storyline(model):
        if story["title_kind"] == "assertion":
            parts.append(_story_section(model, idx, story))
        else:
            # title/section/navigation — не тезис-вывод, но PPTX всё равно даёт под
            # такую запись слайд, а HTML раньше её терял целиком (fix-wave F1b).
            items = T.refs_items(model, idx, story)
            body = _ul([T.item_display_text(i) for i in items])
            parts.append(f"<section><h2>{e(story['message'])}</h2>{body}</section>")
    referenced: set[str] = set()
    for s in model["storyline"]:
        if isinstance(s, dict):
            referenced |= set(s.get("evidence_refs") or [])
    for section, heading in (("actions", "Что требуется"), ("next_steps", "Следующие шаги"),
                              ("impacts", "Эффект для бизнеса"), ("risks", "Риски")):
        orphans = [v for v in idx.values() if v["_section"] == section and v["id"] not in referenced]
        if orphans:
            parts.append(f"<section><h2>{e(heading)}</h2>"
                         + _ul([T.item_display_text(i) for i in orphans]) + "</section>")
    faq = _section_items(idx, "faq")
    if faq:
        parts.append("<section><h2>Частые вопросы</h2>" + "".join(
            _details(q.get("q", ""), f"<p>{e(q.get('a', ''))}</p>") for q in faq) + "</section>")
    escalation = _section_items(idx, "escalation_points")
    if escalation:
        parts.append("<section><h2>Когда обращаться в Legal</h2>"
                     + _ul([T.item_display_text(x) for x in escalation]) + "</section>")
    appendix = M.appendix_storyline(model)
    if appendix:
        parts.append("<section><h2>Приложение</h2>" + "".join(
            _details(s["message"], _ul([T.item_display_text(i) + (f" — {i['detail']}" if i.get("detail") else "")
                                        for i in T.refs_items(model, idx, s)])) for s in appendix) + "</section>")
    if model["sources"]:
        links = []
        for s in model["sources"]:
            line = e(T.source_line(s))
            url = str(s.get("url") or "")
            links.append(f'<li><a href="{e(url)}">{line}</a></li>' if url.startswith("https://") else f"<li>{line}</li>")
        parts.append("<section><h2>Источники</h2><ol>" + "".join(links) + "</ol></section>")
    parts.append("</main></body></html>")
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def inspect_html(path: str | Path) -> list[Issue]:
    out: list[Issue] = []
    raw = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"<[^>]+>", " ", H.unescape(re.sub(r"<style>.*?</style>", " ", raw, flags=re.S)))
    if T.DRAFT_LABEL not in text:
        out.append(Issue("error", "X01", str(path), "нет метки черновика"))
    if DEBRIS_RE.search(text):
        out.append(Issue("error", "X02", str(path), "мусор шаблона в тексте"))
    if FINAL_RE.search(text):
        out.append(Issue("error", "X03", str(path), "«финальный / готов к показу»"))
    if EXTERNAL_RE.search(raw):
        out.append(Issue("error", "X05", str(path), "внешние ресурсы — страница должна быть самодостаточной"))
    return out
