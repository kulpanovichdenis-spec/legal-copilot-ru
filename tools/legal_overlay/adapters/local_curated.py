"""Read-only adapter over canonical local playbooks and their card files."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.profile.profile_lib import repo_root

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..ru_stem import prefix_stem
from .base import ProviderAdapter


ALLOWED_PATTERNS = ("*-playbook*.md", "*-playbook-cards/**/*.md")
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PAGE_CHARS = 200_000
TOOL_NAMES = {"search_local_curated", "get_local_curated"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"[0-9a-zа-я]{2,}", _normalize(value))))


def _title(text: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return match.group(1).strip() if match else fallback


def _snippet(text: str, tokens: tuple[str, ...], *, limit: int = 1200) -> str:
    normalized = _normalize(text)
    positions = [normalized.find(token) for token in tokens if normalized.find(token) >= 0]
    start = max(0, (min(positions) if positions else 0) - 240)
    return normalized[start : start + limit]


class LocalCuratedAdapter(ProviderAdapter):
    def __init__(self, connection: ProviderConnection, *, repository: Path | None = None) -> None:
        self.connection = connection
        self.repository = (repository or repo_root()).resolve()
        self.references = (self.repository / "references").resolve()

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.connection.provider_id,
            adapter=self.connection.adapter,
            enabled=self.connection.enabled,
            configured=self.connection.configured,
            endpoint=None,
            priority=self.connection.priority,
            capabilities=self.connection.capabilities,
            transitional_external_proxy=False,
            missing_secrets=self.connection.missing_secrets,
        )

    def _allowed_files(self) -> dict[str, Path]:
        if not self.references.is_dir():
            return {}
        allowed: dict[str, Path] = {}
        for pattern in ALLOWED_PATTERNS:
            for candidate in self.references.glob(pattern):
                resolved = candidate.resolve()
                try:
                    relative = resolved.relative_to(self.repository).as_posix()
                    resolved.relative_to(self.references)
                except ValueError:
                    continue
                if resolved.is_file() and resolved.suffix.casefold() == ".md":
                    allowed[relative] = resolved
        return dict(sorted(allowed.items()))

    @staticmethod
    def _read(path: Path) -> str:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("local curated file exceeds the 5 MiB safety limit")
        return path.read_text(encoding="utf-8-sig")

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        files = self._allowed_files()
        if not self.references.is_dir():
            return ProviderHealth(self.connection.provider_id, "not_responding", detail="references directory is missing")
        if not files:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail="no allowlisted playbooks found")
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data={"probe": "local_allowlist", "documents": len(files)},
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_NAMES

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_local_curated",
                "description": "Search canonical local playbooks/cards; results are methodology, not sources of law.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_local_curated",
                "description": "Read a bounded page from an allowlisted canonical local playbook/card path.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_CHARS, "default": 50000},
                    },
                    "required": ["path"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_local_curated":
            return self.search(arguments.get("query"), limit=arguments.get("limit", 10))
        if name == "get_local_curated":
            return self.get(
                arguments.get("path"),
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit", 50_000),
            )
        raise KeyError(f"unknown local curated tool: {name}")

    def search(self, query: Any, *, limit: Any = 10) -> dict[str, Any]:
        text_query = str(query or "").strip()
        tokens = _tokens(text_query)
        if not tokens:
            raise ValueError("query must contain searchable text")
        # Substring match on the Russian stem, so other word forms of the query
        # match too ("гарантии" finds "гарантия"); same rule as full-text search.
        tokens = tuple(dict.fromkeys(prefix_stem(token) or token for token in tokens))
        try:
            result_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        if not 1 <= result_limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        matches: list[dict[str, Any]] = []
        retrieved_at = _now()
        phrase = _normalize(text_query)
        for relative, path in self._allowed_files().items():
            content = self._read(path)
            title = _title(content, path.stem)
            normalized_title = _normalize(title)
            normalized_path = _normalize(relative)
            normalized_content = _normalize(content)
            if not any(token in normalized_content or token in normalized_path for token in tokens):
                continue
            score = sum(8 for token in tokens if token in normalized_title)
            score += sum(4 for token in tokens if token in normalized_path)
            score += sum(1 for token in tokens if token in normalized_content)
            if phrase and phrase in normalized_content:
                score += 12
            matches.append(
                {
                    "path": relative,
                    "title": title,
                    "snippet": _snippet(content, tokens),
                    "content_hash": _content_hash(content),
                    "material_type": "methodology",
                    "score": score,
                    "retrieved_at": retrieved_at,
                }
            )
        matches.sort(key=lambda item: (-item["score"], item["path"]))
        return {"status": "OK", "query": text_query, "results": matches[:result_limit], "retrieved_at": retrieved_at}

    def get(self, path: Any, *, offset: Any = 0, limit: Any = 50_000) -> dict[str, Any]:
        relative = str(path or "").strip().replace("\\", "/")
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise ValueError("path must be a safe repository-relative allowlisted path")
        allowed = self._allowed_files()
        if relative not in allowed:
            raise ValueError("path is not in the local curated allowlist")
        try:
            start = int(offset)
            page_size = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("offset and limit must be integers") from exc
        if start < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= page_size <= MAX_PAGE_CHARS:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_CHARS}")
        content = self._read(allowed[relative])
        total = len(content)
        end = min(start + page_size, total)
        truncated = end < total
        return {
            "status": "OK",
            "path": relative,
            "title": _title(content, allowed[relative].stem),
            "material_type": "methodology",
            "content_hash": _content_hash(content),
            "retrieved_at": _now(),
            "total_chars": total,
            "offset": start,
            "limit": page_size,
            "next_offset": end if truncated else None,
            "truncated": truncated,
            "text": content[start:end],
        }
