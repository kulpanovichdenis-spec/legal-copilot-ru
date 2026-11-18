"""Provider registry for the local Legal Overlay gateway."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .adapters.base import ProviderAdapter
from .adapters.dadata import DaDataPartyAdapter
from .adapters.fas_search import FasSearchAdapter
from .adapters.local_curated import LocalCuratedAdapter
from .adapters.local_verified import LocalVerifiedAdapter
from .adapters.pharma_compliance import PharmaComplianceAdapter
from .adapters.pravo_gov_ru import PravoGovRuAdapter
from .adapters.remote_legal_mcp import DISCOVERY_TIMEOUT_SECONDS, RemoteLegalMcpAdapter
from .adapters.sqlite_legal_doctrine import SQLiteLegalDoctrineAdapter
from .adapters.sqlite_legal_memory import SQLiteLegalMemoryAdapter
from .adapters.sqlite_legal_ru import SQLiteLegalRuAdapter
from .adapters.sqlite_legal_uz import SQLiteLegalUzAdapter
from .adapters.tavily import TavilyAdapter
from .config import ConfigurationError, ConnectionsConfig, load_connections, redact_text
from .models import ProviderDescriptor


# Maximum wall-clock time the gateway waits for all providers' tool inventories
# during a single tools/list discovery.  Cached providers return instantly; only
# a cold/stale remote fetch can approach this, and it never exceeds it.
DISCOVERY_BUDGET_SECONDS = 15.0


class ProviderRegistry:
    def __init__(
        self,
        adapters: Iterable[ProviderAdapter],
        unsupported: Iterable[tuple[str, str]] = (),
    ) -> None:
        self._adapters = {
            adapter.descriptor().provider_id: adapter
            for adapter in adapters
        }
        # (provider_id, adapter) pairs from the shared profile config that this
        # code version cannot build; reported in statuses, never fatal.
        self._unsupported = tuple(unsupported)

    @staticmethod
    def _tool_cache_dir() -> Path:
        # Repo-local, gitignored cache so a fresh overlay process serves the last
        # known remote tool inventory instantly instead of blocking discovery.
        return Path(__file__).resolve().parents[2] / ".cache" / "legal_overlay_tools"

    @classmethod
    def from_connections(cls, connections: ConnectionsConfig) -> "ProviderRegistry":
        adapters: list[ProviderAdapter] = []
        unsupported: list[tuple[str, str]] = []
        cache_dir = cls._tool_cache_dir()
        ordered_connections = sorted(
            connections.providers.values(),
            key=lambda connection: (connection.priority, connection.provider_id),
        )
        for connection in ordered_connections:
            if connection.adapter == "tavily":
                adapters.append(TavilyAdapter(connection))
                continue
            if connection.adapter == "dadata_party":
                adapters.append(DaDataPartyAdapter(connection))
                continue
            if connection.adapter == "sqlite_legal_ru":
                adapters.append(SQLiteLegalRuAdapter(connection))
                continue
            if connection.adapter == "sqlite_legal_uz":
                adapters.append(SQLiteLegalUzAdapter(connection))
                continue
            if connection.adapter == "sqlite_legal_doctrine":
                adapters.append(SQLiteLegalDoctrineAdapter(connection))
                continue
            if connection.adapter == "sqlite_legal_memory":
                adapters.append(SQLiteLegalMemoryAdapter(connection))
                continue
            if connection.adapter == "fas_search":
                adapters.append(FasSearchAdapter(connection))
                continue
            if connection.adapter == "local_verified":
                adapters.append(LocalVerifiedAdapter(connection))
                continue
            if connection.adapter == "local_curated":
                adapters.append(LocalCuratedAdapter(connection))
                continue
            if connection.adapter == "pravo_gov_ru":
                adapters.append(PravoGovRuAdapter(connection))
                continue
            if connection.adapter == "remote_legal_mcp":
                adapters.append(
                    RemoteLegalMcpAdapter(
                        connection,
                        tool_cache_dir=cache_dir,
                        discovery_timeout_seconds=DISCOVERY_TIMEOUT_SECONDS,
                    )
                )
                continue
            # profile/settings/connections.yaml is shared by every worktree via
            # .profile-path: a provider added on main must not take down the
            # whole overlay in a branch whose code predates its adapter.
            print(
                f"[legal-overlay] skipped provider '{connection.provider_id}': "
                f"unknown adapter '{connection.adapter}' (code older than profile config?)",
                file=sys.stderr,
            )
            unsupported.append((connection.provider_id, connection.adapter))
        return cls(adapters, unsupported)

    @classmethod
    def from_default_config(cls) -> "ProviderRegistry":
        registry = cls.from_connections(load_connections())
        adapter = PharmaComplianceAdapter()
        registry._adapters.setdefault(adapter.descriptor().provider_id, adapter)
        return registry

    def adapters(self) -> tuple[ProviderAdapter, ...]:
        return tuple(
            sorted(
                self._adapters.values(),
                key=lambda adapter: (
                    adapter.descriptor().priority,
                    adapter.descriptor().provider_id,
                ),
            )
        )

    def adapter(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise ConfigurationError(f"provider is not configured: {provider_id}") from exc

    def descriptors(self) -> list[dict[str, Any]]:
        return [adapter.descriptor().to_dict() for adapter in self.adapters()]

    def statuses(self, *, probe: bool = False) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for adapter in self.adapters():
            descriptor = adapter.descriptor()
            if probe:
                health = adapter.health().to_dict()
            else:
                if not descriptor.enabled:
                    statuses.append({"id": descriptor.provider_id, "status": "disabled"})
                    continue
                health = {
                    "id": descriptor.provider_id,
                    "status": "configured" if descriptor.configured else "not_configured",
                }
                if descriptor.missing_secrets:
                    health["detail"] = f"missing secrets: {', '.join(descriptor.missing_secrets)}"
            statuses.append(health)
        for provider_id, adapter_name in self._unsupported:
            statuses.append(
                {
                    "id": provider_id,
                    "status": "unsupported_adapter",
                    "detail": f"adapter '{adapter_name}' is not known to this code version; "
                    "update the branch (merge main)",
                }
            )
        return statuses

    def provider_tools(self) -> list[dict[str, Any]]:
        # Query providers concurrently under a wall-clock budget so a slow or
        # unreachable remote can never stall the harness tool-discovery handshake.
        # A provider that misses the budget keeps running in the background and
        # populates its on-disk tool cache, so it appears on the next discovery.
        enabled = [adapter for adapter in self.adapters() if adapter.descriptor().enabled]
        if not enabled:
            return []
        executor = ThreadPoolExecutor(max_workers=max(1, len(enabled)))
        futures = [(adapter, executor.submit(adapter.list_tools)) for adapter in enabled]
        deadline = time.monotonic() + DISCOVERY_BUDGET_SECONDS
        tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        for adapter, future in futures:
            remaining = deadline - time.monotonic()
            try:
                adapter_tools = future.result(timeout=max(0.0, remaining))
            except Exception:
                adapter_tools = []
            for tool in adapter_tools:
                name = str(tool.get("name") or "")
                if name and name not in seen:
                    tools.append(tool)
                    seen.add(name)
        executor.shutdown(wait=False, cancel_futures=True)
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        for adapter in self.adapters():
            if adapter.descriptor().enabled and adapter.owns_tool(name):
                return adapter.call_tool(name, arguments)
        raise ConfigurationError(f"no enabled provider owns tool: {name}")

    def secret_values(self) -> tuple[str, ...]:
        values: list[str] = []
        for adapter in self.adapters():
            values.extend(adapter.secret_values())
        return tuple(values)

    def redact(self, value: object) -> str:
        return redact_text(str(value), self.secret_values())
