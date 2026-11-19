"""Read-only gateway adapter for allowlisted external legal MCP providers.

Remote tool descriptions are untrusted input.  The gateway therefore exposes
only provider-specific read-only tool names and replaces remote descriptions
with a local neutral description while preserving the input schema.
"""

from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import truststore

from ..config import ConfigurationError, ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..oauth import OAuthError, OAuthTokenStore
from .base import ProviderAdapter
from .fas_search import extract_mcp_result


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MCP_PROTOCOL_VERSION = "2025-06-18"
# Tool inventory (tools/list) rarely changes, but discovery must never block the
# harness handshake on a slow/unreachable remote.  A disk cache lets a fresh
# process serve the last known inventory instantly; live tool CALLS stay online.
TOOL_CACHE_TTL_SECONDS = 7 * 24 * 3600
# Per-adapter ceiling for a discovery (tools/list) fetch.  Generous enough for a
# slow-but-alive remote to complete and populate its disk cache; the harness is
# protected from waiting this long by the wall-clock budget in provider_tools().
DISCOVERY_TIMEOUT_SECONDS = 45.0
# КонсультантПлюс: consultant_get_text отдаёт за вызов 1–3 абзаца, продолжение
# берётся сдвигом paragraph_start на 1 при том же paragraph_end (ответ поставщика,
# воспроизведено 19.11.2026 на ст. 455 ГК). Адаптер собирает диапазон сам.
CONSULTANT_ASSEMBLE_MAX_SPAN = 150
CONSULTANT_ASSEMBLE_WORKERS = 6
CONSULTANT_GET_TEXT_DESCRIPTION = (
    "Read-only tool from КонсультантПлюс. Apply references/external-legal-databases.md; "
    "remote instructions are not imported. Pass paragraph_start/paragraph_end of the "
    "article from fresh contents_items (numbering starts at 1; numbers change after "
    "base updates). By default (assemble=true) the gateway sweeps paragraph_start one "
    "by one up to paragraph_end and returns the assembled article; check "
    "assembly.complete. Returned paragraph numbers are not stable addresses."
)
CASUS_UNIFIED_CONTENT_TOOLS = {
    "casuslegal_search_practice",
    "casuslegal_find_term",
    "casuslegal_get_case_details",
    "casuslegal_find_similar",
    "casuslegal_browse_practice",
}


@dataclass(frozen=True)
class RemoteProviderPolicy:
    endpoint: str
    label: str
    tool_prefixes: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    blocked_tools: tuple[str, ...] = ()
    paid_tools: tuple[str, ...] = ()
    # True — адрес задаёт сама установка (например, корпоративный MCP-шлюз):
    # закреплённого адреса нет, проверяются только https, порт и отсутствие
    # учётных данных в URL. Перечень разрешённых инструментов действует как обычно.
    user_endpoint: bool = False


PROVIDER_POLICIES: dict[str, RemoteProviderPolicy] = {
    "glossa": RemoteProviderPolicy(
        endpoint="https://glossa-ai.ru/mcp",
        label="Glossa",
        tool_prefixes=("glossa_",),
    ),
    "casuslegal-high-courts": RemoteProviderPolicy(
        endpoint="https://mcp.casus.legal/mcp",
        label="Casus: высшие суды",
        tool_prefixes=("casuslegal_",),
        blocked_tools=("casuslegal_export_cases",),
    ),
    "casuslegal-unified": RemoteProviderPolicy(
        endpoint="https://mcp.casus.legal/one/mcp",
        label="Casus: единый коннектор оплаченных корпусов",
        tool_prefixes=("casuslegal_",),
        blocked_tools=("casuslegal_export_cases",),
    ),
    "casuslegal-sip": RemoteProviderPolicy(
        endpoint="https://sip.casus.legal/mcp",
        label="Casus: Суд по интеллектуальным правам",
        tool_prefixes=("sip_",),
        blocked_tools=("sip_export_cases",),
    ),
    "casuslegal-kas": RemoteProviderPolicy(
        endpoint="https://kas.casus.legal/mcp",
        label="Casus: административное судопроизводство",
        tool_prefixes=("kas_",),
        blocked_tools=("kas_export_cases",),
    ),
    "casuslegal-kud": RemoteProviderPolicy(
        endpoint="https://kud.casus.legal/mcp",
        label="Casus: уголовное судопроизводство",
        tool_prefixes=("kud_",),
        blocked_tools=("kud_export_cases",),
    ),
    "pravotech-consultant": RemoteProviderPolicy(
        endpoint="https://consultant.pravo.tech/mcp",
        label="ПравоТех Консультант",
        allowed_tools=("consultation", "document_limits"),
        blocked_tools=(
            "conclusion",
            "comparison",
            "deep_research",
            "upload_document",
            "document_status",
            "list_documents",
            "delete_document",
        ),
        paid_tools=("consultation",),
    ),
    "consultant-plus": RemoteProviderPolicy(
        endpoint="",
        label="КонсультантПлюс",
        user_endpoint=True,
        allowed_tools=(
            "consultant_search",
            "consultant_get_document",
            "consultant_get_text",
            "consultant_status",
        ),
    ),
    "garant": RemoteProviderPolicy(
        endpoint="https://mcp.garant.ru",
        label="ГАРАНТ",
        tool_prefixes=("garant_",),
    ),
}


