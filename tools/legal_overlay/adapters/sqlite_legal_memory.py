"""Immutable read-only adapter for curated memory and official guidance layers."""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..sqlite_snapshot import SQLiteSnapshot, bounded_int, fts_query
from .base import ProviderAdapter


DATABASE = "legal-memory.sqlite"
REQUIRED_TABLES = ("curated_cards", "topic_maps", "legal_memory_fts")
DEFAULT_TELEGRAM_STATUSES = ("keep_commentary", "keep_guideline")
TELEGRAM_STATUSES = (*DEFAULT_TELEGRAM_STATUSES, "needs_source_review", "delete_candidate")
LABOR_LAYER = "labor_official"
LABOR_AUTHORITY_CLASS = "administrative_guidance"
LABOR_SOURCE_LABEL = "официальное ненормативное разъяснение"
LABOR_WARNING = (
    "Материал Роструда является официальным ненормативным разъяснением, а не нормативным "
    "актом; юридические выводы нужно сверять с действующей редакцией нормы."
)
LABOR_QUERY_STOP_WORDS = {"в", "во", "для", "и", "на", "о", "об", "по", "с", "со"}


def _labor_fts_query(value: Any) -> str:
    """Build a conservative FTS5 AND query with short prefixes for Russian inflections."""
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(value or ""))
    normalized = list(
        dict.fromkeys(
            token.casefold()
            for token in tokens
            if token.strip() and token.casefold() not in LABOR_QUERY_STOP_WORDS
        )
    )
    if not normalized:
        raise ValueError("query must contain searchable text")
    prefixes = [token[:6] if len(token) > 6 else token for token in normalized[:32]]
    return " AND ".join(f'"{prefix.replace(chr(34), chr(34) * 2)}"*' for prefix in prefixes)


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        result["required"] = list(required)
    return result


SEARCH_PROPERTIES = {
    "query": {"type": "string", "minLength": 1},
    "topic": {"type": "string"},
    "status": {"type": "string"},
    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
}


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "search_legal_opinions": {
        "description": "Search local immutable lawyer opinions as internal context, not legal authority.",
        "inputSchema": _object_schema(SEARCH_PROPERTIES, ("query",)),
    },
    "get_legal_opinion": {
        "description": "Read one local lawyer opinion returned by search_legal_opinions.",
        "inputSchema": _object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "max_chars": {"type": "integer", "default": 16000, "minimum": 1, "maximum": 200000},
            },
            ("path",),
        ),
    },
    "search_telegram_reviewed": {
        "description": (
            "Search local reviewed Telegram commentary/guidelines. By default only keep_commentary "
            "and keep_guideline are searchable."
        ),
        "inputSchema": _object_schema(
            {
                **SEARCH_PROPERTIES,
                "channel": {"type": "string"},
                "status": {"type": "string", "enum": list(TELEGRAM_STATUSES)},
            },
            ("query",),
        ),
    },
    "get_telegram_reviewed": {
        "description": "Read one local reviewed Telegram card returned by search_telegram_reviewed.",
        "inputSchema": _object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "max_chars": {"type": "integer", "default": 16000, "minimum": 1, "maximum": 200000},
            },
            ("path",),
        ),
    },
    "search_official_labor_guidance": {
        "description": (
            "Search official non-normative Rostrud guidance. Results include full text and "
            "provenance; verify legal conclusions against current norms in legal-ru.sqlite."
        ),
        "inputSchema": _object_schema(SEARCH_PROPERTIES, ("query",)),
    },
    "get_official_labor_guidance": {
        "description": (
            "Read one official non-normative Rostrud guidance item returned by "
            "search_official_labor_guidance."
        ),
        "inputSchema": _object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "max_chars": {"type": "integer", "default": 20000, "minimum": 1, "maximum": 200000},
            },
            ("path",),
        ),
    },
    "list_topic_maps": {
        "description": "List local legal-pharma topic maps (MOC); maps are navigation only.",
        "inputSchema": _object_schema({}),
    },
    "get_topic_map": {
        "description": "Read one local topic map by slug or path returned by list_topic_maps.",
        "inputSchema": _object_schema(
            {
                "path_or_slug": {"type": "string", "minLength": 1},
                "max_chars": {"type": "integer", "default": 20000, "minimum": 1, "maximum": 200000},
            },
            ("path_or_slug",),
        ),
    },
    "sqlite_legal_memory_status": {
        "description": "Show verified local legal-memory snapshot identity and layer counts.",
        "inputSchema": _object_schema({}),
    },
}


