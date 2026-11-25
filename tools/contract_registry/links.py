"""Связь досье с папками задач, черновики «в работе», журнал конфликтов."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path

from tools.workflow_layout import technical_path

import yaml

from . import registry
from .dossier import _dump, dossier_dir, next_id
from .paths import RegistryError, guard_task


def _load_links(d: Path) -> dict:
    return yaml.safe_load((d / "links.yaml").read_text(encoding="utf-8"))


_OPEN = re.compile(r"^---[ \t]*$")
_KEY = re.compile(r"^contracts:(.*)$")
_ITEM = re.compile(r"^(\s*)-[ \t]+(\S.*)$")
_SPECIAL = set(",:#[]{}&*!|>'\"%@`?")


def _quote(item: str) -> str:
    """Минимальное квотирование элемента списка (двойные кавычки, если нужно)."""
    need = item == "" or item != item.strip() or item[0] == "-" or any(c in _SPECIAL for c in item)
    if not need:
        try:
            need = yaml.safe_load(item) != item
        except yaml.YAMLError:
            need = True
    return json.dumps(item, ensure_ascii=False) if need else item


def _scalars(value) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in value):
        return None
    return [str(x) for x in value]


def _decode(data: bytes) -> tuple[str, str] | None:
    first = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
    for enc in (first, "cp1251"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None


def _atomic_write(path: Path, data: bytes) -> None:
    """Файл юриста: пишем во временный файл рядом и подменяем, чтобы сбой не оставил полфайла."""
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        for attempt in range(3):  # Windows: индексатор или антивирус на миг держат файл
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.1)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _update_case_context(path: Path, key: str) -> str:
    """Добавляет key в `contracts:` фронтматтера case-context.md, не меняя остальные байты файла.

    Возвращает: "updated" | "already" | "missing" (нет файла, фронтматтера или закрывающего ---)
    | "manual" (форма `contracts` не разобрана безопасно, файл не тронут).
    Хвостовой комментарий у однострочного `contracts: [...]` при перезаписи строки теряется.
    """
    if not path.is_file():
        return "missing"
    dec = _decode(path.read_bytes())
    if dec is None:
        return "manual"
    text, enc = dec
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    if not lines or not _OPEN.match(lines[0].rstrip("\r\n")):
        return "missing"
    end = next((i for i in range(1, len(lines)) if _OPEN.match(lines[i].rstrip("\r\n"))), None)
    if end is None:
        return "missing"
    eol = "\r\n" if any(ln.endswith("\r\n") for ln in lines[:end + 1]) else "\n"
    idx = next((i for i in range(1, end) if _KEY.match(lines[i].rstrip("\r\n"))), None)

    if idx is None:
        lines.insert(end, f"contracts: [{_quote(key)}]{eol}")
    else:
        value = _KEY.match(lines[idx].rstrip("\r\n")).group(1)
        try:
            doc = yaml.safe_load("contracts:" + value) if value.strip() else {"contracts": None}
        except yaml.YAMLError:
            return "manual"
        parsed = doc.get("contracts") if isinstance(doc, dict) else None
        if not value.strip():
            j, last = idx + 1, None
            while j < end and _ITEM.match(lines[j].rstrip("\r\n")):
                last = j
                j += 1
            if j < end and lines[j].strip() and lines[j][0] in " \t":
                return "manual"
            if last is None:
                lines[idx] = f"contracts: [{_quote(key)}]{eol}"
            else:
                block = "contracts:\n" + "".join(ln.rstrip("\r\n") + "\n" for ln in lines[idx + 1:last + 1])
                try:
                    items = _scalars(yaml.safe_load(block)["contracts"])
                except (yaml.YAMLError, TypeError, KeyError):
                    return "manual"
                if items is None:
                    return "manual"
                if key in items:
                    return "already"
                indent = _ITEM.match(lines[last].rstrip("\r\n")).group(1)
                lines.insert(last + 1, f"{indent}- {_quote(key)}{eol}")
        elif parsed is None:  # `contracts: null` / `~`
            lines[idx] = f"contracts: [{_quote(key)}]{eol}"
        else:
            items = _scalars(parsed)
            if items is None or not value.lstrip().startswith("["):
                return "manual"
            if key in items:
                return "already"
            lines[idx] = "contracts: [" + ", ".join(_quote(x) for x in items + [key]) + "]" + eol
    try:
        data = "".join(lines).encode(enc)
    except UnicodeEncodeError:  # ключ не кодируется в кодировке файла (cp1251): юрист вносит вручную
        return "manual"
    _atomic_write(path, data)
    return "updated"


def link_task(root: Path, key: str, task_dir: Path) -> dict:
    task_dir = guard_task(Path(task_dir), root)
    entry = registry.find_entry(registry.load(root), key)
    if not entry:
        raise RegistryError(f"досье {key} в реестре нет")
    d = Path(root) / entry["folder"]
    # Сначала case-context (может бросить): при сбое links.yaml не меняется.
    # В contracts: пишется канонический ключ реестра, а не написание юриста или алиас.
    cc = _update_case_context(technical_path(task_dir, "case-context.md"), entry["key"])
    data = _load_links(d)
    if task_dir.name not in [t["task"] for t in data["tasks"]]:
        data["tasks"].append({"task": task_dir.name, "linked": dt.date.today().isoformat()})
        _dump(d / "links.yaml", data)
    return {"case_context": cc}


def add_draft(root: Path, key: str, *, task: str, file: str) -> None:
    task_dir = guard_task(Path(task), root)
    d = dossier_dir(root, key)
    data = _load_links(d)
    data["drafts"].append({"task": task_dir.name, "file": file, "added": dt.date.today().isoformat()})
    _dump(d / "links.yaml", data)


def add_conflict(root: Path, key: str, *, field: str, dossier_value: str, new_value: str, source: str) -> dict:
    d = dossier_dir(root, key)
    data = _load_links(d)
    k = {"id": next_id("K", data["conflicts"]), "field": field, "dossier_value": dossier_value,
         "new_value": new_value, "source": source, "status": "open", "added": dt.date.today().isoformat()}
    data["conflicts"].append(k)
    _dump(d / "links.yaml", data)
    return k
