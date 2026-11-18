"""Канал knowledge_ip: новая выгрузка реестра ТЗ → сборка каталога и индекса (класс A)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from tools.ip_registry.documents import DOC_EXTENSIONS, accept_document
from tools.ip_registry.pipeline import ingest_file
from tools.ip_registry.xlsx_reader import RegistryFormatError
from tools.pre_anonymize import watcher as legacy

from ..core import ChannelRun, safe_log, stable_files
from .knowledge import _logical_profile_ref


def _park(spec, runtime, source: Path, outcome: ChannelRun) -> Path:
    """Сбойную выгрузку переносим в failed/; ошибка переноса не останавливает канал.

    Возвращает каталог, который идёт в карточку очереди (не файл: имя может содержать данные).
    """
    outcome.failed += 1
    failed = spec.inbox / "failed"
    try:
        failed.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.move(str(source), str(legacy.unique_target(failed, source.name)))
    except OSError as exc:
        # Имя файла может содержать реальные данные: в логе только класс ошибки.
        safe_log(runtime, f"[{spec.key}] move_failed type={type(exc).__name__}")
        return spec.inbox
    return failed


def _safe_reason(exc: Exception) -> str | None:
    """Причина из сообщений нашего кода; текст сторонних библиотек отсекается по первому «:»."""
    if not isinstance(exc, RegistryFormatError):
        return None
    message = str(exc)
    if message.startswith("файл не читается"):
        return message.split(":", 1)[0]
    return message


def _handle_document(spec, runtime, queue, root: Path, source: Path, outcome: ChannelRun) -> None:
    card = accept_document(root, source, today=dt.date.today())
    if card["status"] == "duplicate":
        safe_log(runtime, f"[{spec.key}] document_duplicate")
        outcome.skipped += 1
        return
    queued = queue.enqueue(
        channel=spec.key,
        task_type="ip_document",
        task_ref=_logical_profile_ref(root / "pending" / f"{card['doc_id']}.json", runtime.profile_root),
        expose_policy=spec.expose_policy,
        metadata={"domain": "ip", "doc_status": card["status"], "ocr": card["ocr"]},
    )
    outcome.processed += 1
    outcome.queued += int(queued.created)


def _handle_excel(spec, runtime, queue, root: Path, source: Path, outcome: ChannelRun) -> None:
    result = ingest_file(root, source)
    reference = result.changes_path or result.registry_path
    queued = queue.enqueue(
        channel=spec.key,
        task_type="ip_reconcile_review" if result.mode == "reconcile" else "ip_registry_review",
        task_ref=_logical_profile_ref(reference, runtime.profile_root),
        expose_policy=spec.expose_policy,
        metadata={
            "domain": "ip",
            "marks": result.marks,
            "warnings": result.warnings,
            "new_products": len(result.new_products),
            **result.diff_counts,
        },
    )
    outcome.processed += 1
    outcome.queued += int(queued.created)


def handle(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    files, waiting = stable_files(spec.inbox, extensions={".xlsx"} | DOC_EXTENSIONS, wait=stable_wait)
    root = runtime.profile_root / "knowledge" / "ip"
    outcome = ChannelRun(waiting=waiting)
    for source in files:
        try:
            if source.suffix.lower() == ".xlsx":
                _handle_excel(spec, runtime, queue, root, source, outcome)
            else:
                _handle_document(spec, runtime, queue, root, source, outcome)
        except Exception as exc:  # noqa: BLE001 - сбой одного файла не останавливает канал
            # Имя файла и текст ошибки могут содержать реестр: в логе только класс исключения.
            safe_log(runtime, f"[{spec.key}] ingest_error type={type(exc).__name__}")
            folder = _park(spec, runtime, source, outcome)
            queue.enqueue(
                channel=spec.key,
                task_type="ip_registry_failed",
                task_ref=_logical_profile_ref(folder, runtime.profile_root),
                expose_policy=spec.expose_policy,
                metadata={"domain": "ip", "error": type(exc).__name__, "reason": _safe_reason(exc)},
            )
    return outcome
