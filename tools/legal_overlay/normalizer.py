"""Normalize provider-native results into provenance-preserving evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import EvidenceItem


@dataclass(frozen=True)
class NormalizationResult:
    evidence: tuple[EvidenceItem, ...]
    warnings: tuple[str, ...] = ()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_id(provider_id: str, external_id: str | None, title: str) -> str:
    source = f"{provider_id}\0{external_id or ''}\0{title}".encode("utf-8")
    return f"ev_{hashlib.sha256(source).hexdigest()[:24]}"


def _json_from_content(value: Any) -> tuple[Any, list[str]]:
    if not isinstance(value, dict) or not isinstance(value.get("content"), list):
        return value, []
    parsed_values: list[Any] = []
    warnings: list[str] = []
    for item in value["content"]:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = str(item.get("text") or "")
        try:
            parsed_values.append(json.loads(text))
        except json.JSONDecodeError:
            warnings.append("provider returned non-JSON text; it was not normalized as evidence")
    if len(parsed_values) == 1:
        return parsed_values[0], warnings
    return parsed_values, warnings


def _as_items(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    unwrapped, warnings = _json_from_content(value)
    if isinstance(unwrapped, dict) and "result" in unwrapped:
        return _as_items(unwrapped["result"])
    if isinstance(unwrapped, dict):
        for key in ("results", "documents", "items", "evidence"):
            if isinstance(unwrapped.get(key), list):
                return [item for item in unwrapped[key] if isinstance(item, dict)], warnings
        return [unwrapped], warnings
    if isinstance(unwrapped, list):
        flattened: list[dict[str, Any]] = []
        for item in unwrapped:
            if isinstance(item, dict):
                flattened.append(item)
            elif isinstance(item, list):
                flattened.extend(child for child in item if isinstance(child, dict))
        return flattened, warnings
    return [], warnings + ["provider returned an unsupported result shape"]


def _server_type(item: dict[str, Any], expected_type: str) -> str:
    raw = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("doc_type", "unit_type", "type")
    )
    if item.get("case_number") or "court" in raw or "case" in raw:
        return "case"
    if "authority" in raw or "agency" in raw:
        return "authority"
    if any(marker in raw for marker in ("comment", "doctrine", "legal_position")):
        return "doctrine"
    return {
        "legislation": "norm",
        "case_law": "case",
        "authority": "authority",
        "doctrine": "doctrine",
        "internal": "internal",
    }.get(expected_type, "internal")


def normalize_server_result(
    value: Any,
    *,
    expected_type: str,
    jurisdiction: str,
    authority_level: str | None,
    provider_id: str,
) -> NormalizationResult:
    items, warnings = _as_items(value)
    evidence: list[EvidenceItem] = []
    retrieved_at = _now()
    for item in items:
        title = _string(item.get("display_title") or item.get("title") or item.get("unit_heading"))
        if not title:
            warnings.append("provider item without a title was skipped")
            continue
        external_id = _string(
            item.get("document_id")
            or item.get("unit_id")
            or item.get("case_number")
            or item.get("canonical_key")
            or item.get("path")
        )
        fragment = _string(item.get("snippet") or item.get("key_thesis") or item.get("search_preview"))
        item_warnings: list[str] = []
        if fragment:
            fragment = fragment[:8000]
            item_warnings.append("search fragment is navigation only; fetch the source before verbatim citation")
        if item.get("version_is_current") is False:
            item_warnings.append("provider marks this version as not current")
        status = _string(item.get("verification_status") or item.get("status") or item.get("unit_status"))
        if status and status.casefold() in {"needs_review", "verification_pending", "not_verified"}:
            item_warnings.append(f"provider status requires review: {status}")
        evidence.append(
            EvidenceItem(
                evidence_id=_evidence_id(provider_id, external_id, title),
                type=_server_type(item, expected_type),
                title=title,
                date=_string(item.get("act_date") or item.get("decision_date") or item.get("effective_date") or item.get("date")),
                jurisdiction=jurisdiction,
                source_provider=provider_id,
                source_external_id=external_id,
                source_url=_string(item.get("source_url") or item.get("url")),
                source_fragment=fragment,
                content_hash=_string(item.get("content_hash")),
                retrieved_at=retrieved_at,
                authority_level=authority_level,
                supports_issue=None,
                contradicts_issue=None,
                verification_status="provider_result",
                warnings=tuple(dict.fromkeys(item_warnings)),
            )
        )
    return NormalizationResult(tuple(evidence), tuple(dict.fromkeys(warnings)))


def normalize_pravo_resolution(
    value: dict[str, Any],
    *,
    jurisdiction: str,
    authority_level: str | None,
    provider_id: str = "pravo-gov-ru",
) -> NormalizationResult:
    if value.get("status") != "RESOLVED":
        return NormalizationResult(())
    title = _string(value.get("label") or value.get("title") or value.get("act_number")) or "Resolved official act"
    external_id = _string(value.get("nd"))
    item = EvidenceItem(
        evidence_id=_evidence_id(provider_id, external_id, title),
        type="norm",
        title=title,
        date=_string(value.get("act_date")),
        jurisdiction=jurisdiction,
        source_provider=provider_id,
        source_external_id=external_id,
        source_url=_string(value.get("document_url")),
        source_fragment=None,
        content_hash=_string(value.get("content_hash")),
        retrieved_at=_string(value.get("retrieved_at")) or _now(),
        authority_level=authority_level,
        supports_issue=None,
        contradicts_issue=None,
        verification_status="provider_result",
        warnings=("identity fields were checked automatically; legal wording is not human-verified",),
    )
    return NormalizationResult((item,))


def normalize_local_curated_result(
    value: Any,
    *,
    jurisdiction: str,
    authority_level: str | None,
    provider_id: str = "local-curated",
) -> NormalizationResult:
    items, warnings = _as_items(value)
    evidence: list[EvidenceItem] = []
    for item in items:
        title = _string(item.get("title"))
        path = _string(item.get("path"))
        if not title or not path:
            warnings.append("local curated item without title/path was skipped")
            continue
        evidence.append(
            EvidenceItem(
                evidence_id=_evidence_id(provider_id, path, title),
                type="internal",
                title=title,
                date=None,
                jurisdiction=jurisdiction,
                source_provider=provider_id,
                source_external_id=path,
                source_url=None,
                source_fragment=(_string(item.get("snippet")) or "")[:8000] or None,
                content_hash=_string(item.get("content_hash")),
                retrieved_at=_string(item.get("retrieved_at")) or _now(),
                authority_level=authority_level,
                supports_issue=None,
                contradicts_issue=None,
                verification_status="provider_result",
                warnings=(
                    "local curated material is methodology, not a source of law",
                    "fetch the canonical path before relying on detailed wording",
                ),
            )
        )
    return NormalizationResult(tuple(evidence), tuple(dict.fromkeys(warnings)))


def normalize_local_verified_result(
    value: Any,
    *,
    jurisdiction: str,
    authority_level: str | None,
    provider_id: str = "local-verified",
) -> NormalizationResult:
    items, warnings = _as_items(value)
    evidence: list[EvidenceItem] = []
    retrieved_at = _now()
    for item in items:
        knowledge_id = _string(item.get("knowledge_id"))
        issue = _string(item.get("issue"))
        position = _string(item.get("position"))
        verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
        if not knowledge_id or not issue or not position:
            warnings.append("local verified item without knowledge_id/issue/position was skipped")
            continue
        if verification.get("status") != "human_verified" or not verification.get("verified_at"):
            warnings.append(f"non-human-verified knowledge was skipped: {knowledge_id}")
            continue
        item_warnings: list[str] = [
            "human verification applies to this reusable knowledge object, not to every underlying legal source"
        ]
        status = _string(item.get("status")) or "active"
        if status in {"possibly_stale", "requires_revalidation"}:
            item_warnings.append(f"knowledge status requires attention: {status}")
        evidence.append(
            EvidenceItem(
                evidence_id=_evidence_id(provider_id, knowledge_id, issue),
                type="internal",
                title=issue,
                date=_string(item.get("valid_as_of")),
                jurisdiction=jurisdiction,
                source_provider=provider_id,
                source_external_id=knowledge_id,
                source_url=None,
                source_fragment=position[:8000],
                content_hash=_string(item.get("content_hash")),
                retrieved_at=_string(item.get("retrieved_at")) or retrieved_at,
                authority_level=authority_level,
                supports_issue=None,
                contradicts_issue=None,
                verification_status="human_verified",
                warnings=tuple(item_warnings),
            )
        )
    return NormalizationResult(tuple(evidence), tuple(dict.fromkeys(warnings)))
