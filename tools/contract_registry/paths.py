"""Корень реестра и запрет на проекты анонимайзера."""
from __future__ import annotations

import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]


class RegistryError(Exception):
    """Ошибка работы с реестром договоров."""


class ForbiddenPath(RegistryError):
    """Путь внутри workflow/_anonymizer: досье там не создаётся и не читается."""


def _main_checkout() -> Path:
    """Корень основного чекаута, в т. ч. при запуске из git worktree (как case_folder._default_base
    в tools/counterparty_verification): родитель `--git-common-dir`. Любой сбой: корень этого пакета."""
    try:
        out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             cwd=_HERE, capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        if not out:
            return _HERE
        return Path(out).parent
    except Exception:  # noqa: BLE001 — нет git, не репозиторий, таймаут: работаем от пакета
        return _HERE


def default_root() -> Path:
    return _main_checkout() / "workflow" / "_contracts"


def _is_anonymizer(path: Path) -> bool:
    return "_anonymizer" in [p.lower() for p in Path(path).parts]


def guard(path: Path) -> Path:
    """Отвергает путь в проект анонимайзера: и буквальный, и разрешённый (относительный, `..`, ярлык)."""
    p = Path(path)
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        resolved = p
    if _is_anonymizer(p) or _is_anonymizer(resolved):
        raise ForbiddenPath(f"{path}: проект анонимайзера, досье не ведётся (CLAUDE.md, «Конфиденциальность»)")
    return p


def guard_task(path: Path, root: Path) -> Path:
    """Папка задачи: не анонимайзер, внутри папки workflow, где лежит реестр (`root.parent`),
    и не внутри самого реестра. Возвращает разрешённый путь."""
    task = guard(Path(path).resolve())
    root_r = guard(Path(root).resolve())
    workflow = root_r.parent
    if task == workflow or not task.is_relative_to(workflow) or task.is_relative_to(root_r):
        raise ForbiddenPath(f"{path}: папка задачи вне workflow/: уточните у юриста")
    return task
