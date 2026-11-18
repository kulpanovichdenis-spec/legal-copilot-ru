"""Provider-neutral FAS practice tools. The direct fas provider is the only route."""

from __future__ import annotations

from typing import Any

from .config import ConfigurationError
from .registry import ProviderRegistry


class FasSearchRoutingError(ValueError):
    """Controlled error for provider-neutral FAS operations."""


class FasSearchRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def _call(self, native_name: str, arguments: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        attempted: list[str] = []
        warnings: list[str] = []
        try:
            direct = self.registry.adapter("fas")
            if not direct.descriptor().enabled:
                raise ConfigurationError("fas provider is disabled")
            attempted.append("fas")
            value = direct.call_tool(native_name, arguments)
            return value, {
                "status": "OK",
                "provider_used": "fas",
                "sources_attempted": attempted,
                "sources_succeeded": ["fas"],
                "fallbacks_used": [],
                "warnings": warnings,
            }
        except Exception as exc:
            if "fas" not in attempted:
                attempted.append("fas")
            warnings.append(f"direct fas provider failed: {self.registry.redact(exc)}")
            raise FasSearchRoutingError("; ".join(warnings)) from exc

    @staticmethod
    def _limit(value: Any) -> int:
        try:
            limit = int(value if value is not None else 5)
        except (TypeError, ValueError) as exc:
            raise FasSearchRoutingError("limit must be an integer") from exc
        if not 1 <= limit <= 15:
            raise FasSearchRoutingError("limit must be between 1 and 15")
        return limit

    @staticmethod
    def _filter_values(value: Any, *, field: str) -> list[Any]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        if not values or len(values) > 20:
            raise FasSearchRoutingError(f"filters.{field} must contain between 1 and 20 values")
        normalized: list[Any] = []
        for item in values:
            if field == "year":
                try:
                    item = int(item)
                except (TypeError, ValueError) as exc:
                    raise FasSearchRoutingError("filters.year values must be integers") from exc
                if not 2000 <= item <= 2100:
                    raise FasSearchRoutingError("filters.year values must be between 2000 and 2100")
            else:
                item = str(item).strip()
                if not item or len(item) > 300:
                    raise FasSearchRoutingError(f"filters.{field} values must be non-empty and at most 300 characters")
            if item not in normalized:
                normalized.append(item)
        return normalized

    def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise FasSearchRoutingError("query is required")
        if arguments.get("data_classification", "public_or_abstracted") != "public_or_abstracted":
            raise FasSearchRoutingError("FAS search accepts only public_or_abstracted queries")
        filters = arguments.get("filters") or {}
        if not isinstance(filters, dict):
            raise FasSearchRoutingError("filters must be an object")
        limit = self._limit(arguments.get("limit"))
        native_arguments: dict[str, Any] = {"query": query, "top_k": limit}
        for field in ("year", "region", "article"):
            values = self._filter_values(filters.get(field), field=field)
            if values:
                native_arguments[field] = values
        native, meta = self._call("search_fas_cases", native_arguments)
        if not isinstance(native, dict) or not isinstance(native.get("results"), list):
            raise FasSearchRoutingError("FAS search returned an unsupported result shape")
        raw_results = [item for item in native["results"] if isinstance(item, dict)]
        return {
            **meta,
            "operation": "search_fas_ad_practice",
            "query": query,
            "filters": native.get("filters_applied", filters),
            "total_in_corpus": native.get("total_in_corpus"),
            "provider_returned": native.get("returned", len(raw_results)),
            "returned": min(len(raw_results), limit),
            "results": raw_results[:limit],
        }

    def get_case(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_ids = arguments.get("case_ids")
        if raw_ids is None:
            raw_ids = [arguments.get("case_id")]
        if not isinstance(raw_ids, list):
            raise FasSearchRoutingError("case_ids must be an array")
        case_ids: list[str] = []
        for value in raw_ids:
            case_id = str(value or "").strip()
            if not case_id or len(case_id) > 300:
                raise FasSearchRoutingError("each case id is required and must be at most 300 characters")
            if case_id not in case_ids:
                case_ids.append(case_id)
        if not 1 <= len(case_ids) <= 5:
            raise FasSearchRoutingError("get_fas_case accepts between 1 and 5 case ids")
        native, meta = self._call("get_case_details", {"docIds": case_ids})
        if isinstance(native, list):
            cases = [item for item in native if isinstance(item, dict)]
        elif isinstance(native, dict) and isinstance(native.get("results"), list):
            cases = [item for item in native["results"] if isinstance(item, dict)]
        elif isinstance(native, dict):
            cases = [native]
        else:
            raise FasSearchRoutingError("FAS case details returned an unsupported result shape")
        return {
            **meta,
            "operation": "get_fas_case",
            "case_id": case_ids[0] if len(case_ids) == 1 else None,
            "case_ids": case_ids,
            "cases": cases,
        }

    def list_filter_options(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        native, meta = self._call("get_filter_options", {})
        if not isinstance(native, dict):
            raise FasSearchRoutingError("FAS filter options returned an unsupported result shape")
        return {
            **meta,
            "operation": "list_fas_filter_options",
            "years": native.get("years", []),
            "regions": native.get("regions", []),
            "articles": native.get("articles", []),
        }
