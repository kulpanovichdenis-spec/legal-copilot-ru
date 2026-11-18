"""Direct local read-only adapter for DaData party lookup."""

from __future__ import annotations

import json
import re
import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx
import truststore

from ..config import ConfigurationError, ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from .base import ProviderAdapter


ALLOWED_HOST = "suggestions.dadata.ru"
ALLOWED_PATH = "/suggestions/api/4_1/rs/findById/party"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class DaDataPartyAdapter(ProviderAdapter):
    def __init__(
        self,
        connection: ProviderConnection,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.connection = connection
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.connection.provider_id,
            adapter=self.connection.adapter,
            enabled=self.connection.enabled,
            configured=self.connection.configured,
            endpoint=self.connection.endpoint,
            priority=self.connection.priority,
            capabilities=self.connection.capabilities,
            missing_secrets=self.connection.missing_secrets,
        )

    def secret_values(self) -> tuple[str, ...]:
        return self.connection.secret_values()

    def _endpoint(self) -> str:
        endpoint = str(self.connection.endpoint or "").strip()
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != ALLOWED_HOST
            or parsed.port not in {None, 443}
            or parsed.path != ALLOWED_PATH
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("DaData endpoint is outside the adapter allowlist")
        return endpoint

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        if not self.connection.configured:
            return ProviderHealth(self.connection.provider_id, "not_configured")
        return ProviderHealth(
            self.connection.provider_id,
            "configured_not_probed",
            detail="live probe skipped to avoid spending the DaData request quota",
        )

    def owns_tool(self, name: str) -> bool:
        return name == "dadata_party"

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "dadata_party",
                "description": "Find a Russian company or sole proprietor by INN, OGRN or OGRNIP through the direct local DaData connection.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "pattern": "^[0-9]{10,15}$"},
                        "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                    },
                },
            }
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name != "dadata_party":
            raise KeyError(f"unknown DaData tool: {name}")
        query = str(arguments.get("query") or "").strip()
        if not re.fullmatch(r"(?:\d{10}|\d{12}|\d{13}|\d{15})", query):
            raise ValueError("query must be a 10/12-digit INN, 13-digit OGRN or 15-digit OGRNIP")
        count = int(arguments.get("count", 1))
        if count < 1 or count > 20:
            raise ValueError("count must be between 1 and 20")
        api_key = self.connection.secret("api_key")
        secret_key = self.connection.secret("secret_key")
        if not api_key or not secret_key:
            raise ConfigurationError("DaData credentials are not configured")
        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ) as client:
            response = client.post(
                self._endpoint(),
                json={"query": query, "count": count},
                headers={
                    "Authorization": f"Token {api_key}",
                    "X-Secret": secret_key,
                    "Accept": "application/json",
                },
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("DaData response exceeds the 5 MiB safety limit")
        if response.status_code == 429:
            raise RuntimeError("DaData rate limit exceeded")
        if response.status_code >= 400:
            raise RuntimeError(f"DaData request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("DaData returned non-JSON content") from exc
