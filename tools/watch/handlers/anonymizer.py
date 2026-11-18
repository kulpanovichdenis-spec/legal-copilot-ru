from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from tools.pre_anonymize import project as projects
from tools.pre_anonymize import watcher as legacy

from ..core import ChannelRun, safe_log, stable_files


def _unsupported(folder: Path, stable_wait: float) -> list[Path]:
    """Стабильные файлы неподдерживаемых форматов: их нельзя оставлять лежать молча."""
    if not folder.is_dir():
        return []
    exts = {p.suffix.lower() for p in folder.iterdir() if p.is_file()} - legacy.SUPPORTED
    if not exts:
        return []
    files, _waiting = stable_files(folder, extensions=exts, wait=stable_wait)
    # watcher.log — старый лог в корне _inbox; рабочие файлы агента в проекте не трогаем.
    return [p for p in files
            if p.name.lower() != "watcher.log" and not projects.is_agent_file(p.name)]


def _ext(path: Path) -> str:
    return path.suffix.lower() or "(нет)"


def _handle(spec, runtime, _queue, *, profile: str, stable_wait: float) -> ChannelRun:
    files, waiting = stable_files(spec.inbox, extensions=legacy.SUPPORTED, wait=stable_wait)
    ready = runtime.workflow_root / "_anonymizer" / "_ready"
    originals = runtime.workflow_root / "_anonymizer" / "_inbox" / "originals"
    failed = runtime.workflow_root / "_anonymizer" / "_inbox" / "failed"
    outcome = ChannelRun(waiting=waiting)
    for path in _unsupported(spec.inbox, stable_wait):
        try:
            failed.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(legacy.unique_target(failed, path.name)))
        except OSError:
            outcome.waiting += 1
            continue
        outcome.failed += 1
        # Имя файла может содержать реальные данные: в логе только расширение.
        safe_log(runtime, f"[{spec.key}] unsupported ext={_ext(path)} -> failed")
    for path in files:
        status = legacy.process_file(
            path,
            profile,
            ready_dir=ready,
            originals_dir=originals,
            failed_dir=failed,
            stable_wait=0,
            log_path=None,
        )
        if status == "processed":
            outcome.processed += 1
        elif status == "failed":
            outcome.failed += 1
            safe_log(runtime, f"[{spec.key}] failed ext={_ext(path)} -> failed")
        else:
            outcome.waiting += 1
    return outcome


def handle_full(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(spec, runtime, queue, profile="full", stable_wait=stable_wait)


def handle_analytic(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(spec, runtime, queue, profile="analytic", stable_wait=stable_wait)


def handle_projects(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    """workflow/_anonymizer/<проект>/: оригиналы → .anon.md, черновики → готово/."""
    outcome = ChannelRun()
    for project in projects.find_projects(spec.inbox):
        try:
            _run_project(spec, runtime, queue, project, outcome, stable_wait)
        except Exception as exc:  # noqa: BLE001 - ошибка одного проекта не останавливает остальные
            outcome.failed += 1
            safe_log(runtime, f"[{spec.key}] project_error stage=project type={type(exc).__name__}")
    return outcome


def _short_hash(path: Path) -> str:
    try:
        return projects.file_hash(path)[:8]
    except OSError:
        return dt.datetime.now().strftime("%Y%m%d%H%M%S")


def _maybe_needs_restore(project: Path, draft: Path) -> bool:
    """Сбой проверки одного черновика не прерывает стадию: он идёт в per-file try
    восстановления и даёт собственную карточку project_error."""
    try:
        return projects.needs_restore(project, draft)
    except Exception:  # noqa: BLE001
        return True


def _run_project(spec, runtime, queue, project: Path, outcome: ChannelRun,
                 stable_wait: float) -> None:
    projects.ensure_layout(project)
    for folder, profile in ((project, "full"), (project / projects.ANALYTIC, "analytic")):
        for path in _unsupported(folder, stable_wait):
            document = projects.reject_unsupported(project, path)
            if document is None:
                outcome.waiting += 1
                continue
            outcome.failed += 1
            safe_log(runtime, f"[{spec.key}] unsupported ext={_ext(path)} -> not_processed")
            _warn(spec, queue, outcome, project, "not_processed",
                  project / projects.SERVICE / projects.NOT_PROCESSED / document,
                  {"document": document, "reason": "unsupported_format", "ext": _ext(path)})
        if not projects.pending_originals(folder):
            continue
        files, waiting = stable_files(folder, extensions=legacy.SUPPORTED, wait=stable_wait)
        outcome.waiting += waiting
        for path in files:
            if projects.is_agent_file(path.name):
                continue
            try:
                result = projects.process_original(project, path, profile)
            except Exception as exc:  # noqa: BLE001 - один битый файл не блокирует проект
                outcome.failed += 1
                safe_log(runtime,
                         f"[{spec.key}] project_error stage=original type={type(exc).__name__}")
                # Имя файла может содержать реальные данные: в карточке его нет.
                _warn(spec, queue, outcome, project, "project_error",
                      project / projects.SERVICE / f"ошибка-оригинала#{_short_hash(path)}",
                      {"stage": "original", "error": type(exc).__name__})
                continue
            if result["status"] == "processed":
                outcome.processed += 1
                if result["verdict"] == "needs_review":
                    _warn(spec, queue, outcome, project, "quality_review",
                          project / result["anon"], {"document": result["document"]})
            elif result["status"] == "misplaced_draft":
                outcome.skipped += 1
            elif result["status"] == "waiting":
                outcome.waiting += 1
            else:
                outcome.failed += 1
                _warn(spec, queue, outcome, project, "not_processed",
                      project / projects.SERVICE / projects.NOT_PROCESSED / result["document"],
                      {"document": result["document"]})

    drafts = project / projects.DRAFTS
    pending = [d for d in drafts.glob("*.docx")
               if not d.name.startswith(("~$", ".")) and _maybe_needs_restore(project, d)]
    if not pending:
        return
    stable, waiting = stable_files(drafts, extensions={".docx"}, wait=stable_wait)
    outcome.waiting += waiting
    for draft in stable:
        if draft not in pending:
            continue
        try:
            result = projects.restore_draft(project, draft)
        except Exception as exc:  # noqa: BLE001 - один битый черновик не блокирует остальные
            outcome.failed += 1
            safe_log(runtime, f"[{spec.key}] project_error stage=draft type={type(exc).__name__}")
            _warn(spec, queue, outcome, project, "project_error",
                  drafts / f"{draft.name}#{_short_hash(draft)}",
                  {"stage": "draft", "draft": draft.name, "error": type(exc).__name__})
            continue
        if result["status"] == "waiting":
            outcome.waiting += 1
            continue
        outcome.processed += 1
        if result["leftovers"]:
            # В карточку идёт только имя черновика (с метками) и хэш; в готово/ имена
            # тоже с метками, но карточка ссылается на черновик.
            _warn(spec, queue, outcome, project, "restore_leftovers",
                  drafts / f"{draft.name}#{projects.file_hash(draft)[:8]}",
                  {"draft": draft.name, "leftovers": result["leftovers"]})


def _warn(spec, queue, outcome: ChannelRun, project: Path, task_type: str,
          ref: Path, extra: dict) -> None:
    created = queue.enqueue(
        channel=spec.key,
        task_type=task_type,
        task_ref=ref,
        expose_policy=spec.expose_policy,
        metadata={"project": project.name,
                  "noticed_at": dt.datetime.now().isoformat(timespec="seconds"), **extra},
    ).created
    if created:
        outcome.queued += 1
