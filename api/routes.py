from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ItemCreateRequest,
    ItemCreateResponse,
    ProcessingStatusResponse,
    QueryDebugResponse,
    QueryRequest,
    QueryResponse,
    QueueHealthResponse,
)
from core.models import QueryResultItem, QueryTrace, RetrievalStageTrace, RetrievalTraceHit
from core.service import PalliumService
from core.visibility import QueryVisibilityTrace, VisibilityContext, VisibilityExclusion


def _serialize_visibility_context(visibility_context: VisibilityContext | None) -> dict[str, object] | None:
    if visibility_context is None:
        return None
    return {
        "kind": visibility_context.kind,
        "id": visibility_context.id,
    }


def _deserialize_visibility_context(payload) -> VisibilityContext | None:
    if payload is None:
        return None
    return VisibilityContext(kind=payload.kind, id=payload.id)


def _serialize_evidence(evidence) -> dict[str, object]:
    return {
        "source_item_id": evidence.source_item_id,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "occurred_at": evidence.occurred_at,
        "actor_ref": evidence.actor_ref,
        "role": evidence.role,
        "container_ref": evidence.container_ref,
        "thread_ref": evidence.thread_ref,
        "session_ref": evidence.session_ref,
        "source_ref": evidence.source_ref,
        "artifact_kind": evidence.artifact_kind,
        "visibility_context": _serialize_visibility_context(evidence.visibility_context),
    }


def _serialize_result(item: QueryResultItem) -> dict[str, object]:
    return {
        "result_kind": item.result_kind,
        "score": item.score,
        "evidence": [_serialize_evidence(evidence) for evidence in item.evidence],
        "memory_object_id": item.memory_object_id,
        "type": item.type,
        "payload": item.payload,
        "source_item_id": item.source_item_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "excerpt": item.excerpt,
        "occurred_at": item.occurred_at,
        "actor_ref": item.actor_ref,
        "role": item.role,
        "container_ref": item.container_ref,
        "thread_ref": item.thread_ref,
        "session_ref": item.session_ref,
        "source_ref": item.source_ref,
        "artifact_kind": item.artifact_kind,
        "visibility_context": _serialize_visibility_context(item.visibility_context),
    }


def _serialize_trace_hit(hit: RetrievalTraceHit) -> dict[str, object]:
    return {
        "target_kind": hit.target_kind,
        "target_id": hit.target_id,
        "index_entry_id": hit.index_entry_id,
        "index_type": hit.index_type,
        "text_view_name": hit.text_view_name,
        "score": hit.score,
        "matched_tokens": list(hit.matched_tokens),
        "provider_name": hit.provider_name,
        "provider_version": hit.provider_version,
    }


def _serialize_stage_trace(stage: RetrievalStageTrace) -> dict[str, object]:
    return {
        "stage_name": stage.stage_name,
        "candidate_hits_considered": stage.candidate_hits_considered,
        "candidate_hits": [_serialize_trace_hit(hit) for hit in stage.candidate_hits],
        "selected_hits": [_serialize_trace_hit(hit) for hit in stage.selected_hits],
        "candidate_hits_before_visibility": stage.candidate_hits_before_visibility,
        "candidate_hits_after_visibility": stage.candidate_hits_after_visibility,
    }


def _serialize_visibility_exclusion(exclusion: VisibilityExclusion) -> dict[str, object]:
    return {
        "reason": exclusion.reason,
        "count": exclusion.count,
    }


def _serialize_visibility_trace(trace: QueryVisibilityTrace) -> dict[str, object]:
    return {
        "query_visibility_context": _serialize_visibility_context(trace.query_visibility_context),
        "expanded_visibility_contexts": [
            _serialize_visibility_context(item)
            for item in trace.expanded_visibility_contexts
        ],
        "excluded_candidates": [
            _serialize_visibility_exclusion(item)
            for item in trace.excluded_candidates
        ],
        "fail_closed_reason": trace.fail_closed_reason,
    }


def _serialize_trace(trace: QueryTrace) -> dict[str, object]:
    filters = None
    if trace.filters is not None:
        filters = {
            "source_type": trace.filters.source_type,
            "role": trace.filters.role,
            "artifact_kind": trace.filters.artifact_kind,
            "container_ref": trace.filters.container_ref,
            "thread_ref": trace.filters.thread_ref,
            "session_ref": trace.filters.session_ref,
        }
    return {
        "query_text": trace.query_text,
        "query_tokens": list(trace.query_tokens),
        "limit": trace.limit,
        "filters": filters,
        "stages": [_serialize_stage_trace(stage) for stage in trace.stages],
        "routing": trace.routing,
        "visibility": _serialize_visibility_trace(trace.visibility) if trace.visibility is not None else None,
        "result_summary": trace.result_summary,
    }


