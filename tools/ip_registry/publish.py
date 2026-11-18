"""Снимок реестра из журнала событий и атомарная публикация data/ + index/ + catalog.html."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

from .build_catalog import render_catalog
from .build_index import write_index
from .journal import dump_events, read_events, replay, validate_events

PUBLISHED = ("data", "index", "catalog.html")
EVENTS = "events.jsonl"
BASE = "base.json"
NO_PRODUCT_DOC = "Препарат не указан"
PENDING_OPEN = ("awaiting_facts", "needs_decision")
LOCK = ".journal.lock"
STALE_LOCK = 10 * 60  # секунд: блокировка старше считается брошенной упавшей командой
JOURNAL_CHANGED = "журнал изменился с момента чтения: повторите команду"
JOURNAL_BUSY = "журнал занят другой командой"


def _retry(action, attempts: int = 5, delay: float = 0.2) -> None:
    """Повтор при PermissionError: антивирус/индексатор Windows временно держат файлы и папки."""
    for attempt in range(attempts):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _remove(path: Path) -> None:
    def remove() -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    _retry(remove)


def _replace(src: Path, dst: Path) -> None:
    _retry(lambda: os.replace(src, dst))


def _publish(tmp: Path, root: Path) -> None:
    """Подменяет все три выхода как единое целое; при сбое возвращает прежнее состояние."""
    olds = {name: root / f".{name}.old" for name in PUBLISHED}
    for name, old in olds.items():  # восстановление после аварии посреди прошлой публикации
        target = root / name
        if old.exists() and not target.exists():
            _replace(old, target)
    for old in olds.values():
        _remove(old)
    moved: list[str] = []
    placed: list[str] = []
    try:
        for name in PUBLISHED:
            if (root / name).exists():
                _replace(root / name, olds[name])
                moved.append(name)
        for name in PUBLISHED:
            _replace(tmp / name, root / name)
            placed.append(name)
    except BaseException:
        # Каждый шаг отката отдельно: сбой одного не мешает вернуть остальные; наружу — исходная ошибка.
        steps = [(_remove, (root / name,)) for name in placed] +                 [(_replace, (olds[name], root / name)) for name in moved]
        for action, args in steps:
            try:
                action(*args)
            except Exception:  # noqa: BLE001 - откат продолжается, наружу уходит исходная ошибка
                pass
        raise
    for old in olds.values():
        try:
            _remove(old)
        except OSError:
            pass


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    index = 2
    while target.exists():
        target = folder / f"{Path(name).stem}-{index}{Path(name).suffix}"
        index += 1
    return target


def load_base(root: Path) -> dict | None:
    path = root / "data" / BASE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pending_cards(root: Path) -> tuple[list[dict], list[str]]:
    """Открытые карточки ожидания; битые файлы пропускаются и попадают в предупреждения."""
    folder = root / "pending"
    if not folder.exists():
        return [], []
    cards: list[dict] = []
    problems: list[str] = []
    for path in sorted(folder.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            card = None
        if not isinstance(card, dict):
            problems.append(f"pending/{path.name}: карточка не читается")
            continue
        if card.get("status") in PENDING_OPEN:
            cards.append({k: card.get(k) for k in ("doc_id", "document", "status", "reason", "received")})
    return cards, problems


def registry_view(marks: list[dict], events: list[dict], *, today: dt.date, root: Path | None = None,
                  warnings=()) -> dict:
    seed = next((e for e in events if e["kind"] == "seed"), None)
    changes = [e for e in events if e["kind"] != "seed"]
    seed_source = (seed or {}).get("source") or {}
    pending, pending_problems = _pending_cards(root) if root else ([], [])
    warnings = list(warnings) + pending_problems
    return {
        "schema_version": 2,
        "source": {"file": seed_source.get("file"), "sheet": "ТЗ", "exported": seed_source.get("doc_date"),
                   "built": today.isoformat(), "events": len(events),
                   "last_change": changes[-1]["at"][:10] if changes else None},
        "stats": {
            "marks": len(marks),
            "with_image": sum(1 for m in marks if m.get("image")),
            "warnings": len(warnings) + sum(len(m.get("warnings") or []) for m in marks),
            "verified": sum(1 for m in marks if m.get("verification")),
            "from_documents": sum(1 for m in marks
                                  if any(p.get("kind") == "document" for p in m.get("provenance", {}).values())),
            "no_product": sum(1 for m in marks if m.get("product") == NO_PRODUCT_DOC),
            "by_status": dict(Counter(m["status"] for m in marks)),
        },
        "warnings": warnings,
        "pending": pending,
        "marks": marks,
    }


def _acquire_lock(root: Path) -> Path:
    lock = root / LOCK
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_LOCK:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            raise ValueError(JOURNAL_BUSY) from None
    raise ValueError(JOURNAL_BUSY)


def _check_append_only(root: Path, events: list[dict]) -> None:
    """Записанный журнал должен быть началом публикуемого: события только дописываются.

    Сравниваются event_id и сами записи: две команды, прочитавшие журнал одновременно, дают событию
    один и тот же event_id, и только содержимое показывает, что вторая опоздала.
    """
    current = read_events(root / "data" / EVENTS)
    head = [json.loads(json.dumps(event, ensure_ascii=False)) for event in events[:len(current)]]
    if [e.get("event_id") for e in current] != [e.get("event_id") for e in head] or current != head:
        raise ValueError(JOURNAL_CHANGED)


def publish(root: Path, events: list[dict], *, today: dt.date, images: dict[str, bytes] | None = None,
            warnings=()) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(root)
    try:
        _check_append_only(root, events)
        return _publish_locked(root, events, today=today, images=images, warnings=warnings)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _publish_locked(root: Path, events: list[dict], *, today: dt.date, images: dict[str, bytes] | None,
                    warnings) -> dict:
    problems = validate_events(events)
    if problems:
        raise ValueError("журнал повреждён: " + "; ".join(problems))
    marks = replay(events)
    view = registry_view(marks, events, today=today, root=root, warnings=warnings)
    # Переносим только изображения, на которые ссылается текущая запись (поле image после replay).
    referenced = {m["image"] for m in marks if m.get("image")}
    blobs: dict[str, bytes] = {}
    marks_dir = root / "data" / "marks"
    if marks_dir.exists():
        for path in marks_dir.iterdir():
            if path.is_file() and f"marks/{path.name}" in referenced:
                blobs[f"marks/{path.name}"] = path.read_bytes()
    blobs.update({name: data for name, data in (images or {}).items() if name in referenced})
    tmp = root / ".build-tmp"
    _remove(tmp)
    try:
        (tmp / "data" / "marks").mkdir(parents=True)
        (tmp / "data" / EVENTS).write_text(dump_events(events), encoding="utf-8")
        (tmp / "data" / BASE).write_text(json.dumps(view, ensure_ascii=False, indent=1), encoding="utf-8")
        for name, data in blobs.items():
            (tmp / "data" / name).write_bytes(data)
        write_index(view, tmp / "index")
        (tmp / "catalog.html").write_text(render_catalog(view, blobs), encoding="utf-8")
        _publish(tmp, root)
    finally:
        _remove(tmp)
    return view
