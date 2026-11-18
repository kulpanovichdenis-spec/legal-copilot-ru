"""Small stable models shared by the gateway and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


class ContractValidationError(ValueError):
    """A controlled validation error for public Overlay contracts."""


def _validate(value: dict[str, Any], schema_name: str) -> dict[str, Any]:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise ContractValidationError(f"invalid contract at {location}: {first.message}")
    return value


def validate_legal_search_request(value: dict[str, Any]) -> dict[str, Any]:
    return _validate(value, "legal-search-request.schema.json")


def validate_evidence_bundle(value: dict[str, Any]) -> dict[str, Any]:
    return _validate(value, "evidence-bundle.schema.json")


def validate_knowledge_object(value: dict[str, Any]) -> dict[str, Any]:
    return _validate(value, "knowledge-object.schema.json")


@dataclass(frozen=True)
class LegalSearchRequest:
    issue: str
    jurisdiction: str
    data_classification: str
    as_of_date: str | None = None
    act_number: str | None = None
    act_date: str | None = None
    title_hint: str | None = None
    source_types: tuple[str, ...] = ("legislation",)
    need_supporting: bool = True
    need_adverse: bool = False
    official_verification: bool = False
    research_depth: str = "standard"
    limit: int = 10
    matter_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LegalSearchRequest":
        validated = validate_legal_search_request(value)
        issue = str(validated["issue"]).strip()
        if not issue:
            raise ContractValidationError("invalid contract at issue: value must not be blank")
        return cls(
            issue=issue,
            jurisdiction=str(validated["jurisdiction"]).strip().upper(),
            data_classification=str(validated["data_classification"]),
            as_of_date=validated.get("as_of_date"),
            act_number=(str(validated["act_number"]).strip() if validated.get("act_number") else None),
            act_date=validated.get("act_date"),
            title_hint=(str(validated["title_hint"]).strip() if validated.get("title_hint") else None),
            source_types=tuple(validated.get("source_types") or ("legislation",)),
            need_supporting=bool(validated.get("need_supporting", True)),
            need_adverse=bool(validated.get("need_adverse", False)),
            official_verification=bool(validated.get("official_verification", False)),
            research_depth=str(validated.get("research_depth", "standard")),
            limit=int(validated.get("limit", 10)),
            matter_id=validated.get("matter_id"),
        )


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    type: str
    title: str
    date: str | None
    jurisdiction: str | None
    source_provider: str
    source_external_id: str | None
    source_url: str | None
    source_fragment: str | None
    content_hash: str | None
    retrieved_at: str
    authority_level: str | None
    supports_issue: bool | None = None
    contradicts_issue: bool | None = None
    verification_status: str = "provider_result"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "type": self.type,
            "title": self.title,
            "date": self.date,
            "jurisdiction": self.jurisdiction,
            "source_provider": self.source_provider,
            "source_external_id": self.source_external_id,
            "source_url": self.source_url,
            "source_fragment": self.source_fragment,
            "content_hash": self.content_hash,
            "retrieved_at": self.retrieved_at,
            "authority_level": self.authority_level,
            "supports_issue": self.supports_issue,
            "contradicts_issue": self.contradicts_issue,
            "verification_status": self.verification_status,
            "warnings": list(self.warnings),
        }


@dataclass
class EvidenceBundle:
    request_id: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    sources_attempted: list[str] = field(default_factory=list)
    sources_succeeded: list[str] = field(default_factory=list)
    fallbacks_used: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "request_id": self.request_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "sources_attempted": self._unique(self.sources_attempted),
            "sources_succeeded": self._unique(self.sources_succeeded),
            "fallbacks_used": self._unique(self.fallbacks_used),
            "coverage_gaps": self._unique(self.coverage_gaps),
            "warnings": self._unique(self.warnings),
        }
        return validate_evidence_bundle(value)


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    adapter: str
    enabled: bool
    configured: bool
    endpoint: str | None
    priority: int
    capabilities: tuple[str, ...] = ()
    transitional_external_proxy: bool = False
    missing_secrets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "adapter": self.adapter,
            "enabled": self.enabled,
            "configured": self.configured,
            "endpoint": self.endpoint,
            "priority": self.priority,
            "capabilities": list(self.capabilities),
            "transitional_external_proxy": self.transitional_external_proxy,
            "missing_secrets": list(self.missing_secrets),
        }


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.provider_id,
            "status": self.status,
        }
        if self.detail:
            result["detail"] = self.detail
        if self.data:
            result["data"] = self.data
        return result
