#!/usr/bin/env python3
"""Validate common pharma-compliance data and its SQLite projection."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    path = ROOT / "scripts" / "build_database.py"
    spec = importlib.util.spec_from_file_location("pharma_compliance_build", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def validate(db_path: Path) -> dict[str, int]:
    build = load_builder()
    expected = {table: len(json.loads((ROOT / "knowledge" / name).read_text(encoding="utf-8"))) for table, name in build.FILES.items() if table != "links"}
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("integrity_check failed")
        actual = {table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in expected}
        if actual != expected:
            raise RuntimeError(f"record count mismatch: expected={expected}, actual={actual}")
        stored_hash = con.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()[0]
        if stored_hash != build.content_hash():
            raise RuntimeError("database is stale relative to canonical JSON")
        if con.execute("SELECT count(*) FROM cases WHERE jurisdiction != 'RU' AND foreign_pattern_only != 1").fetchone()[0]:
            raise RuntimeError("foreign case missing foreign_pattern_only flag")
        return actual
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "database" / "pharma_compliance.sqlite")
    args = parser.parse_args()
    print(json.dumps(validate(args.database), ensure_ascii=False, sort_keys=True))
