"""Provider adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import ProviderDescriptor, ProviderHealth


class ProviderAdapter(ABC):
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        """Return public capabilities and configuration state."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Perform a cheap read-only probe."""

    @abstractmethod
    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP-compatible tools exposed by this provider."""

    @abstractmethod
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a provider tool; lifecycle writes must enforce their own explicit safety gates."""

    def owns_tool(self, name: str) -> bool:
        """Return whether this adapter explicitly owns a tool name."""
        return False

    def secret_values(self) -> tuple[str, ...]:
        return ()
