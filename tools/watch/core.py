from __future__ import annotations

import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .paths import RuntimePaths
from .queue import QueueStore


@dataclass
class ChannelRun:
    processed: int = 0
    queued: int = 0
    failed: int = 0
    skipped: int = 0
    waiting: int = 0


@dataclass
class RunReport:
    channels: dict[str, ChannelRun] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return sum(item.failed for item in self.channels.values())


class DaemonLock:
    """Межпроцессная блокировка; файл остаётся, lock снимается ОС при падении."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "DaemonLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("единый watcher уже запущен") from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(
            json.dumps(
                {"pid": os.getpid(), "started_at": dt.datetime.now().isoformat()}
            ).encode("utf-8")
        )
        self.handle.flush()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def safe_log(runtime: RuntimePaths, message: str) -> None:
    runtime.state_root.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {message}"
    print(line)
    try:
        with (runtime.state_root / "watcher.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def stable_files(
    inbox: Path,
    *,
    extensions: set[str],
    wait: float,
) -> tuple[list[Path], int]:
    """Вернуть стабильные обычные файлы; имена наружу не логируются."""
    if not inbox.exists():
        return [], 0
    candidates: list[tuple[Path, int]] = []
    waiting = 0
    for path in sorted(inbox.iterdir()):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if (
            path.name == ".gitkeep"
            or lower.startswith((".", "~$"))
            or lower.endswith((".tmp", ".crdownload", ".part", ".download"))
            or path.suffix.lower() not in extensions
        ):
            continue
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                stream.read(1)
        except OSError:
            waiting += 1
            continue
        if size <= 0:
            waiting += 1
            continue
        candidates.append((path, size))
    if candidates and wait > 0:
        time.sleep(wait)
    ready: list[Path] = []
    for path, first_size in candidates:
        try:
            if path.stat().st_size == first_size:
                ready.append(path)
            else:
                waiting += 1
        except OSError:
            waiting += 1
    return ready, waiting


def run_once(
    specs: Iterable,
    *,
    runtime: RuntimePaths,
    queue: QueueStore,
    stable_wait: float = 1.0,
) -> RunReport:
    report = RunReport()
    for spec in specs:
        try:
            outcome = spec.handler(spec, runtime, queue, stable_wait=stable_wait)
            if not isinstance(outcome, ChannelRun):
                raise TypeError("handler должен вернуть ChannelRun")
            report.channels[spec.key] = outcome
            safe_log(
                runtime,
                f"[{spec.key}] processed={outcome.processed} queued={outcome.queued} "
                f"failed={outcome.failed} waiting={outcome.waiting}",
            )
        except Exception as exc:  # noqa: BLE001 - изоляция каналов является инвариантом
            report.channels[spec.key] = ChannelRun(failed=1)
            safe_log(runtime, f"[{spec.key}] handler_error={type(exc).__name__}")
    return report


def run_daemon(
    specs: Iterable,
    *,
    runtime: RuntimePaths,
    queue: QueueStore,
    interval: float,
) -> None:
    runtime.state_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime.state_root / "daemon.lock"
    with DaemonLock(lock_path):
        safe_log(runtime, f"daemon_start pid={os.getpid()} interval={interval:g}s")
        try:
            while True:
                run_once(specs, runtime=runtime, queue=queue)
                time.sleep(interval)
        except KeyboardInterrupt:
            safe_log(runtime, "daemon_stop")
