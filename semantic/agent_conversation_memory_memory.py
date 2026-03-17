from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from core.contracts import ProcessResult, SupersessionHint
from core.indexing import build_index_entry
from core.models import MemoryEnvelope, MemoryEnvelopeConfidence, MemoryEnvelopeDerivation, MemoryEnvelopeKind, MemoryEnvelopeScope, MemoryObject, MemorySubjectAnchor, Relation, SourceItem
from semantic.common import SemanticExtraction, normalize_for_index
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_SCHEMA_ID,
    CONSTRAINT_MEMORY_SCHEMA_VERSION,
    CONSTRAINT_MEMORY_TYPE,
    SUBJECT_HINT_METADATA_KEY,
    _constraint_compatibility_domain,
    _constraint_confidence_from_candidate,
    _constraint_strength_for_polarity,
    _constraint_summary_text,
    _constraint_supersession_identity,
    _merge_subject_anchors,
    _serialize_subject_anchor,
    _serialize_subject_anchors,
)

MEMORY_ENVELOPE_SCHEMA_ID = "core.memory_envelope"

MEMORY_ENVELOPE_SCHEMA_VERSION = "v1"

WRITE_TIME_MODEL_ROLE = "write_time_extraction"

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
        "discussion_summary": "summary",
        "continuity_memory": "summary",
        "pattern_memory": "summary",
    }.get(memory_type, "unknown")

def _memory_confidence_for_type(memory_type: str, *, extraction: SemanticExtraction | None = None) -> MemoryEnvelopeConfidence:
    if memory_type in {"decision", "investigation_outcome"}:
        return "high"
    if memory_type == CONSTRAINT_MEMORY_TYPE:
        return "medium"
    if memory_type in {"task_checkpoint", "thread_summary", "continuity_memory", "pattern_memory"}:
        return "medium"
    if memory_type == "discussion_summary":
        return "medium" if extraction is not None and _has_explicit_semantic_signals(extraction) else "low"
    return "unknown"

