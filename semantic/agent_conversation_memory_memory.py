from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from core.contracts import ProcessResult, SupersessionHint
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryEnvelope, MemoryEnvelopeConfidence, MemoryEnvelopeDerivation, MemoryEnvelopeKind, MemoryEnvelopeScope, MemoryObject, MemorySubjectAnchor, Relation, SourceItem
from semantic.common import SemanticExtraction, normalize_for_index, content_tokens, _resolve_actor_ref, _should_reject_constraint_text
from semantic.agent_conversation_memory_embedding import VECTOR_EMBEDDING_PROVIDER_NAME, VECTOR_EMBEDDING_PROVIDER_VERSION, build_embedding_text
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_SCHEMA_ID,
    CONSTRAINT_MEMORY_SCHEMA_VERSION,
    CONSTRAINT_MEMORY_TYPE,
    SUBJECT_HINT_METADATA_KEY,
    _merge_subject_anchors,
    _serialize_subject_anchors,
)
from semantic.llm_agent_memory import _normalize_work_refs

MEMORY_ENVELOPE_SCHEMA_ID = "core.memory_envelope"

MEMORY_ENVELOPE_SCHEMA_VERSION = "v1"

WRITE_TIME_MODEL_ROLE = "write_time_extraction"

WORK_REFS_METADATA_KEY = "pallium_work_refs"

# Memory types whose supersession hints are emitted at container scope
# (thread_ref dropped). Decisions and investigation_outcomes were widened
# from thread scope as part of T2 (2026-06-04) — same canonical decision
# text in different threads of the same container should collapse onto one
# active row. Constraints have always been container-scoped.
_CONTAINER_SCOPED_HINT_TYPES = frozenset({
    CONSTRAINT_MEMORY_TYPE,
    "decision",
    "investigation_outcome",
})


def _work_refs_from_metadata(metadata: dict[str, object] | None) -> tuple[str, ...]:
    """Read and normalize work_refs from source item metadata (runtime hints)."""
    if not isinstance(metadata, dict):
        return ()
    raw = metadata.get(WORK_REFS_METADATA_KEY)
    return _normalize_work_refs(raw)


