from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def main_checkout_root(start: str | Path | None = None) -> Path:
    """Вернуть основной checkout, даже если команда запущена из worktree."""
    override = os.environ.get("LEGAL_COPILOT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    here = Path(start or Path.cwd()).resolve()
    try:
        common = subprocess.run(
            [
                "git",
                "-C",
                str(here),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        root = Path(common).resolve().parent
        if (root / "AGENTS.md").exists():
            return root
    except (OSError, subprocess.CalledProcessError):
        pass

    for candidate in (here, *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "tools").is_dir():
            return candidate
    raise RuntimeError("не найден корень legal-copilot")


def _profile_root(repo_root: Path) -> Path:
    pointer = repo_root / ".profile-path"
    if pointer.exists():
        for line in pointer.read_text(encoding="utf-8", errors="replace").splitlines():
            value = line.strip()
            if value:
                path = Path(value).expanduser()
                return (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    return repo_root / "profile"


@dataclass(frozen=True)
class RuntimePaths:
    repo_root: Path
    workflow_root: Path
    profile_root: Path
    state_root: Path
    queue_root: Path

    @classmethod
    def for_root(
        cls,
        root: str | Path,
        *,
        profile_root: str | Path | None = None,
    ) -> "RuntimePaths":
        repo = Path(root).resolve()
        profile = Path(profile_root).resolve() if profile_root else _profile_root(repo)
        state = repo / "workflow" / "_watcher"
        return cls(
            repo_root=repo,
            workflow_root=repo / "workflow",
            profile_root=profile,
            state_root=state,
            queue_root=state / "queue",
        )

    @classmethod
    def discover(cls, start: str | Path | None = None) -> "RuntimePaths":
        return cls.for_root(main_checkout_root(start))
