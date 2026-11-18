from __future__ import annotations

import shutil
from pathlib import Path

from tools.pre_anonymize.watcher import SUPPORTED
from tools.sample_intake.intake import IntakeError, promote

from ..core import ChannelRun, stable_files


def _unique(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.exists():
        return target
    index = 2
    while True:
        candidate = folder / f"{Path(name).stem} ({index}){Path(name).suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _handle(spec, runtime, queue, *, kind: str, stable_wait: float) -> ChannelRun:
    files, waiting = stable_files(spec.inbox, extensions=SUPPORTED, wait=stable_wait)
    staging = runtime.state_root / "staging" / kind
    failed = runtime.state_root / "failed" / spec.key
    outcome = ChannelRun(waiting=waiting)
    for source in files:
        staged = _unique(staging, source.name)
        shutil.move(str(source), str(staged))
        try:
            result = promote(
                staged,
                kind=kind,
                workflow_root=runtime.workflow_root,
                samples_root=runtime.profile_root / "knowledge" / "document-samples",
            )
        except (IntakeError, OSError):
            shutil.move(str(staged), str(_unique(failed, staged.name)))
            outcome.failed += 1
            continue
        task_type = "clause_candidate" if kind == "clause" else "sample_candidate"
        queued = queue.enqueue(
            channel=spec.key,
            task_type=task_type,
            task_ref=result["anon_source"],
            expose_policy=spec.expose_policy,
            metadata={
                "kind": kind,
                "category": result.get("category"),
                "ambiguous": bool(result.get("ambiguous")),
                "card_path_hint": result.get("card_path_hint"),
                "anon_quality": {
                    k: (result.get("quality") or {}).get(k)
                    for k in ("verdict", "leaks", "false_positives")
                },
            },
        )
        outcome.processed += 1
        outcome.queued += int(queued.created)
    return outcome


def handle_clause(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(spec, runtime, queue, kind="clause", stable_wait=stable_wait)


def handle_sample(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(spec, runtime, queue, kind="sample", stable_wait=stable_wait)
