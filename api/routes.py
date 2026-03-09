from __future__ import annotations

from fastapi import APIRouter

from api.schemas import ItemCreateRequest, ItemCreateResponse, QueryRequest, QueryResponse
from core.service import PalliumService


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
        )
        return ItemCreateResponse(**result.as_dict())

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
        )
        return QueryResponse(
            results=[
                {
                    "result_kind": item.result_kind,
                    "score": item.score,
                    "evidence": [
                        {
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
                        }
                        for evidence in item.evidence
                    ],
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
                }
                for item in result.results
            ]
        )

    return router
