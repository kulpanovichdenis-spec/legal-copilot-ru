from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .handlers import anonymizer, claims, counterparty, ip, knowledge, samples
from .paths import RuntimePaths


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    inbox: Path
    handler: Callable
    expose_policy: str


def build_registry(runtime: RuntimePaths) -> list[ChannelSpec]:
    """Фиксированные каналы. Ручной legal DD watcher сюда намеренно не входит."""
    profile = runtime.profile_root / "knowledge"
    workflow = runtime.workflow_root
    return [
        ChannelSpec(
            "anonymizer",
            workflow / "_anonymizer" / "_inbox",
            anonymizer.handle_full,
            "none",
        ),
        ChannelSpec(
            "anonymizer_analytic",
            workflow / "_anonymizer" / "_inbox" / "analytic",
            anonymizer.handle_analytic,
            "none",
        ),
        ChannelSpec(
            "anonymizer_projects",
            workflow / "_anonymizer",
            anonymizer.handle_projects,
            "anonymized_only",
        ),
        ChannelSpec("claims", workflow / "_claims", claims.handle, "private_task_card"),
        ChannelSpec(
            "knowledge_products",
            profile / "products" / "_inbox",
            knowledge.handle_products,
            "draft_card",
        ),
        ChannelSpec(
            "knowledge_corporate",
            profile / "corporate" / "_inbox",
            knowledge.handle_corporate,
            "draft_card",
        ),
        ChannelSpec(
            "knowledge_compliance",
            profile / "compliance" / "_inbox",
            knowledge.handle_compliance,
            "draft_card",
        ),
        ChannelSpec(
            "knowledge_ip",
            profile / "ip" / "_inbox",
            ip.handle,
            "private_task_card",
        ),
        ChannelSpec(
            "clauses",
            profile / "clauses" / "_inbox",
            samples.handle_clause,
            "anonymized_only",
        ),
        ChannelSpec(
            "document_samples",
            profile / "document-samples" / "_inbox",
            samples.handle_sample,
            "anonymized_only",
        ),
        ChannelSpec(
            "counterparty",
            workflow / "_counterparty" / "_inbox",
            counterparty.handle,
            "private_task_card",
        ),
    ]


def select_channels(specs: list[ChannelSpec], selected: list[str] | None) -> list[ChannelSpec]:
    if not selected:
        return specs
    known = {spec.key for spec in specs}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"неизвестные каналы: {', '.join(unknown)}")
    wanted = set(selected)
    return [spec for spec in specs if spec.key in wanted]
