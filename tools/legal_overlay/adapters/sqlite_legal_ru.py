"""Immutable read-only adapter for the RU/EAEU SQLite legal corpus."""

from __future__ import annotations

import re
from typing import Any

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..sqlite_snapshot import SQLiteSnapshot, bounded_int, fts_query
from .base import ProviderAdapter


DATABASE = "legal-ru.sqlite"
LEGACY_DOCTRINE_CANONICAL_KEY = "legacy-wiki:doctrine_commentary--%"
REQUIRED_TABLES = (
    "documents",
    "document_versions",
    "legal_units",
    "court_authorities",
    "document_relations",
    "official_document_sources",
    "legal_kb_search_fts",
)


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        result["required"] = list(required)
    return result


QUERY_PROPERTIES = {
    "query": {"type": "string", "minLength": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
}


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "search_legal_kb": {
        "description": "Search the local immutable RU/EAEU legal corpus, including norms, case law and doctrine.",
        "inputSchema": _object_schema(QUERY_PROPERTIES, ("query",)),
    },
    "search_all_legal_memory": {
        "description": "Compatibility alias for broad local RU/EAEU corpus search.",
        "inputSchema": _object_schema(QUERY_PROPERTIES, ("query",)),
    },
    "find_by_act_number": {
        "description": "Find a local RU/EAEU act by its exact act number.",
        "inputSchema": _object_schema(
            {
                "act_number": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            ("act_number",),
        ),
    },
    "find_federal_act": {
        "description": "Existence-check a federal act in the local snapshot; not a current-text authority.",
        "inputSchema": _object_schema(
            {
                "act_number": {"type": "string", "minLength": 1},
                "act_type": {"type": "string"},
                "title_hint": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            ("act_number",),
        ),
    },
    "get_document": {
        "description": "Get local RU/EAEU document metadata by document_id or canonical_key.",
        "inputSchema": _object_schema(
            {"document_id": {"type": "string"}, "canonical_key": {"type": "string"}},
        ),
    },
    "get_legal_text": {
        "description": "Read a bounded page of legal-unit text from the local RU/EAEU snapshot.",
        "inputSchema": _object_schema(
            {
                "document_id": {"type": "string"},
                "canonical_key": {"type": "string"},
                "article": {"type": ["string", "number"]},
                "article_number": {"type": ["string", "number"]},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 50000},
            },
        ),
    },
    "get_document_outline": {
        "description": "List the ordered legal-unit outline for one local document.",
        "inputSchema": _object_schema(
            {"document_id": {"type": "string"}, "canonical_key": {"type": "string"}},
        ),
    },
    "search_positions": {
        "description": "Search local legal positions and court-practice units.",
        "inputSchema": _object_schema(
            {
                "query": {"type": "string"},
                "topic": {"type": "string"},
                "article": {"type": "string"},
                "keyword": {"type": "string"},
                "law": {"type": "string"},
                "case_number": {"type": "string"},
                "link_status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        ),
    },
    "search_comments": {
        "description": "Search local commentary and doctrine documents.",
        "inputSchema": _object_schema(QUERY_PROPERTIES, ("query",)),
    },
    "get_document_relations": {
        "description": "Get local document relations in one or both directions.",
        "inputSchema": _object_schema(
            {
                "document_id": {"type": "string", "minLength": 1},
                "direction": {"enum": ["outgoing", "incoming", "both"], "default": "both"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            ("document_id",),
        ),
    },
    "get_legal_graph_neighbors": {
        "description": "Compatibility alias for local document relations.",
        "inputSchema": _object_schema(
            {
                "document_id": {"type": "string", "minLength": 1},
                "direction": {"enum": ["outgoing", "incoming", "both"], "default": "both"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            ("document_id",),
        ),
    },
    "list_relation_hubs": {
        "description": "List documents with the most local graph relations.",
        "inputSchema": _object_schema(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}
        ),
    },
    "list_position_norm_links": {
        "description": "List local relation records attached to a legal-position unit.",
        "inputSchema": _object_schema(
            {
                "unit_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            ("unit_id",),
        ),
    },
    "get_comment_position": {
        "description": "Get one local court/legal position by unit_id.",
        "inputSchema": _object_schema({"unit_id": {"type": "string", "minLength": 1}}, ("unit_id",)),
    },
    "list_comment_positions": {
        "description": "List local court/legal positions for one document.",
        "inputSchema": _object_schema(
            {
                "document_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 80},
            },
            ("document_id",),
        ),
    },
    "get_comment": {
        "description": "Get local comment/doctrine metadata and outline by document_id.",
        "inputSchema": _object_schema({"document_id": {"type": "string", "minLength": 1}}, ("document_id",)),
    },
    "check_norm_reference": {
        "description": "Parse an act number from a norm reference and check it in the local snapshot.",
        "inputSchema": _object_schema(
            {"reference_text": {"type": "string", "minLength": 1}}, ("reference_text",)
        ),
    },
    "kb_health_report": {
        "description": "Compatibility health report for the immutable local RU/EAEU snapshot.",
        "inputSchema": _object_schema({}),
    },
    "get_kb_status": {
        "description": "Compatibility status report for the immutable local RU/EAEU snapshot.",
        "inputSchema": _object_schema({}),
    },
    "get_storage_report": {
        "description": "Report verified immutable local RU/EAEU snapshot storage metadata.",
        "inputSchema": _object_schema({}),
    },
    "doctor": {
        "description": "Run read-only validation of the immutable local RU/EAEU snapshot.",
        "inputSchema": _object_schema({}),
    },
    "sqlite_legal_ru_status": {
        "description": "Show verified RU/EAEU snapshot identity and freshness without modifying it.",
        "inputSchema": _object_schema({}),
    },
}


class SQLiteLegalRuAdapter(ProviderAdapter):
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
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={**metadata.to_dict(), "documents": documents, "legal_units": units},
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_SPECS

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, **spec} for name, spec in TOOL_SPECS.items()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name in {"search_legal_kb", "search_all_legal_memory"}:
            return self._search(arguments.get("query"), limit=arguments.get("limit"))
        if name == "find_by_act_number":
            return self._find_act(arguments.get("act_number"), limit=arguments.get("limit"))
        if name == "find_federal_act":
            results = self._find_act(arguments.get("act_number"), limit=arguments.get("limit"))
            return {
                "status": "FOUND" if results else "NOT_FOUND",
                "policy": "existence_check_only",
                "not_current_text_authority": True,
                "results": results,
            }
        if name == "get_document":
            return self._get_document(arguments)
        if name == "get_legal_text":
            return self._get_text(arguments)
        if name == "get_document_outline":
            return self._get_outline(arguments)
        if name == "search_positions":
            if arguments.get("link_status"):
                raise ValueError(
                    "link_status filtering is not represented in the SQLite snapshot; use list_position_norm_links"
                )
            query = next(
                (
                    arguments.get(key)
                    for key in ("query", "topic", "article", "keyword", "law", "case_number")
                    if arguments.get(key)
                ),
                None,
            )
            position_types = ("legal_position", "court_practice", "court_practice_item")
            if query:
                return self._search(query, limit=arguments.get("limit"), doc_types=position_types)
            return self._list_by_types(position_types, limit=arguments.get("limit"))
        if name == "search_comments":
            return self._search(
                arguments.get("query"),
                limit=arguments.get("limit"),
                doc_types=("article_commentary_unit", "legal_comment", "legal_literature_note", "book_commentary", "doctrine_article"),
            )
        if name in {"get_document_relations", "get_legal_graph_neighbors"}:
            return self._relations(arguments)
        if name == "list_relation_hubs":
            return self._relation_hubs(arguments.get("limit"))
        if name == "list_position_norm_links":
            return self._position_links(arguments)
        if name == "get_comment_position":
            return self._get_position(arguments)
        if name == "list_comment_positions":
            return self._list_positions(arguments)
        if name == "get_comment":
            document = self._get_document({"document_id": arguments.get("document_id")})
            outline = self._get_outline({"document_id": arguments.get("document_id")})
            return {**document, "children": outline.get("units", [])}
        if name == "check_norm_reference":
            return self._check_norm_reference(arguments)
        if name in {"kb_health_report", "get_kb_status", "get_storage_report", "doctor"}:
            health = self.health().to_dict()
            health["read_only"] = True
            health["maintenance"] = "snapshot regeneration happens outside legal-copilot"
            return health
        if name == "sqlite_legal_ru_status":
            return self.health().to_dict()
        raise KeyError(f"unknown local RU SQLite tool: {name}")

    def _search(self, query: Any, *, limit: Any = None, doc_types: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        match = fts_query(query, stem_russian=True)
        result_limit = bounded_int(limit, default=10, minimum=1, maximum=50, name="limit")
        filters = " AND d.canonical_key NOT LIKE ?"
        params: list[Any] = [match, LEGACY_DOCTRINE_CANONICAL_KEY]
        if doc_types:
            filters += f" AND f.doc_type IN ({','.join('?' for _ in doc_types)})"
            params.extend(doc_types)
        params.append(result_limit)
        # The FTS index stores dashed UUIDs while the tables use compact hex ids:
        # compact the dashed form (keeps the id index usable) and return the table id.
        compact = lambda column: f"CASE WHEN length({column}) = 36 THEN replace({column}, '-', '') ELSE {column} END"
        sql = f"""
            SELECT COALESCE(d.id, f.document_id) AS document_id,
                   COALESCE(v.id, f.version_id) AS version_id,
                   COALESCE(u.id, f.unit_id) AS unit_id,
                   f.doc_type, f.current_status,
                   COALESCE(f.display_title, f.canonical_title) AS title,
                   f.topic, f.issuer, f.act_number, f.unit_number, f.unit_heading,
                   snippet(legal_kb_search_fts, 12, '[', ']', ' … ', 36) AS snippet,
                   d.canonical_key, d.jurisdiction, d.source_url,
                   v.act_date, v.effective_date, v.is_current,
                   u.source_text_hash AS content_hash, u.status AS unit_status
            FROM legal_kb_search_fts AS f
            LEFT JOIN documents AS d ON d.id = {compact('f.document_id')}
            LEFT JOIN document_versions AS v ON v.id = {compact('f.version_id')}
            LEFT JOIN legal_units AS u ON u.id = {compact('f.unit_id')}
            WHERE legal_kb_search_fts MATCH ?{filters}
            ORDER BY bm25(legal_kb_search_fts)
            LIMIT ?
        """
        with self.snapshot.connect() as database:
            return [dict(row) for row in database.execute(sql, params)]

    def _find_act(self, act_number: Any, *, limit: Any = None) -> list[dict[str, Any]]:
        number = str(act_number or "").strip()
        if not number:
            raise ValueError("act_number is required")
        result_limit = bounded_int(limit, default=10, minimum=1, maximum=50, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                """
                SELECT d.id AS document_id, d.canonical_key, d.canonical_title AS title,
                       d.doc_type, d.jurisdiction, d.issuer, d.source_url, d.current_status,
                       v.id AS version_id, v.act_number, v.act_date, v.effective_date,
                       v.is_current, v.text_hash AS content_hash
                FROM document_versions AS v
                JOIN documents AS d ON d.id = v.document_id
                WHERE replace(replace(lower(v.act_number), '№', ''), 'n ', '') =
                      replace(replace(lower(?), '№', ''), 'n ', '')
                ORDER BY v.is_current DESC, v.act_date DESC
                LIMIT ?
                """,
                (number, result_limit),
            )
            return [dict(row) for row in rows]

    def _list_by_types(self, doc_types: tuple[str, ...], *, limit: Any = None) -> list[dict[str, Any]]:
        result_limit = bounded_int(limit, default=10, minimum=1, maximum=50, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                f"""
                SELECT d.id AS document_id, v.id AS version_id, u.id AS unit_id,
                       d.doc_type, d.current_status, d.canonical_title AS title,
                       d.topic, d.issuer, v.act_number, u.unit_number,
                       u.heading AS unit_heading, substr(u.text, 1, 1200) AS snippet,
                       d.canonical_key, d.jurisdiction, d.source_url,
                       v.act_date, v.effective_date, v.is_current,
                       u.source_text_hash AS content_hash, u.status AS unit_status
                FROM documents AS d
                LEFT JOIN document_versions AS v ON v.document_id = d.id AND v.is_current = 1
                LEFT JOIN legal_units AS u ON u.document_id = d.id
                WHERE d.canonical_key NOT LIKE ?
                  AND d.doc_type IN ({','.join('?' for _ in doc_types)})
                ORDER BY d.updated_at DESC, u.order_index, d.id
                LIMIT ?
                """,
                (LEGACY_DOCTRINE_CANONICAL_KEY, *doc_types, result_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _identity(arguments: dict[str, Any]) -> tuple[str | None, str | None]:
        document_id = str(arguments.get("document_id") or "").strip() or None
        canonical_key = str(arguments.get("canonical_key") or "").strip() or None
        if not document_id and not canonical_key:
            raise ValueError("document_id or canonical_key is required")
        return document_id, canonical_key

    def _resolve_document(self, database: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id, canonical_key = self._identity(arguments)
        row = database.execute(
            """
            SELECT d.*, v.id AS version_id, v.version_label, v.act_number, v.act_date,
                   v.effective_date, v.publication_date, v.source_hash,
                   v.text_hash AS content_hash, v.is_current
            FROM documents AS d
            LEFT JOIN document_versions AS v ON v.document_id = d.id AND v.is_current = 1
            WHERE (? IS NOT NULL AND replace(d.id, '-', '') = replace(?, '-', ''))
               OR (? IS NOT NULL AND d.canonical_key = ?)
            ORDER BY v.is_current DESC
            LIMIT 1
            """,
            (document_id, document_id, canonical_key, canonical_key),
        ).fetchone()
        if row is None:
            raise KeyError("local RU document not found")
        return dict(row)

    def _get_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.snapshot.connect() as database:
            item = self._resolve_document(database, arguments)
            official = database.execute(
                "SELECT provider, external_id, source_url, status, last_checked_at, current_content_hash FROM official_document_sources WHERE document_id = ? ORDER BY last_checked_at DESC",
                (item["id"],),
            ).fetchall()
            item["official_sources"] = [dict(row) for row in official]
            item["snapshot"] = self.snapshot.validate().to_dict()
            return item

    def _get_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        offset = bounded_int(arguments.get("offset"), default=0, minimum=0, maximum=100_000_000, name="offset")
        page_limit = bounded_int(arguments.get("limit"), default=50_000, minimum=1, maximum=200_000, name="limit")
        with self.snapshot.connect() as database:
            item = self._resolve_document(database, arguments)
            article = str(arguments.get("article") or arguments.get("article_number") or "").strip() or None
            normalized_article = article
            if normalized_article:
                normalized_article = normalized_article.casefold().replace("статья", "").replace("ст.", "").strip()
            rows = database.execute(
                """
                SELECT unit_type, unit_number, heading, text, path, source_text_hash
                FROM legal_units
                WHERE document_id = ?
                  AND (? IS NULL OR normalized_number = ? OR unit_number = ?)
                ORDER BY order_index, id
                """,
                (item["id"], normalized_article, normalized_article, normalized_article),
            ).fetchall()
        parts = []
        for row in rows:
            heading = " ".join(str(value) for value in (row["unit_type"], row["unit_number"], row["heading"]) if value)
            parts.append((heading + "\n" if heading else "") + str(row["text"] or ""))
        text = "\n\n".join(parts)
        page = text[offset : offset + page_limit]
        return {
            "document_id": item["id"],
            "canonical_key": item.get("canonical_key"),
            "title": item.get("canonical_title"),
            "act_number": item.get("act_number"),
            "act_date": item.get("act_date"),
            "article": article,
            "text": page,
            "offset": offset,
            "returned_chars": len(page),
            "total_chars": len(text),
            "has_more": offset + len(page) < len(text),
            "content_hash": item.get("content_hash"),
            "version_is_current": bool(item.get("is_current")),
            "snapshot": self.snapshot.validate().to_dict(),
        }

    def _get_outline(self, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.snapshot.connect() as database:
            item = self._resolve_document(database, arguments)
            rows = database.execute(
                "SELECT id AS unit_id, parent_unit_id, unit_type, unit_number, heading, path, order_index, status FROM legal_units WHERE document_id = ? ORDER BY order_index, id",
                (item["id"],),
            ).fetchall()
        return {"document_id": item["id"], "title": item.get("canonical_title"), "units": [dict(row) for row in rows]}

    def _relations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id = str(arguments.get("document_id") or "").strip()
        if not document_id:
            raise ValueError("document_id is required")
        direction = str(arguments.get("direction") or "both")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming or both")
        result_limit = bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=200, name="limit")
        with self.snapshot.connect() as database:
            resolved = database.execute(
                "SELECT id FROM documents WHERE replace(id, '-', '') = replace(?, '-', '') LIMIT 1",
                (document_id,),
            ).fetchone()
        if resolved is not None:
            document_id = str(resolved[0])
        clauses = []
        params: list[Any] = []
        if direction in {"outgoing", "both"}:
            clauses.append("r.source_document_id = ?")
            params.append(document_id)
        if direction in {"incoming", "both"}:
            clauses.append("r.target_document_id = ?")
            params.append(document_id)
        params.append(result_limit)
        with self.snapshot.connect() as database:
            rows = database.execute(
                f"""
                SELECT r.id, r.source_document_id, sd.canonical_title AS source_title,
                       r.target_document_id, td.canonical_title AS target_title,
                       r.source_unit_id, r.target_unit_id, r.relation_type,
                       r.evidence, r.metadata_json, r.created_at
                FROM document_relations AS r
                LEFT JOIN documents AS sd ON sd.id = r.source_document_id
                LEFT JOIN documents AS td ON td.id = r.target_document_id
                WHERE {' OR '.join(clauses)}
                ORDER BY r.created_at DESC, r.id
                LIMIT ?
                """,
                params,
            ).fetchall()
        return {"document_id": document_id, "direction": direction, "relations": [dict(row) for row in rows]}

    def _relation_hubs(self, limit: Any) -> list[dict[str, Any]]:
        result_limit = bounded_int(limit, default=20, minimum=1, maximum=100, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                """
                WITH edges AS (
                    SELECT source_document_id AS document_id FROM document_relations
                    UNION ALL
                    SELECT target_document_id AS document_id FROM document_relations
                )
                SELECT e.document_id, d.canonical_title AS title, d.doc_type, count(*) AS relation_count
                FROM edges AS e JOIN documents AS d ON d.id = e.document_id
                GROUP BY e.document_id, d.canonical_title, d.doc_type
                ORDER BY relation_count DESC, title
                LIMIT ?
                """,
                (result_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _position_links(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        unit_id = str(arguments.get("unit_id") or "").strip()
        if not unit_id:
            raise ValueError("unit_id is required")
        result_limit = bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=200, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                """
                SELECT id, source_document_id, target_document_id, source_unit_id,
                       target_unit_id, relation_type, evidence, metadata_json
                FROM document_relations
                WHERE source_unit_id = ? OR target_unit_id = ?
                ORDER BY created_at DESC, id
                LIMIT ?
                """,
                (unit_id, unit_id, result_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_position(self, arguments: dict[str, Any]) -> dict[str, Any]:
        unit_id = str(arguments.get("unit_id") or "").strip()
        if not unit_id:
            raise ValueError("unit_id is required")
        with self.snapshot.connect() as database:
            row = database.execute(
                """
                SELECT u.*, d.canonical_title AS document_title, d.doc_type,
                       d.jurisdiction, d.source_url, d.canonical_key,
                       v.act_number, v.act_date, v.effective_date, v.is_current
                FROM legal_units AS u
                JOIN documents AS d ON d.id = u.document_id
                LEFT JOIN document_versions AS v ON v.id = u.version_id
                WHERE u.id = ?
                LIMIT 1
                """,
                (unit_id,),
            ).fetchone()
        if row is None:
            raise KeyError("local legal position not found")
        result = dict(row)
        result["snapshot"] = self.snapshot.validate().to_dict()
        return result

    def _list_positions(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        document_id = str(arguments.get("document_id") or "").strip()
        if not document_id:
            raise ValueError("document_id is required")
        result_limit = bounded_int(arguments.get("limit"), default=80, minimum=1, maximum=200, name="limit")
        with self.snapshot.connect() as database:
            rows = database.execute(
                """
                SELECT u.id AS unit_id, u.document_id, u.unit_type, u.unit_number,
                       u.heading, u.text, u.path, u.status, u.source_text_hash AS content_hash,
                       d.canonical_title AS document_title, d.doc_type
                FROM legal_units AS u
                JOIN documents AS d ON d.id = u.document_id
                WHERE u.document_id = ?
                  AND d.doc_type IN ('legal_position', 'court_practice', 'court_practice_item')
                ORDER BY u.order_index, u.id
                LIMIT ?
                """,
                (document_id, result_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _check_norm_reference(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reference = str(arguments.get("reference_text") or "").strip()
        if not reference:
            raise ValueError("reference_text is required")
        candidates = re.findall(r"\b\d+[\s-]*(?:ФЗ|FZ|ФКЗ|FKZ)\b", reference, flags=re.IGNORECASE)
        if not candidates:
            return {
                "status": "UNPARSED",
                "reference_text": reference,
                "warnings": ["No federal act number was parsed; do not guess the act identity."],
                "results": [],
            }
        normalized = re.sub(r"\s+", "", candidates[0]).upper()
        results = self._find_act(normalized)
        return {
            "status": "FOUND" if results else "NOT_FOUND",
            "reference_text": reference,
            "act_number": normalized,
            "results": results,
            "warnings": [] if results else ["The parsed act number was not found in the local snapshot."],
        }