def create_router(service: PalliumService) -> APIRouter:
    router = APIRouter()

    @router.post("/items", response_model=ItemCreateResponse)
    def create_item(request: ItemCreateRequest) -> ItemCreateResponse:
        result = service.ingest_item(
            source_type=request.source_type,
            source_id=request.source_id,
            content_type=request.content_type,
            content=request.content,
            metadata=request.metadata,
            use_case=request.use_case,
            occurred_at=request.occurred_at,
            actor_ref=request.actor_ref,
            role=request.role,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            session_ref=request.session_ref,
            source_ref=request.source_ref,
            artifact_kind=request.artifact_kind,
            visibility_context=_deserialize_visibility_context(request.visibility_context),
        )
        return ItemCreateResponse(**result.as_dict())

    @router.get("/items/{source_item_id}/processing", response_model=ProcessingStatusResponse)
    def get_item_processing(source_item_id: str) -> ProcessingStatusResponse:
        try:
            result = service.get_item_processing(source_item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source item not found") from exc
        return ProcessingStatusResponse(**result.as_dict())

    @router.get("/debug/queue/health", response_model=QueueHealthResponse)
    def get_queue_health() -> QueueHealthResponse:
        snapshot = service.get_queue_health()
        return QueueHealthResponse(
            status_counts=snapshot.status_counts,
            oldest_pending_age_seconds=snapshot.oldest_pending_age_seconds,
            pending_without_use_case_count=snapshot.pending_without_use_case_count,
            unclaimable_pending_counts=[
                {"reason": item.reason, "count": item.count}
                for item in snapshot.unclaimable_pending_counts
            ],
            leased_source_items=[
                {
                    "source_item_id": item.source_item_id,
                    "use_case": item.use_case,
                    "processing_claimed_by": item.processing_claimed_by,
                    "processing_claimed_at": item.processing_claimed_at,
                    "processing_lease_expires_at": item.processing_lease_expires_at,
                }
                for item in snapshot.leased_source_items
            ],
            leased_thread_scopes=[
                {
                    "scope_key": item.scope_key,
                    "use_case": item.use_case,
                    "container_ref": item.container_ref,
                    "thread_ref": item.thread_ref,
                    "visibility_context": _serialize_visibility_context(item.visibility_context),
                    "processing_claimed_by": item.processing_claimed_by,
                    "processing_claimed_at": item.processing_claimed_at,
                    "processing_lease_expires_at": item.processing_lease_expires_at,
                }
                for item in snapshot.leased_thread_scopes
            ],
            recent_failures=[
                {
                    "source_item_id": item.source_item_id,
                    "use_case": item.use_case,
                    "failure_category": item.failure_category,
                    "processing_error": item.processing_error,
                    "processing_attempts": item.processing_attempts,
                    "processing_completed_at": item.processing_completed_at,
                }
                for item in snapshot.recent_failures
            ],
        )

    @router.post("/query", response_model=QueryResponse)
    def query_items(request: QueryRequest) -> QueryResponse:
        result = service.query(
            request.text,
            request.limit,
            source_type=request.source_type,
            role=request.role,
            artifact_kind=request.artifact_kind,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            session_ref=request.session_ref,
            visibility_context=_deserialize_visibility_context(request.visibility_context),
        )
        return QueryResponse(results=[_serialize_result(item) for item in result.results])

    @router.post("/query/debug", response_model=QueryDebugResponse)
    def query_items_debug(request: QueryRequest) -> QueryDebugResponse:
        result = service.query(
            request.text,
            request.limit,
            source_type=request.source_type,
            role=request.role,
            artifact_kind=request.artifact_kind,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            session_ref=request.session_ref,
            visibility_context=_deserialize_visibility_context(request.visibility_context),
            include_trace=True,
        )
        if result.trace is None:
            raise ValueError("debug query must include retrieval trace")
        return QueryDebugResponse(
            results=[_serialize_result(item) for item in result.results],
            trace=_serialize_trace(result.trace),
        )

    return router
