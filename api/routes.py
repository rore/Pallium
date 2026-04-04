from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ItemAndQueryDebugResponse,
    ItemAndQueryRequest,
    ItemAndQueryResponse,
    ItemCreateRequest,
    ItemCreateResponse,
    ProcessingStatusResponse,
    QueryDebugResponse,
    QueryRequest,
    QueryResponse,
    QueueHealthResponse,
)
from core.models import FusionStageTrace, FusionTraceHit, InjectableBlock, QueryResultItem, QueryRuntimeContext, QueryTrace, RetrievalStageTrace, RetrievalTraceHit
from core.service import PalliumService
from core.turn_inference import resolve_runtime_context
from core.visibility import QueryVisibilityTrace, VisibilityExclusion


def _deserialize_runtime_context(payload) -> QueryRuntimeContext | None:
    if payload is None:
        return None
    return QueryRuntimeContext(
        turn_kind=payload.turn_kind,
        session_has_sufficient_local_context=payload.session_has_sufficient_local_context,
    )


def _serialize_evidence(evidence) -> dict[str, object]:
    return {
        "source_item_id": evidence.source_item_id,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "occurred_at": evidence.occurred_at,
        "actor_ref": evidence.actor_ref,
        "agent_ref": evidence.agent_ref,
        "role": evidence.role,
        "container_ref": evidence.container_ref,
        "thread_ref": evidence.thread_ref,
        "source_ref": evidence.source_ref,
        "artifact_kind": evidence.artifact_kind,
        "visibility": evidence.visibility,
    }


def _serialize_result(item: QueryResultItem) -> dict[str, object]:
    return {
        "result_id": item.result_id,
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
        "agent_ref": item.agent_ref,
        "role": item.role,
        "container_ref": item.container_ref,
        "thread_ref": item.thread_ref,
        "source_ref": item.source_ref,
        "artifact_kind": item.artifact_kind,
        "visibility": item.visibility,
        "retrieval_source": item.retrieval_source,
    }


def _serialize_injectable_block(block: InjectableBlock) -> dict[str, object]:
    return {
        "result_id": block.result_id,
        "block_type": block.block_type,
        "title": block.title,
        "text": block.text,
        "memory_type": block.memory_type,
        "evidence": [_serialize_evidence(evidence) for evidence in block.evidence],
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
        "query_visibility": trace.query_visibility,
        "query_container_ref": trace.query_container_ref,
        "excluded_candidates": [
            _serialize_visibility_exclusion(item)
            for item in trace.excluded_candidates
        ],
        "fail_closed_reason": trace.fail_closed_reason,
    }


def _serialize_query_filters(filters) -> dict[str, object] | None:
    if filters is None:
        return None
    return {
        "source_type": filters.source_type,
        "role": filters.role,
        "artifact_kind": filters.artifact_kind,
        "container_ref": filters.container_ref,
        "thread_ref": filters.thread_ref,
        "actor_ref": filters.actor_ref,
    }


def _serialize_fusion_trace_hit(hit: FusionTraceHit) -> dict[str, object]:
    return {
        "result_id": hit.result_id,
        "rrf_score": hit.rrf_score,
        "rrf_rank": hit.rrf_rank,
        "fused_score": hit.fused_score,
        "lexical_rank": hit.lexical_rank,
        "vector_rank": hit.vector_rank,
        "retrieval_source": hit.retrieval_source,
    }


def _serialize_fusion_trace(fusion_trace: FusionStageTrace) -> dict[str, object]:
    return {
        "stage_name": fusion_trace.stage_name,
        "k": fusion_trace.k,
        "rrf_score_scale": fusion_trace.rrf_score_scale,
        "lexical_candidate_count": fusion_trace.lexical_candidate_count,
        "vector_candidate_count": fusion_trace.vector_candidate_count,
        "fused_candidate_count": fusion_trace.fused_candidate_count,
        "both_sources_count": fusion_trace.both_sources_count,
        "selected_count": fusion_trace.selected_count,
        "hits": [_serialize_fusion_trace_hit(hit) for hit in fusion_trace.hits],
    }


def _serialize_trace(trace: QueryTrace) -> dict[str, object]:
    return {
        "query_text": trace.query_text,
        "query_tokens": list(trace.query_tokens),
        "limit": trace.limit,
        "filters": _serialize_query_filters(trace.filters),
        "requested_filters": _serialize_query_filters(trace.requested_filters),
        "filter_scope_relaxed": trace.filter_scope_relaxed,
        "filter_scope_reason": trace.filter_scope_reason,
        "stages": [_serialize_stage_trace(stage) for stage in trace.stages],
        "routing": trace.routing,
        "visibility": _serialize_visibility_trace(trace.visibility) if trace.visibility is not None else None,
        "result_summary": trace.result_summary,
        "fusion_trace": _serialize_fusion_trace(trace.fusion_trace) if trace.fusion_trace is not None else None,
    }


