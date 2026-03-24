"""Shared filter and visibility helpers for retrieval and storage layers."""

from __future__ import annotations

from dataclasses import replace

from core.models import EvidenceReference, QueryFilters, SourceItem


def source_item_matches_filters(source_item: SourceItem, filters: QueryFilters) -> bool:
    if filters.source_type is not None and source_item.source_type != filters.source_type:
        return False
    if filters.role is not None and source_item.role != filters.role:
        return False
    if filters.artifact_kind is not None and source_item.artifact_kind != filters.artifact_kind:
        return False
    if filters.container_ref is not None and source_item.visibility != "public" and source_item.container_ref != filters.container_ref:
        return False
    if filters.thread_ref is not None and source_item.thread_ref != filters.thread_ref:
        return False
    if filters.actor_ref is not None and source_item.actor_ref is not None:
        if source_item.actor_ref != filters.actor_ref:
            return False
    return True


def evidence_matches_filters(evidence: EvidenceReference, filters: QueryFilters) -> bool:
    if filters.source_type is not None and evidence.source_type != filters.source_type:
        return False
    if filters.role is not None and evidence.role != filters.role:
        return False
    if filters.artifact_kind is not None and evidence.artifact_kind != filters.artifact_kind:
        return False
    if filters.container_ref is not None and evidence.visibility != "public" and evidence.container_ref != filters.container_ref:
        return False
    if filters.thread_ref is not None and evidence.thread_ref != filters.thread_ref:
        return False
    if filters.actor_ref is not None and evidence.actor_ref is not None:
        if evidence.actor_ref != filters.actor_ref:
            return False
    return True


def matches_filters(
    get_memory_object,
    get_source_item,
    get_evidence_for_memory_object,
    target_kind: str,
    target_id: str,
    filters: QueryFilters | None,
) -> bool:
    """Check lifecycle + field filters for a retrieval target.

    Callers pass in storage accessor callables so this module stays
    independent of any specific StorageProvider implementation.
    """
    if target_kind == "memory_object":
        memory_object = get_memory_object(target_id)
        if memory_object.lifecycle != "active":
            return False
        # Actor-scoped filtering: if query specifies an actor AND the memory
        # has an actor, they must match. Shared memories (actor_ref=null)
        # always pass. Queries without actor_ref skip this filter.
        if filters is not None and filters.actor_ref is not None and memory_object.actor_ref is not None:
            if memory_object.actor_ref != filters.actor_ref:
                return False
    if filters is None:
        return True
    if target_kind == "source_item":
        return source_item_matches_filters(get_source_item(target_id), filters)
    if target_kind == "memory_object":
        evidence = get_evidence_for_memory_object(target_id)
        memory_filters = replace(filters, thread_ref=None) if filters.thread_ref is not None else filters
        # Shared memories (actor_ref=None) passed the actor check above.
        # Don't re-apply actor filtering on their evidence path — the evidence
        # retains the creator's actor_ref, which would block other users from
        # reaching shared memories through standard retrieval.
        if memory_object.actor_ref is None and memory_filters.actor_ref is not None:
            memory_filters = replace(memory_filters, actor_ref=None)
        return any(evidence_matches_filters(item, memory_filters) for item in evidence)
    return True


def target_visibility_and_container(
    get_source_item,
    get_memory_object,
    target_kind: str,
    target_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (visibility, container_ref, actor_ref) for a retrieval target."""
    if target_kind == "source_item":
        item = get_source_item(target_id)
        return item.visibility, item.container_ref, getattr(item, 'actor_ref', None)
    if target_kind == "memory_object":
        mo = get_memory_object(target_id)
        container_ref = mo.container_ref
        if container_ref is None and mo.envelope is not None:
            container_ref = mo.envelope.scope.container_ref
        return mo.visibility, container_ref, getattr(mo, 'actor_ref', None)
    return None, None, None
