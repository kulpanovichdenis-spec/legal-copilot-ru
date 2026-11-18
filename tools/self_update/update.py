#!/usr/bin/env python3
"""Ядро обновления legal-copilot из GitHub (origin/main).

Детерминированные git-операции и парсеры. Оркестрацию и чекпоинт
подтверждения держит skill self-update — здесь только механика:
проверка чистоты базы, fetch, разбор изменений, ff-обновление, зависимости,
smoke, перепривязка оверлея.

Правило безопасности: обновление только быстрой перемоткой (--ff-only).
Не-FF => функция pull_ff бросит CalledProcessError, а skill прервётся.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Поддержка прямого запуска `python tools/.../<mod>.py` (repo root в sys.path)
if __name__ == "__main__" and __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parents[2]
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

from tools.profile.profile_lib import repo_root
from tools.profile.relink import relink

_TOP_DIRS = ("skills", "references", "templates", "tools")


def parse_porcelain(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        out.append(line[3:].strip() if len(line) > 3 else line.strip())
    return out


def base_is_dirty(porcelain: str) -> list[str]:
    return [p for p in parse_porcelain(porcelain) if not p.startswith("profile/")]


def group_changes(paths: list[str]) -> dict:
    groups: dict[str, list[str]] = {d: [] for d in _TOP_DIRS}
    groups["другое"] = []
    for p in paths:
        top = p.split("/", 1)[0]
        (groups[top] if top in groups else groups["другое"]).append(p)
    return {k: v for k, v in groups.items() if v}


def requirements_touched(paths: list[str]) -> bool:
    return any(p == "requirements.txt" for p in paths)


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def status_porcelain(repo: Path) -> str:
    return git(["status", "--porcelain"], repo).stdout


def fetch(repo: Path) -> None:
    git(["fetch", "origin", "main"], repo)


def changed_vs_upstream(repo: Path) -> list[str]:
    out = git(["diff", "--name-only", "HEAD..origin/main"], repo).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def is_fast_forward(repo: Path) -> bool:
    try:
        git(["merge-base", "--is-ancestor", "HEAD", "origin/main"], repo)
        return True
    except subprocess.CalledProcessError:
        return False


def pull_ff(repo: Path) -> None:
    git(["merge", "--ff-only", "origin/main"], repo)


def install_deps(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=repo, capture_output=True, text=True,
    )


def run_smoke(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "tests/doc_ingest_smoke.py"],
        cwd=repo, capture_output=True, text=True,
    )


def main(argv=None) -> int:
    """CLI для skill: печатает машиночитаемую сводку шага.

    Подкоманды:
      check   — fetch + вывести dirty/ff/изменения/requirements
      apply   — pull_ff (+deps если нужно) + smoke + relink
    """
    ap = argparse.ArgumentParser(description="Обновление из GitHub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("apply")
    args = ap.parse_args(argv)
    repo = repo_root()

    if args.cmd == "check":
        dirty = base_is_dirty(status_porcelain(repo))
        if dirty:
            print("БАЗА ГРЯЗНАЯ — обновление остановлено. Изменённые базовые файлы:")
            for p in dirty:
                print(f"  {p}")
            return 2
        fetch(repo)
        changed = changed_vs_upstream(repo)
        if not changed:
            print("Обновлений нет — уже последняя версия.")
            return 0
        print(f"FF-обновление возможно: {is_fast_forward(repo)}")
        print(f"requirements менялся: {requirements_touched(changed)}")
        for grp, items in group_changes(changed).items():
            print(f"[{grp}] {len(items)} файлов")
            for p in items:
                print(f"  {p}")
        return 0

    if args.cmd == "apply":
        if base_is_dirty(status_porcelain(repo)):
            print("БАЗА ГРЯЗНАЯ — apply отменён.")
            return 2
        fetch(repo)
        if not is_fast_forward(repo):
            print("Не быстрая перемотка — apply отменён (нужен разбор вручную).")
            return 3
        changed = changed_vs_upstream(repo)
        pull_ff(repo)
        if requirements_touched(changed):
            r = install_deps(repo)
            print("Зависимости:", "ok" if r.returncode == 0 else "ОШИБКА")
        smoke = run_smoke(repo)
        print("Smoke:", "PASS" if smoke.returncode == 0 else "FAIL")
        rep = relink()
        print(
            f"Перепривязка: skills {rep['skills']}, overrides {rep['overrides']}, "
            f"templates {rep['templates']}, висячих {len(rep['dangling'])}"
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
