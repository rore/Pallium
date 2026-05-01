from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from core.models import (
    IndexEntry,
    InjectableBlock,
    MemoryObject,
    QueryFilters,
    QueryRuntimeContext,
    QueryTrace,
    Relation,
    SourceItem,
)


@dataclass(frozen=True)
class SupersessionHint:
    replacement_memory_id: str
    memory_type: str
    canonical_key: str
    container_ref: str | None
    thread_ref: str | None
    visibility: str = "private"


@dataclass(frozen=True)
class ProcessResult:
    memory_objects: list[MemoryObject]
    relations: list[Relation]
    index_entries: list[IndexEntry]
    source_item_metadata_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    thread_rebuild_requested: bool = True
    supersession_hints: list[SupersessionHint] = field(default_factory=list)


@dataclass(frozen=True)
class IngestResult:
    source_item_id: str
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]
    processing_status: str
    processing_attempts: int
    processing_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "memory_object_ids": self.memory_object_ids,
            "relation_ids": self.relation_ids,
            "index_entry_ids": self.index_entry_ids,
            "processing_status": self.processing_status,
            "processing_attempts": self.processing_attempts,
            "processing_error": self.processing_error,
        }


@dataclass(frozen=True)
class ItemProcessingResult:
    source_item_id: str
    use_case: str | None
    processing_status: str
    processing_attempts: int
    processing_claimed_at: datetime | None
    processing_completed_at: datetime | None
    processing_error: str | None
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]
    failure_category: str | None = None
    memory_object_types: list[str] = field(default_factory=list)
    thread_rebuild_requested: bool = False
    thread_rebuild_completed: bool = False
    produced_memory_provenance: list[dict[str, Any]] = field(default_factory=list)
    packages_processed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "use_case": self.use_case,
            "processing_status": self.processing_status,
            "processing_attempts": self.processing_attempts,
            "processing_claimed_at": self.processing_claimed_at,
            "processing_completed_at": self.processing_completed_at,
            "processing_error": self.processing_error,
            "memory_object_ids": self.memory_object_ids,
            "relation_ids": self.relation_ids,
            "index_entry_ids": self.index_entry_ids,
            "failure_category": self.failure_category,
            "memory_object_types": self.memory_object_types,
            "thread_rebuild_requested": self.thread_rebuild_requested,
            "thread_rebuild_completed": self.thread_rebuild_completed,
            "produced_memory_provenance": self.produced_memory_provenance,
            "packages_processed": self.packages_processed,
        }


@dataclass(frozen=True)
class PackageQueryOutcome:
    results: list
    trace: QueryTrace | None = None
    should_inject: bool = False
    decision_reason: str = "injection_policy_unavailable"
    injectable_blocks: list[InjectableBlock] = field(default_factory=list)
    sharp_candidate_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    ranked_candidates: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class QueryFilterResolution:
    requested_filters: QueryFilters | None
    effective_filters: QueryFilters | None
    filter_scope_relaxed: bool = False
    filter_scope_reason: str | None = None


@dataclass(frozen=True)
class QueryResult:
    results: list
    trace: QueryTrace | None = None
    should_inject: bool = False
    decision_reason: str = "injection_policy_unavailable"
    injectable_blocks: list[InjectableBlock] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryRetentionPolicy:
    """Plugin-declared retention classification for memory types."""
    durable_types: frozenset[str] = frozenset()
    working_types: frozenset[str] = frozenset()
    orphan_delete_types: frozenset[str] = frozenset()


def build_source_item(
    source_type: str,
    source_id: str,
    content_type: str,
    content: str,
    metadata: dict | None,
    occurred_at: datetime | None = None,
    actor_ref: str | None = None,
    agent_ref: str | None = None,
    role: str | None = None,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    source_ref: str | None = None,
    artifact_kind: str | None = None,
    visibility: str = "private",
    use_case: str | None = None,
    processing_status: str = "pending",
    processing_attempts: int = 0,
    processing_claimed_by: str | None = None,
    processing_claimed_at: datetime | None = None,
    processing_lease_expires_at: datetime | None = None,
    processing_completed_at: datetime | None = None,
    processing_error: str | None = None,
    processing_next_attempt_at: datetime | None = None,
) -> SourceItem:
    return SourceItem(
        source_type=source_type,
        source_id=source_id,
        content_type=content_type,
        content=content,
        metadata=metadata,
        occurred_at=occurred_at,
        actor_ref=actor_ref,
        agent_ref=agent_ref,
        role=role,
        container_ref=container_ref,
        thread_ref=thread_ref,
        source_ref=source_ref,
        artifact_kind=artifact_kind,
        visibility=visibility,
        use_case=use_case,
        processing_status=processing_status,
        processing_attempts=processing_attempts,
        processing_claimed_by=processing_claimed_by,
        processing_claimed_at=processing_claimed_at,
        processing_lease_expires_at=processing_lease_expires_at,
        processing_completed_at=processing_completed_at,
        processing_error=processing_error,
        processing_next_attempt_at=processing_next_attempt_at,
    )


