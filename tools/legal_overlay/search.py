"""Provider-neutral legal search orchestration for the local Overlay."""

from __future__ import annotations

from uuid import uuid4

from .config import ConfigurationError
from .models import ContractValidationError, EvidenceBundle, LegalSearchRequest
from .normalizer import (
    normalize_local_curated_result,
    normalize_local_verified_result,
    normalize_pravo_resolution,
    normalize_server_result,
)
from .registry import ProviderRegistry
from .source_profiles import SourceProfile, load_source_profiles, source_profile_map


class RequestValidationError(ValueError):
    """A public, controlled legal_search request error."""


SERVER_TOOLS = {
    "case_law": ("search_positions", lambda request: {"query": request.issue, "limit": request.limit}),
    "authority": ("search_comments", lambda request: {"query": request.issue, "limit": request.limit}),
    "internal": ("search_legal_opinions", lambda request: {"query": request.issue, "limit": request.limit}),
}


class LegalSearchEngine:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        source_profiles: tuple[SourceProfile, ...] | None = None,
    ) -> None:
        self.registry = registry
        self.profiles = source_profile_map(source_profiles if source_profiles is not None else load_source_profiles())

    def _authority(self, provider_id: str) -> str | None:
        profile = self.profiles.get(provider_id)
        return str(profile.metadata.get("authority_level")) if profile else None

    def search(self, arguments: dict) -> dict:
        try:
            request = LegalSearchRequest.from_dict(arguments)
        except ContractValidationError as exc:
            raise RequestValidationError(str(exc)) from exc

        bundle = EvidenceBundle(request_id=f"lsr_{uuid4().hex}")
        if request.jurisdiction not in {"RU", "EAEU", "UZ"}:
            bundle.coverage_gaps.append(
                f"Jurisdiction {request.jurisdiction} is not routed by normalized legal_search yet; corpora were not mixed."
            )
            return bundle.to_dict()
        if request.need_adverse:
            bundle.warnings.append(
                "Automatic adverse/relevance classification is not implemented; contradicts_issue remains null."
            )

        self._search_local_verified(request, bundle)
        self._search_local_curated(request, bundle)
        local_memory_count = self._search_local_memory(request, bundle)
        local_labor_count = self._search_local_labor(request, bundle)
        local_doctrine_count = self._search_local_doctrine(request, bundle)

        local_count, local_legislation_success, _server_dual_run, local_available = self._search_local_corpus(
            request, bundle
        )
        if request.jurisdiction == "UZ" and not local_available:
            bundle.coverage_gaps.append(
                "Jurisdiction UZ has no configured local corpus; corpora were not mixed."
            )
            return bundle.to_dict()
        public_request = request.data_classification == "public_or_abstracted"
        if not public_request:
            bundle.coverage_gaps.append(
                "Request was not sent to remote providers because data_classification is not public_or_abstracted."
            )
            if not bundle.evidence:
                bundle.coverage_gaps.append("No normalized evidence was returned for the requested source types.")
            return bundle.to_dict()

        legislation_requested = "legislation" in request.source_types
        corpus_legislation_success = local_legislation_success
        fallback_needed = legislation_requested and not corpus_legislation_success
        official_requested = (
            request.jurisdiction == "RU" and legislation_requested and request.official_verification
        )
        should_call_pravo = fallback_needed or official_requested
        if request.jurisdiction == "RU" and should_call_pravo:
            if not request.act_number or not request.act_date:
                bundle.coverage_gaps.append(
                    "pravo-gov-ru exact resolution requires both act_number and act_date."
                )
            else:
                if fallback_needed:
                    bundle.fallbacks_used.append("pravo-gov-ru")
                bundle.sources_attempted.append("pravo-gov-ru")
                try:
                    pravo = self.registry.adapter("pravo-gov-ru")
                    if not pravo.descriptor().enabled:
                        raise ConfigurationError("pravo-gov-ru provider is disabled")
                    native = pravo.call_tool(
                        "pravo_resolve_act",
                        {
                            "act_number": request.act_number,
                            "act_date": request.act_date,
                            "title_hint": request.title_hint or "",
                        },
                    )
                    status = str(native.get("status") or "FAILED") if isinstance(native, dict) else "FAILED"
                    if status in {"RESOLVED", "NOT_FOUND", "AMBIGUOUS"}:
                        bundle.sources_succeeded.append("pravo-gov-ru")
                    if status == "RESOLVED":
                        normalized = normalize_pravo_resolution(
                            native,
                            jurisdiction=request.jurisdiction,
                            authority_level=self._authority("pravo-gov-ru"),
                        )
                        bundle.evidence.extend(normalized.evidence)
                        bundle.warnings.extend(normalized.warnings)
                    else:
                        bundle.coverage_gaps.append(f"pravo-gov-ru exact resolution returned {status}.")
                except Exception as exc:
                    bundle.warnings.append(f"pravo-gov-ru failed: {self.registry.redact(exc)}")
                    bundle.coverage_gaps.append("Official portal verification did not complete.")

        if not bundle.evidence:
            bundle.coverage_gaps.append("No normalized evidence was returned for the requested source types.")
        elif local_count + local_memory_count + local_labor_count + local_doctrine_count == 0 and any(
            source_type != "legislation" for source_type in request.source_types
        ):
            bundle.coverage_gaps.append("One or more requested corpus layers returned no normalized evidence.")
        return bundle.to_dict()

    def _search_local_labor(self, request: LegalSearchRequest, bundle: EvidenceBundle) -> int:
        if "authority" not in request.source_types or request.jurisdiction not in {"RU", "EAEU"}:
            return 0
        provider_id = "local-legal-memory-sqlite"
        try:
            adapter = self.registry.adapter(provider_id)
            descriptor = adapter.descriptor()
            if not descriptor.enabled:
                raise ConfigurationError(f"{provider_id} provider is disabled")
            if not descriptor.configured:
                raise ConfigurationError(f"{provider_id} provider is not configured")
            if provider_id not in bundle.sources_attempted:
                bundle.sources_attempted.append(provider_id)
            native = adapter.call_tool(
                "search_official_labor_guidance",
                {"query": request.issue, "limit": request.limit},
            )
            normalized = normalize_server_result(
                native,
                expected_type="authority",
                jurisdiction=request.jurisdiction,
                authority_level="administrative_guidance",
                provider_id=provider_id,
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
            if isinstance(native, dict):
                bundle.warnings.extend(str(item) for item in native.get("warnings", []) if item)
            if provider_id not in bundle.sources_succeeded:
                bundle.sources_succeeded.append(provider_id)
            return len(normalized.evidence)
        except Exception as exc:
            bundle.warnings.append(f"{provider_id} labor guidance failed: {self.registry.redact(exc)}")
            return 0

    def _search_local_doctrine(self, request: LegalSearchRequest, bundle: EvidenceBundle) -> int:
        if "doctrine" not in request.source_types or request.jurisdiction not in {"RU", "EAEU"}:
            return 0
        provider_id = "local-legal-doctrine-sqlite"
        try:
            adapter = self.registry.adapter(provider_id)
            descriptor = adapter.descriptor()
            if not descriptor.enabled:
                raise ConfigurationError(f"{provider_id} provider is disabled")
            if not descriptor.configured:
                raise ConfigurationError(f"{provider_id} provider is not configured")
            bundle.sources_attempted.append(provider_id)
            native = adapter.call_tool(
                "search_doctrine",
                {"query": request.issue, "limit": request.limit},
            )
            normalized = normalize_server_result(
                native,
                expected_type="doctrine",
                jurisdiction=request.jurisdiction,
                authority_level=self._authority(provider_id),
                provider_id=provider_id,
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
            bundle.sources_succeeded.append(provider_id)
            return len(normalized.evidence)
        except Exception as exc:
            bundle.warnings.append(f"{provider_id} failed: {self.registry.redact(exc)}")
            return 0

    def _search_local_memory(self, request: LegalSearchRequest, bundle: EvidenceBundle) -> int:
        if "internal" not in request.source_types or request.jurisdiction not in {"RU", "EAEU"}:
            return 0
        provider_id = "local-legal-memory-sqlite"
        try:
            adapter = self.registry.adapter(provider_id)
            if not adapter.descriptor().enabled:
                raise ConfigurationError(f"{provider_id} provider is disabled")
            bundle.sources_attempted.append(provider_id)
            native = adapter.call_tool(
                "search_legal_opinions",
                {"query": request.issue, "limit": request.limit},
            )
            normalized = normalize_server_result(
                native,
                expected_type="internal",
                jurisdiction=request.jurisdiction,
                authority_level=self._authority(provider_id),
                provider_id=provider_id,
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
            bundle.sources_succeeded.append(provider_id)
            return len(normalized.evidence)
        except Exception as exc:
            bundle.warnings.append(f"{provider_id} failed: {self.registry.redact(exc)}")
            return 0

    def _search_local_corpus(
        self,
        request: LegalSearchRequest,
        bundle: EvidenceBundle,
    ) -> tuple[int, bool, bool, bool]:
        provider_id = "local-legal-uz-sqlite" if request.jurisdiction == "UZ" else "local-legal-ru-sqlite"
        corpus_source_types = tuple(
            source_type
            for source_type in request.source_types
            if source_type != "internal"
            and not (
                request.jurisdiction in {"RU", "EAEU"} and source_type == "doctrine"
            )
        )
        if not corpus_source_types:
            return 0, False, False, True
        try:
            adapter = self.registry.adapter(provider_id)
            descriptor = adapter.descriptor()
            if not descriptor.enabled:
                raise ConfigurationError(f"{provider_id} provider is disabled")
            if not descriptor.configured:
                raise ConfigurationError(f"{provider_id} provider is not configured")
        except Exception as exc:
            bundle.warnings.append(f"{provider_id} unavailable: {self.registry.redact(exc)}")
            return 0, False, False, False

        server_dual_run = bool(getattr(adapter, "connection", None) and adapter.connection.options.get("server_dual_run"))
        total = 0
        legislation_success = False
        for source_type in corpus_source_types:
            if provider_id == "local-legal-uz-sqlite":
                tool_name = "search_uzbek_legal_memory"
                tool_arguments = {"query": request.issue, "limit": request.limit}
            elif source_type == "legislation" and request.act_number:
                tool_name = "find_by_act_number"
                tool_arguments = {"act_number": request.act_number, "limit": request.limit}
            elif source_type == "legislation":
                tool_name = "search_legal_kb"
                tool_arguments = {"query": request.issue, "limit": request.limit}
            else:
                tool_name, arguments_builder = SERVER_TOOLS[source_type]
                tool_arguments = arguments_builder(request)

            if provider_id not in bundle.sources_attempted:
                bundle.sources_attempted.append(provider_id)
            try:
                native = adapter.call_tool(tool_name, tool_arguments)
            except Exception as exc:
                bundle.warnings.append(f"{provider_id} {tool_name} failed: {self.registry.redact(exc)}")
                continue
            normalized = normalize_server_result(
                native,
                expected_type=source_type,
                jurisdiction=request.jurisdiction,
                authority_level=self._authority(provider_id),
                provider_id=provider_id,
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
            total += len(normalized.evidence)
            if source_type == "legislation":
                legislation_success = any(item.type == "norm" for item in normalized.evidence)
        if provider_id in bundle.sources_attempted:
            bundle.sources_succeeded.append(provider_id)
        return total, legislation_success, server_dual_run, True

    def _search_local_curated(self, request: LegalSearchRequest, bundle: EvidenceBundle) -> None:
        if "internal" not in request.source_types:
            return
        bundle.sources_attempted.append("local-curated")
        try:
            adapter = self.registry.adapter("local-curated")
            if not adapter.descriptor().enabled:
                raise ConfigurationError("local-curated provider is disabled")
            native = adapter.call_tool(
                "search_local_curated",
                {"query": request.issue, "limit": request.limit},
            )
            bundle.sources_succeeded.append("local-curated")
            normalized = normalize_local_curated_result(
                native,
                jurisdiction=request.jurisdiction,
                authority_level=self._authority("local-curated"),
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
        except Exception as exc:
            bundle.warnings.append(f"local-curated failed: {self.registry.redact(exc)}")

    def _search_local_verified(self, request: LegalSearchRequest, bundle: EvidenceBundle) -> None:
        if "internal" not in request.source_types:
            return
        try:
            adapter = self.registry.adapter("local-verified")
        except ConfigurationError:
            return
        bundle.sources_attempted.append("local-verified")
        try:
            if not adapter.descriptor().enabled:
                raise ConfigurationError("local-verified provider is disabled")
            native = adapter.call_tool(
                "search_verified_knowledge",
                {"query": request.issue, "limit": request.limit},
            )
            bundle.sources_succeeded.append("local-verified")
            normalized = normalize_local_verified_result(
                native,
                jurisdiction=request.jurisdiction,
                authority_level=self._authority("local-verified"),
            )
            bundle.evidence.extend(normalized.evidence)
            bundle.warnings.extend(normalized.warnings)
        except Exception as exc:
            bundle.warnings.append(f"local-verified failed: {self.registry.redact(exc)}")
