"""Project folder state for legal-ops-assistant. Atomic YAML, no hand edits by the model."""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMA_VERSION = 1
PHASES = ("align", "discover", "redesign", "design", "justify", "implement")
TRACKS = ("transformation", "ai_evaluation")
DECISION_STATUSES = ("confirmed", "revised", "withdrawn")
HUMAN_CONTROLS = ("L0", "L1", "L2", "L3", "L4", "L5")
CLAIM_MARKERS = ("VENDOR CLAIM", "ROADMAP")
STATE_NAME = "project_state.yaml"
DIRS = ("evidence", "artifacts", "processes", "pilots", "outputs")

CARD_KEYS = (
    "process",
    "business_goal",
    "owner",
    "customers",
    "trigger",
    "inputs",
    "outputs",
    "volume",
    "cycle_time",
    "work_time",
    "wait_time",
    "roles",
    "systems",
    "data_sources",
    "knowledge_sources",
    "as_is_steps",
    "pain_points",
    "handoffs",
    "rework",
    "approvals",
    "baseline_metrics",
    "open_questions",
)
METRIC_KEYS = ("volume", "cycle_time", "work_time", "wait_time")
UNKNOWN = "UNKNOWN"


class StateError(Exception):
    pass


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    where: str
    message: str


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


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


def empty_state(project_name: str) -> dict:
    today = dt.date.today().isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": project_name,
        "objective": "",
        "current_phase": "align",
        "track": "transformation",
        "completed": [],
        "active_processes": [],
        "facts": [],
        "assumptions": [],
        "open_questions": [],
        "decisions": [],
        "next_actions": [],
        "blocked_by": [],
        "artifact_refs": [],
        "related_budget_run": "",
        "last_updated": today,
    }


