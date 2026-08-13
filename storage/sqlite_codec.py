from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone

from core.models import (
    EvidenceReference,
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    Relation,
    SourceItem,
    utc_now,
)
from storage.base import RetentionLease, ThreadProcessingLease
from storage.sqlite_schema import (
    IndexEntryRecord,
    MaintenanceStateRecord,
    MemoryObjectRecord,
    RelationRecord,
    SourceItemRecord,
    ThreadProcessingLeaseRecord,
)


MEMORY_ENVELOPE_SCHEMA_ID = "core.memory_envelope"
MEMORY_ENVELOPE_SCHEMA_VERSION = "v1"
MEMORY_ENVELOPE_KINDS = {"constraint", "finding", "episode", "next_step", "summary", "unknown"}
MEMORY_ENVELOPE_CONFIDENCES = {"high", "medium", "low", "unknown"}
MEMORY_ENVELOPE_PRODUCER_KINDS = {"item_extraction", "thread_aggregation", "consolidation"}
MEMORY_SUBJECT_ANCHOR_KINDS = {"workstream", "component", "surface"}


class SQLiteCodecMixin:
    @staticmethod
    def _to_source_item(record: SourceItemRecord) -> SourceItem:
        return SourceItem(
            id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            content_type=record.content_type,
            content=record.content,
            metadata=SQLiteCodecMixin._loads(record.metadata_json),
            occurred_at=SQLiteCodecMixin._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            agent_ref=record.agent_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility=record.visibility or "private",
            use_case=record.use_case,
            processing_status=record.processing_status or "pending",
            processing_attempts=record.processing_attempts or 0,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=SQLiteCodecMixin._normalize_datetime(record.processing_claimed_at),
            processing_lease_expires_at=SQLiteCodecMixin._normalize_datetime(record.processing_lease_expires_at),
            processing_completed_at=SQLiteCodecMixin._normalize_datetime(record.processing_completed_at),
            processing_error=record.processing_error,
            processing_next_attempt_at=SQLiteCodecMixin._normalize_datetime(record.processing_next_attempt_at),
            thread_position=getattr(record, 'thread_position', None),
            forgotten_at=SQLiteCodecMixin._normalize_datetime(getattr(record, 'forgotten_at', None)),
            forgotten_by=getattr(record, 'forgotten_by', None),
            forgotten_reason=getattr(record, 'forgotten_reason', None),
            created_at=SQLiteCodecMixin._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_memory_object(record: MemoryObjectRecord) -> MemoryObject:
        return MemoryObject(
            id=record.id,
            type=record.type,
            schema_id=record.schema_id,
            schema_version=record.schema_version,
            payload=SQLiteCodecMixin._loads(record.payload_json),
            lifecycle=record.lifecycle or "active",
            envelope=SQLiteCodecMixin._load_memory_envelope(record.envelope_json),
            visibility=record.visibility or "private",
            container_ref=record.container_ref,
            actor_ref=record.actor_ref,
            freshness_at=SQLiteCodecMixin._normalize_datetime(record.freshness_at),
            created_at=SQLiteCodecMixin._normalize_datetime(record.created_at) or utc_now(),
            # PR 1 of operational_fact redesign: propagate the
            # soft-delete flag through the codec so read-side callers
            # (retrieval, dashboard, MCP) can honor it. Previously
            # dropped, causing tombstoned rows to be returned as active.
            is_soft_deleted=bool(getattr(record, "is_soft_deleted", 0)),
        )

    @staticmethod
    def _to_relation(record: RelationRecord) -> Relation:
        return Relation(
            id=record.id,
            from_kind=record.from_kind,
            from_id=record.from_id,
            relation_type=record.relation_type,
            to_kind=record.to_kind,
            to_id=record.to_id,
        )

    @staticmethod
    def _to_index_entry(record: IndexEntryRecord) -> IndexEntry:
        return IndexEntry(
            id=record.id,
            target_kind=record.target_kind,
            target_id=record.target_id,
            index_type=record.index_type,
            text_view=record.text_view,
            text_view_name=record.text_view_name or "default",
            provider_name=record.provider_name,
            provider_version=record.provider_version,
        )

    @staticmethod
    def _to_evidence_reference(record: SourceItemRecord) -> EvidenceReference:
        return EvidenceReference(
            source_item_id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            occurred_at=SQLiteCodecMixin._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            agent_ref=record.agent_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility=record.visibility or "private",
        )

    @staticmethod
    def _to_thread_processing_lease(record: ThreadProcessingLeaseRecord) -> ThreadProcessingLease:
        requested_at = SQLiteCodecMixin._normalize_datetime(record.requested_at)
        claimed_at = SQLiteCodecMixin._normalize_datetime(record.processing_claimed_at)
        lease_expires_at = SQLiteCodecMixin._normalize_datetime(record.processing_lease_expires_at)
        if requested_at is None or claimed_at is None or lease_expires_at is None or record.processing_claimed_by is None:
            raise ValueError(f"thread processing lease is incomplete for scope {record.scope_key}")
        return ThreadProcessingLease(
            scope_key=record.scope_key,
            use_case=record.use_case,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            visibility=record.visibility or "private",
            requested_at=requested_at,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=claimed_at,
            processing_lease_expires_at=lease_expires_at,
            collection_watermark_at=SQLiteCodecMixin._normalize_datetime(
                getattr(record, "collection_watermark_at", None)
            ),
        )

    @staticmethod
    def _to_retention_lease(record: MaintenanceStateRecord) -> RetentionLease:
        claimed_at = SQLiteCodecMixin._normalize_datetime(record.claimed_at)
        lease_expires_at = SQLiteCodecMixin._normalize_datetime(record.lease_expires_at)
        if claimed_at is None or lease_expires_at is None or record.claimed_by is None:
            raise ValueError(f"retention lease is incomplete for key {record.key}")
        return RetentionLease(
            key=record.key,
            claimed_by=record.claimed_by,
            claimed_at=claimed_at,
            lease_expires_at=lease_expires_at,
        )

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _dump_memory_envelope(envelope: MemoryEnvelope | None) -> str | None:
        if envelope is None:
            return None
        return json.dumps(asdict(envelope))

    @staticmethod
    def _load_memory_envelope(value: str | None) -> MemoryEnvelope | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        scope_payload = payload.get("scope")
        derivation_payload = payload.get("derivation")
        subjects_payload = payload.get("subjects")
        if (
            payload.get("schema_id") != MEMORY_ENVELOPE_SCHEMA_ID
            or payload.get("schema_version") != MEMORY_ENVELOPE_SCHEMA_VERSION
            or not isinstance(scope_payload, dict)
            or not isinstance(derivation_payload, dict)
            or not isinstance(subjects_payload, list)
        ):
            return None
        kind = SQLiteCodecMixin._load_envelope_enum(payload.get("kind"), allowed=MEMORY_ENVELOPE_KINDS)
        confidence = SQLiteCodecMixin._load_envelope_enum(payload.get("confidence"), allowed=MEMORY_ENVELOPE_CONFIDENCES)
        producer_kind = SQLiteCodecMixin._load_envelope_enum(
            derivation_payload.get("producer_kind"),
            allowed=MEMORY_ENVELOPE_PRODUCER_KINDS,
        )
        producer_schema_id = SQLiteCodecMixin._load_required_envelope_string(
            derivation_payload.get("producer_schema_id")
        )
        producer_schema_version = SQLiteCodecMixin._load_required_envelope_string(
            derivation_payload.get("producer_schema_version")
        )
        if kind is None or confidence is None or producer_kind is None:
            return None
        if producer_schema_id is None or producer_schema_version is None:
            return None
        subjects: list[MemorySubjectAnchor] = []
        for subject_payload in subjects_payload:
            if not isinstance(subject_payload, dict):
                return None
            subject_kind = SQLiteCodecMixin._load_envelope_enum(
                subject_payload.get("kind"),
                allowed=MEMORY_SUBJECT_ANCHOR_KINDS,
            )
            subject_value = SQLiteCodecMixin._load_required_envelope_string(subject_payload.get("value"))
            if subject_kind is None or subject_value is None:
                return None
            subjects.append(MemorySubjectAnchor(kind=subject_kind, value=subject_value))
        container_ref, container_ref_valid = SQLiteCodecMixin._load_optional_envelope_string(
            scope_payload,
            "container_ref",
        )
        thread_ref, thread_ref_valid = SQLiteCodecMixin._load_optional_envelope_string(
            scope_payload,
            "thread_ref",
        )
        raw_work_refs = scope_payload.get("work_refs") if isinstance(scope_payload, dict) else None
        work_refs: tuple[str, ...] = ()
        if isinstance(raw_work_refs, list):
            work_refs = tuple(str(v) for v in raw_work_refs if isinstance(v, str) and v.strip())
        # Phase 4A: optional workstream_id, tolerated absent on legacy rows.
        raw_workstream_id = scope_payload.get("workstream_id") if isinstance(scope_payload, dict) else None
        workstream_id: str | None = (
            str(raw_workstream_id)
            if isinstance(raw_workstream_id, str) and raw_workstream_id.strip()
            else None
        )
        prompt_variant, prompt_variant_valid = SQLiteCodecMixin._load_optional_envelope_string(
            derivation_payload,
            "prompt_variant",
        )
        model_role, model_role_valid = SQLiteCodecMixin._load_optional_envelope_string(
            derivation_payload,
            "model_role",
        )
        kind_basis, kind_basis_valid = SQLiteCodecMixin._load_optional_envelope_string(
            derivation_payload,
            "kind_basis",
        )
        if not all(
            (
                container_ref_valid,
                thread_ref_valid,
                prompt_variant_valid,
                model_role_valid,
                kind_basis_valid,
            )
        ):
            return None
        source_content_length = payload.get("source_content_length", 0)
        if not isinstance(source_content_length, int) or isinstance(source_content_length, bool) or source_content_length < 0:
            source_content_length = 0
        return MemoryEnvelope(
            schema_id=MEMORY_ENVELOPE_SCHEMA_ID,
            schema_version=MEMORY_ENVELOPE_SCHEMA_VERSION,
            kind=kind,
            scope=MemoryEnvelopeScope(
                container_ref=container_ref,
                thread_ref=thread_ref,
                work_refs=work_refs,
                workstream_id=workstream_id,
            ),
            derivation=MemoryEnvelopeDerivation(
                producer_kind=producer_kind,
                producer_schema_id=producer_schema_id,
                producer_schema_version=producer_schema_version,
                prompt_variant=prompt_variant,
                model_role=model_role,
                kind_basis=kind_basis,
            ),
            subjects=subjects,
            confidence=confidence,
            source_content_length=source_content_length,
        )

    @staticmethod
    def _load_envelope_enum(value: object, *, allowed: set[str]) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized or normalized not in allowed:
            return None
        return normalized

    @staticmethod
    def _load_required_envelope_string(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _load_optional_envelope_string(payload: dict[str, object], key: str) -> tuple[str | None, bool]:
        if key not in payload or payload.get(key) is None:
            return None, True
        value = payload.get(key)
        if not isinstance(value, str):
            return None, False
        normalized = value.strip()
        return normalized or None, True

    @staticmethod
    def _dumps(value: dict | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    @staticmethod
    def _loads(value: str | None) -> dict:
        if not value:
            return {}
        return json.loads(value)


_SUBJECT_TYPES = {"atomic_fact", "fact_summary"}


def extract_memory_subject(memory_object: MemoryObject) -> str | None:
    """Extract and normalize subject for the denormalized storage column.

    Returns NFKC-normalized, lowercased, stripped subject for atomic_fact
    and fact_summary types. NULL for all other types.
    """
    if memory_object.type not in _SUBJECT_TYPES:
        return None
    raw = memory_object.payload.get("subject") if memory_object.payload else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return unicodedata.normalize("NFKC", raw.strip()).lower()
