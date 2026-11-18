#!/usr/bin/env python3
"""Build the common pharma-compliance SQLite projection from versioned JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"
DATABASE = ROOT / "database" / "pharma_compliance.sqlite"
FILES = {
    "sources": "sources.json",
    "rules": "rules.json",
    "cases": "cases.json",
    "patterns": "patterns.json",
    "controls": "controls.json",
    "links": "links.json",
}


def load(name: str):
    return json.loads((KNOWLEDGE / name).read_text(encoding="utf-8"))


def content_hash() -> str:
    digest = hashlib.sha256()
    for name in sorted([*FILES.values(), "search_terms.json"]):
        digest.update(name.encode())
        digest.update((KNOWLEDGE / name).read_bytes())
    digest.update((ROOT / "database" / "schema.sql").read_bytes())
    return digest.hexdigest()


def tags_for(obj: dict) -> list[str]:
    tags = set(obj.get("tags", []))
    for key in ("jurisdiction", "jurisdiction_scope", "domain", "risk_dimension", "rule_type", "authority_type", "case_type"):
        if obj.get(key):
            tags.add(str(obj[key]))
    return sorted(tags)


def insert_fts(con: sqlite3.Connection, entity_type: str, entity_id: str, title: str, body: str, tags: list[str], aliases: dict[str, str]) -> None:
    extra = aliases.get(entity_id, "")
    con.execute(
        "INSERT INTO knowledge_fts(entity_type,entity_id,title,body,tags) VALUES(?,?,?,?,?)",
        (entity_type, entity_id, title, f"{body} {extra}".strip(), " ".join(tags)),
    )
    con.executemany(
        "INSERT OR IGNORE INTO entity_tags VALUES(?,?,?)",
        ((entity_type, entity_id, tag) for tag in tags),
    )


def populate(db_path: Path) -> None:
    aliases = load("search_terms.json")
    con = sqlite3.connect(db_path)
    try:
        con.executescript((ROOT / "database" / "schema.sql").read_text(encoding="utf-8"))
        meta = {
            "product": "Pharma Compliance Playbook & Knowledge Layer",
            "format_version": "1",
            "source_sha256": content_hash(),
            "authority_notice": "Navigation index only; legal propositions require verification.",
        }
        con.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", sorted(meta.items()))

        configs = {
            "sources": ("source", "source_id", ["source_id", "title", "jurisdiction", "source_type", "authority_level", "publisher", "url", "source_date", "effective_from", "effective_to", "status", "notes"], ["notes"]),
            "rules": ("rule", "rule_id", ["rule_id", "title", "jurisdiction", "authority_type", "rule_type", "summary", "applicability", "domain", "source_id", "source_locator", "valid_from", "valid_to", "status"], ["summary", "applicability", "source_locator"]),
            "patterns": ("pattern", "pattern_id", ["pattern_id", "title", "pattern_type", "jurisdiction_scope", "domain", "risk_dimension", "severity_hint", "description", "legitimate_explanation", "aggravating_factors", "mitigating_factors", "evidentiary_significance", "russian_legal_relevance", "foreign_pattern", "status"], ["description", "legitimate_explanation", "aggravating_factors", "mitigating_factors", "evidentiary_significance", "russian_legal_relevance"]),
            "controls": ("control", "control_id", ["control_id", "title", "control_type", "domain", "description", "expected_evidence", "status"], ["description", "expected_evidence"]),
            "cases": ("case", "case_id", ["case_id", "title", "jurisdiction", "case_type", "authority_body", "decision_date", "outcome", "summary", "primary_source_id", "source_locator", "foreign_pattern_only"], ["summary", "outcome", "source_locator"]),
        }
        for table in ("sources", "rules", "patterns", "controls", "cases"):
            entity_type, id_key, columns, body_keys = configs[table]
            for obj in load(FILES[table]):
                values = [obj.get(col, "active" if col == "status" else None) for col in columns]
                con.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
                insert_fts(con, entity_type, obj[id_key], obj["title"], " ".join(str(obj.get(k) or "") for k in body_keys), tags_for(obj), aliases)
                if table == "cases":
                    con.executemany("INSERT INTO case_patterns(case_id,pattern_id,treatment) VALUES(?,?,?)", ((obj[id_key], pid, "supported_by_case") for pid in obj.get("patterns", [])))

        for pattern_id, control_ids in load(FILES["links"]).items():
            con.executemany("INSERT INTO pattern_controls(pattern_id,control_id,relation) VALUES(?,?,?)", ((pattern_id, control_id, "mitigates_or_operationalizes") for control_id in control_ids))
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity_check failed")
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()


def build(target: Path, *, confirm_overwrite: bool = False) -> Path:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not confirm_overwrite:
        raise FileExistsError(f"Refusing to overwrite {target}; pass --confirm-overwrite")
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        populate(tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DATABASE)
    parser.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args()
    print(build(args.output, confirm_overwrite=args.confirm_overwrite))
