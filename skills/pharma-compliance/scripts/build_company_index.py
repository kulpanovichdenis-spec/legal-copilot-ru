#!/usr/bin/env python3
"""Build the private company-compliance index from profile cards."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CARD_TYPES = {
    "prohibition", "permission", "permission_with_conditions", "mandatory_action",
    "approval_requirement", "escalation_trigger", "limit_threshold", "exception",
    "role_responsibility", "process_step", "documentation_requirement",
    "retention_requirement", "control", "definition",
}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        value = yaml.safe_load(text)
    elif text.startswith("---"):
        value = yaml.safe_load(text.split("---", 2)[1])
    else:
        value = None
    if not isinstance(value, dict):
        raise ValueError(f"card must contain a mapping: {path}")
    return value


def json_value(value) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def build(layer: Path, target: Path, *, confirm_overwrite: bool = False) -> Path:
    layer, target = layer.resolve(), target.resolve()
    if target.exists() and not confirm_overwrite:
        raise FileExistsError(f"Refusing to overwrite {target}; pass --confirm-overwrite")
    documents = [frontmatter(p) for p in sorted((layer / "cards" / "documents").glob("*.md"))]
    rules = [frontmatter(p) for pattern in ("*.yaml", "*.yml") for p in sorted((layer / "cards" / "rules").glob(pattern))]
    for rule in rules:
        if rule.get("card_type") not in CARD_TYPES:
            raise ValueError(f"invalid card_type in {rule.get('card_id', '<unknown>')}")
        source = rule.get("source") or {}
        if not source.get("original_path") or not any(source.get(k) for k in ("section", "page", "locator_text")):
            raise ValueError(f"missing source locator in {rule.get('card_id', '<unknown>')}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        con = sqlite3.connect(tmp)
        schema = Path(__file__).resolve().parents[1] / "database" / "company_index_schema.sql"
        con.executescript(schema.read_text(encoding="utf-8"))
        manifest_path = layer / "manifest.yaml"
        manifest_text = manifest_path.read_text(encoding="utf-8-sig") if manifest_path.exists() else ""
        con.executemany("INSERT INTO company_manifest(key,value) VALUES(?,?)", [
            ("source_sha256", hashlib.sha256(manifest_text.encode()).hexdigest()),
            ("authority_notice", "Internal company rules; not law. Zero hits do not prove absence."),
        ])
        for doc in documents:
            con.execute(
                "INSERT INTO company_documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (doc.get("document_id"), doc.get("title"), doc.get("document_type"), doc.get("version"),
                 doc.get("status", "candidate"), doc.get("effective_from"), doc.get("effective_to"),
                 doc.get("authority_rank"), doc.get("owner_function"),
                 (doc.get("source_files") or [""])[0], doc.get("source_hash")),
            )
        known_docs = {d.get("document_id") for d in documents}
        for rule in rules:
            doc = rule.get("document") or {}
            doc_id = doc.get("document_id")
            if doc_id not in known_docs:
                con.execute(
                    "INSERT INTO company_documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (doc_id, doc.get("title", doc_id), doc.get("document_type"), doc.get("version"),
                     doc.get("status", "candidate"), doc.get("effective_from"), doc.get("effective_to"),
                     doc.get("authority_rank"), doc.get("owner_function"),
                     (rule.get("source") or {}).get("original_path", ""), None),
                )
                known_docs.add(doc_id)
            source = rule.get("source") or {}
            locator = "; ".join(str(source[k]) for k in ("section", "page", "locator_text") if source.get(k) is not None)
            columns = (rule.get("card_id"), doc_id, rule.get("card_type"), rule.get("title"),
                       rule.get("normalized_rule"), json_value(rule.get("scope")), json_value(rule.get("conditions")),
                       json_value(rule.get("exceptions")), json_value(rule.get("approvals")), json_value(rule.get("thresholds")),
                       json_value(rule.get("documentation")), json_value(rule.get("escalation")),
                       json_value(rule.get("related_global_domains")), json_value(rule.get("related_patterns")), locator,
                       rule.get("effective_from") or doc.get("effective_from"), rule.get("effective_to") or doc.get("effective_to"),
                       rule.get("status", "candidate"))
            con.execute("INSERT INTO company_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", columns)
            tags = " ".join([rule.get("card_type", ""), *rule.get("related_global_domains", []), *rule.get("related_patterns", [])])
            con.execute("INSERT INTO company_fts(card_id,title,normalized_rule,tags) VALUES(?,?,?,?)",
                        (rule.get("card_id"), rule.get("title"), rule.get("normalized_rule"), tags))
        if manifest_text:
            manifest = yaml.safe_load(manifest_text) or {}
            for item in manifest.get("coverage", []):
                con.execute("INSERT INTO coverage(category,loaded,current,verified,notes) VALUES(?,?,?,?,?)",
                            (item["category"], int(bool(item.get("loaded"))), item.get("current"), int(bool(item.get("verified"))), item.get("notes")))
            for item in manifest.get("conflicts", []):
                con.execute("INSERT INTO local_conflicts(conflict_id,card_id_a,card_id_b,status,description) VALUES(?,?,?,?,?)",
                            (item["conflict_id"], item["card_id_a"], item["card_id_b"], item.get("status", "open"), item.get("description")))
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity_check failed")
        con.commit()
        con.close()
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


if __name__ == "__main__":
    from tools.profile.profile_lib import profile_root
    parser = argparse.ArgumentParser()
    default_layer = profile_root() / "knowledge" / "compliance"
    parser.add_argument("--layer", type=Path, default=default_layer)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args()
    output = args.output or args.layer / "index" / "company_compliance.sqlite"
    print(build(args.layer, output, confirm_overwrite=args.confirm_overwrite))
