#!/usr/bin/env python3
"""One local MCP entry point for Codex, Claude and future harnesses."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .fas_search import FasSearchRouter
from .models import SCHEMA_DIR
from .official_text import OfficialTextRouter
from .registry import ProviderRegistry
from .search import LegalSearchEngine
from .source_profiles import SourceProfile, load_source_profiles, source_profile_map


GATEWAY_VERSION = "0.12.0"


def _response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _tool_result(value: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}]}


class OverlayMCPServer:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        source_profiles: tuple[SourceProfile, ...] | None = None,
        stderr: Callable[[str], None] | None = None,
    ) -> None:
        self.registry = registry
        self.source_profiles = source_profiles if source_profiles is not None else load_source_profiles()
        self._source_profile_map = source_profile_map(self.source_profiles)
        self.search_engine = LegalSearchEngine(registry, source_profiles=self.source_profiles)
        self.fas_search = FasSearchRouter(registry)
        self.official_text = OfficialTextRouter(registry)
        self._legal_search_schema = json.loads(
            (SCHEMA_DIR / "legal-search-request.schema.json").read_text(encoding="utf-8")
        )
        self.stderr = stderr or (lambda message: print(message, file=sys.stderr))

    def _listed_sources(self) -> list[dict[str, Any]]:
        connections = {item["id"]: item for item in self.registry.descriptors()}
        sources: list[dict[str, Any]] = []
        referenced_connections: set[str] = set()
        for profile in self.source_profiles:
            item = profile.to_dict()
            connection_ref = item.get("connection_ref")
            if connection_ref in connections:
                item["connection"] = connections[connection_ref]
                referenced_connections.add(str(connection_ref))
            sources.append(item)
        for provider_id, descriptor in connections.items():
            if provider_id not in referenced_connections:
                sources.append(descriptor)
        return sources

    def _overlay_tools(self) -> dict[str, dict[str, Any]]:
        return {
            "overlay_status": {
                "description": "Show configured local Legal Overlay providers; set probe=true for read-only health checks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"probe": {"type": "boolean", "default": False}},
                },
                "handler": lambda args: {
                    "gateway": "legal-overlay",
                    "version": GATEWAY_VERSION,
                    "providers": self.registry.statuses(probe=bool(args.get("probe", False))),
                },
            },
            "list_legal_sources": {
                "description": "List provider-neutral source capabilities without returning credentials.",
                "inputSchema": {"type": "object", "properties": {}},
                "handler": lambda _args: {"sources": self._listed_sources()},
            },
            "get_source_profile": {
                "description": "Get the local interaction guidance and protocol references for one legal source.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"source_id": {"type": "string"}},
                    "required": ["source_id"],
                },
                "handler": self._get_source_profile,
            },
            "route_norm_verification": {
                "description": "List currently usable sources for full-text norm verification; snapshots and search snippets never qualify.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "jurisdiction": {"type": "string", "minLength": 2},
                        "probe": {"type": "boolean", "default": True},
                    },
                    "required": ["jurisdiction"],
                },
                "handler": self._route_norm_verification,
            },
            "legal_search": {
                "description": "Run provider-neutral legal search and return a provenance-preserving EvidenceBundle.",
                "inputSchema": self._legal_search_schema,
                "handler": self.search_engine.search,
            },
            "route_legal_query": {
                "description": "Route a query to the local RU/EAEU, labor-guidance, unified-doctrine or Uzbekistan SQLite corpus.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"query": {"type": "string", "minLength": 1}},
                    "required": ["query"],
                },
                "handler": self._route_legal_query,
            },
            "get_official_document": {
                "description": "Fetch live official text from pravo.gov.ru using canonical identity from the local RU snapshot.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["canonical_key"],
                    "properties": {
                        "canonical_key": {"type": "string", "minLength": 1},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 50000},
                        "force_refresh": {"type": "boolean", "default": False},
                    },
                },
                "handler": self.official_text.get_document,
            },
            "get_official_article": {
                "description": "Fetch one live official article from pravo.gov.ru using canonical identity from the local RU snapshot.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["canonical_key"],
                    "properties": {
                        "canonical_key": {"type": "string", "minLength": 1},
                        "article": {"type": ["string", "number"]},
                        "article_number": {"type": ["string", "number"]},
                        "force_refresh": {"type": "boolean", "default": False},
                    },
                },
                "handler": self.official_text.get_article,
            },
            "search_fas_ad_practice": {
                "description": "Search FAS advertising practice through a stable local contract with provenance and fallback reporting.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "filters": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "year": {
                                    "anyOf": [
                                        {"type": "integer", "minimum": 2000, "maximum": 2100},
                                        {
                                            "type": "array",
                                            "items": {"type": "integer", "minimum": 2000, "maximum": 2100},
                                            "minItems": 1,
                                            "maxItems": 20,
                                        },
                                    ]
                                },
                                "region": {
                                    "anyOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                                    ]
                                },
                                "article": {
                                    "anyOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                                    ]
                                },
                            },
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 15, "default": 5},
                        "data_classification": {
                            "enum": ["public_or_abstracted", "internal", "confidential", "personal_data"],
                            "default": "public_or_abstracted",
                        },
                    },
                },
                "handler": self.fas_search.search,
            },
            "get_fas_case": {
                "description": "Fetch one to five FAS case cards by docId through the stable provider-neutral route.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "anyOf": [{"required": ["case_id"]}, {"required": ["case_ids"]}],
                    "properties": {
                        "case_id": {"type": "string", "minLength": 1, "maxLength": 300},
                        "case_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1, "maxLength": 300},
                            "minItems": 1,
                            "maxItems": 5,
                        },
                    },
                },
                "handler": self.fas_search.get_case,
            },
            "list_fas_filter_options": {
                "description": "List years, regions and legal provisions supported by the configured FAS practice provider.",
                "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
                "handler": self.fas_search.list_filter_options,
            },
        }

    def _get_source_profile(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source_id = str(arguments.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source_id is required")
        try:
            return self._source_profile_map[source_id].to_dict(include_body=True)
        except KeyError as exc:
            raise KeyError(f"unknown source profile: {source_id}") from exc

    def _route_norm_verification(self, arguments: dict[str, Any]) -> dict[str, Any]:
        jurisdiction = str(arguments.get("jurisdiction") or "").strip().upper()
        if len(jurisdiction) < 2:
            raise ValueError("jurisdiction is required")
        probe = bool(arguments.get("probe", True))
        routes: list[dict[str, Any]] = []

        for profile in self.source_profiles:
            metadata = profile.metadata
            roles = set(metadata["verification_roles"])
            if not roles.intersection({"norm_verification", "candidate_norm_verification"}):
                continue
            if jurisdiction not in {str(item).upper() for item in metadata["jurisdictions"]}:
                continue

            contract = metadata["norm_verification"]
            connection_ref = metadata.get("connection_ref")
            runtime_status = str(metadata["status"])
            runtime_detail = ""
            descriptor: dict[str, Any] | None = None
            if connection_ref:
                try:
                    adapter = self.registry.adapter(str(connection_ref))
                    descriptor = adapter.descriptor().to_dict()
                    if not descriptor["enabled"]:
                        runtime_status = "disabled"
                    elif not descriptor["configured"]:
                        runtime_status = "not_configured"
                    elif probe:
                        health = adapter.health().to_dict()
                        runtime_status = str(health["status"])
                        runtime_detail = str(health.get("detail") or "")
                    else:
                        runtime_status = "configured_not_probed"
                except Exception as exc:
                    runtime_status = "not_available"
                    runtime_detail = self.registry.redact(exc)

            qualified = bool(contract["eligible"])
            usable_now = qualified and runtime_status == "connected"
            reasons: list[str] = []
            if not qualified:
                reasons.append(str(contract["mode"]))
            if qualified and not probe:
                reasons.append("live_probe_required")
            elif qualified and runtime_status != "connected":
                reasons.append(f"runtime_status:{runtime_status}")

            item = {
                "source_id": profile.source_id,
                "authority_level": metadata["authority_level"],
                "verification_roles": list(metadata["verification_roles"]),
                "coverage": dict(metadata["coverage"]),
                "norm_verification": dict(contract),
                "runtime_status": runtime_status,
                "usable_now": usable_now,
                "reasons": reasons,
            }
            if descriptor is not None:
                item["connection"] = descriptor
            if runtime_detail:
                item["runtime_detail"] = runtime_detail
            routes.append(item)

        routes.sort(
            key=lambda item: (
                not item["usable_now"],
                item["norm_verification"]["mode"] != "live_official",
                item["source_id"],
            )
        )
        recommended = next((item for item in routes if item["usable_now"]), None)
        return {
            "jurisdiction": jurisdiction,
            "probe_performed": probe,
            "recommended_source": recommended["source_id"] if recommended else None,
            "recommended_tools": recommended["norm_verification"]["verified_tools"] if recommended else [],
            "routes": routes,
            "rule": (
                "Search cards, SQLite results and snippets are navigation only. "
                "Use a route only when usable_now=true, open the full text and record edition/status/provenance."
            ),
            "coverage_gap": None if recommended else "no_connected_norm_verification_source",
        }

    @staticmethod
    def _route_legal_query(arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        normalized = query.casefold()
        uz_markers = ("узбек", "lex.uz", "республика узбекистан", "uzbekistan")
        ru_markers = ("росси", "рф", "еаэс", "евразийск", "фз", "гк рф", "коап")
        doctrine_markers = (
            "доктрин",
            "постатейн",
            "монограф",
        )
        labor_markers = (
            "трудов",
            "работодатель",
            "работник",
            "прием на работу",
            "приём на работу",
            "испытательн",
            "увольнен",
        )
        # «Медицинский/фармацевтический работник», реклама ЛП — фарм-регулирование,
        # а не трудовой вопрос: одного слова «работник» в таком контексте мало.
        pharma_worker_context = ("медицинск", "фармацевтическ", "реклам", "лекарствен")
        matched_uz = [marker for marker in uz_markers if marker in normalized]
        matched_ru = [marker for marker in ru_markers if marker in normalized]
        matched_doctrine = [marker for marker in doctrine_markers if marker in normalized]
        matched_labor = [marker for marker in labor_markers if marker in normalized]
        if matched_labor == ["работник"] and any(
            marker in normalized for marker in pharma_worker_context
        ):
            matched_labor = []
        if matched_uz and not matched_ru:
            return {
                "route": "uzbekistan",
                "jurisdiction": "UZ",
                "corpus": "local-legal-uz-sqlite",
                "recommended_tool": "search_uzbek_legal_memory",
                "confidence": "high",
                "matched_markers": {"uzbekistan": matched_uz, "russia_eaeu": matched_ru},
                "agent_instruction": "Use only the local Uzbekistan corpus unless comparison is requested.",
            }
        if matched_doctrine:
            return {
                "route": "russia_doctrine",
                "jurisdiction": "RU",
                "corpus": "local-legal-doctrine-sqlite",
                "recommended_tool": "search_doctrine",
                "confidence": "high",
                "matched_markers": {
                    "uzbekistan": matched_uz,
                    "russia_eaeu": matched_ru,
                    "doctrine": matched_doctrine,
                },
                "agent_instruction": (
                    "Use the unified local doctrine corpus and verify cited norms and cases separately."
                ),
            }
        if matched_labor:
            return {
                "route": "russia_labor_guidance",
                "jurisdiction": "RU",
                "corpus": "local-legal-memory-sqlite",
                "recommended_tool": "search_official_labor_guidance",
                "companion_norm_tool": "search_legal_kb",
                "confidence": "high",
                "matched_markers": {
                    "uzbekistan": matched_uz,
                    "russia_eaeu": matched_ru,
                    "doctrine": matched_doctrine,
                    "labor": matched_labor,
                },
                "agent_instruction": (
                    "Treat Rostrud materials as official non-normative guidance and verify legal "
                    "conclusions against current norms from the local RU/EAEU corpus."
                ),
            }
        route = "russia_eaeu" if matched_ru else "default_main_corpus"
        return {
            "route": route,
            "jurisdiction": "RU",
            "corpus": "local-legal-ru-sqlite",
            "recommended_tool": "search_legal_kb",
            "confidence": "high" if matched_ru else "medium",
            "matched_markers": {
                "uzbekistan": matched_uz,
                "russia_eaeu": matched_ru,
                "doctrine": matched_doctrine,
            },
            "agent_instruction": "Use the local RU/EAEU SQLite corpus.",
        }

    def list_tools(self) -> list[dict[str, Any]]:
        overlay = [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in self._overlay_tools().items()
        ]
        try:
            provider_tools = self.registry.provider_tools()
        except Exception as exc:
            self.stderr(
                "[legal-overlay] server tools/list unavailable; "
                f"local overlay tools remain available: {self.registry.redact(exc)}"
            )
            provider_tools = []
        overlay_names = {tool["name"] for tool in overlay}
        return overlay + [tool for tool in provider_tools if tool.get("name") not in overlay_names]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        overlay = self._overlay_tools()
        if name in overlay:
            return overlay[name]["handler"](arguments)
        return self.registry.call_tool(name, arguments)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return _response(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "legal-overlay", "version": GATEWAY_VERSION},
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _response(request_id, {"tools": self.list_tools()})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _response(
                    request_id,
                    error={"code": -32602, "message": "tool arguments must be an object"},
                )
            try:
                result = self.call_tool(name, arguments)
            except Exception as exc:
                return _response(
                    request_id,
                    error={"code": -32000, "message": self.registry.redact(exc)},
                )
            if isinstance(result, dict) and "content" in result:
                return _response(request_id, result)
            return _response(request_id, _tool_result(result))
        if request_id is None:
            return None
        return _response(request_id, error={"code": -32601, "message": f"Unknown method: {method}"})


def main() -> int:
    try:
        server = OverlayMCPServer(ProviderRegistry.from_default_config())
    except Exception as exc:
        print(f"[legal-overlay] startup failed: {exc}", file=sys.stderr)
        return 2

    stdin_bin = sys.stdin.buffer
    stdout_bin = sys.stdout.buffer
    for raw_line in stdin_bin:
        try:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            message = json.loads(line)
            result = server.handle(message)
            if result is not None:
                stdout_bin.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
                stdout_bin.flush()
        except Exception as exc:
            stdout_bin.write(
                (
                    json.dumps(
                        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}},
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stdout_bin.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
