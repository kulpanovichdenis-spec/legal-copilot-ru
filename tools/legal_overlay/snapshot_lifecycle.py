#!/usr/bin/env python3
"""Validate, switch and roll back the shared Legal Overlay SQLite snapshot.

Read-only commands are the default. Mutating commands require the explicit
``--confirm-write`` flag and never modify the SQLite databases themselves.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from tools.profile.profile_lib import profile_root, repo_root

from .adapters.sqlite_legal_memory import (
    DATABASE as MEMORY_DATABASE,
    REQUIRED_TABLES as MEMORY_TABLES,
)
from .adapters.sqlite_legal_doctrine import (
    DATABASE as DOCTRINE_DATABASE,
    REQUIRED_TABLES as DOCTRINE_TABLES,
)
from .adapters.sqlite_legal_ru import (
    DATABASE as RU_DATABASE,
    REQUIRED_TABLES as RU_TABLES,
)
from .adapters.sqlite_legal_uz import (
    DATABASE as UZ_DATABASE,
    REQUIRED_TABLES as UZ_TABLES,
)
from .bootstrap_claude_desktop import default_config_path, desired_entry
from .config import ProviderConnection, _parse_env_file, load_connections
from .sqlite_snapshot import SQLiteSnapshot


SNAPSHOT_ENV = "LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR"
STATE_FORMAT = "legal-overlay-snapshot-state"
STATE_VERSION = 1
LOCAL_ENV_NAME = "local.env"
STATE_NAME = "snapshot-state.json"
REQUIRED_PROVIDER_STATUS_TOOLS = {
    "local-legal-ru-sqlite": "sqlite_legal_ru_status",
    "local-legal-uz-sqlite": "uzbek_legal_status",
    "local-legal-memory-sqlite": "sqlite_legal_memory_status",
    "local-legal-doctrine-sqlite": "sqlite_legal_doctrine_status",
}
SNAPSHOT_DATABASES = (
    ("local-legal-ru-sqlite", "sqlite_legal_ru", RU_DATABASE, RU_TABLES),
    ("local-legal-uz-sqlite", "sqlite_legal_uz", UZ_DATABASE, UZ_TABLES),
    ("local-legal-memory-sqlite", "sqlite_legal_memory", MEMORY_DATABASE, MEMORY_TABLES),
    (
        "local-legal-doctrine-sqlite",
        "sqlite_legal_doctrine",
        DOCTRINE_DATABASE,
        DOCTRINE_TABLES,
    ),
)


class SnapshotLifecycleError(ValueError):
    """A controlled lifecycle error that does not expose connector secrets."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolved_snapshot(path: Path | str) -> Path:
    value = str(path).strip()
    if not value or "\n" in value or "\r" in value:
        raise SnapshotLifecycleError("snapshot path is empty or contains a newline")
    resolved = Path(value).expanduser().resolve()
    if not resolved.is_dir():
        raise SnapshotLifecycleError("snapshot directory does not exist")
    return resolved


def _connection(provider_id: str, adapter: str, root: Path) -> ProviderConnection:
    return ProviderConnection(
        provider_id=provider_id,
        adapter=adapter,
        enabled=True,
        endpoint=None,
        priority=30,
        capabilities=("legal_corpus",),
        options={"snapshot_dir": str(root), "stale_after_days": 30},
    )


def validate_snapshot(path: Path | str) -> dict[str, Any]:
    """Validate all four databases without changing the snapshot or profile."""
    root = _resolved_snapshot(path)
    databases: list[dict[str, Any]] = []
    for provider_id, adapter, database, required_tables in SNAPSHOT_DATABASES:
        snapshot = SQLiteSnapshot(
            _connection(provider_id, adapter, root),
            database=database,
            required_tables=required_tables,
        )
        metadata = snapshot.validate().to_dict()
        metadata["provider"] = provider_id
        databases.append(metadata)
    return {
        "status": "validated",
        "snapshot": str(root),
        "database_count": len(databases),
        "databases": databases,
        "read_only": True,
    }


