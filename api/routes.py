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
        )
        return ItemCreateResponse(**result.as_dict())

    @router.post("/query", response_model=QueryResponse)
    def query_items(request: QueryRequest) -> QueryResponse:
        result = service.query(request.text, request.limit)
        return QueryResponse(
            results=[
                {
                    "memory_object_id": item.memory_object_id,
                    "type": item.type,
                    "payload": item.payload,
                    "score": item.score,
                    "evidence": [
                        {
                            "source_item_id": evidence.source_item_id,
                            "source_type": evidence.source_type,
                            "source_id": evidence.source_id,
                        }
                        for evidence in item.evidence
                    ],
                }
                for item in result.results
            ]
        )

    return router