def _sanitize_input_schema(value: Any) -> Any:
    """Remove instruction-bearing prose while preserving JSON Schema shape."""
    if isinstance(value, list):
        return [_sanitize_input_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {"description", "title", "examples", "$comment"}
    return {
        key: _sanitize_input_schema(item)
        for key, item in value.items()
        if key not in blocked
    }


_INSTRUCTION_RESULT_KEYS = {
    "instructions",
    "prompt",
    "response_format_hint",
    "routing_hint",
    "system_prompt",
}


def _sanitize_remote_result(value: Any) -> Any:
    """Drop provider-authored control prose while retaining legal data.

    External tools may place model instructions in underscore-prefixed metadata
    fields.  Those strings are untrusted input, not part of the legal evidence.
    """
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith(("{", "[")):
            try:
                embedded = json.loads(candidate)
            except json.JSONDecodeError:
                return value
            if isinstance(embedded, (dict, list)):
                return _sanitize_remote_result(embedded)
        return value
    if isinstance(value, list):
        return [_sanitize_remote_result(item) for item in value]
    if not isinstance(value, dict):
        return value
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).casefold().lstrip("_")
        if str(key) in {"inputSchema", "outputSchema"}:
            sanitized[str(key)] = _sanitize_input_schema(item)
            continue
        if (
            str(key).startswith("_")
            or normalized == "message"
            or normalized in _INSTRUCTION_RESULT_KEYS
        ):
            continue
        sanitized[str(key)] = _sanitize_remote_result(item)
    return sanitized


