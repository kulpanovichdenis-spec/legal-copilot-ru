"""Preview or explicitly apply the minimal Claude Desktop gateway entry."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SERVER_NAME = "legal-overlay"
LEGACY_SERVER_NAMES = ("legal-kb",)
LAUNCHER = Path(__file__).resolve().parent / "launcher.py"


class ClaudeBootstrapError(ValueError):
    """A safe configuration/bootstrap error."""


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise ClaudeBootstrapError("APPDATA is not available")
    return Path(appdata) / "Claude" / "claude_desktop_config.json"


def desired_entry(*, python_executable: Path | None = None, launcher: Path | None = None) -> dict[str, Any]:
    return {
        "command": str((python_executable or Path(sys.executable)).resolve()),
        "args": [str((launcher or LAUNCHER).resolve())],
    }


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClaudeBootstrapError(f"cannot parse Claude Desktop config: {path}") from exc
    if not isinstance(loaded, dict):
        raise ClaudeBootstrapError("Claude Desktop config must be a JSON object")
    servers = loaded.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ClaudeBootstrapError("Claude Desktop mcpServers must be a JSON object")
    return loaded


def _safe_current_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    result: dict[str, Any] = {}
    if "command" in entry:
        result["command"] = str(entry["command"])
    if "args" in entry:
        args = entry["args"]
        result["args"] = ["[VALUE HIDDEN]" for _item in args] if isinstance(args, list) else "[VALUE HIDDEN]"
    if "env" in entry:
        env = entry["env"]
        result["env_keys"] = sorted(str(key) for key in env) if isinstance(env, dict) else "[VALUE HIDDEN]"
    result["other_keys"] = sorted(key for key in entry if key not in {"command", "args", "env"})
    return result


def preview(path: Path, *, entry: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _read_config(path)
    servers = current.get("mcpServers", {})
    target = entry or desired_entry()
    existing = servers.get(SERVER_NAME)
    legacy_names = sorted(name for name in LEGACY_SERVER_NAMES if name in servers)
    legacy_entry = next((servers[name] for name in legacy_names if isinstance(servers[name], dict)), None)
    action = (
        "create_file"
        if not path.exists()
        else "migrate_entry"
        if legacy_names
        else "no_change"
        if existing == target
        else "add_entry"
        if existing is None
        else "replace_entry"
    )
    return {
        "target": str(path.resolve()),
        "action": action,
        "preserved_server_names": sorted(
            str(name) for name in servers if name != SERVER_NAME and name not in LEGACY_SERVER_NAMES
        ),
        "removed_legacy_server_names": legacy_names,
        "current_target_entry": _safe_current_entry(existing or legacy_entry),
        "proposed_target_entry": target,
        "secrets_in_harness_config": False,
    }


def _replace_with_retry(source: str, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def apply(path: Path, *, entry: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _read_config(path)
    target = entry or desired_entry()
    servers = dict(current.get("mcpServers", {}))
    removed_legacy_names = [name for name in LEGACY_SERVER_NAMES if servers.pop(name, None) is not None]
    servers[SERVER_NAME] = target
    updated = dict(current)
    updated["mcpServers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)

    backup: Path | None = None
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-{timestamp}")
        shutil.copy2(path, backup)

    payload = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
            handle.write(payload)
            temporary_name = handle.name
        _replace_with_retry(temporary_name, path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return {
        "target": str(path.resolve()),
        "backup": str(backup.resolve()) if backup else None,
        "entry": target,
        "removed_legacy_server_names": removed_legacy_names,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Override Claude Desktop config path")
    parser.add_argument("--apply", action="store_true", help="Write the entry after explicit confirmation")
    parser.add_argument("--confirm-write", action="store_true", help="Required together with --apply")
    args = parser.parse_args(argv)
    path = args.config or default_config_path()
    if args.apply and not args.confirm_write:
        parser.error("--apply requires --confirm-write")
    result = apply(path) if args.apply else preview(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
