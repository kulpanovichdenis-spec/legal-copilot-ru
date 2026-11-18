"""Приём документов из входящей папки: копия, текст, карточка ожидания. Без ИИ."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from .journal import read_events
from .pipeline import _name_date
from .publish import EVENTS, _free_name, _replace

DOC_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".html", ".htm"}
MIN_TEXT = 20
DOC_ID = re.compile(r"doc-\d{8}-[0-9a-f]{8}")


def _cards_dir(root: Path) -> Path:
    return root / "pending"


def check_doc_id(doc_id) -> str:
    """doc_id из ввода (факты, CLI) — только вида doc-ГГГГММДД-xxxxxxxx: путь из него не выходит за pending/."""
    if not isinstance(doc_id, str) or not DOC_ID.fullmatch(doc_id):
        raise ValueError(f"недопустимый doc_id {doc_id!r}: ожидается doc-ГГГГММДД-xxxxxxxx")
    return doc_id


def load_card(root: Path, doc_id: str) -> dict:
    check_doc_id(doc_id)
    return json.loads((_cards_dir(root) / f"{doc_id}.json").read_text(encoding="utf-8"))


def save_card(root: Path, card: dict) -> None:
    folder = _cards_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{card['doc_id']}.json"
    tmp = folder / f".{card['doc_id']}.json.tmp"
    tmp.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _replace(tmp, target)  # атомарно: при сбое прежняя карточка остаётся целой
    finally:
        if tmp.exists():
            os.unlink(tmp)


def list_cards(root: Path, statuses=None) -> list[dict]:
    folder = _cards_dir(root)
    if not folder.exists():
        return []
    cards: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        if path.name.endswith(".facts.json"):  # файлы фактов лежат рядом с карточками, это не карточки
            continue
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(card, dict) or not card.get("doc_id"):
            continue
        if statuses is None or card.get("status") in statuses:
            cards.append(card)
    return cards


def _known_doc_id(root: Path, digest: str) -> str | None:
    for card in list_cards(root):
        if card.get("sha256") == digest and card.get("doc_id"):
            return card["doc_id"]
    try:
        events = read_events(root / "data" / EVENTS)
    except (OSError, ValueError):
        events = []
    for event in events:
        source = event.get("source") or {}
        if source.get("sha256") == digest:
            return source.get("doc_id") or f"doc-{digest[:8]}"
    return None


def accept_document(root: Path, path: Path, *, today: dt.date) -> dict:
    from tools.doc_ingest import router

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    known = _known_doc_id(root, digest)
    if known:
        path.unlink()
        return {"status": "duplicate", "doc_id": known}
    name = path.name if _name_date(path.name) else f"{today.isoformat()}_{path.name}"
    documents = root / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    stored = _free_name(documents, name)
    shutil.copy2(path, stored)
    warnings: list[str] = []
    ocr = False
    try:
        result = router.convert(path)
        text = result.get("markdown") or ""
        metadata = result.get("metadata") or {}
        ocr = "ocr" in (metadata.get("backend") or "").lower()
        warnings = list(metadata.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001 - любой сбой извлечения уходит юристу на решение
        text = ""
        warnings = [f"ошибка извлечения текста: {type(exc).__name__}"]
    text_path = _free_name(documents, stored.stem + ".md")
    text_path.write_text(text, encoding="utf-8")
    empty = len("".join(text.split())) < MIN_TEXT
    card = {
        "doc_id": f"doc-{today:%Y%m%d}-{digest[:8]}",
        "document": f"documents/{stored.name}",
        "text": f"documents/{text_path.name}",
        "sha256": digest,
        "ocr": ocr,
        "received": today.isoformat(),
        "status": "needs_decision" if empty else "awaiting_facts",
        "reason": "текст не извлечён" if empty else None,
        "warnings": warnings,
    }
    save_card(root, card)
    path.unlink()
    return card
