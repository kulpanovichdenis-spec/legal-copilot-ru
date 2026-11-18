# -*- coding: utf-8 -*-
"""Каталог типовых решений ООО (references/corporate-decisions/llc.yaml): чтение и проверка.

Каталог — указатель, а не источник права: позиции ссылаются на карточки норм, текст нормы
открывается живым маршрутом. Правовые позиции каталога меняются только по указанию юриста.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402

CATALOG_PATH = store.ROOT / "references" / "corporate-decisions" / "llc.yaml"
DECISION_ID_RE = re.compile(r"[a-z][a-z0-9_]*")
TEXT_FIELDS = ("title", "organs_by_law", "majority_by_law", "confirmation", "sole_member")


def read_catalog(path: Path = CATALOG_PATH) -> dict:
    if not path.is_file():
        raise store.GovError(f"каталог решений не найден: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise store.GovError(f"каталог решений не читается как YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise store.GovError("каталог решений: нужен словарь с ключом decisions (список позиций)")
    return data


def _validate_item(item, index: int, seen: set[str]) -> list[str]:
    if not isinstance(item, dict):
        return [f"позиция {index}: не словарь"]
    did = item.get("decision_id")
    label = did if isinstance(did, str) and did else f"позиция {index}"
    errs: list[str] = []

    def add(msg: str) -> None:
        errs.append(f"{label}: {msg}")

    if not isinstance(did, str) or not DECISION_ID_RE.fullmatch(did):
        add("decision_id должен быть в snake_case латиницей (loan, charter_amendment)")
    elif did in seen:
        add("повторяющийся decision_id")
    else:
        seen.add(did)
    for field in TEXT_FIELDS:
        if schema._blank(item.get(field)):
            add(f"{field} пуст")
    synonyms = item.get("synonyms")
    if not isinstance(synonyms, list) or not all(isinstance(s, str) and s.strip() for s in synonyms):
        add("synonyms должен быть списком строк")
    topics = item.get("topics")
    if not isinstance(topics, list) or not topics:
        add("topics должен быть непустым списком тем таксономии")
    else:
        for topic in topics:
            if topic not in schema.TOPICS:
                add(f"неизвестная тема {topic!r}")
    cards = item.get("norm_cards")
    if not isinstance(cards, list) or not cards:
        add("norm_cards должен быть непустым списком {card, article}")
    else:
        for ref in cards:
            if not isinstance(ref, dict) or schema._blank(ref.get("article")):
                add("norm_cards: у ссылки нет article (статья и пункт)")
            elif not schema._card_exists(ref.get("card")):
                add(f"norm_cards: несуществующая карточка {ref.get('card')}")
    if item.get("verified_at") is not None and not schema.is_iso_date(item.get("verified_at")):
        add("verified_at должен быть датой YYYY-MM-DD или пустым")
    return errs


def validate_catalog(data: dict) -> list[str]:
    errs: list[str] = []
    if data.get("entity_type") != "LLC":
        errs.append("entity_type должен быть LLC")
    approved_by = data.get("approved_by")
    if approved_by is not None:
        if schema._blank(approved_by) or store.is_placeholder_approver(str(approved_by)):
            errs.append("approved_by должен быть ФИО юриста, а не роль или заглушка")
        if not schema.is_iso_date(data.get("approved_at")):
            errs.append("approved_by требует approved_at (дата YYYY-MM-DD)")
    seen: set[str] = set()
    for index, item in enumerate(data["decisions"], start=1):
        errs.extend(_validate_item(item, index, seen))
    return errs


def decision_ids(data: dict) -> set[str]:
    return {d["decision_id"] for d in data["decisions"]
            if isinstance(d, dict) and isinstance(d.get("decision_id"), str)}


def find_decision(data: dict, decision_id: str) -> dict:
    for item in data["decisions"]:
        if isinstance(item, dict) and item.get("decision_id") == decision_id:
            return item
    known = ", ".join(sorted(decision_ids(data)))
    raise store.GovError(f"позиции {decision_id!r} нет в каталоге решений; есть: {known}")
