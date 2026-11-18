from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnqueueResult:
    task_id: str
    path: Path
    created: bool


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass


class QueueStore:
    """Мета-очередь: ссылки и статусы, без текста документов и mapping."""

    def __init__(self, root: str | Path, *, repo_root: str | Path) -> None:
        self.root = Path(root)
        self.repo_root = Path(repo_root).resolve()

    def _ref(self, value: str | Path) -> str:
        path = Path(value)
        if path.is_absolute():
            try:
                return path.resolve().relative_to(self.repo_root).as_posix()
            except ValueError:
                return str(path.resolve())
        return path.as_posix()

    @staticmethod
    def _id(channel: str, task_type: str, task_ref: str) -> str:
        raw = f"{channel}\0{task_type}\0{task_ref}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def enqueue(
        self,
        *,
        channel: str,
        task_type: str,
        task_ref: str | Path,
        expose_policy: str,
        metadata: dict | None = None,
    ) -> EnqueueResult:
        ref = self._ref(task_ref)
        task_id = self._id(channel, task_type, ref)
        target = self.root / f"{task_id}.json"
        lock = self.root / f".{task_id}.lock"
        self.root.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return EnqueueResult(task_id, target, False)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return EnqueueResult(task_id, target, False)
        os.close(descriptor)
        try:
            if target.exists():
                return EnqueueResult(task_id, target, False)
            card = {
                "schema_version": 1,
                "task_id": task_id,
                "status": "pending",
                "channel": channel,
                "task_type": task_type,
                "task_ref": ref,
                "expose_policy": expose_policy,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "metadata": metadata or {},
            }
            atomic_json(target, card)
            return EnqueueResult(task_id, target, True)
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

    def cards(self, *, status: str | None = None) -> list[dict]:
        if not self.root.exists():
            return []
        out: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status is None or data.get("status") == status:
                data["_path"] = str(path)
                out.append(data)
        return out

    def set_status(self, task_id: str, status: str, *, note: str | None = None) -> dict:
        if status not in {"pending", "in_progress", "completed", "blocked", "failed"}:
            raise ValueError(f"неподдерживаемый статус: {status}")
        path = self.root / f"{task_id}.json"
        if not path.exists():
            raise FileNotFoundError(task_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        if note:
            data["note"] = note
        atomic_json(path, data)
        return data

    def session_summary(self) -> str:
        pending = self.cards(status="pending")
        if not pending:
            return ""
        counts: dict[str, int] = {}
        for card in pending:
            channel = str(card.get("channel") or "unknown")
            counts[channel] = counts.get(channel, 0) + 1
        parts = ", ".join(f"{key}: {counts[key]}" for key in sorted(counts))
        return (
            f"Единая очередь входящих: {len(pending)} pending ({parts}). "
            "Сводка не содержит имён и текста документов. Для просмотра карточек: "
            "python -m tools.watch.queue_cli list. DD dataroom в эту очередь не входит."
        )