def _build_memory_envelope(
    *,
    kind: MemoryEnvelopeKind,
    container_ref: str | None,
    thread_ref: str | None,
    session_ref: str | None,
    confidence: MemoryEnvelopeConfidence,
    producer_kind: str,
    producer_schema_id: str,
    producer_schema_version: str,
    prompt_variant: str | None,
    kind_basis: str,
    subjects: list[MemorySubjectAnchor],
) -> MemoryEnvelope:
    return MemoryEnvelope(
        schema_id=MEMORY_ENVELOPE_SCHEMA_ID,
        schema_version=MEMORY_ENVELOPE_SCHEMA_VERSION,
        kind=kind,
        scope=MemoryEnvelopeScope(
            container_ref=container_ref,
            thread_ref=thread_ref,
            session_ref=session_ref,
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
    )

def _semantic_provenance_from_process_result(result: ProcessResult) -> dict[str, object]:
    for annotation in result.annotations:
        payload = annotation.payload if isinstance(annotation.payload, dict) else {}
        semantic_provenance = payload.get("semantic_provenance")
        if isinstance(semantic_provenance, dict) and semantic_provenance:
            return dict(semantic_provenance)
    for memory_object in result.memory_objects:
        payload = memory_object.payload if isinstance(memory_object.payload, dict) else {}
        semantic_provenance = payload.get("semantic_provenance")
        if isinstance(semantic_provenance, dict) and semantic_provenance:
            return dict(semantic_provenance)
    return {}

def _append_typed_constraint_memory_objects(
    result: ProcessResult,
    *,
    source_item: SourceItem,
    extraction: SemanticExtraction,
) -> ProcessResult:
    if not extraction.constraint_candidates:
        return result
    semantic_provenance = _semantic_provenance_from_process_result(result)
    producer_schema_id = str(semantic_provenance.get("prompt_schema_id") or CONSTRAINT_MEMORY_SCHEMA_ID)
    producer_schema_version = str(semantic_provenance.get("prompt_schema_version") or CONSTRAINT_MEMORY_SCHEMA_VERSION)
    prompt_variant = semantic_provenance.get("prompt_variant") if isinstance(semantic_provenance.get("prompt_variant"), str) else None
    memory_objects = list(result.memory_objects)
    relations = list(result.relations)
    index_entries = list(result.index_entries)
    for candidate in extraction.constraint_candidates:
        canonical_key = _constraint_supersession_identity(candidate.primary_scope_anchor, candidate.target_anchor, candidate.action_class)
        constraint_text = candidate.constraint_text.strip()
        envelope_subjects = _merge_subject_anchors((candidate.primary_scope_anchor,), (candidate.target_anchor,), extraction.subject_hints)
        payload = {
            "summary": _constraint_summary_text(candidate),
            "constraint_text": constraint_text,
            "primary_scope_anchor": _serialize_subject_anchor(candidate.primary_scope_anchor),
            "target_anchor": _serialize_subject_anchor(candidate.target_anchor),
            "action_class": candidate.action_class,
            "polarity": candidate.polarity,
            "strength": _constraint_strength_for_polarity(candidate.polarity),
            "status": "active",
            "evidence": [constraint_text],
            "freshness_signal": source_item.occurred_at.isoformat() if source_item.occurred_at is not None else None,
            "confidence": candidate.confidence,
            "canonical_key": canonical_key,
            "compatibility_domain_key": _constraint_compatibility_domain(candidate.primary_scope_anchor, candidate.action_class),
            "precise_coverage_key": canonical_key,
            "container_ref": source_item.container_ref,
            "thread_ref": source_item.thread_ref,
            "session_ref": source_item.session_ref,
            "semantic_provenance": dict(semantic_provenance),
        }
        memory_object = MemoryObject(
            type=CONSTRAINT_MEMORY_TYPE,
            schema_id=CONSTRAINT_MEMORY_SCHEMA_ID,
            schema_version=CONSTRAINT_MEMORY_SCHEMA_VERSION,
            payload=payload,
            visibility_context=source_item.visibility_context,
            freshness_at=source_item.occurred_at,
            envelope=_build_memory_envelope(
                kind="constraint",
                container_ref=source_item.container_ref,
                thread_ref=source_item.thread_ref,
                session_ref=source_item.session_ref,
                confidence=_constraint_confidence_from_candidate(candidate),
                producer_kind="item_extraction",
                producer_schema_id=producer_schema_id,
                producer_schema_version=producer_schema_version,
                prompt_variant=prompt_variant,
                kind_basis="constraint_candidate",
                subjects=envelope_subjects,
            ),
        )
        memory_objects.append(memory_object)
        relations.append(
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item.id,
            )
        )
        index_entries.append(
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object.id,
                index_type="lexical",
                text_view=normalize_for_index(
                    " ".join(
                        part
                        for part in (
                            payload["summary"],
                            constraint_text,
                            candidate.primary_scope_anchor.value,
                            candidate.target_anchor.value,
                            candidate.action_class,
                            candidate.polarity,
                        )
                        if part
                    )
                ),
                text_view_name="memory_object.constraint_memory_context",
            )
        )
    return replace(result, memory_objects=memory_objects, relations=relations, index_entries=index_entries)

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
                    session_ref=source_item.session_ref,
                    confidence=_memory_confidence_for_type(memory_object.type, extraction=extraction),
                    producer_kind="item_extraction",
                    producer_schema_id=producer_schema_id,
                    producer_schema_version=producer_schema_version,
                    prompt_variant=str(prompt_variant) if isinstance(prompt_variant, str) and prompt_variant else None,
                    kind_basis=kind_basis,
                    subjects=direct_subjects,
                ),
            )
        )
    return replace(
        result,
        memory_objects=enveloped_memory_objects,
        source_item_metadata_updates=updated_metadata,
    )


def build_supersession_hints(source_item: SourceItem, result: ProcessResult) -> list[SupersessionHint]:
    if not source_item.container_ref or not source_item.thread_ref:
        return []
    hints: list[SupersessionHint] = []
    for memory_object in result.memory_objects:
        if memory_object.type not in {'decision', 'investigation_outcome'} and memory_object.type != CONSTRAINT_MEMORY_TYPE:
            continue
        canonical_key = str(memory_object.payload.get('canonical_key') or '').strip()
        if not canonical_key:
            continue
        hints.append(
            SupersessionHint(
                replacement_memory_id=memory_object.id,
                memory_type=memory_object.type,
                canonical_key=canonical_key,
                container_ref=source_item.container_ref,
                thread_ref=source_item.thread_ref,
                visibility_context=source_item.visibility_context,
            )
        )
    return hints