class SQLiteLegalMemoryAdapter(ProviderAdapter):
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
                counts = {
                    row["layer"]: row["count"]
                    for row in database.execute(
                        "SELECT layer, count(*) AS count FROM curated_cards GROUP BY layer"
                    )
                }
                counts["topic_maps"] = database.execute("SELECT count(*) FROM topic_maps").fetchone()[0]
                unsafe_default = database.execute(
                    """
                    SELECT count(*) FROM curated_cards
                    WHERE layer = 'telegram_reviewed'
                      AND default_searchable = 1
                      AND status NOT IN ('keep_commentary', 'keep_guideline')
                    """
                ).fetchone()[0]
                if unsafe_default:
                    raise ValueError("snapshot exposes non-reviewed Telegram statuses by default")
                invalid_authority = database.execute(
                    """
                    SELECT count(*) FROM curated_cards
                    WHERE authority_class IS NULL
                       OR (layer = 'opinions' AND authority_class <> 'internal_context')
                       OR (layer = 'telegram_reviewed' AND authority_class <> 'secondary_context')
                       OR (layer = 'labor_official' AND authority_class <> 'administrative_guidance')
                       OR layer NOT IN ('opinions', 'telegram_reviewed', 'labor_official')
                    """
                ).fetchone()[0]
                if invalid_authority:
                    raise ValueError("curated cards contain an unexpected authority class")
                incomplete_opinions = database.execute(
                    """
                    SELECT count(*) FROM curated_cards
                    WHERE layer = 'opinions'
                      AND (linked_text IS NULL OR trim(linked_text) = ''
                           OR linked_text_sha256 IS NULL OR length(linked_text_sha256) <> 64)
                    """
                ).fetchone()[0]
                if incomplete_opinions:
                    raise ValueError("one or more opinions have no verified linked full text")
                invalid_frontmatter = database.execute(
                    "SELECT count(*) FROM curated_cards WHERE json_valid(frontmatter_json) = 0"
                ).fetchone()[0]
                if invalid_frontmatter:
                    raise ValueError("one or more curated cards have invalid frontmatter JSON")
                incomplete_labor = database.execute(
                    """
                    SELECT count(*) FROM curated_cards
                    WHERE layer = 'labor_official'
                      AND (default_searchable <> 1
                           OR linked_text IS NULL OR trim(linked_text) = ''
                           OR linked_text_sha256 IS NULL OR length(linked_text_sha256) <> 64
                           OR json_extract(frontmatter_json, '$.source_url') IS NULL
                           OR trim(json_extract(frontmatter_json, '$.source_url')) = ''
                           OR json_extract(frontmatter_json, '$.legal_weight') <> 'official_non_normative_position'
                           OR json_extract(frontmatter_json, '$.jurisdiction') <> 'RU')
                    """
                ).fetchone()[0]
                if incomplete_labor:
                    raise ValueError("one or more labor guidance cards have incomplete provenance or full text")
                invalid_maps = database.execute(
                    """
                    SELECT count(*) FROM topic_maps
                    WHERE authority_class <> 'navigation_only' OR authority_class IS NULL
                    """
                ).fetchone()[0]
                if invalid_maps:
                    raise ValueError("topic maps contain an unexpected authority class")
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={**metadata.to_dict(), **counts},
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_SPECS

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, **spec} for name, spec in TOOL_SPECS.items()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_legal_opinions":
            return self._search(arguments, layer="opinions")
        if name == "get_legal_opinion":
            return self._get_card(arguments, layer="opinions")
        if name == "search_telegram_reviewed":
            return self._search(arguments, layer="telegram_reviewed")
        if name == "get_telegram_reviewed":
            return self._get_card(arguments, layer="telegram_reviewed")
        if name == "search_official_labor_guidance":
            return self._search_labor(arguments)
        if name == "get_official_labor_guidance":
            return self._get_labor(arguments)
        if name == "list_topic_maps":
            return self._list_topic_maps()
        if name == "get_topic_map":
            return self._get_topic_map(arguments)
        if name == "sqlite_legal_memory_status":
            return self.health().to_dict()
        raise KeyError(f"unknown local legal-memory SQLite tool: {name}")

    @staticmethod
    def _metadata(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _labor_item(self, item: dict[str, Any], *, full_text: str) -> dict[str, Any]:
        metadata = self._metadata(item.get("frontmatter_json"))
        explicit_refs = metadata.get("explicit_legal_refs")
        if not isinstance(explicit_refs, list):
            explicit_refs = []
        provenance = {
            "provider": self.connection.provider_id,
            "database": DATABASE,
            "source_path": item.get("source_path"),
            "linked_text_path": item.get("linked_text_path"),
            "source_capture_file": metadata.get("source_capture_file"),
            "full_text_file": metadata.get("full_text_file"),
            "source_sha256": item.get("source_sha256"),
            "linked_text_sha256": item.get("linked_text_sha256"),
            "source_hash_scope": metadata.get("source_hash_scope"),
            "retrieved_at": metadata.get("retrieved_at"),
        }
        return {
            "path": item.get("source_path"),
            "title": item.get("title"),
            "type": "official_non_normative_guidance",
            "source_label": LABOR_SOURCE_LABEL,
            "status": item.get("status"),
            "topic": item.get("topic"),
            "authority": metadata.get("authority"),
            "authority_class": item.get("authority_class"),
            "legal_weight": metadata.get("legal_weight"),
            "verification_status": metadata.get("verification_status"),
            "source_url": metadata.get("source_url"),
            "explicit_legal_refs": explicit_refs,
            "full_text": full_text,
            "content_hash": item.get("linked_text_sha256") or item.get("source_sha256"),
            "provenance": provenance,
            "warnings": [LABOR_WARNING],
        }

    def _search_labor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        match = _labor_fts_query(query)
        result_limit = bounded_int(arguments.get("limit"), default=10, minimum=1, maximum=50, name="limit")
        topic = str(arguments.get("topic") or "").strip() or None
        status = str(arguments.get("status") or "").strip() or None
        clauses = ["legal_memory_fts MATCH ?", "c.layer = ?", "c.default_searchable = 1"]
        params: list[Any] = [match, LABOR_LAYER]
        if topic:
            clauses.append("c.topic = ?")
            params.append(topic)
        if status:
            clauses.append("c.status = ?")
            params.append(status)
        where = " AND ".join(clauses)
        with self.snapshot.connect() as database:
            total = database.execute(
                f"""
                SELECT count(*)
                FROM legal_memory_fts AS f
                JOIN curated_cards AS c ON c.source_path = f.item_id
                WHERE {where}
                """,
                params,
            ).fetchone()[0]
            rows = database.execute(
                f"""
                SELECT c.*, bm25(legal_memory_fts) AS rank,
                       snippet(legal_memory_fts, 5, '[', ']', ' ... ', 48) AS snippet
                FROM legal_memory_fts AS f
                JOIN curated_cards AS c ON c.source_path = f.item_id
                WHERE {where}
                ORDER BY rank, c.source_path
                LIMIT ?
                """,
                (*params, result_limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            result = self._labor_item(item, full_text=str(item.get("linked_text") or ""))
            result["snippet"] = item.get("snippet")
            rank = float(item.get("rank") or 0)
            result["score"] = max(0, round(1000 / (1 + abs(rank))))
            results.append(result)
        return {
            "layer": LABOR_LAYER,
            "source_label": LABOR_SOURCE_LABEL,
            "query": query,
            "filters": {"topic": topic, "status": status},
            "total": total,
            "results": results,
            "snapshot": self.snapshot.validate().to_dict(),
            "warnings": [LABOR_WARNING],
        }

    def _get_labor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        max_chars = bounded_int(
            arguments.get("max_chars"), default=20000, minimum=1, maximum=200000, name="max_chars"
        )
        with self.snapshot.connect() as database:
            row = database.execute(
                "SELECT * FROM curated_cards WHERE source_path = ? AND layer = ?",
                (path, LABOR_LAYER),
            ).fetchone()
        if row is None:
            raise KeyError("official labor guidance card not found")
        item = dict(row)
        full_text = str(item.get("linked_text") or "")
        page = full_text[:max_chars]
        result = self._labor_item(item, full_text=page)
        result["truncated"] = len(page) < len(full_text)
        result["snapshot"] = self.snapshot.validate().to_dict()
        return result

    def _search(self, arguments: dict[str, Any], *, layer: str) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        match = fts_query(query, stem_russian=True)
        result_limit = bounded_int(arguments.get("limit"), default=10, minimum=1, maximum=50, name="limit")
        topic = str(arguments.get("topic") or "").strip() or None
        channel = str(arguments.get("channel") or "").strip() or None
        status = str(arguments.get("status") or "").strip() or None
        if layer == "telegram_reviewed" and status and status not in TELEGRAM_STATUSES:
            raise ValueError("unsupported Telegram status")

        clauses = ["legal_memory_fts MATCH ?", "c.layer = ?"]
        params: list[Any] = [match, layer]
        if topic:
            clauses.append("c.topic = ?")
            params.append(topic)
        if channel:
            clauses.append("c.source_channel = ?")
            params.append(channel)
        if status:
            clauses.append("c.status = ?")
            params.append(status)
        elif layer == "telegram_reviewed":
            clauses.append("c.default_searchable = 1")

        where = " AND ".join(clauses)
        with self.snapshot.connect() as database:
            total = database.execute(
                f"""
                SELECT count(*)
                FROM legal_memory_fts AS f
                JOIN curated_cards AS c ON c.source_path = f.item_id
                WHERE {where}
                """,
                params,
            ).fetchone()[0]
            rows = database.execute(
                f"""
                SELECT c.source_path AS path, c.title, c.card_type AS type, c.status,
                       c.topic, c.related_topics_json, c.source_channel, c.source_date,
                       c.source_sha256 AS content_hash, c.authority_class,
                       bm25(legal_memory_fts) AS rank,
                       snippet(legal_memory_fts, 5, '[', ']', ' ... ', 48) AS snippet
                FROM legal_memory_fts AS f
                JOIN curated_cards AS c ON c.source_path = f.item_id
                WHERE {where}
                ORDER BY rank, c.source_path
                LIMIT ?
                """,
                (*params, result_limit),
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            raw_topics = item.pop("related_topics_json", "[]")
            try:
                item["related_topics"] = json.loads(raw_topics or "[]")
            except (TypeError, json.JSONDecodeError):
                item["related_topics"] = []
            rank = float(item.pop("rank"))
            item["score"] = max(0, round(1000 / (1 + abs(rank))))
            item["warnings"] = ["internal context only; verify legal propositions against authoritative sources"]
            results.append(item)

        return {
            "layer": layer,
            "query": query,
            "filters": {"channel": channel, "topic": topic, "status": status},
            "default_status_policy": (
                "keep_commentary_or_keep_guideline" if layer == "telegram_reviewed" else "explicit_or_all"
            ),
            "total": total,
            "results": results,
            "snapshot": self.snapshot.validate().to_dict(),
        }

    def _get_card(self, arguments: dict[str, Any], *, layer: str) -> dict[str, Any]:
        path = str(arguments.get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        max_chars = bounded_int(
            arguments.get("max_chars"), default=16000, minimum=1, maximum=200000, name="max_chars"
        )
        with self.snapshot.connect() as database:
            row = database.execute(
                "SELECT * FROM curated_cards WHERE source_path = ? AND layer = ?",
                (path, layer),
            ).fetchone()
        if row is None:
            raise KeyError(f"local {layer} card not found")
        item = dict(row)
        metadata = json.loads(item.get("frontmatter_json") or "{}")
        body = str(item.get("body") or "")
        linked_text = str(item.get("linked_text") or "")
        content = body
        if linked_text and linked_text.strip() not in body:
            content = f"{body}\n\n## Full extracted text\n\n{linked_text}"
        page = content[:max_chars]
        metadata["source_sha256"] = item.get("source_sha256")
        metadata["linked_text_sha256"] = item.get("linked_text_sha256")
        metadata["authority_class"] = item.get("authority_class")
        return {
            "layer": layer,
            "path": item["source_path"],
            "title": item["title"],
            "metadata": metadata,
            "content": page,
            "truncated": len(page) < len(content),
            "snapshot": self.snapshot.validate().to_dict(),
            "warnings": ["internal context only; verify legal propositions against authoritative sources"],
        }

    def _list_topic_maps(self) -> dict[str, Any]:
        with self.snapshot.connect() as database:
            rows = database.execute(
                "SELECT slug, title, source_path AS path, status, source_sha256 AS content_hash "
                "FROM topic_maps ORDER BY title, slug"
            ).fetchall()
        return {
            "total": len(rows),
            "topic_maps": [dict(row) for row in rows],
            "snapshot": self.snapshot.validate().to_dict(),
            "warnings": ["topic maps are navigation only, not legal authority"],
        }

    def _get_topic_map(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identity = str(arguments.get("path_or_slug") or "").strip()
        if not identity:
            raise ValueError("path_or_slug is required")
        max_chars = bounded_int(
            arguments.get("max_chars"), default=20000, minimum=1, maximum=200000, name="max_chars"
        )
        with self.snapshot.connect() as database:
            row = database.execute(
                "SELECT * FROM topic_maps WHERE slug = ? OR source_path = ? LIMIT 1",
                (identity, identity),
            ).fetchone()
        if row is None:
            raise KeyError("local topic map not found")
        item = dict(row)
        content = str(item.get("body") or "")
        page = content[:max_chars]
        return {
            "slug": item["slug"],
            "title": item["title"],
            "path": item["source_path"],
            "content": page,
            "truncated": len(page) < len(content),
            "status": item.get("status"),
            "content_hash": item.get("source_sha256"),
            "authority_class": item.get("authority_class"),
            "snapshot": self.snapshot.validate().to_dict(),
            "warnings": ["topic maps are navigation only, not legal authority"],
        }
