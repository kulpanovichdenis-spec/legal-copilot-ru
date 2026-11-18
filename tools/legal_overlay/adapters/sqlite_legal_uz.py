"""Immutable read-only adapter for the Uzbekistan SQLite legal corpus."""

from __future__ import annotations

from typing import Any

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..sqlite_snapshot import SQLiteSnapshot, bounded_int, fts_query
from .base import ProviderAdapter


DATABASE = "legal-uz.sqlite"
REQUIRED_TABLES = ("documents", "legal_units", "legal_uz_fts")
TOOL_NAMES = {"search_uzbek_legal_memory", "get_uzbek_legal_card", "uzbek_legal_status"}


class SQLiteLegalUzAdapter(ProviderAdapter):
    def __init__(self, connection: ProviderConnection) -> None:
        self.connection = connection
        self.snapshot = SQLiteSnapshot(connection, database=DATABASE, required_tables=REQUIRED_TABLES)

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.connection.provider_id,
            adapter=self.connection.adapter,
            enabled=self.connection.enabled,
            configured=self.snapshot.configured,
            endpoint=self.snapshot.public_root(),
            priority=self.connection.priority,
            capabilities=self.connection.capabilities,
        )

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        if not self.snapshot.configured:
            return ProviderHealth(self.connection.provider_id, "not_configured", detail="snapshot_dir is not configured")
        try:
            metadata = self.snapshot.validate()
            with self.snapshot.connect() as database:
                documents = database.execute("SELECT count(*) FROM documents").fetchone()[0]
                units = database.execute("SELECT count(*) FROM legal_units").fetchone()[0]
                unverified = database.execute(
                    "SELECT count(*) FROM documents WHERE verification_status = 'not_verified'"
                ).fetchone()[0]
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={
                **metadata.to_dict(),
                "documents": documents,
                "legal_units": units,
                "not_verified_documents": unverified,
                "authority_policy": "lex.uz official text; preserve verification_status",
            },
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_NAMES

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_uzbek_legal_memory",
                "description": "Search the local immutable Uzbekistan corpus without mixing jurisdictions.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_uzbek_legal_card",
                "description": "Get one Uzbekistan document/card and its units from the local snapshot.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"id": {"type": "string"}, "document_id": {"type": "string"}},
                },
            },
            {
                "name": "uzbek_legal_status",
                "description": "Show verified Uzbekistan snapshot identity, counts and freshness.",
                "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_uzbek_legal_memory":
            return self._search(arguments.get("query"), arguments.get("limit"))
        if name == "get_uzbek_legal_card":
            return self._get(arguments)
        if name == "uzbek_legal_status":
            return self.health().to_dict()
        raise KeyError(f"unknown local UZ SQLite tool: {name}")

    def _search(self, query: Any, limit: Any) -> list[dict[str, Any]]:
        match = fts_query(query)
        result_limit = bounded_int(limit, default=10, minimum=1, maximum=50, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                """
                SELECT f.document_id, f.unit_id,
                       COALESCE(f.title, f.official_title) AS title,
                       f.act_number, f.heading, f.article_ref,
                       snippet(legal_uz_fts, 6, '[', ']', ' … ', 36) AS snippet,
                       d.record_type, d.jurisdiction, d.act_date, d.effective_date,
                       d.last_amendment_date, d.source_url, d.language, d.topic,
                       d.source_text_status, d.verification_status,
                       d.source_sha256 AS content_hash
                FROM legal_uz_fts AS f
                JOIN documents AS d ON d.id = f.document_id
                WHERE legal_uz_fts MATCH ?
                ORDER BY bm25(legal_uz_fts)
                LIMIT ?
                """,
                (match, result_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id = str(arguments.get("document_id") or arguments.get("id") or "").strip()
        if not document_id:
            raise ValueError("document_id or id is required")
        with self.snapshot.connect() as database:
            row = database.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if row is None:
                raise KeyError("local UZ document not found")
            units = database.execute(
                "SELECT * FROM legal_units WHERE document_id = ? ORDER BY order_index, id",
                (document_id,),
            ).fetchall()
        result = dict(row)
        result["units"] = [dict(unit) for unit in units]
        result["snapshot"] = self.snapshot.validate().to_dict()
        result["warnings"] = []
        if result.get("verification_status") == "not_verified":
            result["warnings"].append("candidate document is not verified; check the official text on lex.uz")
        return result
