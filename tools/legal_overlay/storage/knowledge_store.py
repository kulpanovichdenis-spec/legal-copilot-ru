"""Schema-backed local lifecycle store for reusable verified knowledge."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from tools.profile.profile_lib import profile_root

from ..models import ContractValidationError, validate_knowledge_object


STATES = ("candidates", "verified", "superseded")
ID_PATTERN = re.compile(r"^ko_[a-z0-9][a-z0-9._-]{2,127}$")
MAX_OBJECT_BYTES = 2 * 1024 * 1024


class KnowledgeStoreError(ValueError):
    """Controlled error for local knowledge lifecycle operations."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def _tokens(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"[0-9a-zа-я]{2,}", _normalize(value))))


class KnowledgeStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or (profile_root() / "knowledge")).resolve()

    def _ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for state in STATES:
            (self.root / state).mkdir(exist_ok=True)

    @staticmethod
    def _knowledge_id(value: Any, *, generate: bool = False) -> str:
        knowledge_id = str(value or "").strip().casefold()
        if not knowledge_id and generate:
            return f"ko_{uuid4().hex}"
        if not ID_PATTERN.fullmatch(knowledge_id):
            raise KnowledgeStoreError(
                "knowledge_id must start with ko_ and contain only lowercase letters, digits, dot, underscore or hyphen"
            )
        return knowledge_id

    def _path(self, state: str, knowledge_id: Any) -> Path:
        if state not in STATES:
            raise KnowledgeStoreError(f"unknown knowledge storage state: {state}")
        safe_id = self._knowledge_id(knowledge_id)
        state_root = (self.root / state).resolve()
        try:
            state_root.relative_to(self.root)
        except ValueError as exc:
            raise KnowledgeStoreError("knowledge state directory leaves the knowledge store") from exc
        path = (state_root / f"{safe_id}.json").resolve()
        try:
            path.relative_to(state_root)
        except ValueError as exc:
            raise KnowledgeStoreError("knowledge_id leaves the knowledge store") from exc
        return path

    @staticmethod
    def _validate(value: dict[str, Any]) -> dict[str, Any]:
        try:
            return validate_knowledge_object(value)
        except ContractValidationError as exc:
            raise KnowledgeStoreError(str(exc)) from exc

    def _read(self, state: str, knowledge_id: Any) -> tuple[dict[str, Any], bytes, Path]:
        path = self._path(state, knowledge_id)
        label = "verified knowledge object" if state == "verified" else f"knowledge {state[:-1]}"
        if not path.is_file():
            raise KnowledgeStoreError(f"{label} not found: {self._knowledge_id(knowledge_id)}")
        if path.stat().st_size > MAX_OBJECT_BYTES:
            raise KnowledgeStoreError("knowledge object exceeds the 2 MiB safety limit")
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KnowledgeStoreError(f"invalid JSON in local knowledge object: {path.name}") from exc
        if not isinstance(value, dict):
            raise KnowledgeStoreError("knowledge object must be a JSON object")
        self._validate(value)
        if value["knowledge_id"] != self._knowledge_id(knowledge_id):
            raise KnowledgeStoreError("knowledge_id does not match its filename")
        return value, raw, path

    @staticmethod
    def _write_new(path: Path, value: dict[str, Any]) -> str:
        raw = _canonical_bytes(value)
        if len(raw) > MAX_OBJECT_BYTES:
            raise KnowledgeStoreError("knowledge object exceeds the 2 MiB safety limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(raw)
        except FileExistsError as exc:
            raise KnowledgeStoreError(f"knowledge object already exists: {path.stem}") from exc
        return _hash_bytes(raw)

    def counts(self) -> dict[str, int]:
        return {
            state: len(list((self.root / state).glob("ko_*.json"))) if (self.root / state).is_dir() else 0
            for state in STATES
        }

    def propose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        knowledge_id = self._knowledge_id(arguments.get("knowledge_id"), generate=True)
        extraction_status = str(arguments.get("extraction_status") or "machine_extracted")
        if extraction_status not in {"machine_extracted", "machine_reviewed"}:
            raise KnowledgeStoreError("candidate extraction_status cannot be human_verified")
        timestamp = _now()
        knowledge = {
            "knowledge_id": knowledge_id,
            "type": arguments.get("type"),
            "topic": arguments.get("topic"),
            "issue": arguments.get("issue"),
            "position": arguments.get("position"),
            "applies_when": list(arguments.get("applies_when") or []),
            "does_not_apply_when": list(arguments.get("does_not_apply_when") or []),
            "provenance": list(arguments.get("provenance") or []),
            "verification": {
                "status": extraction_status,
                "verified_at": None,
                "verified_by": None,
                "note": None,
                "candidate_hash": None,
            },
            "valid_as_of": arguments.get("valid_as_of"),
            "review_questions": list(arguments.get("review_questions") or []),
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "superseded_at": None,
            "superseded_by": None,
            "supersession_reason": None,
        }
        if knowledge["type"] == "practice_pattern":
            knowledge.update(
                {
                    "pattern_kind": arguments.get("pattern_kind"),
                    "support_level": arguments.get("support_level"),
                    "source_case_ids": list(arguments.get("source_case_ids") or []),
                    "reuse_target": list(arguments.get("reuse_target") or []),
                    "legal_dependencies": list(arguments.get("legal_dependencies") or []),
                    "requires_current_law_check": (
                        True
                        if arguments.get("requires_current_law_check") is None
                        else bool(arguments.get("requires_current_law_check"))
                    ),
                }
            )
        self._validate(knowledge)
        self._ensure_layout()
        path = self._path("candidates", knowledge_id)
        content_hash = self._write_new(path, knowledge)
        return {
            "status": "OK",
            "storage_state": "candidates",
            "content_hash": content_hash,
            "knowledge": knowledge,
        }

    def get_verified(self, knowledge_id: Any) -> dict[str, Any]:
        knowledge, raw, _path = self._read("verified", knowledge_id)
        if knowledge["verification"]["status"] != "human_verified":
            raise KnowledgeStoreError("verified directory contains a non-human-verified object")
        if knowledge["status"] == "superseded":
            raise KnowledgeStoreError("verified directory contains a superseded object")
        return {
            "status": "OK",
            "storage_state": "verified",
            "content_hash": _hash_bytes(raw),
            "knowledge": knowledge,
        }

    def search_verified(self, query: Any, *, limit: Any = 10) -> dict[str, Any]:
        query_text = str(query or "").strip()
        tokens = _tokens(query_text)
        if not tokens:
            raise KnowledgeStoreError("query must contain searchable text")
        try:
            result_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise KnowledgeStoreError("limit must be an integer") from exc
        if not 1 <= result_limit <= 50:
            raise KnowledgeStoreError("limit must be between 1 and 50")

        results: list[dict[str, Any]] = []
        verified_dir = self.root / "verified"
        for path in sorted(verified_dir.glob("ko_*.json")) if verified_dir.is_dir() else ():
            knowledge_id = path.stem
            knowledge, raw, _ = self._read("verified", knowledge_id)
            if knowledge["verification"]["status"] != "human_verified":
                raise KnowledgeStoreError(f"verified object is not human_verified: {knowledge_id}")
            if knowledge["status"] == "superseded":
                raise KnowledgeStoreError(f"superseded object is misplaced in verified storage: {knowledge_id}")
            haystack = _normalize(
                " ".join(
                    [
                        str(knowledge.get("topic") or ""),
                        str(knowledge.get("pattern_kind") or ""),
                        str(knowledge.get("support_level") or ""),
                        str(knowledge["issue"]),
                        str(knowledge["position"]),
                        *[str(item) for item in knowledge.get("source_case_ids", [])],
                        *[str(item) for item in knowledge.get("applies_when", [])],
                        *[str(item) for item in knowledge.get("does_not_apply_when", [])],
                        *[str(item) for item in knowledge.get("reuse_target", [])],
                    ]
                )
            )
            if not any(token in haystack for token in tokens):
                continue
            phrase = _normalize(query_text)
            score = sum(2 for token in tokens if token in haystack) + (10 if phrase in haystack else 0)
            results.append(
                {
                    "knowledge_id": knowledge_id,
                    "type": knowledge["type"],
                    "topic": knowledge.get("topic"),
                    "pattern_kind": knowledge.get("pattern_kind"),
                    "support_level": knowledge.get("support_level"),
                    "source_case_ids": knowledge.get("source_case_ids", []),
                    "reuse_target": knowledge.get("reuse_target", []),
                    "issue": knowledge["issue"],
                    "position": knowledge["position"],
                    "valid_as_of": knowledge.get("valid_as_of"),
                    "status": knowledge["status"],
                    "verification": knowledge["verification"],
                    "content_hash": _hash_bytes(raw),
                    "score": score,
                }
            )
        results.sort(key=lambda item: (-item["score"], item["knowledge_id"]))
        return {"status": "OK", "query": query_text, "results": results[:result_limit], "retrieved_at": _now()}

    def verify_candidate(
        self,
        knowledge_id: Any,
        *,
        candidate_hash: Any,
        verified_by: Any,
        verification_note: Any = None,
        apply: bool = False,
        confirm_human_verified: bool = False,
    ) -> dict[str, Any]:
        candidate, raw, candidate_path = self._read("candidates", knowledge_id)
        actual_hash = _hash_bytes(raw)
        if str(candidate_hash or "").strip().casefold() != actual_hash:
            raise KnowledgeStoreError("candidate hash does not match the current file")
        verifier = str(verified_by or "").strip()
        if not verifier:
            raise KnowledgeStoreError("verified_by is required for human verification")
        timestamp = _now()
        verified = deepcopy(candidate)
        verified["verification"] = {
            "status": "human_verified",
            "verified_at": timestamp,
            "verified_by": verifier,
            "note": str(verification_note).strip() if verification_note else None,
            "candidate_hash": actual_hash,
        }
        verified["updated_at"] = timestamp
        self._validate(verified)
        target = self._path("verified", candidate["knowledge_id"])
        response = {
            "status": "PREVIEW" if not apply else "OK",
            "applied": False,
            "storage_state": "verified",
            "candidate_hash": actual_hash,
            "operations": [
                f"create verified/{target.name}",
                f"remove candidates/{candidate_path.name}",
            ],
            "knowledge": verified,
        }
        if not apply:
            return response
        if confirm_human_verified is not True:
            raise KnowledgeStoreError("explicit human verification confirmation is required")
        if target.exists():
            raise KnowledgeStoreError(f"verified knowledge object already exists: {target.stem}")
        content_hash = self._write_new(target, verified)
        try:
            candidate_path.unlink()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        response.update({"status": "OK", "applied": True, "content_hash": content_hash})
        return response

    def supersede_verified(
        self,
        knowledge_id: Any,
        *,
        content_hash: Any,
        reason: Any,
        confirmed_by: Any,
        replacement_id: Any = None,
        apply: bool = False,
        confirm_supersede: bool = False,
    ) -> dict[str, Any]:
        verified, raw, verified_path = self._read("verified", knowledge_id)
        actual_hash = _hash_bytes(raw)
        if str(content_hash or "").strip().casefold() != actual_hash:
            raise KnowledgeStoreError("verified content hash does not match the current file")
        reason_text = str(reason or "").strip()
        actor = str(confirmed_by or "").strip()
        if not reason_text or not actor:
            raise KnowledgeStoreError("reason and confirmed_by are required to supersede knowledge")
        replacement = self._knowledge_id(replacement_id) if replacement_id else None
        timestamp = _now()
        superseded = deepcopy(verified)
        superseded["status"] = "superseded"
        superseded["updated_at"] = timestamp
        superseded["superseded_at"] = timestamp
        superseded["superseded_by"] = replacement
        superseded["supersession_reason"] = f"{reason_text} (confirmed by {actor})"
        self._validate(superseded)
        target = self._path("superseded", verified["knowledge_id"])
        response = {
            "status": "PREVIEW" if not apply else "OK",
            "applied": False,
            "storage_state": "superseded",
            "source_hash": actual_hash,
            "operations": [
                f"create superseded/{target.name}",
                f"remove verified/{verified_path.name}",
            ],
            "knowledge": superseded,
        }
        if not apply:
            return response
        if confirm_supersede is not True:
            raise KnowledgeStoreError("explicit supersede confirmation is required")
        if target.exists():
            raise KnowledgeStoreError(f"superseded knowledge object already exists: {target.stem}")
        new_hash = self._write_new(target, superseded)
        try:
            verified_path.unlink()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        response.update({"status": "OK", "applied": True, "content_hash": new_hash})
        return response
