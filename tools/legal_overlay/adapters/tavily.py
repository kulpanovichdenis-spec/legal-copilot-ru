"""Direct local read-only adapter for the Tavily HTTP API."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import ConfigurationError, ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from .base import ProviderAdapter


ALLOWED_HOST = "api.tavily.com"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
TOOL_NAMES = {"tavily_search", "tavily_extract", "tavily_research", "tavily_get_research"}


def _trimmed(value: Any, name: str, *, maximum: int = 10_000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum or any(char in text for char in "\r\n\0"):
        raise ValueError(f"{name} must be a single-line value of at most {maximum} characters")
    return text


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, name: str) -> int:
    number = default if value is None else int(value)
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _domains(value: Any, *, maximum: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"domains must be an array with at most {maximum} entries")
    result: list[str] = []
    for item in value:
        domain = str(item or "").strip().casefold().rstrip(".")
        if not domain or len(domain) > 253 or "://" in domain or any(char in domain for char in "/?#@"):
            raise ValueError("domain filters must contain host names only")
        result.append(domain)
    return result


def _urls(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValueError("urls must contain between 1 and 20 HTTP(S) URLs")
    result: list[str] = []
    for item in value:
        url = _trimmed(item, "url", maximum=2_048)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("each extract URL must be an absolute HTTP(S) URL without credentials")
        result.append(url)
    return result


class TavilyAdapter(ProviderAdapter):
    def __init__(
        self,
        connection: ProviderConnection,
        *,
        timeout_seconds: float = 120.0,
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

    def _base_url(self) -> str:
        endpoint = str(self.connection.endpoint or "").strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != ALLOWED_HOST
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Tavily endpoint is outside the adapter allowlist")
        return endpoint

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
        api_key = self.connection.secret("api_key")
        if not api_key:
            raise ConfigurationError("Tavily API key is not configured")
        with httpx.Client(timeout=self.timeout_seconds, transport=self.transport, follow_redirects=False) as client:
            response = client.request(
                method,
                f"{self._base_url()}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("Tavily response exceeds the 10 MiB safety limit")
        if response.status_code == 429:
            retry_after = str(response.headers.get("retry-after") or "").strip()
            suffix = f"; retry after {retry_after}" if retry_after else ""
            raise RuntimeError(f"Tavily rate limit exceeded{suffix}")
        if response.status_code >= 400:
            raise RuntimeError(f"Tavily request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("Tavily returned non-JSON content") from exc

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        if not self.connection.configured:
            return ProviderHealth(self.connection.provider_id, "not_configured")
        return ProviderHealth(
            self.connection.provider_id,
            "configured_not_probed",
            detail="live probe skipped because Tavily API calls consume credits",
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_NAMES

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "tavily_search",
                "description": "Search the public web through the direct local Tavily connection.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                        "search_depth": {"type": "string", "enum": ["basic", "advanced", "fast", "ultra-fast"], "default": "basic"},
                        "include_domains": {"type": "array", "maxItems": 300, "items": {"type": "string"}},
                        "exclude_domains": {"type": "array", "maxItems": 150, "items": {"type": "string"}},
                        "include_answer": {"type": ["boolean", "string"], "default": False},
                    },
                },
            },
            {
                "name": "tavily_extract",
                "description": "Extract public HTTP(S) pages through the direct local Tavily connection.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["urls"],
                    "properties": {
                        "urls": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string", "format": "uri"}},
                        "extract_depth": {"type": "string", "enum": ["basic", "advanced"], "default": "basic"},
                        "include_images": {"type": "boolean", "default": False},
                        "format": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
                        "query": {"type": "string"},
                        "chunks_per_source": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                },
            },
            {
                "name": "tavily_research",
                "description": "Create an asynchronous Tavily research task; use tavily_get_research to poll it.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "model": {"type": "string", "enum": ["mini", "pro", "auto"], "default": "mini"},
                        "citation_format": {"type": "string", "enum": ["numbered", "mla", "apa", "chicago"], "default": "numbered"},
                        "output_schema": {"type": "object"},
                    },
                },
            },
            {
                "name": "tavily_get_research",
                "description": "Get status or result of an asynchronous Tavily research task.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request_id"],
                    "properties": {"request_id": {"type": "string", "minLength": 8, "maxLength": 100}},
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "tavily_search":
            payload: dict[str, Any] = {
                "query": _trimmed(arguments.get("query"), "query"),
                "max_results": _bounded_int(arguments.get("max_results"), default=5, minimum=1, maximum=20, name="max_results"),
                "search_depth": str(arguments.get("search_depth") or "basic"),
                "include_answer": arguments.get("include_answer", False),
            }
            if payload["search_depth"] not in {"basic", "advanced", "fast", "ultra-fast"}:
                raise ValueError("unsupported search_depth")
            included = _domains(arguments.get("include_domains"), maximum=300)
            excluded = _domains(arguments.get("exclude_domains"), maximum=150)
            if included:
                payload["include_domains"] = included
            if excluded:
                payload["exclude_domains"] = excluded
            return self._request("POST", "/search", payload=payload)
        if name == "tavily_extract":
            depth = str(arguments.get("extract_depth") or "basic")
            output_format = str(arguments.get("format") or "markdown")
            if depth not in {"basic", "advanced"} or output_format not in {"markdown", "text"}:
                raise ValueError("unsupported Tavily extract option")
            payload = {
                "urls": _urls(arguments.get("urls")),
                "extract_depth": depth,
                "include_images": bool(arguments.get("include_images", False)),
                "format": output_format,
            }
            if arguments.get("query"):
                payload["query"] = _trimmed(arguments["query"], "query")
            if arguments.get("chunks_per_source") is not None:
                payload["chunks_per_source"] = _bounded_int(arguments["chunks_per_source"], default=3, minimum=1, maximum=5, name="chunks_per_source")
            return self._request("POST", "/extract", payload=payload)
        if name == "tavily_research":
            model = str(arguments.get("model") or "mini")
            citation_format = str(arguments.get("citation_format") or "numbered")
            if model not in {"mini", "pro", "auto"} or citation_format not in {"numbered", "mla", "apa", "chicago"}:
                raise ValueError("unsupported Tavily research option")
            payload = {
                "input": _trimmed(arguments.get("query"), "query"),
                "model": model,
                "stream": False,
                "citation_format": citation_format,
            }
            if arguments.get("output_schema") is not None:
                payload["output_schema"] = arguments["output_schema"]
            return self._request("POST", "/research", payload=payload)
        if name == "tavily_get_research":
            request_id = _trimmed(arguments.get("request_id"), "request_id", maximum=100)
            if not re.fullmatch(r"[A-Za-z0-9-]{8,100}", request_id):
                raise ValueError("request_id has an invalid format")
            return self._request("GET", f"/research/{request_id}")
        raise KeyError(f"unknown Tavily tool: {name}")
