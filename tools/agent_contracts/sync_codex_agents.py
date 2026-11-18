#!/usr/bin/env python3
"""Один источник определений субагентов: `.codex/agents/*.toml` генерируются из `.claude/agents/*.md`.

Тело инструкции переносится дословно, `name`/`description` — из frontmatter, модель и
reasoning effort — по таблице MODEL_MAP (класс модели, а не конкретная версия, задаётся в
`.claude/agents`; здесь — её аналог для Codex). Правки агентов вносятся только в `.md`.

Usage:
    python tools/agent_contracts/sync_codex_agents.py            # проверить расхождение (exit 1)
    python tools/agent_contracts/sync_codex_agents.py --write    # перегенерировать .toml
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_DIR = ROOT / ".claude" / "agents"
CODEX_DIR = ROOT / ".codex" / "agents"

# Класс модели Claude → аналог в Codex (`references/execution-profiles.md`, классы A/B/C).
MODEL_MAP = {
    "opus": ("gpt-5.6", "high"),
    "sonnet": ("gpt-5.6", "medium"),
    "haiku": ("gpt-5.6-luna", "medium"),
}


def parse_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: нет frontmatter")
    _, fm, body = text.split("---\n", 2)
    meta = yaml.safe_load(fm) or {}
    for key in ("name", "description", "model"):
        if not meta.get(key):
            raise ValueError(f"{path.name}: во frontmatter нет {key}")
    if meta["model"] not in MODEL_MAP:
        raise ValueError(f"{path.name}: модель {meta['model']!r} не описана в MODEL_MAP")
    return meta, body.strip()


def _basic(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_toml(meta: dict, body: str) -> str:
    model, effort = MODEL_MAP[meta["model"]]
    if "'''" not in body:
        instructions = "'''\n" + body + "'''"
    else:
        instructions = '"""\n' + body.replace("\\", "\\\\").replace('"""', '\\"""') + '"""'
    return (
        f"# Сгенерировано из .claude/agents/{meta['name']}.md — tools/agent_contracts/sync_codex_agents.py.\n"
        f"# Правки вносить в .md и перегенерировать (--write).\n"
        f"name = {_basic(meta['name'])}\n"
        f"description = {_basic(str(meta['description']).strip())}\n"
        f"model = {_basic(model)}\n"
        f"model_reasoning_effort = {_basic(effort)}\n"
        f'sandbox_mode = "read-only"\n'
        f"developer_instructions = {instructions}\n"
    )


def expected() -> dict[Path, str]:
    out = {}
    for md in sorted(CLAUDE_DIR.glob("*.md")):
        meta, body = parse_md(md)
        out[CODEX_DIR / f"{meta['name']}.toml"] = render_toml(meta, body)
    return out


def check() -> list[str]:
    """Расхождения между .claude/agents и .codex/agents; пустой список — синхронно."""
    errors = []
    want = expected()
    for path, text in want.items():
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: нет файла — запустить sync_codex_agents.py --write")
            continue
        if path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            errors.append(f"{path.relative_to(ROOT)}: расходится с .claude/agents — запустить sync_codex_agents.py --write")
    for path in CODEX_DIR.glob("*.toml"):
        if path not in want:
            errors.append(f"{path.relative_to(ROOT)}: нет исходного .claude/agents/{path.stem}.md")
    return errors


def write() -> int:
    for path, text in expected().items():
        tomllib.loads(text)  # не записывать сломанный TOML
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"записан {path.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        return write()
    errors = check()
    for e in errors:
        print(f"ERROR: {e}")
    if not errors:
        print("OK: .codex/agents синхронны с .claude/agents")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
