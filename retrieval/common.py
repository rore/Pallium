"""Shared helpers for building retrieval result components."""

from __future__ import annotations

from datetime import timezone

from core.models import EvidenceReference, SourceItem
from storage.base import IndexSearchHit

MAX_EXCERPT_LENGTH = 160


def build_excerpt(text: str, *, max_length: int = MAX_EXCERPT_LENGTH) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def build_evidence(source_item: SourceItem) -> EvidenceReference:
    occurred_at = source_item.occurred_at
    if occurred_at is not None and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return EvidenceReference(
        source_item_id=source_item.id,
        source_type=source_item.source_type,
        source_id=source_item.source_id,
        occurred_at=occurred_at,
        actor_ref=source_item.actor_ref,
        agent_ref=source_item.agent_ref,
        role=source_item.role,
        container_ref=source_item.container_ref,
        thread_ref=source_item.thread_ref,
        source_ref=source_item.source_ref,
        artifact_kind=source_item.artifact_kind,
        container_visibility=source_item.container_visibility,
    )


def build_trace_hit(hit: IndexSearchHit):
    from core.models import RetrievalTraceHit

    return RetrievalTraceHit(
        target_kind=hit.target_kind,
        target_id=hit.target_id,
        index_entry_id=hit.index_entry_id,
        index_type=hit.index_type,
        text_view_name=hit.text_view_name,
        score=hit.score,
        matched_tokens=tuple(hit.matched_tokens),
        provider_name=hit.provider_name,
        provider_version=hit.provider_version,
    )
