#!/usr/bin/env python3
"""Content model skill business-communication: константы, загрузка, индекс, схема.

Единый объект, из которого рендерятся PPTX / DOCX / HTML (ТЗ §26).
Спецификация полей — tools/business_comm/schema.md.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import yaml

MODES = ("BRIEFING", "REPORT", "RECOMMENDATION", "TRAINING", "CHANGE", "INCIDENT")
OUTPUTS = ("pptx", "docx", "html")
CLAIM_TYPES = ("fact", "legal_rule", "legal_interpretation",
               "business_estimate", "recommendation", "assumption")
VALUE_CLASSES = ("actual", "estimated", "exposure", "qualitative")
IMPACT_TYPES = ("cash_recovered", "cost_avoided", "exposure_reduced", "revenue_enabled",
                "business_continuity", "time_saved", "cycle_time_improved",
                "dispute_resolved", "asset_or_right_preserved", "process_improved",
                "compliance_assurance", "strategic_option_enabled")
CONTENT_BLOCKS = ("key_message", "business_context", "fact", "legal_rule",
                  "enforcement_case", "internal_case", "wrong_example", "better_example",
                  "business_consequence", "recommendation", "required_action", "decision",
                  "metric", "timeline", "process", "checklist", "decision_tree", "faq",
                  "escalation_rule", "source")
VISUAL_HINTS = ("text", "timeline", "comparison", "flow", "decision_tree", "chart",
                "annotated_document", "side_by_side", "risk_matrix", "hierarchy",
                "checklist", "metric")
TITLE_KINDS = ("assertion", "title", "section", "appendix", "navigation")
LAYERS = ("main", "appendix")
SOURCE_RANK = {"primary_law": 1, "court_or_regulator": 2, "internal_policy": 3,
               "reported": 3, "secondary_reliable": 4, "commentary": 5}
CONFIDENTIALITY = ("cleared", "anonymized", "unknown")
FACT_STATUS = ("verified", "unverified")
CONFIDENCE = ("low", "medium", "high")
DOCX_VARIANTS = ("memo", "one_pager")
EXAMPLE_KINDS = ("case", "wrong", "better")

# раздел content -> (claim_type по умолчанию, content_block по умолчанию)
SECTIONS: dict[str, tuple[str | None, str]] = {
    "business_context": ("fact", "business_context"),
    "facts": ("fact", "fact"),
    "timeline": ("fact", "timeline"),
    "legal_rules": ("legal_rule", "legal_rule"),
    "interpretations": ("legal_interpretation", "legal_rule"),
    "cases": ("fact", "enforcement_case"),
    "internal_examples": ("fact", "internal_case"),
    "estimates": ("business_estimate", "business_consequence"),
    "metrics": (None, "metric"),
    "impacts": (None, "metric"),
    "recommendations": ("recommendation", "recommendation"),
    "options": (None, "decision"),
    "risks": (None, "business_consequence"),
    "actions": (None, "required_action"),
    "next_steps": (None, "required_action"),
    "escalation_points": (None, "escalation_rule"),
    "triggers": (None, "checklist"),
    "checks": (None, "checklist"),
    "decision_nodes": (None, "decision_tree"),
    "faq": (None, "faq"),
}


@dataclass(frozen=True)
class Issue:
    level: str   # "error" | "warn"
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()} {self.code}] {self.where}: {self.message}"


def normalize(raw: dict) -> dict:
    m = copy.deepcopy(raw or {})
    for key in ("project", "objective", "minto", "content", "render", "quality", "change", "incident"):
        if not isinstance(m.get(key), dict):
            m[key] = {}
    if not isinstance(m.get("storyline"), list):
        m["storyline"] = []
    if not isinstance(m.get("sources"), list):
        m["sources"] = []
    if m["minto"].get("supporting_arguments") is None:
        m["minto"]["supporting_arguments"] = []
    if m["objective"].get("learning_objectives") is None:
        m["objective"]["learning_objectives"] = []
    for section in SECTIONS:
        if m["content"].get(section) is None:
            m["content"][section] = []
    for q in ("assumptions", "open_questions", "validation_results"):
        if m["quality"].get(q) is None:
            m["quality"][q] = []
    for s in m["storyline"]:
        if not isinstance(s, dict):
            continue
        s["visual_hint"] = s.get("visual_hint") or "text"
        s["title_kind"] = s.get("title_kind") or "assertion"
        s["layer"] = s.get("layer") or "main"
        s["evidence_refs"] = s.get("evidence_refs") or []
    return m


def load_model(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"content model должен быть YAML-объектом: {path}")
    return normalize(data)


def index_items(model: dict) -> dict[str, dict]:
    sources = {s["id"]: s for s in model.get("sources") or [] if isinstance(s, dict) and s.get("id")}
    idx: dict[str, dict] = {}
    for section in SECTIONS:
        items = model["content"].get(section) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id") and item["id"] not in idx:
                entry = dict(item)
                entry["_section"] = section
                if entry.get("calibrated") and entry.get("source_refs"):
                    ranks = [SOURCE_RANK[sources[r]["type"]] for r in entry["source_refs"]
                             if r in sources and sources[r].get("type") in SOURCE_RANK]
                    if ranks and min(ranks) >= 4:
                        entry["_calibrated_weak_source"] = True
                idx[item["id"]] = entry
    return idx


def claim_type_of(item: dict) -> str | None:
    if item.get("claim_type"):
        return item["claim_type"]
    section = item.get("_section")
    if section == "internal_examples" and item.get("kind") in ("wrong", "better"):
        return None
    return SECTIONS.get(section, (None, ""))[0]


def block_of(item: dict) -> str:
    section = item.get("_section")
    if section == "internal_examples":
        return {"wrong": "wrong_example", "better": "better_example"}.get(item.get("kind"), "internal_case")
    return SECTIONS.get(section, (None, "fact"))[1]


def _sorted(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda s: (s.get("order") is None, s.get("order") or 0))


def main_storyline(model: dict) -> list[dict]:
    return _sorted([s for s in model["storyline"] if isinstance(s, dict) and s.get("layer") == "main"])


def appendix_storyline(model: dict) -> list[dict]:
    return _sorted([s for s in model["storyline"] if isinstance(s, dict) and s.get("layer") == "appendix"])


def _err(code: str, where: str, message: str) -> Issue:
    return Issue("error", code, where, message)


def schema_errors(model: dict) -> list[Issue]:
    out: list[Issue] = []
    p, o, mi = model["project"], model["objective"], model["minto"]
    if not p.get("title"):
        out.append(_err("S01", "project.title", "нет названия проекта"))
    if p.get("mode") not in MODES:
        out.append(_err("S02", "project.mode", f"режим должен быть одним из {MODES}"))
    sec = p.get("secondary_mode")
    if sec is not None and (sec not in MODES or sec == p.get("mode")):
        out.append(_err("S03", "project.secondary_mode", "вторичный режим пуст или из MODES и не равен основному"))
    if not p.get("audience"):
        out.append(_err("S04", "project.audience", "аудитория не определена"))
    outputs = p.get("output") or []
    if not outputs or any(x not in OUTPUTS for x in outputs):
        out.append(_err("S05", "project.output", f"формат(ы) из {OUTPUTS}"))
    if not o.get("business_question"):
        out.append(_err("S06", "objective.business_question", "нет бизнес-вопроса"))
    for part in ("situation", "complication", "question", "answer"):
        if not mi.get(part):
            out.append(_err("S07", f"minto.{part}", "SCQA неполный"))

    if not model["storyline"]:
        out.append(_err("S08", "storyline", "storyline пуст"))
    for n, s in enumerate(model["storyline"]):
        w = f"storyline[{n}]"
        if not isinstance(s, dict) or not s.get("message"):
            out.append(_err("S08", w, "нет message"))
            continue
        if s.get("content_block") not in CONTENT_BLOCKS:
            out.append(_err("S08", w, f"content_block не из словаря: {s.get('content_block')!r}"))
        if s["visual_hint"] not in VISUAL_HINTS:
            out.append(_err("S08", w, f"visual_hint не из словаря: {s['visual_hint']!r}"))
        if s["title_kind"] not in TITLE_KINDS:
            out.append(_err("S08", w, f"title_kind не из словаря: {s['title_kind']!r}"))
        if s["layer"] not in LAYERS:
            out.append(_err("S08", w, f"layer не из словаря: {s['layer']!r}"))

    seen: set[str] = set()
    for section in SECTIONS:
        items = model["content"].get(section)
        if not isinstance(items, list):
            out.append(_err("S17", f"content.{section}", "раздел должен быть списком"))
            continue
        for n, item in enumerate(items):
            w = f"content.{section}[{n}]"
            if not isinstance(item, dict) or not item.get("id"):
                out.append(_err("S09", w, "у элемента нет id"))
                continue
            if item["id"] in seen:
                out.append(_err("S09", w, f"повторный id {item['id']!r}"))
            seen.add(item["id"])
    source_ids: set[str] = set()
    for n, src in enumerate(model["sources"]):
        w = f"sources[{n}]"
        if not isinstance(src, dict) or not src.get("id"):
            out.append(_err("S09", w, "у источника нет id"))
            continue
        if src["id"] in source_ids or src["id"] in seen:
            out.append(_err("S09", w, f"повторный id {src['id']!r}"))
        source_ids.add(src["id"])
        if src.get("type") not in SOURCE_RANK:
            out.append(_err("S12", w, f"тип источника из {tuple(SOURCE_RANK)}"))

    idx = index_items(model)
    for n, s in enumerate(model["storyline"]):
        if not isinstance(s, dict):
            continue
        for ref in s.get("evidence_refs") or []:
            if ref not in idx and ref not in source_ids:
                out.append(_err("S10", f"storyline[{n}]", f"evidence_ref {ref!r} не найден"))
    for item_id, item in idx.items():
        for ref in item.get("source_refs") or []:
            if ref not in source_ids:
                out.append(_err("S11", item_id, f"source_ref {ref!r} не найден"))
        section = item["_section"]
        if section == "impacts":
            if item.get("type") not in IMPACT_TYPES:
                out.append(_err("S13", item_id, f"тип эффекта из {IMPACT_TYPES}"))
            if item.get("value_class") not in VALUE_CLASSES:
                out.append(_err("S13", item_id, f"value_class из {VALUE_CLASSES}"))
            if item.get("confidence") is not None and item["confidence"] not in CONFIDENCE:
                out.append(_err("S13", item_id, f"confidence из {CONFIDENCE}"))
        if section == "metrics" and item.get("value") is None:
            out.append(_err("S13", item_id, "metrics: обязательно value"))
        if section == "internal_examples" and item.get("kind", "case") not in EXAMPLE_KINDS:
            out.append(_err("S14", item_id, f"kind из {EXAMPLE_KINDS}"))
        if item.get("confidentiality") is not None and item["confidentiality"] not in CONFIDENTIALITY:
            out.append(_err("S14", item_id, f"confidentiality из {CONFIDENTIALITY}"))
        if section in ("facts", "timeline") and item.get("status") is not None \
                and item["status"] not in FACT_STATUS:
            out.append(_err("S15", item_id, f"status из {FACT_STATUS}"))
        if item.get("claim_type") is not None and item["claim_type"] not in CLAIM_TYPES:
            out.append(_err("S15", item_id, f"claim_type из {CLAIM_TYPES}"))
    variant = (model["render"].get("docx") or {}).get("variant")
    if variant is not None and variant not in DOCX_VARIANTS:
        out.append(_err("S16", "render.docx.variant", f"вариант из {DOCX_VARIANTS}"))
    return out