def _merge_work_refs(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Union and deduplicate work_refs from multiple sources."""
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for ref in group:
            if ref not in seen:
                seen.add(ref)
                result.append(ref)
    return tuple(result)


def _has_explicit_semantic_signals(extraction: SemanticExtraction) -> bool:
    return any(
        getattr(extraction, field_name)
        for field_name in ("constraint_text", "next_step_text", "blocker_text", "progress_text", "key_finding_text")
    )

def _memory_kind_for_type(memory_type: str) -> MemoryEnvelopeKind:
    return {
        "decision": "finding",
        "investigation_outcome": "finding",
        CONSTRAINT_MEMORY_TYPE: "constraint",
        "task_checkpoint": "episode",
        "thread_summary": "summary",
        "turn_summary": "summary",
        "interest": "summary",
        "continuity_memory": "summary",
        "pattern_memory": "summary",
    }.get(memory_type, "unknown")

def _memory_confidence_for_type(memory_type: str, *, extraction: SemanticExtraction | None = None) -> MemoryEnvelopeConfidence:
    if memory_type in {"decision", "investigation_outcome"}:
        return "high"
    if memory_type == CONSTRAINT_MEMORY_TYPE:
        return "medium"
    if memory_type in {"task_checkpoint", "thread_summary", "continuity_memory", "pattern_memory", "interest"}:
        return "medium"
    if memory_type == "turn_summary":
        return "medium" if extraction is not None and _has_explicit_semantic_signals(extraction) else "low"
    return "unknown"

def _build_memory_envelope(
    *,
    kind: MemoryEnvelopeKind,
    container_ref: str | None,
    thread_ref: str | None,
    confidence: MemoryEnvelopeConfidence,
    producer_kind: str,
    producer_schema_id: str,
    producer_schema_version: str,
    prompt_variant: str | None,
    kind_basis: str,
    subjects: list[MemorySubjectAnchor],
    work_refs: tuple[str, ...] = (),
    source_content_length: int = 0,
) -> MemoryEnvelope:
    return MemoryEnvelope(
        schema_id=MEMORY_ENVELOPE_SCHEMA_ID,
        schema_version=MEMORY_ENVELOPE_SCHEMA_VERSION,
        kind=kind,
        scope=MemoryEnvelopeScope(
            container_ref=container_ref,
            thread_ref=thread_ref,
            work_refs=work_refs,
        ),
        subjects=list(subjects),
        confidence=confidence,
        derivation=MemoryEnvelopeDerivation(
            producer_kind=producer_kind,
            producer_schema_id=producer_schema_id,
            producer_schema_version=producer_schema_version,
            prompt_variant=prompt_variant,
            model_role=WRITE_TIME_MODEL_ROLE if prompt_variant else None,
            kind_basis=kind_basis,
        ),
        source_content_length=source_content_length,
    )

def _semantic_provenance_from_process_result(result: ProcessResult) -> dict[str, object]:
    for memory_object in result.memory_objects:
        payload = memory_object.payload if isinstance(memory_object.payload, dict) else {}
        semantic_provenance = payload.get("semantic_provenance")
        if isinstance(semantic_provenance, dict) and semantic_provenance:
            return dict(semantic_provenance)
    return {}

def _constraint_canonical_key(constraint_text: str) -> str:
    """Generate a dedup key from sorted content tokens (stopwords removed)."""
    tokens = sorted(content_tokens(constraint_text))
    return " ".join(tokens)


def _append_typed_constraint_memory_objects(
    result: ProcessResult,
    *,
    source_item: SourceItem,
    extraction: SemanticExtraction,
) -> ProcessResult:
    constraint_text = (extraction.constraint_text or "").strip()
    if not constraint_text:
        return result
    if _should_reject_constraint_text(constraint_text):
        return result
    if source_item.role and source_item.role.lower() != "user":
        return result
    if source_item.visibility in ("container", "public"):
        return result
    semantic_provenance = _semantic_provenance_from_process_result(result)
    producer_schema_id = str(semantic_provenance.get("prompt_schema_id") or CONSTRAINT_MEMORY_SCHEMA_ID)
    producer_schema_version = str(semantic_provenance.get("prompt_schema_version") or CONSTRAINT_MEMORY_SCHEMA_VERSION)
    prompt_variant = semantic_provenance.get("prompt_variant") if isinstance(semantic_provenance.get("prompt_variant"), str) else None
    envelope_subjects = _merge_subject_anchors(extraction.subject_hints)
    canonical_key = _constraint_canonical_key(constraint_text)
    payload = {
        "summary": constraint_text,
        "constraint_text": constraint_text,
        "canonical_key": canonical_key,
        "evidence_context": source_item.content,
        "container_ref": source_item.container_ref,
        "thread_ref": source_item.thread_ref,
        "semantic_provenance": dict(semantic_provenance),
    }
    memory_object = MemoryObject(
        type=CONSTRAINT_MEMORY_TYPE,
        schema_id=CONSTRAINT_MEMORY_SCHEMA_ID,
        schema_version=CONSTRAINT_MEMORY_SCHEMA_VERSION,
        payload=payload,
        visibility=source_item.visibility,
        container_ref=source_item.container_ref,
        actor_ref=_resolve_actor_ref(source_item),
        freshness_at=source_item.occurred_at,
        envelope=_build_memory_envelope(
            kind="constraint",
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            confidence="medium",
            producer_kind="item_extraction",
            producer_schema_id=producer_schema_id,
            producer_schema_version=producer_schema_version,
            prompt_variant=prompt_variant,
            kind_basis="constraint_text",
            subjects=envelope_subjects,
        ),
    )
    return replace(
        result,
        memory_objects=list(result.memory_objects) + [memory_object],
        relations=list(result.relations) + [
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        ],
        index_entries=list(result.index_entries) + _build_constraint_index_entries(
            memory_object=memory_object,
            constraint_text=constraint_text,
        ),
    )


def _build_constraint_index_entries(
    *,
    memory_object: MemoryObject,
    constraint_text: str,
) -> list:
    entries = [
        build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(constraint_text),
            text_view_name="memory_object.constraint_memory_context",
        )
    ]
    embedding_text = build_embedding_text(memory_object)
    if embedding_text is not None:
        entries.append(
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view=embedding_text,
                text_view_name="memory_object.constraint_memory_context.embedding",
                provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
            )
        )
    return entries

def _apply_direct_memory_envelopes(
    result: ProcessResult,
    *,
    source_item: SourceItem,
    extraction: SemanticExtraction,
) -> ProcessResult:
    updated_metadata = dict(result.source_item_metadata_updates)
    if extraction.subject_hints:
        source_updates = dict(updated_metadata.get(source_item.id, {}))
        source_updates[SUBJECT_HINT_METADATA_KEY] = _serialize_subject_anchors(extraction.subject_hints)
        updated_metadata[source_item.id] = source_updates
    # Merge work_refs from LLM extraction and runtime metadata hints
    metadata_work_refs = _work_refs_from_metadata(source_item.metadata)
    merged_work_refs = _merge_work_refs(extraction.work_refs, metadata_work_refs)
    # Persist merged work_refs back to source item metadata
    if merged_work_refs:
        source_updates = dict(updated_metadata.get(source_item.id, {}))
        source_updates[WORK_REFS_METADATA_KEY] = list(merged_work_refs)
        updated_metadata[source_item.id] = source_updates
    if not result.memory_objects:
        return replace(result, source_item_metadata_updates=updated_metadata)
    direct_subjects = _merge_subject_anchors(extraction.subject_hints)
    kind_basis = "llm_subject_hints" if direct_subjects else "type_map"
    enveloped_memory_objects = []
    for memory_object in result.memory_objects:
        if memory_object.envelope is not None:
            enveloped_memory_objects.append(memory_object)
            continue
        semantic_provenance = memory_object.payload.get("semantic_provenance", {}) if isinstance(memory_object.payload, dict) else {}
        producer_schema_id = str(semantic_provenance.get("prompt_schema_id") or memory_object.schema_id)
        producer_schema_version = str(semantic_provenance.get("prompt_schema_version") or memory_object.schema_version)
        prompt_variant = semantic_provenance.get("prompt_variant") if isinstance(semantic_provenance, dict) else None
        enveloped_memory_objects.append(
            replace(
                memory_object,
                envelope=_build_memory_envelope(
                    kind=_memory_kind_for_type(memory_object.type),
                    container_ref=source_item.container_ref,
                    thread_ref=source_item.thread_ref,
                    confidence=_memory_confidence_for_type(memory_object.type, extraction=extraction),
                    producer_kind="item_extraction",
                    producer_schema_id=producer_schema_id,
                    producer_schema_version=producer_schema_version,
                    prompt_variant=str(prompt_variant) if isinstance(prompt_variant, str) and prompt_variant else None,
                    kind_basis=kind_basis,
                    subjects=direct_subjects,
                    work_refs=merged_work_refs,
                    source_content_length=len(source_item.content),
                ),
            )
        )
    return replace(
        result,
        memory_objects=enveloped_memory_objects,
        source_item_metadata_updates=updated_metadata,
    )


def build_supersession_hints(source_item: SourceItem, result: ProcessResult) -> list[SupersessionHint]:
    if not source_item.container_ref:
        return []
    hints: list[SupersessionHint] = []
    for memory_object in result.memory_objects:
        if memory_object.type not in _CONTAINER_SCOPED_HINT_TYPES:
            continue
        canonical_key = str(memory_object.payload.get('canonical_key') or '').strip()
        if not canonical_key:
            continue
        # All eligible types are container-scoped: same canonical_key in different
        # threads should supersede. Decisions/investigations were thread-scoped
        # before T2; widening to container scope catches the cross-thread rebuild
        # collisions observed in production (see merge_policy.md).
        hints.append(
            SupersessionHint(
                replacement_memory_id=memory_object.id,
                memory_type=memory_object.type,
                canonical_key=canonical_key,
                container_ref=source_item.container_ref,
                thread_ref=None,
                visibility=source_item.visibility,
            )
        )
    return hints