def build_query_filters(
    source_type: str | None = None,
    role: str | None = None,
    artifact_kind: str | None = None,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    actor_ref: str | None = None,
    work_refs: tuple[str, ...] = (),
) -> QueryFilters | None:
    filters = QueryFilters(
        source_type=source_type,
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        actor_ref=actor_ref,
        work_refs=work_refs,
    )
    if not any(value is not None for value in (filters.source_type, filters.role, filters.artifact_kind, filters.container_ref, filters.thread_ref, filters.actor_ref)) and not filters.work_refs:
        return None
    return filters


def build_query_runtime_context(
    *,
    turn_kind: str | None = None,
    session_has_sufficient_local_context: bool | None = None,
) -> QueryRuntimeContext | None:
    runtime_context = QueryRuntimeContext(
        turn_kind=turn_kind,
        session_has_sufficient_local_context=session_has_sufficient_local_context,
    )
    if runtime_context.turn_kind is None and runtime_context.session_has_sufficient_local_context is None:
        return None
    return runtime_context


def resolve_query_filters(
    *,
    source_type: str | None = None,
    role: str | None = None,
    artifact_kind: str | None = None,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    actor_ref: str | None = None,
    work_refs: tuple[str, ...] = (),
    runtime_context: QueryRuntimeContext | None = None,
) -> QueryFilterResolution:
    requested_filters = build_query_filters(
        source_type=source_type,
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        actor_ref=actor_ref,
        work_refs=work_refs,
    )
    if requested_filters is None or runtime_context is None:
        return QueryFilterResolution(
            requested_filters=requested_filters,
            effective_filters=requested_filters,
        )

    effective_filters = requested_filters
    filter_scope_relaxed = False
    filter_scope_reason: str | None = None
    turn_kind = runtime_context.turn_kind
    session_has_sufficient_local_context = runtime_context.session_has_sufficient_local_context

    if turn_kind in {"same_thread", "same_thread_continuation"}:
        if requested_filters.container_ref is not None and requested_filters.thread_ref is not None:
            effective_filters = replace(effective_filters, thread_ref=None)
            filter_scope_relaxed = True
            filter_scope_reason = "same_thread_scope_relaxed_for_local_context_relevance_check"
        effective_filters = build_query_filters(
            source_type=effective_filters.source_type,
            role=effective_filters.role,
            artifact_kind=effective_filters.artifact_kind,
            container_ref=effective_filters.container_ref,
            thread_ref=effective_filters.thread_ref,
            actor_ref=effective_filters.actor_ref,
            work_refs=effective_filters.work_refs,
        )
        return QueryFilterResolution(
            requested_filters=requested_filters,
            effective_filters=effective_filters,
            filter_scope_relaxed=filter_scope_relaxed,
            filter_scope_reason=filter_scope_reason,
        )

    if turn_kind == "resumed_session" and requested_filters.thread_ref is not None:
        effective_filters = replace(effective_filters, thread_ref=None)
        filter_scope_relaxed = True
        filter_scope_reason = "resumed_session_thread_scope_relaxed"

    if turn_kind in {"new_thread", "new_session"} and session_has_sufficient_local_context is False:
        if effective_filters.thread_ref is not None:
            effective_filters = replace(effective_filters, thread_ref=None)
            filter_scope_relaxed = True
            filter_scope_reason = "fresh_thread_scope_relaxed_for_cross_thread_recall"

    effective_filters = build_query_filters(
        source_type=effective_filters.source_type,
        role=effective_filters.role,
        artifact_kind=effective_filters.artifact_kind,
        container_ref=effective_filters.container_ref,
        thread_ref=effective_filters.thread_ref,
        actor_ref=effective_filters.actor_ref,
        work_refs=effective_filters.work_refs,
    )
    return QueryFilterResolution(
        requested_filters=requested_filters,
        effective_filters=effective_filters,
        filter_scope_relaxed=filter_scope_relaxed,
        filter_scope_reason=filter_scope_reason,
    )
