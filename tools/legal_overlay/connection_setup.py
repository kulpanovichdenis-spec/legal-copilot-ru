"""Safe first-run selection of optional Legal Overlay providers.

The generated configuration contains every supported connector, but optional
external providers start disabled.  Enabling a credentialed provider is
refused until its local secret is present, so an unavailable database cannot
receive search traffic accidentally.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.profile.profile_lib import profile_root, repo_root

from .config import DEFAULT_CONNECTIONS, ConfigurationError, load_connections
from .oauth import OAuthError, _replace_with_retry, authorize_provider, oauth_store_path


OPTIONAL_EXTERNAL_PROVIDERS = (
    "glossa",
    "casuslegal-unified",
    "casuslegal-high-courts",
    "casuslegal-sip",
    "casuslegal-kas",
    "casuslegal-kud",
    "pravotech-consultant",
    "garant",
)

OAUTH_PROVIDERS = (
    "casuslegal-unified",
    "casuslegal-high-courts",
    "casuslegal-sip",
    "casuslegal-kas",
    "casuslegal-kud",
    "pravotech-consultant",
)

CASUS_CORPORA = ("main", "sip", "kas", "kud")


def starter_connections() -> dict[str, Any]:
    raw = copy.deepcopy(DEFAULT_CONNECTIONS)
    for provider_id in OPTIONAL_EXTERNAL_PROVIDERS:
        raw["providers"][provider_id]["enabled"] = False
    return raw


def _write_yaml_atomic(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _replace_with_retry(temporary, path)


def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return path.with_name(f"{path.name}.{stamp}.bak")


def _extract_glossa_code(source: Path) -> str:
    text = source.read_text(encoding="utf-8-sig")
    pattern = re.compile(
        r"(?i)(?:код|code)(?:\s+доступа|\s+access)?\s*[:=\-]?\s*"
        r"([A-Za-z0-9._~+/\-]{4,256}=*)\s*$"
    )
    for line in text.splitlines():
        match = pattern.search(line.strip())
        if match:
            return match.group(1)
    raise ConfigurationError("Glossa access code was not found in the source file")


def import_glossa_code(
    source: Path,
    secrets_path: Path,
    *,
    confirm_write: bool,
) -> str:
    if not confirm_write:
        raise ConfigurationError("secret import requires --confirm-write")
    if not source.is_file():
        raise ConfigurationError("Glossa source file does not exist")
    code = _extract_glossa_code(source)
    key = "GLOSSA_ACCESS_CODE"
    lines = secrets_path.read_text(encoding="utf-8-sig").splitlines() if secrets_path.exists() else []
    replacement = f"{key}={code}"
    found = False
    changed = False
    updated: list[str] = []
    for line in lines:
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            found = True
            changed = changed or line != replacement
            updated.append(replacement)
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)
        changed = True
    if not changed:
        return "no_change"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    if secrets_path.exists():
        shutil.copy2(secrets_path, _backup_path(secrets_path))
    temporary = secrets_path.with_suffix(secrets_path.suffix + ".tmp")
    temporary.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    _replace_with_retry(temporary, secrets_path)
    return "stored_locally"


def initialize_connections(path: Path, *, confirm_write: bool) -> str:
    if path.exists():
        return "already_exists"
    if not confirm_write:
        raise ConfigurationError("initialization requires --confirm-write")
    _write_yaml_atomic(path, starter_connections())
    return "created"


def provider_status_rows(
    path: Path,
    *,
    repository: Path,
    profile: Path,
) -> list[dict[str, Any]]:
    connections = load_connections(path if path.exists() else None, repository=repository, profile=profile)
    rows: list[dict[str, Any]] = []
    for provider_id in OPTIONAL_EXTERNAL_PROVIDERS:
        connection = connections.provider(provider_id)
        if not connection.enabled:
            state = (
                "authorized_disabled_no_network"
                if not connection.missing_secrets
                else "disabled_no_network"
            )
        elif connection.missing_secrets:
            state = "not_configured_no_network"
        else:
            state = "ready"
        rows.append(
            {
                "id": provider_id,
                "state": state,
                "enabled": connection.enabled,
                "network_allowed": connection.enabled and not connection.missing_secrets,
                "missing_credentials": list(connection.missing_secrets),
            }
        )
    return rows


def login_oauth_provider(
    provider_id: str,
    *,
    confirm_write: bool,
    repository: Path,
    profile: Path,
    timeout_seconds: int,
) -> str:
    if provider_id not in OAUTH_PROVIDERS:
        raise ConfigurationError(f"provider does not use interactive OAuth: {provider_id}")
    if not confirm_write:
        raise ConfigurationError("OAuth login writes local credential state; use --confirm-write")
    connection = load_connections(repository=repository, profile=profile).provider(provider_id)
    if not connection.endpoint:
        raise ConfigurationError(f"provider has no OAuth endpoint: {provider_id}")
    store_path = oauth_store_path(profile, provider_id)
    if store_path.exists():
        return "already_authorized"
    try:
        return authorize_provider(
            provider_id,
            connection.endpoint,
            store_path,
            timeout_seconds=timeout_seconds,
        )
    except OAuthError as exc:
        raise ConfigurationError(str(exc)) from exc


def set_provider_enabled(
    path: Path,
    provider_id: str,
    *,
    enabled: bool,
    confirm_write: bool,
    repository: Path,
    profile: Path,
) -> str:
    if provider_id not in OPTIONAL_EXTERNAL_PROVIDERS:
        raise ConfigurationError(f"provider is not an optional external database: {provider_id}")
    if not path.exists():
        raise ConfigurationError("connections.yaml does not exist; run init first")
    if not confirm_write:
        raise ConfigurationError("provider change requires --confirm-write")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), dict):
        raise ConfigurationError("connections.yaml must contain a providers mapping")
    provider = raw["providers"].get(provider_id)
    if not isinstance(provider, dict):
        raise ConfigurationError(f"provider is missing from connections.yaml: {provider_id}")

    current = bool(provider.get("enabled"))
    if current == enabled:
        return "no_change"
    if enabled:
        loaded = load_connections(path, repository=repository, profile=profile)
        missing = loaded.provider(provider_id).missing_secrets
        if missing:
            raise ConfigurationError(
                "provider remains disabled; missing local credentials: " + ", ".join(missing)
            )

    shutil.copy2(path, _backup_path(path))
    provider["enabled"] = enabled
    _write_yaml_atomic(path, raw)
    return "enabled" if enabled else "disabled"


def set_casus_corpora(
    path: Path,
    corpora: list[str],
    *,
    confirm_write: bool,
) -> str:
    if not confirm_write:
        raise ConfigurationError("Casus corpus change requires --confirm-write")
    if not path.exists():
        raise ConfigurationError("connections.yaml does not exist; run init first")
    selected = list(dict.fromkeys(corpora))
    if not selected or any(corpus not in CASUS_CORPORA for corpus in selected):
        raise ConfigurationError("select at least one supported Casus corpus")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    provider = raw.get("providers", {}).get("casuslegal-unified") if isinstance(raw, dict) else None
    if not isinstance(provider, dict):
        raise ConfigurationError("casuslegal-unified is missing from connections.yaml")
    options = provider.setdefault("options", {})
    if not isinstance(options, dict):
        raise ConfigurationError("casuslegal-unified options must be a mapping")
    if options.get("allowed_corpora") == selected:
        return "no_change"
    shutil.copy2(path, _backup_path(path))
    options["allowed_corpora"] = selected
    _write_yaml_atomic(path, raw)
    return "updated"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure optional external legal databases")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create local connections.yaml with optional providers disabled")
    init.add_argument("--confirm-write", action="store_true")

    subparsers.add_parser("status", help="show non-secret provider readiness and network gate")

    import_glossa = subparsers.add_parser(
        "import-glossa",
        help="store a Glossa code from an owner instruction file without printing it",
    )
    import_glossa.add_argument("--source", type=Path, required=True)
    import_glossa.add_argument("--confirm-write", action="store_true")

    oauth_login = subparsers.add_parser(
        "oauth-login",
        help="open the provider login and store OAuth tokens in the ignored local profile",
    )
    oauth_login.add_argument("provider", choices=OAUTH_PROVIDERS)
    oauth_login.add_argument("--timeout-seconds", type=int, default=600)
    oauth_login.add_argument("--confirm-write", action="store_true")

    casus_corpora = subparsers.add_parser(
        "set-casus-corpora",
        help="allow only Casus corpora that passed a live content smoke",
    )
    casus_corpora.add_argument("corpora", nargs="+", choices=CASUS_CORPORA)
    casus_corpora.add_argument("--confirm-write", action="store_true")

    for command in ("enable", "disable"):
        action = subparsers.add_parser(command)
        action.add_argument("provider", choices=OPTIONAL_EXTERNAL_PROVIDERS)
        action.add_argument("--confirm-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = repo_root().resolve()
    profile = profile_root().resolve()
    path = profile / "settings" / "connections.yaml"
    try:
        if args.command == "init":
            result: Any = {"action": initialize_connections(path, confirm_write=args.confirm_write)}
        elif args.command == "status":
            result = provider_status_rows(path, repository=repository, profile=profile)
        elif args.command == "import-glossa":
            result = {
                "provider": "glossa",
                "action": import_glossa_code(
                    args.source,
                    profile / "settings" / "secrets.env",
                    confirm_write=args.confirm_write,
                ),
            }
        elif args.command == "oauth-login":
            result = {
                "provider": args.provider,
                "action": login_oauth_provider(
                    args.provider,
                    confirm_write=args.confirm_write,
                    repository=repository,
                    profile=profile,
                    timeout_seconds=args.timeout_seconds,
                ),
            }
        elif args.command == "set-casus-corpora":
            result = {
                "provider": "casuslegal-unified",
                "action": set_casus_corpora(
                    path,
                    args.corpora,
                    confirm_write=args.confirm_write,
                ),
                "allowed_corpora": args.corpora,
            }
        else:
            result = {
                "provider": args.provider,
                "action": set_provider_enabled(
                    path,
                    args.provider,
                    enabled=args.command == "enable",
                    confirm_write=args.confirm_write,
                    repository=repository,
                    profile=profile,
                ),
            }
    except ConfigurationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
