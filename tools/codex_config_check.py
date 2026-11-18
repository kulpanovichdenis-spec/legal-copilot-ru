#!/usr/bin/env python3
"""Validate repository-local Codex discovery and custom-agent configuration."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_AGENT_KEYS = {
    "name",
    "description",
    "developer_instructions",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
}


def main() -> int:
    errors: list[str] = []

    config_path = ROOT / ".codex" / "config.toml"
    try:
        codex_config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        errors.append(f"invalid {config_path.relative_to(ROOT)}: {exc}")
        codex_config = {}
    codex_servers = codex_config.get("mcp_servers", {}) if isinstance(codex_config, dict) else {}
    if "legal-overlay" not in codex_servers or "legal-kb" in codex_servers:
        errors.append(".codex/config.toml must expose legal-overlay and must not expose legacy legal-kb")

    claude_code_path = ROOT / ".mcp.json"
    try:
        claude_code_config = json.loads(claude_code_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        errors.append(f"invalid {claude_code_path.relative_to(ROOT)}: {exc}")
        claude_code_config = {}
    claude_code_servers = (
        claude_code_config.get("mcpServers", {}) if isinstance(claude_code_config, dict) else {}
    )
    if "legal-overlay" not in claude_code_servers or "legal-kb" in claude_code_servers:
        errors.append(".mcp.json must expose legal-overlay and must not expose legacy legal-kb")

    agents = sorted((ROOT / ".codex" / "agents").glob("*.toml"))
    # Codex зеркалит субагентов Claude Code: набор задаётся каталогом .claude/agents/.
    expected = {path.stem for path in (ROOT / ".claude" / "agents").glob("*.md")}
    names: set[str] = set()
    for path in agents:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"invalid {path.relative_to(ROOT)}: {exc}")
            continue
        missing = REQUIRED_AGENT_KEYS.difference(data)
        if missing:
            errors.append(f"{path.relative_to(ROOT)} missing keys: {sorted(missing)}")
        if data.get("sandbox_mode") != "read-only":
            errors.append(f"{path.relative_to(ROOT)} must use sandbox_mode=read-only")
        if data.get("name"):
            names.add(str(data["name"]))

    if names != expected:
        errors.append(f"custom agent names {sorted(names)} != expected {sorted(expected)}")

    # Один источник: .codex/agents генерируются из .claude/agents (tools/agent_contracts/sync_codex_agents.py).
    sys.path.insert(0, str(ROOT))
    from tools.agent_contracts.sync_codex_agents import check as sync_check  # noqa: PLC0415
    errors.extend(sync_check())

    canonical = (ROOT / "skills").resolve()
    discovery = ROOT / ".agents" / "skills"
    if not discovery.exists():
        errors.append(".agents/skills is missing; run tools/setup_codex_skills.ps1")
    elif discovery.resolve() != canonical:
        errors.append(f".agents/skills resolves to {discovery.resolve()}, expected {canonical}")
    else:
        canonical_names = {p.parent.name for p in canonical.glob("*/SKILL.md")}
        discovered_names = {p.parent.name for p in discovery.glob("*/SKILL.md")}
        if discovered_names != canonical_names:
            errors.append("Codex skill discovery set differs from canonical skills/")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"OK: Codex config valid; agents={len(agents)}, skills={len(canonical_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
