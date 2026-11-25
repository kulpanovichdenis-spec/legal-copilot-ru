"""Временный ключ → наш номер. Старый ключ остаётся алиасом, ссылки задач не рвутся."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import yaml

from . import registry
from .card import set_fm_field
from .keys import folder_name, number_key
from .paths import RegistryError, guard

RETRIES, PAUSE = 3, 0.2
_MATTER = re.compile(rb"^matter:[^\r\n]*", re.M)


def _move(src: Path, dst: Path) -> None:
    """Переименование папки с повтором: на Windows открытый в Word файл досье держит папку."""
    for attempt in range(RETRIES):
        try:
            os.rename(src, dst)
            return
        except OSError:
            if attempt == RETRIES - 1:
                raise RegistryError("не удалось переименовать папку досье: закройте файлы досье и повторите")
            time.sleep(PAUSE)


def _set_timeline_matter(path: Path, new_key: str) -> None:
    """Строка `matter:` хронологии; если после правки YAML не сходится, файл возвращается как был."""
    if not path.is_file():
        return
    raw = path.read_bytes()
    m = _MATTER.search(raw)
    if m is None:
        return
    new = raw[:m.start()] + b"matter: " + json.dumps(new_key, ensure_ascii=False).encode("utf-8") + raw[m.end():]
    try:
        ok = (yaml.safe_load(new.decode("utf-8")) or {}).get("matter") == new_key
    except (yaml.YAMLError, UnicodeDecodeError, AttributeError):
        ok = False
    if ok:
        from .links import _atomic_write  # noqa: PLC0415
        _atomic_write(path, new)


def rename_key(root: Path, old: str, new_key: str) -> Path:
    root = guard(Path(root))
    if not str(new_key or "").strip() or not number_key(new_key):
        raise RegistryError("пустой новый ключ: укажите номер договора")
    data = registry.load(root)
    entry = registry.find_entry(data, old)
    if not entry:
        raise RegistryError(f"досье {old} в реестре нет")
    other = registry.find_entry(data, new_key)
    if other and other is not entry:
        raise RegistryError(f"ключ {new_key} уже занят досье {other['folder']}")
    old_dir, new_folder = root / entry["folder"], folder_name(new_key, entry["counterparty"])
    new_dir = root / new_folder
    if new_dir.exists():
        raise RegistryError(f"папка {new_folder} уже существует")
    _move(old_dir, new_dir)
    if entry["key"] not in entry["aliases"]:
        entry["aliases"].append(entry["key"])
    entry.update({"key": new_key, "folder": new_folder, "temporary_key": False})
    try:
        registry.save(root, data)
    except Exception as exc:
        try:
            _move(new_dir, old_dir)
        except RegistryError:
            raise RegistryError(f"реестр не сохранён ({exc}), папка досье осталась {new_folder}: "
                                f"верните имя {old_dir.name} вручную") from exc
        raise RegistryError(f"реестр не сохранён, переименование отменено: {exc}") from exc
    # Карточка и хронология: только строки ключа, остальные байты не трогаются (FNM-CD-06).
    q = json.dumps(new_key, ensure_ascii=False)
    card = new_dir / "contract-card.md"
    if card.is_file():
        set_fm_field(card, "key", q)
        set_fm_field(card, "number", q)
    _set_timeline_matter(new_dir / "matter-timeline.yaml", new_key)
    return new_dir
