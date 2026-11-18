"""Validate and optionally import a JSON batch of knowledge candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __name__ == "__main__" and __package__ in (None, ""):
    import sys as _sys

    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

from tools.legal_overlay.storage.knowledge_store import KnowledgeStore, KnowledgeStoreError


class CandidateBatchError(ValueError):
    """Controlled failure for candidate batch import."""


def _load_batch(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or not value:
        raise CandidateBatchError("candidate batch must be a non-empty JSON array")
    if not all(isinstance(item, dict) for item in value):
        raise CandidateBatchError("every candidate must be a JSON object")
    ids = [str(item.get("knowledge_id") or "") for item in value]
    if len(ids) != len(set(ids)):
        raise CandidateBatchError("candidate batch contains duplicate knowledge_id values")
    return value


def validate_batch(candidates: list[dict[str, Any]]) -> None:
    with TemporaryDirectory(prefix="case-knowledge-") as temp_dir:
        store = KnowledgeStore(Path(temp_dir) / "knowledge")
        for candidate in candidates:
            store.propose(candidate)


def import_batch(path: Path, knowledge_root: Path, *, apply: bool = False) -> dict[str, Any]:
    candidates = _load_batch(path)
    validate_batch(candidates)
    store = KnowledgeStore(knowledge_root)
    conflicts = [
        candidate["knowledge_id"]
        for candidate in candidates
        if (knowledge_root / "candidates" / f"{candidate['knowledge_id']}.json").exists()
        or (knowledge_root / "verified" / f"{candidate['knowledge_id']}.json").exists()
        or (knowledge_root / "superseded" / f"{candidate['knowledge_id']}.json").exists()
    ]
    if conflicts:
        raise CandidateBatchError(f"knowledge_id already exists: {', '.join(conflicts)}")
    if not apply:
        return {"status": "PREVIEW", "count": len(candidates), "knowledge_ids": [item["knowledge_id"] for item in candidates]}
    results = [store.propose(candidate) for candidate in candidates]
    return {
        "status": "OK",
        "count": len(results),
        "knowledge_ids": [item["knowledge"]["knowledge_id"] for item in results],
        "content_hashes": {item["knowledge"]["knowledge_id"]: item["content_hash"] for item in results},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--knowledge-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = import_batch(args.input.resolve(), args.knowledge_root.resolve(), apply=args.apply)
    except (CandidateBatchError, KnowledgeStoreError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