def init_project(folder: Path, project_name: str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in DIRS:
        (folder / name).mkdir(exist_ok=True)
    decisions = folder / "decisions.md"
    if not decisions.exists():
        decisions.write_text(
            "# Журнал решений\n\n"
            "Сюда попадают только решения, подтверждённые пользователем. "
            "Рекомендация сама по себе решением не становится.\n",
            encoding="utf-8",
        )
    target = folder / STATE_NAME
    if not target.exists():
        save_state(folder, empty_state(project_name))
    return target


def load_state(folder: Path) -> dict:
    path = Path(folder) / STATE_NAME
    if not path.exists():
        raise StateError(f"нет {STATE_NAME} в {folder} (сначала init)")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StateError(f"{path} не является картой состояния")
    return data


def validate_state_dict(folder: Path, state: dict) -> list[Issue]:
    issues: list[Issue] = []
    phase = state.get("current_phase")
    if not isinstance(phase, str) or not phase.strip():
        issues.append(Issue("error", "empty_phase", "current_phase", "фаза пустая"))
    elif phase not in PHASES:
        issues.append(Issue("error", "bad_phase", "current_phase", f"неизвестная фаза: {phase}"))
    track = state.get("track")
    if track not in TRACKS:
        issues.append(Issue("error", "bad_track", "track", f"неизвестный track: {track}"))
    for index, ref in enumerate(state.get("artifact_refs") or []):
        if not isinstance(ref, str) or not (Path(folder) / ref).exists():
            issues.append(
                Issue("error", "missing_artifact", f"artifact_refs[{index}]", f"нет файла: {ref}")
            )
    for index, item in enumerate(state.get("decisions") or []):
        if not isinstance(item, dict) or not str(item.get("date") or "").strip():
            issues.append(
                Issue("error", "decision_without_date", f"decisions[{index}]", "у решения нет даты")
            )
    return issues


def _decision_ids_in_journal(folder: Path) -> list[str]:
    path = Path(folder) / "decisions.md"
    if not path.exists():
        return []
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## DEC-"):
            ids.append(line[3:].strip())
    return ids


def validate_project(folder: Path) -> list[Issue]:
    folder = Path(folder)
    state = load_state(folder)
    issues = validate_state_dict(folder, state)
    journal = _decision_ids_in_journal(folder)
    stored = [str(item.get("id")) for item in (state.get("decisions") or []) if isinstance(item, dict)]
    if journal != stored:
        issues.append(
            Issue(
                "error",
                "decision_journal_mismatch",
                "decisions.md",
                "DEC в decisions.md не совпадают с project_state.yaml",
            )
        )
    return issues


def save_state(folder: Path, state: dict) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["last_updated"] = dt.date.today().isoformat()
    errors = [item for item in validate_state_dict(folder, state) if item.level == "error"]
    if errors:
        raise StateError("; ".join(f"{item.code}: {item.message}" for item in errors))
    atomic_write_text(folder / STATE_NAME, _dump(state))


def _iso_date(value: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise StateError(f"дата должна быть ISO YYYY-MM-DD: {value}") from exc


def record_decision(folder: Path, text_fields: dict) -> str:
    date = _iso_date(str(text_fields.get("date") or "").strip())
    title = str(text_fields.get("decision") or "").strip()
    status = str(text_fields.get("status") or "confirmed").strip()
    if not title:
        raise StateError("decision требует непустые date и decision")
    if status not in DECISION_STATUSES:
        raise StateError(f"status должен быть одним из {DECISION_STATUSES}")
    text_fields = dict(text_fields)
    text_fields["date"] = date
    text_fields["status"] = status
    state = load_state(folder)
    number = len(state.get("decisions") or []) + 1
    decision_id = f"DEC-{number:03d}"
    state.setdefault("decisions", []).append(
        {"id": decision_id, "date": date, "title": title, "status": status}
    )
    save_state(folder, state)
    labels = (
        ("Decision", "decision"),
        ("Date", "date"),
        ("Owner", "owner"),
        ("Status", "status"),
        ("Problem", "problem"),
        ("Evidence", "evidence"),
        ("Assumptions", "assumptions"),
        ("Alternatives considered", "alternatives"),
        ("Selected option", "selected"),
        ("Why", "why"),
        ("Risks", "risks"),
        ("Controls", "controls"),
        ("Reconsideration trigger", "reconsideration_trigger"),
    )
    lines = [f"\n## {decision_id}\n"]
    for label, key in labels:
        value = str(text_fields.get(key) or "").strip() or "—"
        lines.append(f"- {label}: {value}")
    lines.append("")
    path = Path(folder) / "decisions.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Журнал решений\n"
    atomic_write_text(path, existing.rstrip() + "\n" + "\n".join(lines))
    return decision_id


def _phase_allowed(state: dict, phase: str) -> None:
    if phase not in PHASES:
        raise StateError(f"bad_phase: неизвестная фаза: {phase}")
    current = state.get("current_phase")
    if phase == current or phase in (state.get("completed") or []):
        return
    if current in PHASES and PHASES.index(phase) == PHASES.index(current) + 1:
        return
    raise StateError("phase_jump: переход только на следующую фазу или на уже закрытую")


def _budget_run_folder(value: str) -> None:
    folder = Path(value)
    if not (folder / "state" / "budget_context.json").is_file():
        raise StateError("related_budget_run должен быть папкой запуска с state/budget_context.json")


def update_state(
    folder: Path,
    *,
    phase: str | None = None,
    track: str | None = None,
    objective: str | None = None,
    fact: str | None = None,
    assumption: str | None = None,
    question: str | None = None,
    related_budget_run: str | None = None,
    artifact_ref: str | None = None,
    completed: str | None = None,
    active_process: str | None = None,
    next_action: str | None = None,
    blocked_by: str | None = None,
    human_control: str | None = None,
    decision_id: str | None = None,
) -> dict:
    folder = Path(folder)
    state = load_state(folder)
    if fact:
        upper = fact.upper()
        if any(marker in upper for marker in CLAIM_MARKERS):
            raise StateError("VENDOR CLAIM и ROADMAP не факт: запишите допущение или открытый вопрос")
    if related_budget_run is not None:
        _budget_run_folder(related_budget_run)
    if phase is not None:
        _phase_allowed(state, phase)
        state["current_phase"] = phase
    if completed is not None:
        if completed not in PHASES:
            raise StateError(f"bad_phase: неизвестная фаза: {completed}")
        done = list(state.get("completed") or [])
        if completed not in done:
            done.append(completed)
        state["completed"] = done
    if artifact_ref is not None:
        if not (folder / artifact_ref).exists():
            raise StateError(f"missing_artifact: нет файла: {artifact_ref}")
        refs = list(state.get("artifact_refs") or [])
        if artifact_ref not in refs:
            refs.append(artifact_ref)
        state["artifact_refs"] = refs
    if active_process:
        items = list(state.get("active_processes") or [])
        items.append(active_process)
        state["active_processes"] = items
    if next_action:
        items = list(state.get("next_actions") or [])
        items.append(next_action)
        state["next_actions"] = items
    if blocked_by:
        items = list(state.get("blocked_by") or [])
        items.append(blocked_by)
        state["blocked_by"] = items
    if human_control is not None:
        if human_control not in HUMAN_CONTROLS:
            raise StateError(f"human_control должен быть одним из {HUMAN_CONTROLS}")
        if human_control in {"L4", "L5"}:
            known = {item.get("id") for item in (state.get("decisions") or []) if isinstance(item, dict)}
            if not decision_id or decision_id not in known:
                raise StateError("L4 и L5 только вместе с уже записанным DEC")
        state["human_control"] = human_control
        if decision_id:
            state["human_control_decision"] = decision_id
    if track is not None:
        state["track"] = track
    if objective is not None:
        state["objective"] = objective
    if fact:
        state.setdefault("facts", []).append(fact)
    if assumption:
        state.setdefault("assumptions", []).append(assumption)
    if question:
        state.setdefault("open_questions", []).append(question)
    if related_budget_run is not None:
        state["related_budget_run"] = related_budget_run
    save_state(folder, state)
    return state



def validate_process_card(card: dict) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(card, dict):
        return [Issue("error", "not_a_card", "process_card", "карточка не является картой")]
    for key in CARD_KEYS:
        if key not in card:
            issues.append(Issue("error", "missing_field", key, "обязательное поле отсутствует"))
    trigger = card.get("trigger")
    if "trigger" in card and (not isinstance(trigger, str) or not trigger.strip()):
        issues.append(Issue("error", "empty_trigger", "trigger", "trigger пустой"))
    for key in METRIC_KEYS:
        if key not in card:
            continue
        value = card[key]
        if value == UNKNOWN:
            continue
        if isinstance(value, bool) or value is None:
            issues.append(Issue("error", "bad_metric", key, "нужно число или UNKNOWN"))
        elif isinstance(value, str):
            if not value.strip():
                issues.append(Issue("error", "empty_metric", key, "пустая метрика; поставьте число или UNKNOWN"))
            else:
                try:
                    float(value.replace(",", "."))
                except ValueError:
                    issues.append(Issue("error", "bad_metric", key, "нужно число или UNKNOWN"))
        elif not isinstance(value, (int, float)):
            issues.append(Issue("error", "bad_metric", key, "нужно число или UNKNOWN"))
    return issues