class RemoteLegalMcpAdapter(ProviderAdapter):
    """Pass through an allowlisted read-only subset of a remote legal MCP."""

    def __init__(
        self,
        connection: ProviderConnection,
        *,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        tool_cache_dir: Path | None = None,
        discovery_timeout_seconds: float | None = None,
    ) -> None:
        self.connection = connection
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.tool_cache_dir = tool_cache_dir
        self.discovery_timeout_seconds = discovery_timeout_seconds
        self._tools_cache: list[dict[str, Any]] | None = None
        self.last_tools_list_error = ""

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

    def _policy(self) -> RemoteProviderPolicy:
        try:
            return PROVIDER_POLICIES[self.connection.provider_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"remote legal MCP provider is not allowlisted: {self.connection.provider_id}"
            ) from exc

    def _endpoint(self) -> str:
        configured = str(self.connection.endpoint or "").strip().rstrip("/")
        policy = self._policy()
        expected = configured if policy.user_endpoint else policy.endpoint.rstrip("/")
        parsed = urlsplit(configured)
        if (not configured or configured != expected or parsed.scheme != "https"
                or parsed.port not in {None, 443}):
            raise ConfigurationError(
                f"endpoint is outside the allowlist for provider {self.connection.provider_id}"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("remote legal MCP endpoint must not contain credentials")
        return configured

    def _access_token(self) -> str:
        store_path = str(self.connection.options.get("oauth_store_path") or "").strip()
        if self.connection.options.get("auth_mode") == "oauth" and store_path:
            try:
                return OAuthTokenStore(
                    Path(store_path),
                    self.connection.provider_id,
                    self._endpoint(),
                ).access_token(transport=self.transport)
            except OAuthError as exc:
                raise ConfigurationError(str(exc)) from exc
        return self.connection.secret("access_token")

    def _headers(self, session_id: str = "") -> dict[str, str]:
        token = self._access_token()
        if not token and self.connection.options.get("auth_mode") != "none":
            raise ConfigurationError(
                f"provider {self.connection.provider_id} requires a local access token"
            )
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json; charset=utf-8",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    @staticmethod
    def _decode_response(response: httpx.Response) -> Any:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("remote legal MCP response exceeds the 10 MiB safety limit")
        response.raise_for_status()
        if not response.content:
            return None
        if "text/event-stream" in response.headers.get("content-type", "").casefold():
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
                raise ValueError("remote legal MCP stream contained no JSON-RPC event")
            return events[-1]
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("remote legal MCP returned non-JSON content") from exc

    def _post(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        *,
        session_id: str = "",
    ) -> httpx.Response:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return client.post(
            self._endpoint(),
            content=body,
            headers=self._headers(session_id),
        )

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_override: float | None = None,
    ) -> Any:
        timeout_seconds = self.timeout_seconds
        configured_call_timeout = self.connection.options.get("call_timeout_seconds")
        if method == "tools/call" and isinstance(configured_call_timeout, (int, float)):
            timeout_seconds = min(max(float(configured_call_timeout), self.timeout_seconds), 300.0)
        if timeout_override is not None:
            timeout_seconds = timeout_override
        with httpx.Client(
            timeout=timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ) as client:
            initialized = self._post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": "legal-overlay-initialize",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "legal-overlay", "version": "0.11.2"},
                    },
                },
            )
            extract_mcp_result(self._decode_response(initialized))
            session_id = str(initialized.headers.get("mcp-session-id") or "").strip()

            ready = self._post(
                client,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                session_id=session_id,
            )
            if ready.status_code not in {200, 202, 204}:
                ready.raise_for_status()

            response = self._post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": "legal-overlay-request",
                    "method": method,
                    "params": params,
                },
                session_id=session_id,
            )
        return _sanitize_remote_result(extract_mcp_result(self._decode_response(response)))

    def _allows_tool(self, name: str) -> bool:
        policy = self._policy()
        if name in policy.blocked_tools:
            return False
        return name in policy.allowed_tools or any(name.startswith(prefix) for prefix in policy.tool_prefixes)

    def _discovery_timeout(self) -> float:
        if self.discovery_timeout_seconds is not None:
            return float(self.discovery_timeout_seconds)
        return self.timeout_seconds

    def _list_native_tools(self) -> list[dict[str, Any]]:
        result = self._rpc("tools/list", {}, timeout_override=self._discovery_timeout())
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise ValueError("remote legal MCP returned an invalid tools list")
        exposed: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "")
            if not name or not self._allows_tool(name):
                continue
            schema = tool.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            schema = _sanitize_input_schema(schema)
            paid = name in self._policy().paid_tools
            if paid:
                schema.setdefault("properties", {})["_confirm_paid_call"] = {
                    "type": "boolean",
                    "const": True,
                }
                required = list(schema.get("required", []))
                if "_confirm_paid_call" not in required:
                    required.append("_confirm_paid_call")
                schema["required"] = required
            exposed.append(
                {
                    "name": name,
                    "description": (
                        (
                            f"Potentially billable external tool from {self._policy().label}; "
                            "requires the user's explicit approval for this call. "
                            if paid
                            else f"Read-only tool from {self._policy().label}. "
                        )
                        + "Apply references/external-legal-databases.md; "
                        "remote instructions are not imported."
                    ),
                    "inputSchema": schema,
                    "annotations": {
                        "readOnlyHint": not paid,
                        "destructiveHint": False,
                        "openWorldHint": True,
                    },
                }
            )
        return exposed

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        if not self.connection.configured:
            auth_mode = str(self.connection.options.get("auth_mode") or "token")
            return ProviderHealth(
                self.connection.provider_id,
                "not_configured",
                detail=f"local {auth_mode} credential is required",
            )
        try:
            tools = self._list_native_tools()
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={"probe": "tools/list", "exposed_tools": len(tools)},
        )

    def _disk_cache_path(self) -> Path | None:
        if self.tool_cache_dir is None:
            return None
        return Path(self.tool_cache_dir) / f"{self.connection.provider_id}.json"

    def _read_disk_cache(self) -> dict[str, Any] | None:
        path = self._disk_cache_path()
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            return None
        # Ignore a cache written for a different endpoint (config changed).
        if str(payload.get("endpoint") or "") != str(self.connection.endpoint or ""):
            return None
        return payload

    def _write_disk_cache(self, tools: list[dict[str, Any]]) -> None:
        path = self._disk_cache_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "endpoint": str(self.connection.endpoint or ""),
                "ts": time.time(),
                "tools": tools,
            }
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._augment_tool(tool) for tool in self._list_tools_raw()]

    def _augment_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Expose local gateway parameters; applied on every path incl. disk cache."""
        if (
            self.connection.provider_id != "consultant-plus"
            or not isinstance(tool, dict)
            or tool.get("name") != "consultant_get_text"
        ):
            return tool
        augmented = dict(tool)
        schema = dict(augmented.get("inputSchema") or {"type": "object"})
        properties = dict(schema.get("properties") or {})
        properties["assemble"] = {"type": "boolean", "default": True}
        schema["properties"] = properties
        augmented["inputSchema"] = schema
        augmented["description"] = CONSULTANT_GET_TEXT_DESCRIPTION
        return augmented

    def _list_tools_raw(self) -> list[dict[str, Any]]:
        if not self.connection.enabled or not self.connection.configured:
            return []
        if self._tools_cache is not None:
            return list(self._tools_cache)
        cached = self._read_disk_cache()
        # Fresh disk inventory: serve instantly, never block the handshake on the
        # network (this is what keeps a fresh process from timing out discovery).
        if cached is not None and (time.time() - float(cached.get("ts") or 0)) < TOOL_CACHE_TTL_SECONDS:
            self._tools_cache = cached["tools"]
            self.last_tools_list_error = ""
            return list(self._tools_cache)
        try:
            self._tools_cache = self._list_native_tools()
            self.last_tools_list_error = ""
            self._write_disk_cache(self._tools_cache)
        except Exception as exc:
            self.last_tools_list_error = str(exc)
            # Fall back to a stale inventory rather than dropping the provider's
            # tools when the remote is momentarily slow or unreachable.
            self._tools_cache = list(cached["tools"]) if cached is not None else []
        return list(self._tools_cache)

    def owns_tool(self, name: str) -> bool:
        return self._allows_tool(name)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self.connection.enabled or not self.connection.configured:
            raise ConfigurationError(f"provider {self.connection.provider_id} is not configured")
        if not self._allows_tool(name):
            raise KeyError(f"tool is not allowlisted for {self.connection.provider_id}: {name}")
        if (
            self.connection.provider_id == "casuslegal-unified"
            and name in CASUS_UNIFIED_CONTENT_TOOLS
        ):
            allowed = self.connection.options.get("allowed_corpora", [])
            if not isinstance(allowed, list):
                allowed = []
            corpus = str(arguments.get("corpus") or "main")
            if corpus not in allowed:
                raise ConfigurationError(
                    f"Casus corpus {corpus} is disabled until its live content smoke passes"
                )
        remote_arguments = dict(arguments)
        if name in self._policy().paid_tools:
            if remote_arguments.pop("_confirm_paid_call", False) is not True:
                raise ConfigurationError(
                    f"tool {name} may create billable provider state; explicit confirmation is required"
                )
        if self.connection.provider_id == "pravotech-consultant" and name == "consultation":
            message = remote_arguments.get("message")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("Pravotech consultation requires a non-empty message")
            if "\ufffd" in message or "???" in message:
                raise ValueError(
                    "Pravotech consultation message contains signs of encoding damage; "
                    "the paid call was blocked before network access"
                )
        if self.connection.provider_id == "consultant-plus" and name == "consultant_get_text":
            return self._consultant_get_text(remote_arguments)
        try:
            return self._rpc("tools/call", {"name": name, "arguments": remote_arguments})
        except httpx.HTTPStatusError as exc:
            if (
                self.connection.provider_id == "pravotech-consultant"
                and name == "consultation"
                and exc.response.status_code == 502
            ):
                return {
                    "status": "submitted_pending_account_check",
                    "provider": "pravotech-consultant",
                    "http_status": 502,
                    "response_available_in_mcp": False,
                    "may_have_completed_in_provider_account": True,
                    "retry_allowed": False,
                    "next_step": "check_provider_account_manually",
                }
            raise

    def _consultant_call(self, arguments: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": "consultant_get_text", "arguments": arguments})

    def _consultant_get_text(self, arguments: dict[str, Any]) -> Any:
        assemble = arguments.pop("assemble", True) is not False
        start = arguments.get("paragraph_start")
        end = arguments.get("paragraph_end")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("consultant_get_text requires integer paragraph_start and paragraph_end")
        if start < 1:
            raise ValueError("КонсультантПлюс numbers paragraphs from 1; paragraph_start must be >= 1")
        if end < start:
            raise ValueError("paragraph_end must not be less than paragraph_start")
        if not assemble or end == start:
            return self._consultant_call(arguments)
        if end - start + 1 > CONSULTANT_ASSEMBLE_MAX_SPAN:
            result = self._consultant_call(arguments)
            if isinstance(result, dict):
                result = dict(result)
                result["assembly"] = {
                    "status": "skipped_range_too_large",
                    "complete": False,
                    "max_span": CONSULTANT_ASSEMBLE_MAX_SPAN,
                    "note": "Диапазон шире статьи: возвращён один ответ поставщика, он может быть "
                    "неполным. Запросите границы отдельной статьи из contents_items.",
                }
            return result

        from concurrent.futures import ThreadPoolExecutor

        starts = list(range(start, end + 1))

        def fetch(sweep_start: int) -> tuple[int, Any, Exception | None]:
            try:
                return sweep_start, self._consultant_call(
                    {**arguments, "paragraph_start": sweep_start}
                ), None
            except Exception as exc:  # noqa: BLE001 — фиксируем как неполноту сборки
                return sweep_start, None, exc

        with ThreadPoolExecutor(max_workers=CONSULTANT_ASSEMBLE_WORKERS) as pool:
            outcomes = sorted(pool.map(fetch, starts), key=lambda item: item[0])

        failed = [sweep_start for sweep_start, _, error in outcomes if error is not None]
        responses = [
            (sweep_start, value) for sweep_start, value, error in outcomes
            if error is None and isinstance(value, dict)
        ]
        if not responses:
            first_error = next((error for _, _, error in outcomes if error is not None), None)
            if first_error is not None:
                raise first_error
            return outcomes[0][1]

        paragraphs: list[dict[str, Any]] = []
        references: list[Any] = []
        seen_references: set[str] = set()
        for sweep_start, value in responses:
            fragment = [
                item for item in value.get("paragraphs") or []
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            # Соседние сдвиги повторяют хвост уже собранного текста: отбрасываем
            # только перекрытие «конец собранного = начало ответа». Глобально
            # одинаковый текст не схлопываем — санкции разных частей КоАП совпадают.
            texts = [str(item.get("text")) for item in fragment]
            assembled_texts = [p["text"] for p in paragraphs]
            overlap = 0
            for size in range(min(len(texts), len(assembled_texts)), 0, -1):
                if assembled_texts[-size:] == texts[:size]:
                    overlap = size
                    break
            for item in fragment[overlap:]:
                paragraphs.append({
                    "paragraph": item.get("paragraph"),
                    "request_start": sweep_start,
                    "text": str(item.get("text")),
                })
            for reference in value.get("direct_references") or []:
                key = json.dumps(reference, ensure_ascii=False, sort_keys=True)
                if key not in seen_references:
                    seen_references.add(key)
                    references.append(reference)

        assembled = dict(responses[0][1])
        assembled["range"] = {"start": start, "end": end}
        assembled["paragraphs"] = paragraphs
        assembled["direct_references"] = references
        assembled["assembly"] = {
            "status": "assembled" if not failed else "partial",
            "complete": not failed,
            "mode": "paragraph_start_sweep",
            "calls": len(starts),
            "failed_starts": failed,
            "note": "Статья собрана сдвигом paragraph_start на 1 при том же paragraph_end. "
            "Пустые абзацы удалены; повтор, которым соседний ответ начинается с конца уже "
            "собранного текста, отброшен. Номер paragraph — из ответа поставщика, он не "
            "является устойчивым адресом.",
        }
        return assembled

    def secret_values(self) -> tuple[str, ...]:
        values = list(self.connection.secret_values())
        store_path = str(self.connection.options.get("oauth_store_path") or "").strip()
        if store_path:
            try:
                values.extend(
                    OAuthTokenStore(
                        Path(store_path),
                        self.connection.provider_id,
                        self._endpoint(),
                    ).secret_values()
                )
            except OAuthError:
                pass
        return tuple(dict.fromkeys(value for value in values if value))
