from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from tools.case_intake import core as intake_core
from tools.case_intake.watcher import extract_text, move_aside

from ..core import ChannelRun, stable_files
from ..queue import atomic_json


def _identifiers(text: str) -> dict[str, list[str]]:
    digits = re.compile(r"(?<!\d)(?:\d[\s-]?){10,15}(?!\d)")
    found = {"inn": [], "ogrn": [], "ogrnip": []}
    for match in digits.finditer(text):
        value = re.sub(r"\D", "", match.group(0))
        if len(value) in {10, 12} and value not in found["inn"]:
            found["inn"].append(value)
        elif len(value) == 13 and value not in found["ogrn"]:
            found["ogrn"].append(value)
        elif len(value) == 15 and value not in found["ogrnip"]:
            found["ogrnip"].append(value)
    return found


def handle(spec, runtime, queue, *, stable_wait: float = 1.0) -> ChannelRun:
    files, waiting = stable_files(spec.inbox, extensions=intake_core.SUPPORTED, wait=stable_wait)
    processed = spec.inbox / "processed"
    failed = spec.inbox / "failed"
    cards = spec.inbox / "queue"
    for folder in (processed, failed, cards):
        folder.mkdir(parents=True, exist_ok=True)
    outcome = ChannelRun(waiting=waiting)
    for source in files:
        try:
            text, metadata = extract_text(source)
        except RuntimeError:
            move_aside(source, failed, "Локальная ингестия не удалась.")
            outcome.failed += 1
            continue
        moved = move_aside(source, processed)
        card_path = cards / f"{moved.stem}.json"
        card = {
            "schema_version": 1,
            "status": "pending",
            "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source_file": moved.name,
            "processed_path": moved.relative_to(runtime.repo_root).as_posix(),
            "ingest_backend": metadata.get("backend"),
            "identifiers": _identifiers(text),
            "text_head": text[:6000],
            "text_truncated": len(text) > 6000,
            "next_skill": "counterparty-verification",
        }
        atomic_json(card_path, card)
        queued = queue.enqueue(
            channel=spec.key,
            task_type="counterparty_verification",
            task_ref=card_path,
            expose_policy=spec.expose_policy,
        )
        outcome.processed += 1
        outcome.queued += int(queued.created)
    return outcome
