"""Local canonical-key bridge to the direct pravo.gov.ru adapter."""

from __future__ import annotations

import re
from typing import Any

from .config import ConfigurationError
from .registry import ProviderRegistry


class OfficialTextRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def _resolve(self, canonical_key: Any) -> tuple[dict[str, Any], str]:
        key = str(canonical_key or "").strip()
        if not key:
            raise ValueError("canonical_key is required")
        local = self.registry.adapter("local-legal-ru-sqlite")
        if not local.descriptor().enabled or not local.descriptor().configured:
            raise ConfigurationError("local-legal-ru-sqlite is not available")
        document = local.call_tool("get_document", {"canonical_key": key})
        for source in document.get("official_sources", []):
            external_id = str(source.get("external_id") or "").strip()
            provider = str(source.get("provider") or "").casefold()
            if re.fullmatch(r"\d{6,30}", external_id) and (not provider or "pravo" in provider):
                return document, external_id

        act_number = document.get("act_number")
        act_date = document.get("act_date")
        if not act_number or not act_date:
            raise KeyError("local document has no exact official identity for pravo.gov.ru")
        pravo = self.registry.adapter("pravo-gov-ru")
        resolved = pravo.call_tool(
            "pravo_resolve_act",
            {
                "act_number": act_number,
                "act_date": act_date,
                "title_hint": document.get("canonical_title") or "",
            },
        )
        if resolved.get("status") != "RESOLVED":
            raise LookupError(f"pravo.gov.ru resolution returned {resolved.get('status', 'FAILED')}")
        return document, str(resolved["nd"])

    @staticmethod
    def _decorate(result: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        value = dict(result)
        value.update(
            {
                "canonical_key": document.get("canonical_key"),
                "document_id": document.get("id"),
                "title": document.get("canonical_title"),
                "act_number": document.get("act_number"),
                "act_date": document.get("act_date"),
                "freshness": {
                    "state": "verified_live" if result.get("status") == "OK" else "needs_review",
                    "verified_at": result.get("retrieved_at"),
                    "source": "pravo.gov.ru",
                },
            }
        )
        return value

    def get_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document, nd = self._resolve(arguments.get("canonical_key"))
        pravo = self.registry.adapter("pravo-gov-ru")
        result = pravo.call_tool(
            "pravo_get_document",
            {
                "nd": nd,
                "offset": arguments.get("offset", 0),
                "limit": arguments.get("limit", 50_000),
            },
        )
        return self._decorate(result, document)

    def get_article(self, arguments: dict[str, Any]) -> dict[str, Any]:
        article_number = arguments.get("article_number", arguments.get("article"))
        if article_number is None or str(article_number).strip() == "":
            raise ValueError("article_number or article is required")
        document, nd = self._resolve(arguments.get("canonical_key"))
        pravo = self.registry.adapter("pravo-gov-ru")
        result = pravo.call_tool(
            "pravo_get_article",
            {"nd": nd, "article_number": article_number},
        )
        return self._decorate(result, document)
