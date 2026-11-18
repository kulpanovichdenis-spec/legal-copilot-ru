#!/usr/bin/env python3
"""Перепривязка пользовательского слоя (overlay) к текущей базе.

Пересобирает profile/INDEX.md из фактического содержимого profile/, проверяет,
что каждая заметка overrides/<skill>.md указывает на существующий базовый skill,
и помечает «висячие» привязки (базовый skill переименован/удалён). Запускается
автоматически внутри self-update и отдельной командой «перепривяжи профиль».
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

# Поддержка прямого запуска `python tools/.../<mod>.py` (repo root в sys.path)
if __name__ == "__main__" and __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parents[2]
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

from tools.profile.profile_lib import (
    base_version,
    load_profile_yaml,
    profile_root,
    repo_root,
    save_profile_yaml,
)


def base_skill_names(repo: Path) -> set[str]:
    skills_dir = repo / "skills"
    if not skills_dir.is_dir():
        return set()
    return {
        p.name for p in skills_dir.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    }


def list_overlay_skills(profile: Path) -> list[str]:
    d = profile / "skills"
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    )


def list_overrides(profile: Path) -> list[str]:
    d = profile / "overrides"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def list_overlay_templates(profile: Path) -> list[str]:
    d = profile / "templates"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and p.name != ".gitkeep")


def find_dangling(overrides: list[str], base: set[str]) -> list[str]:
    return [o for o in overrides if o not in base]


def render_index(overlay_skills, overrides, templates, dangling) -> str:
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# INDEX оверлея (генерируется автоматически — не редактировать руками)",
        "",
        f"Пересобрано: {ts}",
        "",
        "## Свои skills (добавлены)",
    ]
    lines += [f"- `profile/skills/{s}/SKILL.md`" for s in overlay_skills] or ["- (нет)"]
    lines += ["", "## Заметки к базовым skills (overrides)"]
    if overrides:
        for o in overrides:
            mark = "  ⚠ ВИСЯЧАЯ (нет такого базового skill)" if o in dangling else ""
            lines.append(f"- `profile/overrides/{o}.md` → базовый `{o}`{mark}")
    else:
        lines.append("- (нет)")
    lines += ["", "## Свои шаблоны (побеждают базовые при совпадении имени)"]
    lines += [f"- `profile/templates/{t}`" for t in templates] or ["- (нет)"]
    if dangling:
        lines += [
            "",
            "## ⚠ Требует внимания",
            "Есть заметки к базовым skills, которых больше нет в базе "
            "(переименованы/удалены при обновлении). Проверь и переименуй/удали:",
        ]
        lines += [f"- `profile/overrides/{d}.md`" for d in dangling]
    return "\n".join(lines) + "\n"


def relink(user: str | None = None) -> dict:
    repo = repo_root()
    profile = profile_root()
    profile.mkdir(parents=True, exist_ok=True)
    overlay_skills = list_overlay_skills(profile)
    overrides = list_overrides(profile)
    templates = list_overlay_templates(profile)
    dangling = find_dangling(overrides, base_skill_names(repo))
    (profile / "INDEX.md").write_text(
        render_index(overlay_skills, overrides, templates, dangling),
        encoding="utf-8",
    )
    data = load_profile_yaml()
    bv = base_version()
    data["base_version"] = bv["hash"]
    data["base_version_date"] = bv["date"]
    data.setdefault("location", str(profile))
    if user is not None and user.strip():
        data["user"] = user.strip()
    save_profile_yaml(data)
    return {
        "skills": len(overlay_skills),
        "overrides": len(overrides),
        "templates": len(templates),
        "dangling": dangling,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Перепривязать overlay к базе")
    parser.add_argument(
        "--name",
        dest="name",
        default=None,
        help="имя пользователя для profile.yaml (онбординг)",
    )
    args = parser.parse_args(argv)
    r = relink(user=args.name)
    print(
        f"Перепривязка готова: своих skills {r['skills']}, "
        f"заметок {r['overrides']}, шаблонов {r['templates']}."
    )
    if r["dangling"]:
        print("⚠ Висячие привязки (базовый skill исчез): " + ", ".join(r["dangling"]))
    else:
        print("Висячих привязок нет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
