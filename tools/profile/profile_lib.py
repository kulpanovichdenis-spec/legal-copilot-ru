#!/usr/bin/env python3
"""Фундамент пользовательского слоя (overlay).

Резолвинг физического расположения профиля, чтение/запись profile.yaml,
определение версии базы из git. Другие ядра профиля (relink, portable,
self_update, feedback_submit) строятся поверх этого модуля.

Расположение профиля:
    <repo>/.profile-path  (если есть) -> путь оттуда;  иначе  <repo>/profile
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def repo_root() -> Path:
    """Корень репозитория (по расположению этого файла: tools/profile/..)."""
    return Path(__file__).resolve().parents[2]


def parse_pointer(text: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return None


def profile_root() -> Path:
    pointer = repo_root() / ".profile-path"
    if pointer.exists():
        target = parse_pointer(pointer.read_text(encoding="utf-8"))
        if target:
            return Path(target)
    return repo_root() / "profile"


def profile_subpath(*parts: str) -> Path:
    return profile_root().joinpath(*parts)


def _profile_yaml_path() -> Path:
    return profile_root() / "profile.yaml"


def load_profile_yaml() -> dict:
    p = _profile_yaml_path()
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data or {}


def save_profile_yaml(data: dict) -> None:
    root = profile_root()
    root.mkdir(parents=True, exist_ok=True)
    _profile_yaml_path().write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def base_version(root: Path | None = None) -> dict:
    cwd = root or repo_root()
    try:
        h = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, check=True, capture_output=True, text=True,
        ).stdout.strip()
        d = subprocess.run(
            ["git", "show", "-s", "--format=%ci", "HEAD"],
            cwd=cwd, check=True, capture_output=True, text=True,
        ).stdout.strip()
        return {"hash": h, "date": d}
    except (subprocess.CalledProcessError, OSError):
        return {"hash": "unknown", "date": ""}
