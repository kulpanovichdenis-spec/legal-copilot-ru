"""Shared validation and read-only access for SQLite Copilot snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .config import ConfigurationError, ProviderConnection
from .ru_stem import prefix_stem


SUPPORTED_SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 2 * 1024 * 1024
DEFAULT_STALE_AFTER_DAYS = 30


class SnapshotValidationError(ConfigurationError):
    """A controlled error raised before an untrusted snapshot is queried."""


@dataclass(frozen=True)
class SnapshotMetadata:
    database: str
    database_path: Path
    bytes: int
    sha256: str
    generated_at: str
    source_exported_at: str | None
    schema_version: int
    possibly_stale: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "generated_at": self.generated_at,
            "source_exported_at": self.source_exported_at,
            "schema_version": self.schema_version,
            "hash_verified": True,
            "possibly_stale": self.possibly_stale,
            "access": "mode=ro&immutable=1",
        }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SnapshotValidationError(f"snapshot report is missing: {path.name}")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise SnapshotValidationError(f"snapshot report is too large: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"snapshot report is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"snapshot report must contain an object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(value: str | None, stale_after_days: int) -> bool:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return True
    age = datetime.now(timezone.utc) - parsed
    return age.total_seconds() > stale_after_days * 86400


def fts_query(value: Any, *, stem_russian: bool = False) -> str:
    """Turn arbitrary user text into a literal, operator-free FTS5 OR query.

    With ``stem_russian`` each Russian word is replaced by its stem as a prefix
    term, so other word forms match ("недостатки" also finds "недостатками").
    Off by default: corpora in other languages (Uzbek) must not be stemmed with
    Russian rules. Known Snowball limit: fleeting vowels ("недостаток" has the
    stem "недостаток", "недостатки" has "недостатк").
    """
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(value or ""))
    tokens = list(dict.fromkeys(token.casefold() for token in tokens if token.strip()))
    if not tokens:
        raise ValueError("query must contain searchable text")
    terms = []
    for token in tokens[:32]:
        quoted = token.replace(chr(34), chr(34) * 2)
        root = prefix_stem(token) if stem_russian else None
        terms.append(f'"{root}"*' if root else f'"{quoted}"')
    return " OR ".join(dict.fromkeys(terms))


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int, name: str) -> int:
    try:
        result = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


class SQLiteSnapshot:
    """Validate one database against aggregate and per-database reports, once."""

    def __init__(
        self,
        connection: ProviderConnection,
        *,
        database: str,
        required_tables: tuple[str, ...],
    ) -> None:
        self.connection = connection
        self.database = database
        self.required_tables = required_tables
        raw_root = str(connection.options.get("snapshot_dir") or "").strip()
        self._unresolved_root = not raw_root or "${" in raw_root
        self.root = Path(raw_root).expanduser() if raw_root and not self._unresolved_root else None
        self._metadata: SnapshotMetadata | None = None

    @property
    def configured(self) -> bool:
        return bool(self.connection.enabled and self.root is not None)

    def public_root(self) -> str | None:
        return str(self.root) if self.root is not None else None

    def validate(self) -> SnapshotMetadata:
        if self._metadata is not None:
            return self._metadata
        if self.root is None:
            raise SnapshotValidationError("snapshot_dir is not configured")

        root = self.root.resolve()
        if not root.is_dir():
            raise SnapshotValidationError("snapshot directory does not exist")
        database_path = (root / self.database).resolve()
        try:
            database_path.relative_to(root)
        except ValueError as exc:
            raise SnapshotValidationError("snapshot database escapes configured directory") from exc
        if not database_path.is_file():
            raise SnapshotValidationError(f"snapshot database is missing: {self.database}")

        aggregate = _read_json(root / "migration-report.json")
        if aggregate.get("format") != "sqlite-copilot-aggregate-migration-report":
            raise SnapshotValidationError("unsupported aggregate migration report format")
        if aggregate.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise SnapshotValidationError("unsupported aggregate schema_version")
        if aggregate.get("status") != "OK":
            raise SnapshotValidationError("aggregate migration report status is not OK")
        entries = aggregate.get("databases")
        if not isinstance(entries, list):
            raise SnapshotValidationError("aggregate migration report has no databases list")
        entry = next((item for item in entries if isinstance(item, dict) and item.get("database") == self.database), None)
        if entry is None:
            raise SnapshotValidationError(f"aggregate report has no entry for {self.database}")
        if entry.get("integrity_check") != "ok" or entry.get("foreign_key_violations") != 0:
            raise SnapshotValidationError(f"aggregate integrity checks failed for {self.database}")

        report_name = self.database.removesuffix(".sqlite") + "-migration-report.json"
        report = _read_json(root / report_name)
        if report.get("format") != "sqlite-copilot-migration-report":
            raise SnapshotValidationError(f"unsupported report format for {self.database}")
        if report.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise SnapshotValidationError(f"unsupported schema_version for {self.database}")
        if report.get("database") != self.database:
            raise SnapshotValidationError(f"per-database report identity mismatch for {self.database}")
        if report.get("integrity_check") != "ok" or report.get("foreign_key_violations") != 0:
            raise SnapshotValidationError(f"per-database integrity checks failed for {self.database}")

        actual_size = database_path.stat().st_size
        expected_size = entry.get("bytes")
        if expected_size != actual_size:
            raise SnapshotValidationError(f"snapshot size mismatch for {self.database}")
        expected_hash = str(entry.get("sha256") or "").casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise SnapshotValidationError(f"aggregate SHA-256 is invalid for {self.database}")
        if str(report.get("database_sha256") or "").casefold() != expected_hash:
            raise SnapshotValidationError(f"migration reports disagree for {self.database}")
        actual_hash = _sha256(database_path)
        if actual_hash != expected_hash:
            raise SnapshotValidationError(f"snapshot SHA-256 mismatch for {self.database}")

        uri = database_path.as_uri() + "?mode=ro&immutable=1"
        try:
            with sqlite3.connect(uri, uri=True) as database:
                database.execute("PRAGMA query_only = ON")
                tables = {
                    str(row[0])
                    for row in database.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
                }
                missing_tables = sorted(set(self.required_tables) - tables)
                if missing_tables:
                    raise SnapshotValidationError(
                        f"snapshot schema is missing required tables for {self.database}: {', '.join(missing_tables)}"
                    )
                quick_check = database.execute("PRAGMA quick_check").fetchone()
                if not quick_check or quick_check[0] != "ok":
                    raise SnapshotValidationError(f"live quick_check failed for {self.database}")
                foreign_key_violation = database.execute("PRAGMA foreign_key_check").fetchone()
                if foreign_key_violation is not None:
                    raise SnapshotValidationError(f"live foreign_key_check failed for {self.database}")
        except sqlite3.Error as exc:
            raise SnapshotValidationError(f"snapshot database is unreadable: {self.database}") from exc

        generated_at = str(aggregate.get("generated_at") or "")
        source_exported_at = str(report.get("source_exported_at") or "") or None
        stale_after_days = bounded_int(
            self.connection.options.get("stale_after_days"),
            default=DEFAULT_STALE_AFTER_DAYS,
            minimum=1,
            maximum=3650,
            name="stale_after_days",
        )
        metadata = SnapshotMetadata(
            database=self.database,
            database_path=database_path,
            bytes=actual_size,
            sha256=actual_hash,
            generated_at=generated_at,
            source_exported_at=source_exported_at,
            schema_version=SUPPORTED_SCHEMA_VERSION,
            possibly_stale=_is_stale(source_exported_at or generated_at, stale_after_days),
        )

        with self.connect(metadata=metadata) as connection:
            available = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
            }
            missing = sorted(set(self.required_tables) - available)
            if missing:
                raise SnapshotValidationError(f"snapshot is missing required tables: {', '.join(missing)}")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SnapshotValidationError(f"SQLite quick_check failed for {self.database}")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise SnapshotValidationError(f"SQLite foreign_key_check failed for {self.database}")

        self._metadata = metadata
        return metadata

    def connect(self, *, metadata: SnapshotMetadata | None = None) -> sqlite3.Connection:
        selected = metadata or self.validate()
        uri = selected.database_path.as_uri() + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
