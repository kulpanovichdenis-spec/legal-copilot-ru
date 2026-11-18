"""Local adapter for explicitly promoted reusable knowledge objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from ..storage.knowledge_store import KnowledgeStore
from .base import ProviderAdapter


TOOL_NAMES = {
    "search_verified_knowledge",
    "get_verified_knowledge",
    "propose_knowledge_candidate",
    "verify_knowledge_candidate",
    "supersede_verified_knowledge",
}


class LocalVerifiedAdapter(ProviderAdapter):
    def __init__(self, connection: ProviderConnection, *, knowledge_root: Path | None = None) -> None:
        self.connection = connection
        self.store = KnowledgeStore(knowledge_root)

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

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        return ProviderHealth(
            self.connection.provider_id,
            "connected",
            data=self.store.counts(),
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_NAMES

    @staticmethod
    def _proposal_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "issue", "position", "provenance"],
            "properties": {
                "knowledge_id": {"type": "string"},
                "type": {"enum": ["legal_issue", "case_position", "authority_position", "doctrine_point", "practice_pattern"]},
                "pattern_kind": {"enum": ["evidence", "drafting", "procedure", "settlement", "enforcement", "risk_antipattern"]},
                "support_level": {"enum": ["single_case", "multi_case", "court_confirmed"]},
                "source_case_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "review_questions": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "reuse_target": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "legal_dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["norm", "status"],
                        "properties": {
                            "norm": {"type": "string", "minLength": 3},
                            "status": {"enum": ["requires_current_law_check", "verified_current"]},
                        },
                    },
                },
                "requires_current_law_check": {"type": "boolean"},
                "topic": {"type": ["string", "null"]},
                "issue": {"type": "string", "minLength": 1},
                "position": {"type": "string", "minLength": 1},
                "applies_when": {"type": "array", "items": {"type": "string"}},
                "does_not_apply_when": {"type": "array", "items": {"type": "string"}},
                "provenance": {"type": "array", "minItems": 1, "items": {"type": "object"}},
                "valid_as_of": {"type": ["string", "null"], "format": "date"},
                "extraction_status": {"enum": ["machine_extracted", "machine_reviewed"], "default": "machine_extracted"},
            },
            "allOf": [
                {
                    "if": {"properties": {"type": {"const": "practice_pattern"}}, "required": ["type"]},
                    "then": {
                        "required": [
                            "pattern_kind",
                            "support_level",
                            "source_case_ids",
                            "review_questions",
                            "reuse_target",
                            "requires_current_law_check",
                        ]
                    },
                }
            ],
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_verified_knowledge",
                "description": "Search only local human-verified reusable knowledge; candidates are never returned.",
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
                "name": "get_verified_knowledge",
                "description": "Get one local human-verified knowledge object by safe knowledge_id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"knowledge_id": {"type": "string"}},
                    "required": ["knowledge_id"],
                },
            },
            {
                "name": "propose_knowledge_candidate",
                "description": "Create a local candidate only; this tool can never create human_verified knowledge.",
                "inputSchema": self._proposal_schema(),
            },
            {
                "name": "verify_knowledge_candidate",
                "description": "Preview or explicitly promote one unchanged candidate to human_verified after user review.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["knowledge_id", "candidate_hash", "verified_by"],
                    "properties": {
                        "knowledge_id": {"type": "string"},
                        "candidate_hash": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
                        "verified_by": {"type": "string", "minLength": 1},
                        "verification_note": {"type": ["string", "null"]},
                        "apply": {"type": "boolean", "default": False},
                        "confirm_human_verified": {"type": "boolean", "default": False},
                    },
                },
            },
            {
                "name": "supersede_verified_knowledge",
                "description": "Preview or explicitly move one unchanged verified object to superseded.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["knowledge_id", "content_hash", "reason", "confirmed_by"],
                    "properties": {
                        "knowledge_id": {"type": "string"},
                        "content_hash": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
                        "reason": {"type": "string", "minLength": 1},
                        "confirmed_by": {"type": "string", "minLength": 1},
                        "replacement_id": {"type": ["string", "null"]},
                        "apply": {"type": "boolean", "default": False},
                        "confirm_supersede": {"type": "boolean", "default": False},
                    },
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "search_verified_knowledge":
            return self.store.search_verified(arguments.get("query"), limit=arguments.get("limit", 10))
        if name == "get_verified_knowledge":
            return self.store.get_verified(arguments.get("knowledge_id"))
        if name == "propose_knowledge_candidate":
            return self.store.propose(arguments)
        if name == "verify_knowledge_candidate":
            return self.store.verify_candidate(
                arguments.get("knowledge_id"),
                candidate_hash=arguments.get("candidate_hash"),
                verified_by=arguments.get("verified_by"),
                verification_note=arguments.get("verification_note"),
                apply=bool(arguments.get("apply", False)),
                confirm_human_verified=arguments.get("confirm_human_verified") is True,
            )
        if name == "supersede_verified_knowledge":
            return self.store.supersede_verified(
                arguments.get("knowledge_id"),
                content_hash=arguments.get("content_hash"),
                reason=arguments.get("reason"),
                confirmed_by=arguments.get("confirmed_by"),
                replacement_id=arguments.get("replacement_id"),
                apply=bool(arguments.get("apply", False)),
                confirm_supersede=arguments.get("confirm_supersede") is True,
            )
        raise KeyError(f"unknown local verified tool: {name}")
