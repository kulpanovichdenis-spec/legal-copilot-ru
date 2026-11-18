"""Persistent budget run. JSON is written atomically and is not an accounting ledger."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from lb_local import load

_model = load("model")
GOALS = _model.GOALS
BudgetError = _model.BudgetError

STATE_FILES = (
    "budget_context.json",
    "budget_state.json",
    "assumptions.json",
    "open_issues.json",
    "source_manifest.json",
    "calculation_log.json",
    "decisions.json",
    "view_model.json",
)


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a unique temp file in the same directory. Retry only PermissionError."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        delay = 0.05
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 2
    finally:
        if tmp.exists():
            tmp.unlink()


def save_json(path: Path, data) -> None:
    atomic_write_text(Path(path), json.dumps(data, ensure_ascii=False, indent=2))


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def init_run(folder: Path, run_id: str, goal: str) -> None:
    if goal not in GOALS:
        raise BudgetError(f"goal должен быть одним из {GOALS}")
    folder = Path(folder)
    for name in ("input", "working", "state", "output"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    context = {
        "run_id": run_id,
        "budget_period": {"start": "", "end": ""},
        "reporting_currency": "",
        "goal": goal,
        "materiality_threshold": None,
        "industry": "",
        "related_ops_project": "",
    }
    state = {
        "run_id": run_id,
        "goal": goal,
        "lines": [],
        "actuals": [],
        "accruals": [],
        "history": [],
        "allocations": [],
        "headcount_change": None,
        "external_spend_change": None,
        "workload_transfer": None,
        "stages": {},
        "quality_gate": "not_ready",
    }
    payloads = {
        "budget_context.json": context,
        "budget_state.json": state,
        "assumptions.json": [],
        "open_issues.json": [],
        "source_manifest.json": [],
        "calculation_log.json": [],
        "decisions.json": [],
        "view_model.json": {},
    }
    for name, payload in payloads.items():
        target = folder / "state" / name
        if not target.exists():
            save_json(target, payload)


def append_log(folder: Path, entry: dict) -> None:
    path = Path(folder) / "state" / "calculation_log.json"
    current = load_json(path) if path.exists() else []
    current.append(entry)
    save_json(path, current)
