#!/usr/bin/env python3
"""Валидация content model перед рендером (ТЗ §27 и acceptance §28–31).

Механически проверяемое — здесь; смысловое (логика аргументов, MECE,
уместность тона) — суждение модели по references/business-communication-method.md.
Любая ошибка (level=error) блокирует рендер.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable

import bc_model as M
from bc_model import Issue

ABSOLUTES_RE = re.compile(
    r"(?<!\w)(всегда|никогда|однозначно|гарантированно|безусловно|в любом случае|лишается всех)(?!\w)",
    re.IGNORECASE)
SAVINGS_RE = re.compile(
    r"(сэконом|экономи[яиюей]|сберег|сохранил[аи]?\s+компании|предотвратил[аи]?\s+(ущерб|штраф))",
    re.IGNORECASE)
FINAL_RE = re.compile(r"(финальн|готов[аоы]?\s+к\s+(показу|отправке|подаче|рассылке))", re.IGNORECASE)
DEBRIS_RE = re.compile(
    r"(click to add|нажмите, чтобы добавить|lorem ipsum|(?<!\w)todo(?!\w)|(?<!\w)tbd(?!\w)|placeholder)",
    re.IGNORECASE)
FIRST_BLOCKS = {"key_message", "recommendation", "decision"}
NO_EVIDENCE_OK = {"key_message", "recommendation", "decision", "required_action", "checklist"}
ACTION_MODES = {"TRAINING", "CHANGE", "INCIDENT", "RECOMMENDATION"}
PPTX_TEXT_LIMIT = 350
STALE_DAYS = 183
TEXT_FIELDS = ("text", "title", "label", "what", "q", "a", "why", "detail", "question", "when",
               "pros", "cons", "risk", "contact", "if_yes", "if_no")

MODE_CHECKS: dict[str, Callable[[dict, dict], list[Issue]]] = {}


def _e(code: str, where: str, message: str) -> Issue:
    return Issue("error", code, where, message)


def _w(code: str, where: str, message: str) -> Issue:
    return Issue("warn", code, where, message)


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)


def item_text(item: dict) -> str:
    return " ".join(str(item[f]) for f in TEXT_FIELDS if item.get(f))


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", (text or "").lower()) if len(w) > 2]


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def _as_date(value) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dict_texts(where_prefix: str, d: dict | None) -> list[tuple[str, str]]:
    return [(f"{where_prefix}.{k}", v) for k, v in (d or {}).items() if isinstance(v, str) and v]


def _audience_texts(model: dict, idx: dict) -> list[tuple[str, str]]:
    out = [("minto.answer", model["minto"].get("answer") or "")]
    out += [(f"minto.supporting_arguments[{n}]", a) for n, a in enumerate(model["minto"]["supporting_arguments"])]
    out += [(f"storyline[{s.get('order')}]", s["message"]) for s in model["storyline"]]
    out += [(item_id, item_text(item)) for item_id, item in idx.items()]
    out += _dict_texts("change", model.get("change"))
    out += _dict_texts("incident", model.get("incident"))
    return out


def _duplicates(where: str, texts: list[str]) -> list[Issue]:
    out: list[Issue] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _norm(texts[i]) == _norm(texts[j]):
                out.append(_e("M02", where, f"дублирование: «{texts[i]}»"))
                continue
            a, b = set(_words(texts[i])), set(_words(texts[j]))
            if len(a) >= 3 and len(b) >= 3 and len(a & b) / len(a | b) >= 0.7:
                out.append(_w("M02", where, f"почти дубли: «{texts[i]}» / «{texts[j]}»"))
    return out


def check_minto(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    args = model["minto"]["supporting_arguments"]
    if not args:
        out.append(_e("M01", "minto.supporting_arguments", "нет поддерживающих аргументов"))
    elif len(args) > 5:
        out.append(_w("M01", "minto.supporting_arguments", "больше 5 аргументов — объединить или сгруппировать"))
    main = M.main_storyline(model)
    out += _duplicates("storyline", [s["message"] for s in main])
    out += _duplicates("minto.supporting_arguments", list(args))
    for s in main:
        if s["title_kind"] == "assertion" and not s["evidence_refs"] and s["content_block"] not in NO_EVIDENCE_OK:
            out.append(_w("M04", f"storyline[{s.get('order')}]", "тезис без привязанного доказательства"))
    return out


def check_business(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    impacts = {k: v for k, v in idx.items() if v["_section"] == "impacts"}
    for item_id, imp in impacts.items():
        cls = imp.get("value_class")
        if cls in ("estimated", "exposure") and not imp.get("method"):
            out.append(_e("B01", item_id, f"{cls}: не раскрыт метод оценки"))
        if cls == "actual" and not imp.get("source_refs"):
            out.append(_e("B01", item_id, "actual: нет источника фактического результата"))
        if cls == "qualitative" and isinstance(imp.get("value"), (int, float)):
            out.append(_e("B01", item_id, "qualitative не может иметь денежного/числового значения"))
    has_actual = any(i.get("value_class") == "actual" for i in impacts.values())
    for s in model["storyline"]:
        if not SAVINGS_RE.search(s["message"]):
            continue
        ref_classes = {impacts[r].get("value_class") for r in s["evidence_refs"] if r in impacts}
        if not ref_classes or ref_classes - {"actual"}:
            out.append(_e("B02", f"storyline[{s.get('order')}]",
                          "«экономия» допустима только для actual-эффекта; exposure/estimate — не экономия"))
    for where, text in [("minto.answer", model["minto"].get("answer") or "")] + \
            [(f"minto.supporting_arguments[{n}]", a) for n, a in enumerate(model["minto"]["supporting_arguments"])]:
        if SAVINGS_RE.search(text) and not has_actual:
            out.append(_e("B02", where, "«экономия» без actual-эффекта"))
    for item_id, imp in impacts.items():
        if imp.get("value_class") != "actual" and SAVINGS_RE.search(item_text(imp)):
            out.append(_e("B02", item_id,
                          "название/подпись эффекта звучит как «экономия», но value_class не actual"))
    for item_id, met in idx.items():
        if met["_section"] == "metrics" and met.get("kind") == "activity":
            if met.get("explains") not in impacts:
                out.append(_w("B03", item_id, "activity-метрика не связана с бизнес-эффектом (explains)"))
    mode = model["project"]["mode"]
    actions = [v for v in idx.values() if v["_section"] == "actions"]
    if not actions:
        if mode in ACTION_MODES:
            out.append(_e("B04", "content.actions", f"{mode}: нет действий (что / кто / когда)"))
        elif mode == "BRIEFING":
            out.append(_w("B04", "content.actions", "нет требуемых действий — проверить, нужны ли они"))
    for a in actions:
        if not a.get("what") or not a.get("who"):
            out.append(_e("B04", a["id"], "у действия нет «что» или «кто»"))
        elif not a.get("when"):
            out.append(_w("B04", a["id"], "у действия нет срока «когда»"))
    for where, text in _audience_texts(model, idx):
        if FINAL_RE.search(text):
            out.append(_e("B05", where, "результат — черновик; «финальный / готов к показу» запрещено"))
    for item_id, item in idx.items():
        if M.claim_type_of(item) == "business_estimate" and not item.get("method"):
            out.append(_e("B06", item_id, "бизнес-оценка без метода"))
    return out


def check_legal(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    sources = {s["id"]: s for s in model["sources"]}
    for item_id, item in idx.items():
        ct = M.claim_type_of(item)
        refs = [sources[r] for r in item.get("source_refs") or [] if r in sources]
        if ct in ("fact", "legal_rule") and not refs:
            out.append(_e("L01", item_id, f"{ct} без источника — маркер или источник"))
        if ct == "legal_interpretation" and not refs:
            out.append(_w("L02", item_id, "интерпретация без источника"))
        if ct == "legal_rule" and refs and min(M.SOURCE_RANK[s["type"]] for s in refs) >= 4:
            if item.get("calibrated"):
                out.append(_w("L03", item_id, "норма только из вторичного источника — калиброванная формулировка"))
            else:
                out.append(_e("L03", item_id,
                              "норма опирается только на вторичный источник — не выдавать как бесспорную"))
    for where, text in _audience_texts(model, idx):
        hit = ABSOLUTES_RE.search(text)
        if hit:
            out.append(_w("L04", where, f"категоричный абсолют «{hit.group(0)}»"))
    prepared = _as_date(model["project"].get("prepared_at")) or dt.date.today()
    for s in model["sources"]:
        if s.get("type") != "primary_law":
            continue
        checked = _as_date(s.get("checked_at"))
        if checked is None:
            out.append(_w("L05", s["id"], "нет даты сверки редакции (checked_at)"))
        elif (prepared - checked).days > STALE_DAYS:
            out.append(_w("L05", s["id"], "сверка редакции старше 6 мес. — [ПРОВЕРИТЬ АКТУАЛЬНОСТЬ РЕДАКЦИИ]"))
    if any(M.claim_type_of(i) == "assumption" for i in idx.values()) and not model["quality"]["assumptions"]:
        out.append(_w("L06", "quality.assumptions", "есть допущения, но они не вынесены в quality.assumptions"))
    return out


def check_communication(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    main = [s for s in M.main_storyline(model) if s["title_kind"] == "assertion"]
    if main and main[0]["content_block"] not in FIRST_BLOCKS:
        out.append(_e("C01", f"storyline[{main[0].get('order')}]",
                      "первый содержательный блок должен давать вывод (key_message / recommendation / decision)"))
    for s in main:
        if len(_words(s["message"])) < 4:
            out.append(_w("C02", f"storyline[{s.get('order')}]", f"«{s['message']}» похоже на тему, а не на вывод"))
    blocks = [s["content_block"] for s in main]
    for n in range(1, len(blocks)):
        if blocks[n] == "legal_rule" and blocks[n - 1] == "legal_rule":
            out.append(_e("C03", f"storyline[{main[n].get('order')}]",
                          "подряд несколько норм в основной части — law dump, перенести в приложение"))
            break
    if len(blocks) >= 3 and blocks.count("legal_rule") / len(blocks) > 0.4:
        out.append(_w("C03", "storyline", "основная часть перегружена правовыми блоками"))
    if "pptx" in model["project"]["output"]:
        for s in main:
            size = sum(len(item_text(idx[r])) for r in s["evidence_refs"] if r in idx)
            if size > PPTX_TEXT_LIMIT:
                out.append(_w("C04", f"storyline[{s.get('order')}]",
                              f"на слайд {size} знаков — перенести детали в notes / приложение"))
    return out


def check_confidentiality(model: dict, idx: dict) -> list[Issue]:
    out: list[Issue] = []
    for item_id, item in idx.items():
        if item["_section"] == "internal_examples" and item.get("confidentiality") in (None, "unknown"):
            out.append(_e("P01", item_id,
                          "статус конфиденциальности внутреннего примера не подтверждён — предложить обезличивание"))
    return out


COMMON_CHECKS = (check_minto, check_business, check_legal, check_communication, check_confidentiality)


def validate(model: dict) -> list[Issue]:
    schema = M.schema_errors(model)
    if schema:
        return schema
    idx = M.index_items(model)
    issues: list[Issue] = []
    for check in COMMON_CHECKS:
        issues += check(model, idx)
    mode = model["project"]["mode"]
    if mode in MODE_CHECKS:
        issues += MODE_CHECKS[mode](model, idx)
    secondary = model["project"].get("secondary_mode")
    if secondary in MODE_CHECKS:
        issues += [Issue("warn", i.code, i.where, f"(вторичный {secondary}) {i.message}")
                   for i in MODE_CHECKS[secondary](model, idx)]
    return issues


import validate_modes as _vm  # noqa: E402  регистрация проверок режимов

MODE_CHECKS.update(_vm.REGISTRY)
