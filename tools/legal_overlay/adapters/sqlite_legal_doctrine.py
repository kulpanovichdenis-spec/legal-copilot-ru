"""Immutable read-only adapter for the unified local doctrine corpus."""

from __future__ import annotations

import json
from typing import Any

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..sqlite_snapshot import SQLiteSnapshot, bounded_int, fts_query
from .base import ProviderAdapter


DATABASE = "legal-doctrine.sqlite"
REQUIRED_TABLES = (
    "_sqlite_copilot_meta",
    "doctrine_sources",
    "doctrine_units",
    "doctrine_fts",
)
AUTHORITY_CLASS = "doctrine_only"
DOCTRINE_WARNING = (
    "doctrine_only: verify cited norms and judicial acts separately before relying on them"
)


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        result["required"] = list(required)
    return result


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "sqlite_legal_doctrine_status": {
        "description": "Show verified unified-doctrine snapshot identity and read-only status.",
        "inputSchema": _object_schema({}),
    },
    "list_doctrine_sources": {
        "description": "List source works in the unified local doctrine corpus.",
        "inputSchema": _object_schema(
            {
                "source_family": {"type": "string", "minLength": 1},
                "source_category": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
            }
        ),
    },
    "search_doctrine": {
        "description": (
            "Search the unified local doctrine corpus. Results are doctrine_only and cited norms "
            "or cases require separate verification."
        ),
        "inputSchema": _object_schema(
            {
                "query": {"type": "string", "minLength": 1},
                "source_family": {"type": "string", "minLength": 1},
                "unit_type": {"type": "string", "minLength": 1},
                "article": {"type": ["string", "number"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            ("query",),
        ),
    },
    "get_doctrine_unit": {
        "description": (
            "Read a bounded text page and provenance for one unified-doctrine unit. "
            "Doctrine is not norm or case verification."
        ),
        "inputSchema": _object_schema(
            {
                "unit_id": {"type": "string", "minLength": 1},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 50000},
            },
            ("unit_id",),
        ),
    },
}


def _json_value(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


class SQLiteLegalDoctrineAdapter(ProviderAdapter):
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
            return ProviderHealth(
                self.connection.provider_id,
                "not_configured",
                detail="snapshot_dir is not configured",
            )
        try:
            metadata = self.snapshot.validate()
            with self.snapshot.connect() as database:
                sources = int(database.execute("SELECT count(*) FROM doctrine_sources").fetchone()[0])
                units = int(database.execute("SELECT count(*) FROM doctrine_units").fetchone()[0])
                fts_rows = int(database.execute("SELECT count(*) FROM doctrine_fts").fetchone()[0])
                authority_classes = sorted(
                    {
                        str(row[0])
                        for row in database.execute(
                            "SELECT DISTINCT authority_class FROM doctrine_units"
                        )
                    }
                )
                source_authority_classes = sorted(
                    {
                        str(row[0])
                        for row in database.execute(
                            "SELECT DISTINCT authority_class FROM doctrine_sources"
                        )
                    }
                )
            if authority_classes != [AUTHORITY_CLASS] or source_authority_classes != [AUTHORITY_CLASS]:
                raise ValueError("unified doctrine snapshot contains a non-doctrine authority class")
            if units != fts_rows:
                raise ValueError("unified doctrine FTS row count does not match doctrine_units")
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={
                **metadata.to_dict(),
                "doctrine_sources": sources,
                "doctrine_units": units,
                "fts_rows": fts_rows,
                "authority_classes": authority_classes,
            },
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_SPECS

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, **spec} for name, spec in TOOL_SPECS.items()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "sqlite_legal_doctrine_status":
            return self.health().to_dict()
        if name == "list_doctrine_sources":
            return self._list_sources(arguments)
        if name == "search_doctrine":
            return self._search(arguments)
        if name == "get_doctrine_unit":
            return self._get_unit(arguments)
        raise KeyError(f"unknown local doctrine SQLite tool: {name}")

    @staticmethod
    def _source_result(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["authors"] = _json_value(item.pop("authors_json", None), [])
        item["source_file_present"] = bool(item.get("source_file_present"))
        item["authority_class"] = AUTHORITY_CLASS
        return item

    @staticmethod
    def _unit_result(row: Any, *, include_text: bool = False) -> dict[str, Any]:
        item = dict(row)
        related_topics = _json_value(item.pop("related_topics_json", None), [])
        related_norms = _json_value(item.pop("related_norms_json", None), [])
        related_cases = _json_value(item.pop("related_cases_json", None), [])
        source_cards = _json_value(item.pop("source_cards_json", None), [])
        source_anchors = _json_value(item.pop("source_anchors_json", None), [])
        authors = _json_value(item.pop("authors_json", None), [])
        text_page = item.pop("text_page", None)
        item["related_topics"] = related_topics
        item["related_norms"] = related_norms
        item["related_cases"] = related_cases
        item["authority_class"] = AUTHORITY_CLASS
        item["content_hash"] = item.get("text_sha256")
        item["provenance"] = {
            "source_id": item.get("source_id"),
            "source_title": item.get("source_title"),
            "source_work": item.get("source_work"),
            "authors": authors,
            "source_sha256": item.get("source_sha256"),
            "full_text_sha256": item.get("full_text_sha256"),
            "source_card_path": item.get("source_card_path"),
            "unit_card_path": item.get("card_path"),
            "source_cards": source_cards,
            "source_anchors": source_anchors,
            "source_offsets": {
                "pdf_page_start": item.get("pdf_page_start"),
                "pdf_page_end": item.get("pdf_page_end"),
                "start_char": item.get("start_char"),
                "end_char": item.get("end_char"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
            },
            "text_origin": item.get("text_origin"),
        }
        if include_text:
            item["text"] = str(text_page or "")
        item["warnings"] = [DOCTRINE_WARNING]
        return item

    def _list_sources(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result_limit = bounded_int(
            arguments.get("limit"), default=100, minimum=1, maximum=200, name="limit"
        )
        clauses = ["authority_class = ?"]
        params: list[Any] = [AUTHORITY_CLASS]
        for field in ("source_family", "source_category"):
            value = str(arguments.get(field) or "").strip()
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        where = " AND ".join(clauses)
        with self.snapshot.connect() as database:
            total = int(
                database.execute(
                    f"SELECT count(*) FROM doctrine_sources WHERE {where}", params
                ).fetchone()[0]
            )
            rows = database.execute(
                f"""
                SELECT id AS source_id, source_family, source_category, title, source_work,
                       authors_json, publication_year, edition, publisher, jurisdiction,
                       source_format, source_file_present, source_sha256, full_text_sha256,
                       pdf_page_count, extracted_text_chars, source_card_path,
                       verification_status, authority_class
                FROM doctrine_sources
                WHERE {where}
                ORDER BY source_family, source_work, id
                LIMIT ?
                """,
                [*params, result_limit],
            ).fetchall()
        return {
            "total": total,
            "returned": len(rows),
            "sources": [self._source_result(row) for row in rows],
            "snapshot": self.snapshot.validate().to_dict(),
            "warnings": [DOCTRINE_WARNING],
        }

    def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        match = fts_query(arguments.get("query"), stem_russian=True)
        result_limit = bounded_int(
            arguments.get("limit"), default=10, minimum=1, maximum=50, name="limit"
        )
        clauses = [
            "doctrine_fts MATCH ?",
            "u.authority_class = ?",
            "s.authority_class = ?",
        ]
        params: list[Any] = [match, AUTHORITY_CLASS, AUTHORITY_CLASS]
        for field in ("source_family", "unit_type"):
            value = str(arguments.get(field) or "").strip()
            if value:
                clauses.append(f"f.{field} = ?")
                params.append(value)
        article = str(arguments.get("article") or "").strip()
        if article:
            clauses.append("lower(f.article) LIKE '%' || lower(?) || '%'")
            params.append(article)
        where = " AND ".join(clauses)
        with self.snapshot.connect() as database:
            total = int(
                database.execute(
                    f"""
                    SELECT count(*)
                    FROM doctrine_fts AS f
                    JOIN doctrine_units AS u ON u.id = f.unit_id
                    JOIN doctrine_sources AS s ON s.id = u.source_id
                    WHERE {where}
                    """,
                    params,
                ).fetchone()[0]
            )
            rows = database.execute(
                f"""
                SELECT u.id AS unit_id, u.source_id, s.source_family, s.source_category,
                       s.title AS source_title, s.source_work, s.authors_json,
                       s.source_sha256, s.full_text_sha256, s.source_card_path,
                       u.unit_type, u.title, u.chapter, u.section_number, u.code, u.article,
                       u.position_scope, u.related_topics_json, u.related_norms_json,
                       u.related_cases_json, u.source_cards_json, u.source_anchors_json,
                       u.pdf_page_start, u.pdf_page_end, u.start_char, u.end_char,
                       u.start_line, u.end_line, u.text_origin, u.text_sha256, u.card_path,
                       u.status, u.verification_status, u.authority_class,
                       snippet(doctrine_fts, 9, '[', ']', ' … ', 48) AS snippet
                FROM doctrine_fts AS f
                JOIN doctrine_units AS u ON u.id = f.unit_id
                JOIN doctrine_sources AS s ON s.id = u.source_id
                WHERE {where}
                ORDER BY bm25(doctrine_fts), u.id
                LIMIT ?
                """,
                [*params, result_limit],
            ).fetchall()
        return {
            "total": total,
            "returned": len(rows),
            "results": [self._unit_result(row) for row in rows],
            "warnings": [DOCTRINE_WARNING],
        }

    def _get_unit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        unit_id = str(arguments.get("unit_id") or "").strip()
        if not unit_id:
            raise ValueError("unit_id is required")
        offset = bounded_int(
            arguments.get("offset"), default=0, minimum=0, maximum=100_000_000, name="offset"
        )
        page_limit = bounded_int(
            arguments.get("limit"), default=50_000, minimum=1, maximum=200_000, name="limit"
        )
        with self.snapshot.connect() as database:
            row = database.execute(
                """
                SELECT u.id AS unit_id, u.source_id, s.source_family, s.source_category,
                       s.title AS source_title, s.source_work, s.authors_json,
                       s.source_sha256, s.full_text_sha256, s.source_card_path,
                       u.unit_type, u.title, u.chapter, u.section_number, u.code, u.article,
                       u.position_scope, u.related_topics_json, u.related_norms_json,
                       u.related_cases_json, u.source_cards_json, u.source_anchors_json,
                       u.pdf_page_start, u.pdf_page_end, u.start_char, u.end_char,
                       u.start_line, u.end_line, u.text_origin, u.text_sha256, u.card_path,
                       u.status, u.verification_status, u.authority_class,
                       length(u.text) AS total_chars,
                       substr(u.text, ? + 1, ?) AS text_page
                FROM doctrine_units AS u
                JOIN doctrine_sources AS s ON s.id = u.source_id
                WHERE u.id = ? AND u.authority_class = ? AND s.authority_class = ?
                LIMIT 1
                """,
                (offset, page_limit, unit_id, AUTHORITY_CLASS, AUTHORITY_CLASS),
            ).fetchone()
        if row is None:
            raise KeyError("local doctrine unit not found")
        result = self._unit_result(row, include_text=True)
        total_chars = int(result.get("total_chars") or 0)
        returned_chars = len(result["text"])
        result.update(
            {
                "offset": offset,
                "returned_chars": returned_chars,
                "total_chars": total_chars,
                "has_more": offset + returned_chars < total_chars,
                "snapshot": self.snapshot.validate().to_dict(),
            }
        )
        return result
