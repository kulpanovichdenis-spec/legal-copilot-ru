"""Direct local adapter for the external FAS advertising-practice MCP."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import ConfigurationError, ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from .base import ProviderAdapter


ALLOWED_HOSTS = {"search.delay-rag.ru"}
NATIVE_TOOLS = {"search_fas_cases", "get_case_details", "get_filter_options"}
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MCP_PROTOCOL_VERSION = "2025-06-18"


class FasRateLimitError(RuntimeError):
    """The public FAS provider rejected the request because its IP quota was exhausted."""


def extract_mcp_result(value: Any) -> Any:
    """Unwrap a JSON-RPC/MCP content envelope without assuming a double proxy layer."""
    current = value
    for _ in range(4):
        if isinstance(current, dict) and "error" in current:
            error = current["error"]
            if isinstance(error, dict):
                raise RuntimeError(str(error.get("message") or json.dumps(error, ensure_ascii=False)))
            raise RuntimeError(str(error))
        if isinstance(current, dict) and "result" in current:
            current = current["result"]
            continue
        if isinstance(current, dict) and isinstance(current.get("structuredContent"), (dict, list)):
            current = current["structuredContent"]
            continue
        if isinstance(current, dict) and isinstance(current.get("content"), list):
            texts = [
                str(item.get("text") or "")
                for item in current["content"]
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if not texts:
                return current
            text = texts[0]
            try:
                current = json.loads(text)
            except json.JSONDecodeError:
                return text
            continue
        break
    return current


class FasSearchAdapter(ProviderAdapter):
    def __init__(
        self,
        connection: ProviderConnection,
        *,
        timeout_seconds: float = 60.0,
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
            transitional_external_proxy=False,
            missing_secrets=self.connection.missing_secrets,
        )

    def _endpoint(self) -> str:
        endpoint = str(self.connection.endpoint or "").strip()
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HOSTS
            or parsed.port not in {None, 443}
            or parsed.path.rstrip("/") != "/mcp"
        ):
            raise ConfigurationError("FAS endpoint is outside the adapter allowlist")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("FAS endpoint must not contain credentials, query or fragment")
        return endpoint.rstrip("/") + "/"

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        )

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("FAS response exceeds the 10 MiB safety limit")
        if response.status_code == 429:
            retry_after = str(response.headers.get("retry-after") or "").strip()
            detail = f"; retry after {retry_after}" if retry_after else ""
            raise FasRateLimitError(f"FAS provider rate limit exceeded{detail}")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").casefold()
        if "text/event-stream" in content_type:
            events: list[Any] = []
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
            if not events:
                raise ValueError("FAS stream contained no JSON-RPC event")
            return events[-1]
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("FAS provider returned non-JSON content") from exc

    def _request(self, payload: dict[str, Any]) -> Any:
        with self._client() as client:
            response = client.post(
                self._endpoint(),
                json=payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                },
            )
        return self._decode_response(response)

    def _call_native(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in NATIVE_TOOLS:
            raise KeyError(f"unknown FAS native tool: {name}")
        response = self._request(
            {
                "jsonrpc": "2.0",
                "id": "legal-overlay-fas",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return extract_mcp_result(response)

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        if not self.connection.configured:
            return ProviderHealth(self.connection.provider_id, "not_configured")
        try:
            value = self._call_native("get_filter_options", {})
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        data = {"probe": "get_filter_options"}
        if isinstance(value, dict):
            data["years"] = len(value.get("years", [])) if isinstance(value.get("years"), list) else 0
        return ProviderHealth(self.connection.provider_id, "connected", data=data)

    def list_tools(self) -> list[dict[str, Any]]:
        # Provider-native names stay private; the gateway exposes flat stable tools.
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._call_native(name, arguments)
