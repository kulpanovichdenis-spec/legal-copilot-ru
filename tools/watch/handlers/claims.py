from __future__ import annotations

from pathlib import Path

from tools.case_intake import watcher as legacy

from ..core import ChannelRun


def handle(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    stats = legacy.process_once(
        spec.inbox,
        verbose=False,
        stable_wait=stable_wait,
        workflow_root=runtime.workflow_root,
        repo_root=runtime.repo_root,
    )
    queued = 0
    for card in stats.get("cards", []):
        result = queue.enqueue(
            channel=spec.key,
            task_type="document_intake",
            task_ref=Path(card),
            expose_policy=spec.expose_policy,
        )
        queued += int(result.created)
    return ChannelRun(
        processed=int(stats.get("queued", 0)),
        queued=queued,
        failed=int(stats.get("failed", 0)),
        skipped=int(stats.get("unsorted", 0)) + int(stats.get("notified", 0)),
        waiting=int(stats.get("waiting", 0)),
    )
