"""Load portable provider settings without exposing secret values.

Precedence for local settings, secrets and endpoint environment names:
    process environment > profile/settings/secrets.env > profile/settings/local.env > legacy repo .env

The legacy root .env fallback keeps the first increment compatible with the
current legal-kb setup. It can be deprecated only after both harnesses use the
profile settings successfully.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from tools.profile.profile_lib import profile_root, repo_root


ENV_TEMPLATE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


class ConfigurationError(ValueError):
    """A controlled, non-secret-bearing connection configuration error."""


@dataclass(frozen=True)
class ProviderConnection:
    provider_id: str
    adapter: str
    enabled: bool
    endpoint: str | None
    priority: int = 100
    capabilities: tuple[str, ...] = ()
    transitional_external_proxy: bool = False
    secret_refs: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    _secret_values: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def missing_secrets(self) -> tuple[str, ...]:
        return tuple(
            env_name
            for logical_name, env_name in self.secret_refs.items()
            if not self._secret_values.get(logical_name)
        )

    @property
    def configured(self) -> bool:
        return self.enabled and not self.missing_secrets

    def secret(self, logical_name: str) -> str:
        return self._secret_values.get(logical_name, "")

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in self._secret_values.values() if value)


@dataclass(frozen=True)
class ConnectionsConfig:
    version: int
    source_path: Path | None
    providers: Mapping[str, ProviderConnection]

    def enabled(self) -> tuple[ProviderConnection, ...]:
        return tuple(
            sorted(
                (provider for provider in self.providers.values() if provider.enabled),
                key=lambda provider: (provider.priority, provider.provider_id),
            )
        )

    def provider(self, provider_id: str) -> ProviderConnection:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise ConfigurationError(f"unknown provider: {provider_id}") from exc


DEFAULT_CONNECTIONS: dict[str, Any] = {
    "version": 1,
    "providers": {
        "local-verified": {
            "enabled": True,
            "adapter": "local_verified",
            "priority": 10,
            "capabilities": ["verified_knowledge", "knowledge_lifecycle"],
        },
        "local-curated": {
            "enabled": True,
            "adapter": "local_curated",
            "priority": 20,
            "capabilities": ["local_playbooks", "playbook_cards", "methodology"],
        },
        "local-legal-ru-sqlite": {
            "enabled": True,
            "adapter": "sqlite_legal_ru",
            "priority": 30,
            "capabilities": [
                "legal_corpus",
                "legislation",
                "case_positions",
                "comments",
                "relations",
            ],
            "options": {
                "snapshot_dir": "${LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR}",
                "stale_after_days": 30,
                "server_dual_run": False,
            },
        },
        "local-legal-uz-sqlite": {
            "enabled": True,
            "adapter": "sqlite_legal_uz",
            "priority": 35,
            "capabilities": ["legal_corpus", "legislation", "uzbekistan"],
            "options": {
                "snapshot_dir": "${LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR}",
                "stale_after_days": 30,
            },
        },
        "local-legal-doctrine-sqlite": {
            "enabled": True,
            "adapter": "sqlite_legal_doctrine",
            "priority": 40,
            "capabilities": ["legal_doctrine", "civil_law", "doctrine_sources"],
            "options": {
                "snapshot_dir": "${LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR}",
                "stale_after_days": 30,
            },
        },
        "local-legal-memory-sqlite": {
            "enabled": True,
            "adapter": "sqlite_legal_memory",
            "priority": 42,
            "capabilities": ["legal_opinions", "reviewed_telegram", "topic_maps"],
            "options": {
                "snapshot_dir": "${LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR}",
                "stale_after_days": 30,
            },
        },
        "tavily": {
            "enabled": True,
            "adapter": "tavily",
            "endpoint": "https://api.tavily.com",
            "secret_refs": {"api_key": "TAVILY_API_KEY"},
            "priority": 45,
            "capabilities": ["web_search", "web_extract", "deep_research"],
        },
        "dadata": {
            "enabled": True,
            "adapter": "dadata_party",
            "endpoint": "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
            "secret_refs": {
                "api_key": "DADATA_API_KEY",
                "secret_key": "DADATA_SECRET_KEY",
            },
            "priority": 46,
            "capabilities": ["counterparty", "party_registry"],
        },
        "glossa": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://glossa-ai.ru/mcp",
            "secret_refs": {"access_token": "GLOSSA_ACCESS_CODE"},
            "priority": 55,
            "capabilities": ["legal_doctrine", "civil_law", "case_practice"],
            "options": {"auth_mode": "static_bearer"},
        },
        "casuslegal-high-courts": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://mcp.casus.legal/mcp",
            "secret_refs": {"access_token": "CASUSLEGAL_HIGH_COURTS_ACCESS_TOKEN"},
            "priority": 60,
            "capabilities": ["constitutional_court", "supreme_court", "supreme_arbitration_court"],
            "options": {"auth_mode": "oauth"},
        },
        "casuslegal-unified": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://mcp.casus.legal/one/mcp",
            "secret_refs": {"access_token": "CASUSLEGAL_UNIFIED_ACCESS_TOKEN"},
            "priority": 59,
            "capabilities": [
                "constitutional_court",
                "supreme_court",
                "supreme_arbitration_court",
                "intellectual_property",
                "administrative_procedure",
                "criminal_procedure",
            ],
            "options": {
                "auth_mode": "oauth",
                "tool_inventory_review_required": False,
                "allowed_corpora": [],
            },
        },
        "casuslegal-sip": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://sip.casus.legal/mcp",
            "secret_refs": {"access_token": "CASUSLEGAL_SIP_ACCESS_TOKEN"},
            "priority": 61,
            "capabilities": ["intellectual_property", "court_practice"],
            "options": {"auth_mode": "oauth"},
        },
        "casuslegal-kas": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://kas.casus.legal/mcp",
            "secret_refs": {"access_token": "CASUSLEGAL_KAS_ACCESS_TOKEN"},
            "priority": 62,
            "capabilities": ["administrative_procedure", "supreme_court"],
            "options": {"auth_mode": "oauth"},
        },
        "casuslegal-kud": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://kud.casus.legal/mcp",
            "secret_refs": {"access_token": "CASUSLEGAL_KUD_ACCESS_TOKEN"},
            "priority": 63,
            "capabilities": ["criminal_procedure", "supreme_court"],
            "options": {"auth_mode": "oauth"},
        },
        "pravotech-consultant": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://consultant.pravo.tech/mcp",
            "secret_refs": {"access_token": "PRAVOTECH_CONSULTANT_ACCESS_TOKEN"},
            "priority": 65,
            "capabilities": ["legislation", "court_practice", "commercial_navigation"],
            "options": {
                "auth_mode": "oauth",
                "tool_inventory_review_required": False,
                "call_timeout_seconds": 180,
            },
        },
        "consultant-plus": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint_env": "CONSULTANT_PLUS_MCP_URL",
            "priority": 64,
            "capabilities": ["legislation", "court_practice", "commentary", "document_status"],
            "options": {"auth_mode": "none"},
        },
        "garant": {
            "enabled": False,
            "adapter": "remote_legal_mcp",
            "endpoint": "https://mcp.garant.ru",
            "secret_refs": {"access_token": "GARANT_API_TOKEN"},
            "priority": 66,
            "capabilities": ["legislation", "court_practice", "document_export", "legal_news"],
            "options": {"auth_mode": "static_bearer"},
        },
        "fas": {
            "enabled": True,
            "adapter": "fas_search",
            "endpoint": "https://search.delay-rag.ru/mcp/",
            "priority": 80,
            "capabilities": [
                "administrative_practice",
                "advertising",
                "case_details",
                "filter_options",
            ],
            "options": {"server_fallback": False},
        },
        "pravo-gov-ru": {
            "enabled": True,
            "adapter": "pravo_gov_ru",
            "endpoint": "http://pravo.gov.ru/proxy/ips/",
            "priority": 100,
            "capabilities": [
                "legislation",
                "exact_act_resolution",
                "official_full_text",
            ],
        }
    },
}


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _merged_environment(
    *,
    repository: Path,
    profile: Path,
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    values = _parse_env_file(repository / ".env")
    values.update(_parse_env_file(profile / "settings" / "local.env"))
    values.update(_parse_env_file(profile / "settings" / "secrets.env"))
    values.update(dict(os.environ if environ is None else environ))
    return values


def _expand_string(value: str, env_values: Mapping[str, str]) -> str:
    return ENV_TEMPLATE.sub(lambda match: env_values.get(match.group(1), match.group(0)), value)


def _expand_value(value: Any, env_values: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _expand_string(value, env_values)
    if isinstance(value, list):
        return [_expand_value(item, env_values) for item in value]
    if isinstance(value, dict):
        return {key: _expand_value(item, env_values) for key, item in value.items()}
    return value


def _load_schema(name: str) -> dict[str, Any]:
    import json

    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validate_connections(raw: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema("connections.schema.json")).iter_errors(raw),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "root"
    raise ConfigurationError(f"invalid connections configuration at {location}: {first.message}")


def load_connections(
    path: Path | None = None,
    *,
    repository: Path | None = None,
    profile: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConnectionsConfig:
    repository_path = (repository or repo_root()).resolve()
    profile_path = (profile or profile_root()).resolve()
    config_path = path or profile_path / "settings" / "connections.yaml"

    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ConfigurationError("connections configuration must be a mapping")
        raw = loaded
        source_path: Path | None = config_path
    else:
        raw = DEFAULT_CONNECTIONS
        source_path = None

    _validate_connections(raw)
    env_values = _merged_environment(
        repository=repository_path,
        profile=profile_path,
        environ=environ,
    )

    providers: dict[str, ProviderConnection] = {}
    for provider_id, item in raw["providers"].items():
        endpoint = item.get("endpoint")
        endpoint_env = item.get("endpoint_env")
        if endpoint_env and env_values.get(endpoint_env):
            endpoint = env_values[endpoint_env]
        if isinstance(endpoint, str):
            endpoint = _expand_string(endpoint, env_values).rstrip("/")

        secret_refs = dict(item.get("secret_refs", {}))
        secret_values = {
            logical_name: env_values.get(env_name, "")
            for logical_name, env_name in secret_refs.items()
        }
        options = _expand_value(item.get("options", {}), env_values)
        if not isinstance(options, dict):
            options = {}
        if options.get("auth_mode") == "oauth" and not secret_values.get("access_token"):
            # OAuth credentials belong to the ignored user profile, not a
            # tracked env file. Import lazily to keep config/oauth modules
            # independent and make an explicit environment token win.
            from .oauth import oauth_store_path, stored_access_token

            store_path = oauth_store_path(profile_path, provider_id)
            token = stored_access_token(store_path)
            if token:
                secret_values["access_token"] = token
                options["oauth_store_path"] = str(store_path)
        providers[provider_id] = ProviderConnection(
            provider_id=provider_id,
            adapter=item["adapter"],
            enabled=bool(item["enabled"]),
            endpoint=endpoint,
            priority=int(item.get("priority", 100)),
            capabilities=tuple(item.get("capabilities", [])),
            transitional_external_proxy=bool(item.get("transitional_external_proxy", False)),
            secret_refs=secret_refs,
            options=options,
            _secret_values=secret_values,
        )

    return ConnectionsConfig(
        version=int(raw["version"]),
        source_path=source_path,
        providers=providers,
    )


def redact_text(text: str, secrets: tuple[str, ...] | list[str]) -> str:
    redacted = str(text)
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted
