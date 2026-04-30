from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from core.indexing import build_index_entry
from core.models import (
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    Relation,
    SourceItem,
    MemorySubjectAnchor,
)

DEFAULT_INDEX_TEXT_VIEW_NAME = "scenario.seed"


def seed_memory_objects(client: TestClient, specs: list[dict[str, Any]]) -> None:
    storage = client.app.state.pallium_service._storage
    for raw_spec in specs:
        spec = dict(raw_spec)
        index_text = str(spec.pop("index_text", "") or _default_index_text(spec.get("payload") or {}))
        text_view_name = str(spec.pop("index_text_view_name", DEFAULT_INDEX_TEXT_VIEW_NAME))
        evidence_specs = list(spec.pop("evidence", []) or [])
        memory_object = memory_object_from_spec(spec)
        storage.create_memory_object(memory_object)
        _seed_memory_evidence(storage, memory_object, evidence_specs)
        if index_text:
            storage.create_index_entry(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_object.id,
                    index_type="lexical",
                    text_view=index_text,
                    text_view_name=text_view_name,
                )
            )


def memory_object_from_spec(spec: dict[str, Any]) -> MemoryObject:
    return MemoryObject(
        id=str(spec["id"]) if spec.get("id") is not None else MemoryObject.__dataclass_fields__["id"].default_factory(),
        type=str(spec["type"]),
        schema_id=str(spec["schema_id"]),
        schema_version=str(spec["schema_version"]),
        payload=dict(spec.get("payload") or {}),
        lifecycle=str(spec.get("lifecycle") or "active"),
        visibility=str(spec.get("visibility") or "private"),
        container_ref=spec.get("container_ref"),
        actor_ref=spec.get("actor_ref"),
        freshness_at=_parse_datetime(spec.get("freshness_at")),
        envelope=_memory_envelope_from_spec(spec.get("envelope")),
        created_at=_parse_datetime(spec.get("created_at")) or MemoryObject.__dataclass_fields__["created_at"].default_factory(),
    )


def _memory_envelope_from_spec(spec: dict[str, Any] | None) -> MemoryEnvelope | None:
    if not spec:
        return None
    scope_spec = dict(spec.get("scope") or {})
    derivation_spec = dict(spec.get("derivation") or {})
    subject_specs = list(spec.get("subjects") or [])
    return MemoryEnvelope(
        schema_id=str(spec["schema_id"]),
        schema_version=str(spec["schema_version"]),
        kind=str(spec["kind"]),
        scope=MemoryEnvelopeScope(
            container_ref=scope_spec.get("container_ref"),
            thread_ref=scope_spec.get("thread_ref"),
            work_refs=tuple(scope_spec.get("work_refs") or ()),
        ),
        derivation=MemoryEnvelopeDerivation(
            producer_kind=str(derivation_spec["producer_kind"]),
            producer_schema_id=str(derivation_spec["producer_schema_id"]),
            producer_schema_version=str(derivation_spec["producer_schema_version"]),
            prompt_variant=derivation_spec.get("prompt_variant"),
            model_role=derivation_spec.get("model_role"),
            kind_basis=derivation_spec.get("kind_basis"),
        ),
        subjects=[
            MemorySubjectAnchor(kind=str(subject["kind"]), value=str(subject["value"]))
            for subject in subject_specs
        ],
        confidence=str(spec.get("confidence") or "unknown"),
        source_content_length=int(spec.get("source_content_length") or 0),
    )


def _default_index_text(payload: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for key in ("summary", "statement", "decision", "current_state", "question", "answer", "subject", "category"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value.strip())
    return " ".join(text_parts)


def _seed_memory_evidence(storage: Any, memory_object: MemoryObject, evidence_specs: list[dict[str, Any]]) -> None:
    for raw_spec in evidence_specs:
        source_item = _source_item_from_spec(raw_spec, memory_object=memory_object)
        storage.create_source_item(source_item)
        storage.create_relation(
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        )


def _source_item_from_spec(spec: dict[str, Any], *, memory_object: MemoryObject) -> SourceItem:
    return SourceItem(
        id=str(spec["id"]) if spec.get("id") is not None else SourceItem.__dataclass_fields__["id"].default_factory(),
        source_type=str(spec.get("source_type") or "assistant_artifact"),
        source_id=str(spec.get("source_id") or spec.get("id") or memory_object.id),
        content_type=str(spec.get("content_type") or "text/plain"),
        content=str(spec.get("content") or _default_index_text(memory_object.payload)),
        metadata=dict(spec.get("metadata") or {}),
        occurred_at=_parse_datetime(spec.get("occurred_at")),
        actor_ref=spec.get("actor_ref"),
        agent_ref=spec.get("agent_ref"),
        role=spec.get("role"),
        container_ref=spec.get("container_ref") or memory_object.container_ref,
        thread_ref=spec.get("thread_ref"),
        source_ref=spec.get("source_ref"),
        artifact_kind=spec.get("artifact_kind"),
        visibility=str(spec.get("visibility") or memory_object.visibility),
        use_case=spec.get("use_case"),
        created_at=_parse_datetime(spec.get("created_at")) or SourceItem.__dataclass_fields__["created_at"].default_factory(),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)