def _request_messages() -> str:
    messages: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "overlay_status", "arguments": {"probe": False}},
        },
    ]
    for request_id, tool_name in enumerate(REQUIRED_PROVIDER_STATUS_TOOLS.values(), start=4):
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
            }
        )
    return "".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages)


def _tool_payload(response: dict[str, Any]) -> Any:
    result = response.get("result")
    if not isinstance(result, dict):
        raise SnapshotLifecycleError("MCP tools/call response has no result object")
    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        raise SnapshotLifecycleError("MCP tools/call response has no text content")
    text = content[0].get("text")
    if not isinstance(text, str):
        raise SnapshotLifecycleError("MCP tools/call response text is missing")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SnapshotLifecycleError("MCP tools/call response is not JSON") from exc


def _run_entrypoint(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    snapshot: Path,
    inherit_snapshot_env: bool,
) -> dict[str, Any]:
    environment = dict(os.environ)
    if inherit_snapshot_env:
        environment.pop(SNAPSHOT_ENV, None)
    else:
        environment[SNAPSHOT_ENV] = str(snapshot)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            input=_request_messages(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotLifecycleError(f"{name} smoke could not run: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1200:]
        raise SnapshotLifecycleError(f"{name} smoke exited {completed.returncode}: {detail}")
    responses: dict[int, dict[str, Any]] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SnapshotLifecycleError(f"{name} smoke emitted invalid JSON") from exc
        if isinstance(response, dict) and isinstance(response.get("id"), int):
            responses[response["id"]] = response
    expected_ids = set(range(1, 4 + len(REQUIRED_PROVIDER_STATUS_TOOLS)))
    if set(responses) != expected_ids:
        raise SnapshotLifecycleError(f"{name} smoke returned an incomplete MCP response set")
    for response in responses.values():
        if "error" in response:
            message = response.get("error", {}).get("message", "unknown MCP error")
            raise SnapshotLifecycleError(f"{name} smoke failed: {message}")

    initialize = responses[1].get("result", {})
    server_info = initialize.get("serverInfo", {}) if isinstance(initialize, dict) else {}
    if server_info.get("name") != "legal-overlay":
        raise SnapshotLifecycleError(f"{name} smoke reached an unexpected MCP server")
    tools_result = responses[2].get("result", {})
    listed_tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
    tool_names = {item.get("name") for item in listed_tools if isinstance(item, dict)}
    missing_tools = sorted(set(REQUIRED_PROVIDER_STATUS_TOOLS.values()) - tool_names)
    if missing_tools:
        raise SnapshotLifecycleError(f"{name} smoke is missing tools: {', '.join(missing_tools)}")

    overlay = _tool_payload(responses[3])
    providers = overlay.get("providers", []) if isinstance(overlay, dict) else []
    by_id = {item.get("id"): item for item in providers if isinstance(item, dict)}
    if "server-legal-kb" in by_id:
        raise SnapshotLifecycleError(f"{name} smoke found removed provider server-legal-kb")

    provider_results: dict[str, str] = {}
    for request_id, provider_id in enumerate(REQUIRED_PROVIDER_STATUS_TOOLS, start=4):
        payload = _tool_payload(responses[request_id])
        status = payload.get("status") if isinstance(payload, dict) else None
        if status != "connected":
            raise SnapshotLifecycleError(f"{name} smoke provider {provider_id} is not connected")
        provider_results[provider_id] = status
    return {
        "entrypoint": name,
        "status": "passed",
        "gateway_version": server_info.get("version"),
        "tool_count": len(tool_names),
        "providers": provider_results,
    }


def _claude_command() -> list[str]:
    config_path = default_config_path()
    if not config_path.is_file():
        raise SnapshotLifecycleError("Claude Desktop config is missing")
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotLifecycleError("Claude Desktop config is unreadable") from exc
    entry = loaded.get("mcpServers", {}).get("legal-overlay") if isinstance(loaded, dict) else None
    expected = desired_entry()
    if entry != expected:
        raise SnapshotLifecycleError(
            "Claude Desktop legal-overlay entry differs from the approved absolute local launcher"
        )
    return [expected["command"], *expected["args"]]


def smoke_harnesses(path: Path | str, *, inherit_snapshot_env: bool = False) -> list[dict[str, Any]]:
    """Run the same read-only MCP checks through Codex and Claude entrypoints."""
    snapshot = _resolved_snapshot(path)
    repository = repo_root().resolve()
    codex = _run_entrypoint(
        "codex",
        [sys.executable, "-m", "tools.legal_overlay"],
        cwd=repository,
        snapshot=snapshot,
        inherit_snapshot_env=inherit_snapshot_env,
    )
    claude = _run_entrypoint(
        "claude-desktop",
        _claude_command(),
        cwd=Path(tempfile.gettempdir()),
        snapshot=snapshot,
        inherit_snapshot_env=inherit_snapshot_env,
    )
    return [codex, claude]


def preflight(path: Path | str, *, validation_only: bool = False) -> dict[str, Any]:
    root = _resolved_snapshot(path)
    result = validate_snapshot(root)
    result["harness_smoke"] = [] if validation_only else smoke_harnesses(root)
    result["status"] = "validated" if validation_only else "ready"
    return result


def _settings_paths(profile: Path | None = None) -> tuple[Path, Path]:
    settings = (profile or profile_root()).resolve() / "settings"
    return settings / LOCAL_ENV_NAME, settings / STATE_NAME


def _local_env_snapshot(path: Path) -> str | None:
    value = _parse_env_file(path).get(SNAPSHOT_ENV, "").strip()
    return value or None


def _state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotLifecycleError("snapshot state file is unreadable") from exc
    if not isinstance(value, dict) or value.get("format") != STATE_FORMAT or value.get("version") != STATE_VERSION:
        raise SnapshotLifecycleError("snapshot state file has an unsupported format")
    return value


def current_status(*, profile: Path | None = None) -> dict[str, Any]:
    local_env, state_path = _settings_paths(profile)
    configured = _local_env_snapshot(local_env)
    connections = load_connections(profile=(profile or profile_root()).resolve())
    effective = str(
        connections.provider("local-legal-ru-sqlite").options.get("snapshot_dir") or ""
    ).strip() or None
    process_override = os.environ.get(SNAPSHOT_ENV)
    return {
        "local_env": str(local_env),
        "local_env_snapshot": configured,
        "effective_snapshot": effective,
        "process_override_active": bool(process_override),
        "state_file": str(state_path),
        "state": _state(state_path),
    }


def preview_switch(path: Path | str, *, profile: Path | None = None) -> dict[str, Any]:
    target = _resolved_snapshot(path)
    status = current_status(profile=profile)
    current = status["local_env_snapshot"]
    return {
        "action": "no_change" if current and Path(current).resolve() == target else "switch",
        "current_snapshot": current,
        "target_snapshot": str(target),
        "process_override_active": status["process_override_active"],
        "preflight": preflight(target),
        "writes_performed": False,
    }


def _render_local_env(original: str, snapshot: Path) -> str:
    line = f"{SNAPSHOT_ENV}={snapshot}"
    output: list[str] = []
    replaced = False
    for existing in original.splitlines():
        stripped = existing.strip()
        if not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name == SNAPSHOT_ENV:
                if not replaced:
                    output.append(line)
                    replaced = True
                continue
        output.append(existing)
    if not replaced:
        if output and output[-1] != "":
            output.append("")
        output.append(line)
    return "\n".join(output) + "\n"


def _replace_with_retry(source: str, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            handle.write(payload)
            temporary = handle.name
        _replace_with_retry(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(payload)
            temporary = handle.name
        _replace_with_retry(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def _backup_local_env(local_env: Path, original: bytes | None) -> Path | None:
    if original is None:
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = local_env.with_name(f"{local_env.name}.bak-{timestamp}")
    backup.write_bytes(original)
    return backup


def _restore_local_env(local_env: Path, original: bytes | None) -> None:
    if original is None:
        if local_env.exists():
            local_env.unlink()
        return
    _atomic_write_bytes(local_env, original)


def switch_snapshot(
    path: Path | str,
    *,
    confirm_write: bool,
    profile: Path | None = None,
    smoke: Callable[..., list[dict[str, Any]]] = smoke_harnesses,
) -> dict[str, Any]:
    if not confirm_write:
        raise SnapshotLifecycleError("snapshot switch requires explicit confirm_write")
    target = _resolved_snapshot(path)
    local_env, state_path = _settings_paths(profile)
    current = _local_env_snapshot(local_env)
    if current and Path(current).resolve() == target:
        validation = validate_snapshot(target)
        validation["harness_smoke"] = smoke(target, inherit_snapshot_env=True)
        validation["status"] = "ready"
        return {
            "action": "no_change",
            "current_snapshot": current,
            "target_snapshot": str(target),
            "preflight": validation,
            "writes_performed": False,
        }
    if os.environ.get(SNAPSHOT_ENV):
        raise SnapshotLifecycleError(
            f"process environment overrides {SNAPSHOT_ENV}; clear it before switching local.env"
        )

    validation = validate_snapshot(target)
    pre_switch_smoke = smoke(target, inherit_snapshot_env=False)
    original = local_env.read_bytes() if local_env.is_file() else None
    original_text = original.decode("utf-8-sig") if original is not None else ""
    backup = _backup_local_env(local_env, original)
    _atomic_write(local_env, _render_local_env(original_text, target))
    try:
        post_switch_smoke = smoke(target, inherit_snapshot_env=True)
        state = {
            "format": STATE_FORMAT,
            "version": STATE_VERSION,
            "switched_at": _utc_now(),
            "current_snapshot": str(target),
            "previous_snapshot": current,
            "local_env_backup": str(backup) if backup else None,
        }
        _atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        _restore_local_env(local_env, original)
        raise
    return {
        "action": "switched",
        "previous_snapshot": current,
        "current_snapshot": str(target),
        "local_env_backup": str(backup) if backup else None,
        "validation": validation,
        "pre_switch_smoke": pre_switch_smoke,
        "post_switch_smoke": post_switch_smoke,
        "state_file": str(state_path),
    }


def rollback_snapshot(
    *,
    confirm_write: bool,
    profile: Path | None = None,
    smoke: Callable[..., list[dict[str, Any]]] = smoke_harnesses,
) -> dict[str, Any]:
    if not confirm_write:
        raise SnapshotLifecycleError("snapshot rollback requires explicit confirm_write")
    local_env, state_path = _settings_paths(profile)
    state = _state(state_path)
    previous = state.get("previous_snapshot") if state else None
    if not previous:
        raise SnapshotLifecycleError("no previous snapshot is recorded for rollback")
    current = _local_env_snapshot(local_env)
    recorded_current = str(state.get("current_snapshot") or "").strip()
    if not current or not recorded_current or Path(current).resolve() != Path(recorded_current).resolve():
        raise SnapshotLifecycleError(
            "rollback state does not match the current local.env snapshot; run status and review manually"
        )
    result = switch_snapshot(
        previous,
        confirm_write=True,
        profile=profile,
        smoke=smoke,
    )
    result["action"] = "rolled_back" if result["action"] == "switched" else result["action"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show current path and rollback state without probing databases")
    for command in ("preflight", "preview", "apply"):
        child = subparsers.add_parser(command)
        child.add_argument("--snapshot", type=Path, required=True)
        if command == "preflight":
            child.add_argument("--validation-only", action="store_true")
        if command == "apply":
            child.add_argument("--confirm-write", action="store_true")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--confirm-write", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = current_status()
        elif args.command == "preflight":
            result = preflight(args.snapshot, validation_only=args.validation_only)
        elif args.command == "preview":
            result = preview_switch(args.snapshot)
        elif args.command == "apply":
            result = switch_snapshot(args.snapshot, confirm_write=args.confirm_write)
        else:
            result = rollback_snapshot(confirm_write=args.confirm_write)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
