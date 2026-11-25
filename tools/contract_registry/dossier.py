"""Досье: заведение папки и добавление подписанных документов (копия, хеш, кеш текста)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import registry
from .keys import folder_name, number_key
from .paths import RegistryError, guard

KINDS = ("contract", "amendment", "annex", "specification", "disagreement_protocol")
STATUSES = ("signed", "unconfirmed")
TEXT_SUFFIXES = (".md", ".txt")
REPO = Path(__file__).resolve().parents[2]

CARD_SKELETON = """---
key: {key_q}
counterparty: {counterparty_q}
our_party: ""
number: {number_q}
date: ""
aliases: []
card_status: draft
---

# Карточка договора {key}

Перечень документов и статус подписания: `documents.yaml`. Каждое поле со ссылкой «документ, пункт».

## Стороны
## Предмет
## Цена и порядок оплаты
## Срок действия и пролонгация
## Уведомления
## Применимое право и споры
## Ответственность и неустойки
## Определённые термины
## Предупреждения
"""


def _dump(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for attempt in range(5):  # Windows: индексатор или антивирус на миг держат файл (как links._atomic_write)
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def next_id(prefix: str, items: list[dict]) -> str:
    """Следующий id: максимум существующих номеров + 1 (после удаления записи id не повторяется)."""
    nums = [int(m.group(1)) for it in items
            if (m := re.fullmatch(rf"{prefix}-(\d+)", str(it.get("id", ""))))]
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def init(root: Path, key: str, counterparty: str, *, inn: str = "",
         aliases: list[str] | None = None, temporary: bool = False) -> Path:
    root = guard(Path(root))
    if not str(key or "").strip() or not number_key(key):
        raise RegistryError("пустой ключ досье: укажите номер договора или временный ключ")
    data = registry.load(root)
    clash = registry.find_entry(data, key)
    if clash:
        raise RegistryError(f"ключ {key} совпадает после нормализации с досье {clash['folder']} "
                            f"({number_key(key)}): уточните у юриста")
    for alias in aliases or []:
        clash = registry.find_entry(data, alias) if str(alias).strip() else None
        if clash:
            raise RegistryError(f"алиас {alias} совпадает после нормализации с досье {clash['folder']} "
                                f"({number_key(alias)}): уточните у юриста")
    d = root / folder_name(key, counterparty)
    if d.exists():
        raise RegistryError(f"папка {d} уже существует")
    (d / "docs").mkdir(parents=True)
    (d / "_text").mkdir()
    # JSON-строка — валидный YAML: двоеточия и кавычки в наименовании не ломают frontmatter.
    (d / "contract-card.md").write_text(CARD_SKELETON.format(
        key=key, key_q=json.dumps(key, ensure_ascii=False),
        number_q='""' if temporary else json.dumps(key, ensure_ascii=False),
        counterparty_q=json.dumps(counterparty, ensure_ascii=False)), encoding="utf-8")
    _dump(d / "amendments.yaml", {"version": 1, "clauses": []})
    _dump(d / "links.yaml", {"version": 1, "tasks": [], "drafts": [], "conflicts": []})
    _dump(d / "documents.yaml", {"version": 1, "documents": []})
    try:
        subprocess.run([sys.executable, str(REPO / "tools" / "matter_model" / "model.py"), "init",
                        "--file", str(d / "matter-timeline.yaml"), "--matter", key],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(d, ignore_errors=True)  # откат: повторный init должен быть возможен
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise RegistryError(f"не удалось создать хронологию дела (matter_model): {err}") from exc
    data["contracts"].append({"key": key, "folder": d.name, "counterparty": counterparty, "inn": inn,
                              "aliases": list(aliases or []), "temporary_key": temporary, "status": "active"})
    registry.save(root, data)
    return d


def dossier_dir(root: Path, key: str) -> Path:
    entry = registry.find_entry(registry.load(root), key)
    if not entry:
        raise RegistryError(f"досье {key} в реестре нет")
    return Path(root) / entry["folder"]


def load_documents(d: Path) -> list[dict]:
    data = yaml.safe_load((d / "documents.yaml").read_text(encoding="utf-8")) or {}
    return data.get("documents", [])


def _read_plain(src: Path) -> str:
    raw = src.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251")


def _text_of(src: Path) -> tuple[str, list[str]]:
    if src.suffix.lower() in TEXT_SUFFIXES:
        return _read_plain(src), []
    from tools.doc_ingest.router import convert  # noqa: PLC0415 — тяжёлый импорт только при нужде
    res = convert(src)
    return res["markdown"], list(res["metadata"].get("warnings", []))


def _free_name(folder: Path, name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 2
    while (folder / candidate).exists():
        candidate = f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def _check_date(date: str) -> None:
    """Дата документа: пусто или ISO ГГГГ-ММ-ДД (по ней chain сортирует ДС строкой)."""
    if not date:
        return
    try:
        ok = len(date) == 10 and dt.date.fromisoformat(date).isoformat() == date
    except ValueError:
        ok = False
    if not ok:
        raise RegistryError(f"дата в формате ГГГГ-ММ-ДД: {date!r}")


def add_doc(root: Path, key: str, src: Path, *, kind: str, status: str,
            evidence: str = "", date: str = "") -> dict:
    src = guard(Path(src).resolve())
    if kind not in KINDS:
        raise RegistryError(f"kind должен быть из {KINDS}")
    if status not in STATUSES:
        raise RegistryError(f"status должен быть из {STATUSES}")
    if status == "signed" and not evidence.strip():
        raise RegistryError("signed без evidence: укажите признак подписания (скан, ЭДО, слово юриста)")
    _check_date(date)
    d = dossier_dir(root, key)
    docs = load_documents(d)
    digest = sha256(src)
    for doc in docs:
        if doc["sha256"] == digest:
            return {"result": "exists", "doc": doc}
    # Текст извлекаем до копирования: сбой конвертации не оставляет осиротевшую копию в docs/.
    text, warnings = _text_of(src)
    doc_id = next_id("D", docs)
    name = _free_name(d / "docs", src.name)
    shutil.copy2(src, d / "docs" / name)
    # Кеш назван по id документа: одноимённые файлы с разным расширением не перезаписывают друг друга.
    text_rel = f"_text/{doc_id}.txt.md"
    (d / text_rel).write_text(text, encoding="utf-8")
    entry = {"id": doc_id, "file": f"docs/{name}", "text": text_rel, "kind": kind,
             "status": status, "evidence": evidence, "date": date, "sha256": digest,
             "source_path": str(src), "added": dt.date.today().isoformat(), "warnings": warnings}
    docs.append(entry)
    _dump(d / "documents.yaml", {"version": 1, "documents": docs})
    return {"result": "added", "doc": entry}


def set_doc_status(root: Path, key: str, doc_id: str, status: str, evidence: str = "") -> dict:
    """Подтверждение подписания (или откат в unconfirmed) уже добавленного документа."""
    if status not in STATUSES:
        raise RegistryError(f"status должен быть из {STATUSES}")
    if status == "signed" and not evidence.strip():
        raise RegistryError("signed без evidence: укажите признак подписания (скан, ЭДО, слово юриста)")
    d = dossier_dir(root, key)
    docs = load_documents(d)
    doc = next((x for x in docs if x.get("id") == doc_id), None)
    if doc is None:
        raise RegistryError(f"{doc_id} нет в documents.yaml")
    status_changed = doc.get("status") != status
    doc["status"] = status
    if evidence.strip():
        doc["evidence"] = evidence
    _dump(d / "documents.yaml", {"version": 1, "documents": docs})
    note = reset_reviewed_card(d, "карточка возвращена в draft: изменился статус документа") if status_changed else None
    return {**doc, "card_note": note} if note else doc


def reset_reviewed_card(d: Path, note: str) -> str | None:
    """reviewed-карточка возвращается в draft (изменилось то, что действует: статус или связи документов).
    Возвращает note, если карточка была reviewed, иначе None."""
    card_path = d / "contract-card.md"
    if not card_path.is_file():
        return None
    from . import card  # noqa: PLC0415 — card импортирует links, а links импортирует dossier
    parts = card.parse(card_path.read_bytes())
    if isinstance(parts, str) or parts[0].get("card_status") != "reviewed":
        return None
    card.set_card_status(card_path, "draft")
    return note
