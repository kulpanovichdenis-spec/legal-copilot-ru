"""Read-only adapters for bundled and private pharma-compliance knowledge."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.profile.profile_lib import profile_root, repo_root

from ..models import ProviderDescriptor, ProviderHealth
from .base import ProviderAdapter

PROVIDER_ID = "local-pharma-compliance"
COMMON_DB = repo_root() / "skills" / "pharma-compliance" / "database" / "pharma_compliance.sqlite"
PRIVATE_DB = lambda: profile_root() / "knowledge" / "compliance" / "index" / "company_compliance.sqlite"
STOP = {"и", "в", "во", "на", "по", "с", "со", "для", "это", "ли", "наш", "можно", "хотим"}
TABLES = {"source": ("sources", "source_id"), "rule": ("rules", "rule_id"), "case": ("cases", "case_id"), "pattern": ("patterns", "pattern_id"), "control": ("controls", "control_id")}


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def fts_query(value: Any) -> str:
    tokens = [t.casefold() for t in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(value or ""))]
    tokens = list(dict.fromkeys(t for t in tokens if len(t) >= 3 and t not in STOP))[:24]
    if not tokens:
        raise ValueError("query must contain searchable text")
    return " OR ".join(f'"{t[:8].replace(chr(34), chr(34) * 2)}"*' for t in tokens)


def schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    result = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        result["required"] = list(required)
    return result


TOOLS = {
    "search_pharma_compliance": {"description": "Search bundled pharma-compliance rules, patterns, cases and controls; navigation only.", "inputSchema": schema({"query": {"type": "string", "minLength": 1}, "entity_types": {"type": "array", "items": {"enum": list(TABLES)}}, "domain": {"type": "string"}, "jurisdiction": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}, ("query",))},
    "get_pharma_compliance_item": {"description": "Get one bundled compliance item by type and ID.", "inputSchema": schema({"entity_type": {"enum": list(TABLES)}, "entity_id": {"type": "string", "minLength": 1}}, ("entity_type", "entity_id"))},
    "search_company_compliance": {"description": "Search confidential company compliance cards when the private index exists.", "inputSchema": schema({"query": {"type": "string", "minLength": 1}, "status": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}, ("query",))},
    "pharma_compliance_status": {"description": "Show health and record counts for common and private compliance indexes.", "inputSchema": schema({})},
}


class PharmaComplianceAdapter(ProviderAdapter):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(PROVIDER_ID, "builtin_pharma_compliance", True, COMMON_DB.is_file(), str(COMMON_DB), 25, ("pharma_compliance", "company_policies", "controls"))

    def health(self) -> ProviderHealth:
        if not COMMON_DB.is_file():
            return ProviderHealth(PROVIDER_ID, "not_configured", detail="bundled common index is missing")
        try:
            with connect(COMMON_DB) as con:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("common index integrity_check failed")
                counts = {table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("sources", "rules", "cases", "patterns", "controls")}
            private = PRIVATE_DB()
            if private.is_file():
                with connect(private) as con:
                    counts["company_cards"] = con.execute("SELECT count(*) FROM company_cards").fetchone()[0]
                    counts["open_company_conflicts"] = con.execute("SELECT count(*) FROM local_conflicts WHERE status='open'").fetchone()[0]
            else:
                counts["company_cards"] = 0
            return ProviderHealth(PROVIDER_ID, "connected", data=counts)
        except Exception as exc:
            return ProviderHealth(PROVIDER_ID, "not_responding", detail=str(exc))

    def owns_tool(self, name: str) -> bool:
        return name in TOOLS

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": name, **spec} for name, spec in TOOLS.items()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_pharma_compliance":
            return self._search_common(arguments)
        if name == "get_pharma_compliance_item":
            return self._get_common(arguments)
        if name == "search_company_compliance":
            return self._search_private(arguments)
        if name == "pharma_compliance_status":
            return self.health().to_dict()
        raise KeyError(f"unknown pharma-compliance tool: {name}")

    def _search_common(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limit", 10)), 50))
        types = args.get("entity_types") or list(TABLES)
        unknown = set(types) - set(TABLES)
        if unknown:
            raise ValueError(f"unknown entity_types: {sorted(unknown)}")
        with connect(COMMON_DB) as con:
            rows = con.execute("SELECT entity_type,entity_id,title,snippet(knowledge_fts,3,'[',']',' … ',24) AS snippet,bm25(knowledge_fts) AS rank FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?", (fts_query(args.get("query")), limit * 4)).fetchall()
            results = []
            for row in rows:
                if row["entity_type"] not in types:
                    continue
                table, key = TABLES[row["entity_type"]]
                item = dict(con.execute(f"SELECT * FROM {table} WHERE {key}=?", (row["entity_id"],)).fetchone())
                if args.get("domain") and item.get("domain") != args["domain"]:
                    continue
                jurisdiction = item.get("jurisdiction") or item.get("jurisdiction_scope")
                if args.get("jurisdiction") and jurisdiction != args["jurisdiction"]:
                    continue
                results.append({"entity_type": row["entity_type"], "entity_id": row["entity_id"], "title": row["title"], "snippet": row["snippet"], "data": item})
                if len(results) >= limit:
                    break
        return {"total": len(results), "results": results, "warnings": ["navigation index only; verify legal propositions against current authoritative sources", "foreign cases are pattern-only and do not state Russian law"]}

    def _get_common(self, args: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(args.get("entity_type") or "")
        if entity_type not in TABLES:
            raise ValueError("unknown entity_type")
        table, key = TABLES[entity_type]
        with connect(COMMON_DB) as con:
            row = con.execute(f"SELECT * FROM {table} WHERE {key}=?", (str(args.get("entity_id") or ""),)).fetchone()
        if row is None:
            raise KeyError("pharma-compliance item not found")
        return {"entity_type": entity_type, "data": dict(row), "warnings": ["navigation record only; check provenance and verify legal propositions"]}

    def _search_private(self, args: dict[str, Any]) -> dict[str, Any]:
        path = PRIVATE_DB()
        warning = "no indexed company rule was found; zero hits do not prove absence; coverage and source documents must still be checked"
        if not path.is_file():
            return {"total": 0, "results": [], "index_status": "missing", "warnings": [warning]}
        limit = max(1, min(int(args.get("limit", 10)), 50))
        with connect(path) as con:
            sql = "SELECT c.*, d.title AS document_title, d.version AS document_version, d.status AS document_status FROM company_fts f JOIN company_cards c ON c.card_id=f.card_id JOIN company_documents d ON d.document_id=c.document_id WHERE company_fts MATCH ?"
            values: list[Any] = [fts_query(args.get("query"))]
            if args.get("status"):
                sql += " AND c.status=?"
                values.append(args["status"])
            sql += " ORDER BY bm25(company_fts) LIMIT ?"
            values.append(limit)
            rows = [dict(row) for row in con.execute(sql, values)]
            conflicts = [dict(row) for row in con.execute("SELECT * FROM local_conflicts WHERE status='open'")]
        warnings = ["company rules are internal requirements, not law"]
        if not rows:
            warnings.append(warning)
        if conflicts:
            warnings.append("LOCAL_RULE_CONFLICT: unresolved policy conflicts exist")
        return {"total": len(rows), "results": rows, "open_conflicts": conflicts, "warnings": warnings}