def create_router(service: PalliumService) -> APIRouter:
    router = APIRouter()

    def _ingest_one(request: ItemCreateRequest) -> ItemCreateResponse:
        result = service.ingest_item(
            source_type=request.source_type,
            source_id=request.source_id,
            content_type=request.content_type,
            content=request.content,
            metadata=request.metadata,
            use_case=request.use_case,
            occurred_at=request.occurred_at,
            actor_ref=request.actor_ref,
            agent_ref=request.agent_ref,
            role=request.role,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            source_ref=request.source_ref,
            artifact_kind=request.artifact_kind,
            visibility=request.visibility_kind(),
        )
        return ItemCreateResponse(**result.as_dict())

    MAX_ITEMS_PER_REQUEST = 50

    @router.post("/items", response_model=list[ItemCreateResponse])
    def create_items(request: list[ItemCreateRequest]) -> list[ItemCreateResponse]:
        if len(request) > MAX_ITEMS_PER_REQUEST:
            raise HTTPException(status_code=422, detail=f"Too many items: max {MAX_ITEMS_PER_REQUEST} per request")
        return [_ingest_one(item) for item in request]

    @router.get("/items/{source_item_id}/processing", response_model=ProcessingStatusResponse)
    def get_item_processing(source_item_id: str) -> ProcessingStatusResponse:
        try:
            result = service.get_item_processing(source_item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source item not found") from exc
        return ProcessingStatusResponse(**result.as_dict())

    @router.get("/health")
    def health_check():
        return {"status": "ok"}

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
                    "visibility": item.visibility,
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
            retention={
                "enabled": snapshot.retention.enabled,
                "last_run_started_at": snapshot.retention.last_run_started_at,
                "last_run_completed_at": snapshot.retention.last_run_completed_at,
                "last_deleted_source_items": snapshot.retention.last_deleted_source_items,
                "last_deleted_memory_objects": snapshot.retention.last_deleted_memory_objects,
                "last_deleted_relations": snapshot.retention.last_deleted_relations,
                "last_deleted_index_entries": snapshot.retention.last_deleted_index_entries,
                "last_stripped_debug_metadata": snapshot.retention.last_stripped_debug_metadata,
                "last_skipped_protected_source_items": snapshot.retention.last_skipped_protected_source_items,
            },
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
            actor_ref=request.actor_ref,
            visibility=request.visibility_kind(),
            runtime_context=_deserialize_runtime_context(request.runtime_context),
        )
        return QueryResponse(
            results=[_serialize_result(item) for item in result.results],
            should_inject=result.should_inject,
            decision_reason=result.decision_reason,
            injectable_blocks=[_serialize_injectable_block(block) for block in result.injectable_blocks],
        )

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
            actor_ref=request.actor_ref,
            visibility=request.visibility_kind(),
            runtime_context=_deserialize_runtime_context(request.runtime_context),
            include_trace=True,
        )
        if result.trace is None:
            raise ValueError("debug query must include retrieval trace")
        return QueryDebugResponse(
            results=[_serialize_result(item) for item in result.results],
            should_inject=result.should_inject,
            decision_reason=result.decision_reason,
            injectable_blocks=[_serialize_injectable_block(block) for block in result.injectable_blocks],
            trace=_serialize_trace(result.trace),
        )

    @router.post("/item-and-query", response_model=ItemAndQueryResponse)
    def item_and_query(request: ItemAndQueryRequest) -> ItemAndQueryResponse:
        ingest_result = service.ingest_item(
            source_type=request.source_type,
            source_id=request.source_id,
            content_type=request.content_type,
            content=request.content,
            metadata=request.metadata,
            use_case=request.use_case,
            occurred_at=request.occurred_at,
            actor_ref=request.actor_ref,
            agent_ref=request.agent_ref,
            role=request.role,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            source_ref=request.source_ref,
            artifact_kind=request.artifact_kind,
            visibility=request.visibility_kind(),
        )
        query_text = request.query_text or request.content
        runtime_context = resolve_runtime_context(
            service._storage,
            request.thread_ref,
            _deserialize_runtime_context(request.runtime_context),
            exclude_item_id=ingest_result.source_item_id,
        )
        query_result = service.query(
            query_text,
            request.query_limit,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            actor_ref=request.query_actor_ref,
            visibility=request.visibility_kind(),
            runtime_context=runtime_context,
        )
        return ItemAndQueryResponse(
            source_item_id=ingest_result.source_item_id,
            results=[_serialize_result(item) for item in query_result.results],
            should_inject=query_result.should_inject,
            decision_reason=query_result.decision_reason,
            injectable_blocks=[_serialize_injectable_block(block) for block in query_result.injectable_blocks],
        )

    @router.post("/item-and-query/debug", response_model=ItemAndQueryDebugResponse)
    def item_and_query_debug(request: ItemAndQueryRequest) -> ItemAndQueryDebugResponse:
        ingest_result = service.ingest_item(
            source_type=request.source_type,
            source_id=request.source_id,
            content_type=request.content_type,
            content=request.content,
            metadata=request.metadata,
            use_case=request.use_case,
            occurred_at=request.occurred_at,
            actor_ref=request.actor_ref,
            agent_ref=request.agent_ref,
            role=request.role,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            source_ref=request.source_ref,
            artifact_kind=request.artifact_kind,
            visibility=request.visibility_kind(),
        )
        query_text = request.query_text or request.content
        runtime_context = resolve_runtime_context(
            service._storage,
            request.thread_ref,
            _deserialize_runtime_context(request.runtime_context),
            exclude_item_id=ingest_result.source_item_id,
        )
        query_result = service.query(
            query_text,
            request.query_limit,
            container_ref=request.container_ref,
            thread_ref=request.thread_ref,
            actor_ref=request.query_actor_ref,
            visibility=request.visibility_kind(),
            runtime_context=runtime_context,
            include_trace=True,
        )
        if query_result.trace is None:
            raise ValueError("debug query must include retrieval trace")
        return ItemAndQueryDebugResponse(
            source_item_id=ingest_result.source_item_id,
            results=[_serialize_result(item) for item in query_result.results],
            should_inject=query_result.should_inject,
            decision_reason=query_result.decision_reason,
            injectable_blocks=[_serialize_injectable_block(block) for block in query_result.injectable_blocks],
            trace=_serialize_trace(query_result.trace),
        )

    return router
