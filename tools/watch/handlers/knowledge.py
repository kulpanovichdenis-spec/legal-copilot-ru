from __future__ import annotations

from pathlib import Path

from tools.knowledge_ingest import intake as legacy

from ..core import ChannelRun, stable_files


def _logical_profile_ref(path: Path, profile_root: Path) -> str:
    try:
        return "profile/" + path.resolve().relative_to(profile_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _handle(spec, runtime, queue, *, domain: str, doc_type: str, stable_wait: float) -> ChannelRun:
    files, waiting = stable_files(spec.inbox, extensions=legacy.SUPPORTED, wait=stable_wait)
    domain_dir = runtime.profile_root / "knowledge" / domain
    stats = legacy.process_once(domain_dir, doc_type, verbose=False, files=files)
    queued = 0
    for card in stats.get("cards", []):
        result = queue.enqueue(
            channel=spec.key,
            task_type="knowledge_enrichment",
            task_ref=_logical_profile_ref(Path(card), runtime.profile_root),
            expose_policy=spec.expose_policy,
            metadata={"domain": domain},
        )
        queued += int(result.created)
    return ChannelRun(
        processed=int(stats.get("drafted", 0)),
        queued=queued,
        skipped=int(stats.get("skipped", 0)),
        waiting=waiting,
    )


def handle_products(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(
        spec,
        runtime,
        queue,
        domain="products",
        doc_type="product",
        stable_wait=stable_wait,
    )


def handle_corporate(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(
        spec,
        runtime,
        queue,
        domain="corporate",
        doc_type="corporate",
        stable_wait=stable_wait,
    )


def handle_compliance(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    return _handle(
        spec,
        runtime,
        queue,
        domain="compliance",
        doc_type="compliance_document",
        stable_wait=stable_wait,
    )
