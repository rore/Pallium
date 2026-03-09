from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ItemCreateRequest(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    use_case: str | None = None


class ItemCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_item_id: str
    annotation_ids: list[str]
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]


class QueryRequest(BaseModel):
    text: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class EvidenceResponse(BaseModel):
    source_item_id: str
    source_type: str
    source_id: str


class QueryResultResponse(BaseModel):
    result_kind: str
    score: int
    evidence: list[EvidenceResponse]
    memory_object_id: str | None = None
    type: str | None = None
    payload: dict[str, Any] | None = None
    source_item_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    results: list[QueryResultResponse]
