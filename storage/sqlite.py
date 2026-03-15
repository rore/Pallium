from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from core.contracts import ProcessResult
from core.models import Annotation, EvidenceReference, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem, new_id, utc_now
from core.visibility import VisibilityContext, VisibilityExclusion, visibility_context_is_visible
from storage.base import (
    IndexSearchHit,
    IndexSearchResult,
    LeasedSourceItemInfo,
    LeasedThreadScopeInfo,
    QueueHealthReasonCount,
    QueueHealthSnapshot,
    RecentFailureInfo,
    StorageProvider,
    ThreadProcessingLease,
    ThreadProcessingScope,
)


Base = declarative_base()
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class SourceItemRecord(Base):
    __tablename__ = "source_items"

    id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    actor_ref = Column(String, nullable=True)
    role = Column(String, nullable=True)
    container_ref = Column(String, nullable=True)
    thread_ref = Column(String, nullable=True)
    session_ref = Column(String, nullable=True)
    source_ref = Column(String, nullable=True)
    artifact_kind = Column(String, nullable=True)
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    use_case = Column(String, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")
    processing_attempts = Column(Integer, nullable=False, default=0)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_error = Column(Text, nullable=True)
    processing_next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class AnnotationRecord(Base):
    __tablename__ = "annotations"

    id = Column(String, primary_key=True)
    source_item_id = Column(String, nullable=False)
    type = Column(String, nullable=False)
    schema_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MemoryObjectRecord(Base):
    __tablename__ = "memory_objects"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    schema_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    lifecycle = Column(String, nullable=False, default="active")
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RelationRecord(Base):
    __tablename__ = "relations"

    id = Column(String, primary_key=True)
    from_kind = Column(String, nullable=False)
    from_id = Column(String, nullable=False)
    relation_type = Column(String, nullable=False)
    to_kind = Column(String, nullable=False)
    to_id = Column(String, nullable=False)


class IndexEntryRecord(Base):
    __tablename__ = "index_entries"

    id = Column(String, primary_key=True)
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    index_type = Column(String, nullable=False)
    text_view = Column(Text, nullable=False)
    text_view_name = Column(String, nullable=True)
    provider_name = Column(String, nullable=True)
    provider_version = Column(String, nullable=True)


class ThreadProcessingLeaseRecord(Base):
    __tablename__ = "thread_processing_leases"

    scope_key = Column(String, primary_key=True)
    use_case = Column(String, nullable=False)
    container_ref = Column(String, nullable=False)
    thread_ref = Column(String, nullable=False)
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=True)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SQLiteStorageProvider(StorageProvider):
    _SOURCE_ITEM_MIGRATIONS = {
        "occurred_at": "ALTER TABLE source_items ADD COLUMN occurred_at DATETIME",
        "actor_ref": "ALTER TABLE source_items ADD COLUMN actor_ref VARCHAR",
        "role": "ALTER TABLE source_items ADD COLUMN role VARCHAR",
        "container_ref": "ALTER TABLE source_items ADD COLUMN container_ref VARCHAR",
        "thread_ref": "ALTER TABLE source_items ADD COLUMN thread_ref VARCHAR",
        "session_ref": "ALTER TABLE source_items ADD COLUMN session_ref VARCHAR",
        "source_ref": "ALTER TABLE source_items ADD COLUMN source_ref VARCHAR",
        "artifact_kind": "ALTER TABLE source_items ADD COLUMN artifact_kind VARCHAR",
        "visibility_kind": "ALTER TABLE source_items ADD COLUMN visibility_kind VARCHAR",
        "visibility_id": "ALTER TABLE source_items ADD COLUMN visibility_id VARCHAR",
        "use_case": "ALTER TABLE source_items ADD COLUMN use_case VARCHAR",
        "processing_status": "ALTER TABLE source_items ADD COLUMN processing_status VARCHAR DEFAULT 'pending'",
        "processing_attempts": "ALTER TABLE source_items ADD COLUMN processing_attempts INTEGER DEFAULT 0",
        "processing_claimed_by": "ALTER TABLE source_items ADD COLUMN processing_claimed_by VARCHAR",
        "processing_claimed_at": "ALTER TABLE source_items ADD COLUMN processing_claimed_at DATETIME",
        "processing_lease_expires_at": "ALTER TABLE source_items ADD COLUMN processing_lease_expires_at DATETIME",
        "processing_completed_at": "ALTER TABLE source_items ADD COLUMN processing_completed_at DATETIME",
        "processing_error": "ALTER TABLE source_items ADD COLUMN processing_error TEXT",
        "processing_next_attempt_at": "ALTER TABLE source_items ADD COLUMN processing_next_attempt_at DATETIME",
    }
    _MEMORY_OBJECT_MIGRATIONS = {
        "lifecycle": "ALTER TABLE memory_objects ADD COLUMN lifecycle VARCHAR DEFAULT 'active'",
        "visibility_kind": "ALTER TABLE memory_objects ADD COLUMN visibility_kind VARCHAR",
        "visibility_id": "ALTER TABLE memory_objects ADD COLUMN visibility_id VARCHAR",
    }
    _INDEX_ENTRY_MIGRATIONS = {
        "text_view_name": "ALTER TABLE index_entries ADD COLUMN text_view_name VARCHAR",
        "provider_name": "ALTER TABLE index_entries ADD COLUMN provider_name VARCHAR",
        "provider_version": "ALTER TABLE index_entries ADD COLUMN provider_version VARCHAR",
    }

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, class_=Session)
        Base.metadata.create_all(self._engine)
        self._ensure_source_item_columns()
        self._ensure_memory_object_columns()
        self._ensure_index_entry_columns()

    def find_source_item(self, source_type: str, source_id: str) -> SourceItem | None:
        with self._session_factory() as session:
            record = session.scalar(
                select(SourceItemRecord).where(
                    SourceItemRecord.source_type == source_type,
                    SourceItemRecord.source_id == source_id,
                )
            )
            if record is None:
                return None
            return self._to_source_item(record)

    def create_source_item(self, source_item: SourceItem) -> None:
        visibility_kind, visibility_id = self._split_visibility_context(source_item.visibility_context)
        record = SourceItemRecord(
            id=source_item.id,
            source_type=source_item.source_type,
            source_id=source_item.source_id,
            content_type=source_item.content_type,
            content=source_item.content,
            metadata_json=self._dumps(source_item.metadata),
            occurred_at=source_item.occurred_at,
            actor_ref=source_item.actor_ref,
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            session_ref=source_item.session_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
            visibility_kind=visibility_kind,
            visibility_id=visibility_id,
            use_case=source_item.use_case,
            processing_status=source_item.processing_status,
            processing_attempts=source_item.processing_attempts,
            processing_claimed_by=source_item.processing_claimed_by,
            processing_claimed_at=source_item.processing_claimed_at,
            processing_lease_expires_at=source_item.processing_lease_expires_at,
            processing_completed_at=source_item.processing_completed_at,
            processing_error=source_item.processing_error,
            processing_next_attempt_at=source_item.processing_next_attempt_at,
            created_at=source_item.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_source_item(self, source_item_id: str) -> SourceItem:
        with self._session_factory() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            return self._to_source_item(record)

    def claim_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> SourceItem | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE source_items
            SET processing_status = 'processing',
                processing_attempts = COALESCE(processing_attempts, 0) + 1,
                processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                processing_next_attempt_at = NULL
            WHERE id = (
                SELECT id
                FROM source_items
                WHERE use_case IS NOT NULL
                  AND (
                    (processing_status = 'pending'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND (processing_next_attempt_at IS NULL OR processing_next_attempt_at <= :claimed_at))
                    OR (processing_status = 'failed'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND processing_next_attempt_at IS NOT NULL
                        AND processing_next_attempt_at <= :claimed_at)
                    OR (processing_status = 'processing'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND processing_lease_expires_at IS NOT NULL
                        AND processing_lease_expires_at <= :claimed_at)
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT 1
            )
            RETURNING id
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                    "max_attempts": max_attempts,
                },
            ).first()
            if row is None:
                return None
            record = session.get(SourceItemRecord, row[0])
            if record is None:
                return None
            return self._to_source_item(record)

    def complete_source_item_processing(self, source_item_id: str, *, completed_at: datetime | None = None) -> None:
        finished_at = completed_at or utc_now()
        with self._session_factory.begin() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            record.processing_status = "completed"
            record.processing_completed_at = finished_at
            record.processing_error = None
            record.processing_lease_expires_at = None
            record.processing_next_attempt_at = None

    def fail_source_item_processing(
        self,
        source_item_id: str,
        *,
        error: str,
        next_attempt_at: datetime | None,
        final: bool,
        metadata_updates: dict[str, object] | None = None,
    ) -> None:
        finished_at = utc_now()
        with self._session_factory.begin() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            if metadata_updates:
                existing_metadata = self._loads(record.metadata_json)
                existing_metadata.update(metadata_updates)
                record.metadata_json = self._dumps(existing_metadata)
            record.processing_status = "failed" if final else "pending"
            record.processing_error = error
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.processing_completed_at = finished_at if final else None
            record.processing_next_attempt_at = next_attempt_at
    def commit_processed_source_item(
        self,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        finished_at = completed_at or utc_now()
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            self._apply_supersession_pairs_in_session(session, supersession_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            if thread_rebuild_scope is not None:
                self._upsert_thread_processing_scope_in_session(
                    session,
                    scope=thread_rebuild_scope,
                    requested_at=finished_at,
                )
            self._after_commit_processed_source_item_persist(
                session,
                source_item_id=source_item_id,
                result=result,
                supersession_pairs=supersession_pairs,
            )
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            record.processing_status = "completed"
            record.processing_completed_at = finished_at
            record.processing_error = None
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.processing_next_attempt_at = None

    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            self._apply_supersession_pairs_in_session(session, supersession_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
    def claim_thread_processing_scope(
        self,
        *,
        scope: ThreadProcessingScope,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE thread_processing_leases
            SET processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                updated_at = :claimed_at
            WHERE scope_key = :scope_key
              AND requested_at IS NOT NULL
              AND (processing_lease_expires_at IS NULL OR processing_lease_expires_at <= :claimed_at)
            RETURNING scope_key
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "scope_key": scope.scope_key,
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                },
            ).first()
            if row is None:
                return None
            record = session.get(ThreadProcessingLeaseRecord, row[0])
            if record is None:
                return None
            return self._to_thread_processing_lease(record)

    def claim_next_thread_processing_scope(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE thread_processing_leases
            SET processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                updated_at = :claimed_at
            WHERE scope_key = (
                SELECT scope_key
                FROM thread_processing_leases
                WHERE requested_at IS NOT NULL
                  AND (processing_lease_expires_at IS NULL OR processing_lease_expires_at <= :claimed_at)
                ORDER BY requested_at ASC, created_at ASC, scope_key ASC
                LIMIT 1
            )
            RETURNING scope_key
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                },
            ).first()
            if row is None:
                return None
            record = session.get(ThreadProcessingLeaseRecord, row[0])
            if record is None:
                return None
            return self._to_thread_processing_lease(record)

    def complete_thread_processing_scope(
        self,
        *,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
    ) -> bool:
        finished_at = completed_at or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        with self._session_factory.begin() as session:
            record = session.get(ThreadProcessingLeaseRecord, scope_key)
            if record is None:
                raise KeyError(scope_key)
            record_claimed_at = self._normalize_datetime(record.processing_claimed_at)
            if record.processing_claimed_by != worker_id or record_claimed_at != normalized_claimed_at:
                return record.requested_at is not None
            requested_at = self._normalize_datetime(record.requested_at)
            pending_after = requested_at is not None and requested_at > normalized_claimed_at
            if not pending_after:
                record.requested_at = None
            record.processing_completed_at = finished_at
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.updated_at = finished_at
            return pending_after

    def list_source_items_for_thread(self, container_ref: str, thread_ref: str) -> list[SourceItem]:
        with self._session_factory() as session:
            records = session.scalars(
                select(SourceItemRecord)
                .where(
                    SourceItemRecord.container_ref == container_ref,
                    SourceItemRecord.thread_ref == thread_ref,
                )
                .order_by(SourceItemRecord.created_at.asc(), SourceItemRecord.id.asc())
            ).all()
        return [self._to_source_item(record) for record in records]

    def create_annotation(self, annotation: Annotation) -> None:
        record = AnnotationRecord(
            id=annotation.id,
            source_item_id=annotation.source_item_id,
            type=annotation.type,
            schema_id=annotation.schema_id,
            schema_version=annotation.schema_version,
            payload_json=self._dumps(annotation.payload) or "{}",
            created_at=annotation.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_annotation(self, annotation_id: str) -> Annotation:
        with self._session_factory() as session:
            record = session.get(AnnotationRecord, annotation_id)
            if record is None:
                raise KeyError(annotation_id)
            return self._to_annotation(record)

    def list_annotations_for_source_item(self, source_item_id: str) -> list[Annotation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(AnnotationRecord).where(AnnotationRecord.source_item_id == source_item_id)
            ).all()
        return [self._to_annotation(record) for record in records]

    def create_memory_object(self, memory_object: MemoryObject) -> None:
        visibility_kind, visibility_id = self._split_visibility_context(memory_object.visibility_context)
        record = MemoryObjectRecord(
            id=memory_object.id,
            type=memory_object.type,
            schema_id=memory_object.schema_id,
            schema_version=memory_object.schema_version,
            payload_json=self._dumps(memory_object.payload) or "{}",
            lifecycle=memory_object.lifecycle,
            visibility_kind=visibility_kind,
            visibility_id=visibility_id,
            created_at=memory_object.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_memory_object(self, memory_object_id: str) -> MemoryObject:
        with self._session_factory() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            return self._to_memory_object(record)

    def update_memory_object_lifecycle(self, memory_object_id: str, lifecycle: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            record.lifecycle = lifecycle

    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None) -> list[MemoryObject]:
        with self._session_factory() as session:
            statement = select(MemoryObjectRecord)
            if memory_types:
                statement = statement.where(MemoryObjectRecord.type.in_(memory_types))
            if lifecycle is not None:
                statement = statement.where(MemoryObjectRecord.lifecycle == lifecycle)
            records = session.scalars(statement).all()
        return [self._to_memory_object(record) for record in records]

    def list_memory_objects_for_source_item(self, source_item_id: str) -> list[MemoryObject]:
        with self._session_factory() as session:
            relation_records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                    RelationRecord.from_kind == "memory_object",
                )
            ).all()
            memory_object_ids = [record.from_id for record in relation_records]
            if not memory_object_ids:
                return []
            records = session.scalars(
                select(MemoryObjectRecord).where(MemoryObjectRecord.id.in_(memory_object_ids))
            ).all()
        return [self._to_memory_object(record) for record in records]

    def create_relation(self, relation: Relation) -> None:
        record = RelationRecord(
            id=relation.id,
            from_kind=relation.from_kind,
            from_id=relation.from_id,
            relation_type=relation.relation_type,
            to_kind=relation.to_kind,
            to_id=relation.to_id,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                )
            ).all()
        return [self._to_relation(record) for record in records]

    def create_index_entry(self, index_entry: IndexEntry) -> None:
        record = IndexEntryRecord(
            id=index_entry.id,
            target_kind=index_entry.target_kind,
            target_id=index_entry.target_id,
            index_type=index_entry.index_type,
            text_view=index_entry.text_view,
            text_view_name=index_entry.text_view_name,
            provider_name=index_entry.provider_name,
            provider_version=index_entry.provider_version,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                )
            ).all()
        return [self._to_index_entry(record) for record in records]

    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility_contexts: tuple[VisibilityContext, ...] | None = None,
        include_visibility_trace: bool = False,
    ) -> IndexSearchResult:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == "lexical")
            ).all()
        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0
        for record in records:
            if not self._matches_filters(record.target_kind, record.target_id, filters):
                continue
            text_tokens = set(TOKEN_PATTERN.findall(record.text_view.lower()))
            matched_tokens = tuple(sorted(unique_tokens.intersection(text_tokens)))
            score = len(matched_tokens)
            if score == 0:
                continue
            total_hits_before_visibility += 1
            visibility_context = self._target_visibility_context(record.target_kind, record.target_id)
            if not visibility_context_is_visible(visibility_context, visibility_contexts):
                if include_visibility_trace and visibility_contexts is not None:
                    reason = (
                        "candidate_visibility_context_missing"
                        if visibility_context is None
                        else "query_visibility_context_excludes_candidate"
                    )
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue
            total_hits_after_visibility += 1
            hits.append(
                IndexSearchHit(
                    target_kind=record.target_kind,
                    target_id=record.target_id,
                    index_entry_id=record.id,
                    index_type=record.index_type,
                    text_view_name=record.text_view_name or "default",
                    score=score,
                    matched_tokens=matched_tokens,
                    provider_name=record.provider_name,
                    provider_version=record.provider_version,
                )
            )
        hits.sort(key=lambda item: (item.score, 1 if item.target_kind == "memory_object" else 0), reverse=True)
        exclusions = tuple(
            VisibilityExclusion(reason=reason, count=count)
            for reason, count in sorted(exclusion_counts.items())
        )
        return IndexSearchResult(
            hits=hits[:limit],
            visibility_exclusions=exclusions,
            total_hits_before_visibility=total_hits_before_visibility,
            total_hits_after_visibility=total_hits_after_visibility,
        )

    def get_evidence_for_memory_object(self, memory_object_id: str) -> list[EvidenceReference]:
        with self._session_factory() as session:
            relations = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.from_kind == "memory_object",
                    RelationRecord.from_id == memory_object_id,
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                )
            ).all()
            source_ids = [relation.to_id for relation in relations]
            if not source_ids:
                return []
            records = session.scalars(
                select(SourceItemRecord).where(SourceItemRecord.id.in_(source_ids))
            ).all()
        return [self._to_evidence_reference(record) for record in records]

    def get_queue_health_snapshot(
        self,
        *,
        now: datetime,
        max_attempts: int,
        known_use_cases: tuple[str, ...],
        scoped_use_cases: tuple[str, ...],
        recent_failure_limit: int = 10,
    ) -> QueueHealthSnapshot:
        normalized_now = self._normalize_datetime(now) or now
        known_use_case_set = set(known_use_cases)
        scoped_use_case_set = set(scoped_use_cases)
        with self._session_factory() as session:
            source_records = session.scalars(select(SourceItemRecord)).all()
            thread_records = session.scalars(select(ThreadProcessingLeaseRecord)).all()

        status_counts: dict[str, int] = {}
        pending_without_use_case_count = 0
        unclaimable_counts: dict[str, int] = {}
        oldest_pending_created_at: datetime | None = None
        leased_source_items: list[LeasedSourceItemInfo] = []
        recent_failures: list[RecentFailureInfo] = []

        for record in source_records:
            status = record.processing_status or "pending"
            status_counts[status] = status_counts.get(status, 0) + 1
            created_at = self._normalize_datetime(record.created_at)
            if status == "pending":
                if not record.use_case:
                    pending_without_use_case_count += 1
                if created_at is not None and (oldest_pending_created_at is None or created_at < oldest_pending_created_at):
                    oldest_pending_created_at = created_at
                reason = self._classify_unclaimable_pending_reason(
                    record,
                    now=normalized_now,
                    max_attempts=max_attempts,
                    known_use_cases=known_use_case_set,
                    scoped_use_cases=scoped_use_case_set,
                )
                if reason is not None:
                    unclaimable_counts[reason] = unclaimable_counts.get(reason, 0) + 1
            lease_expires_at = self._normalize_datetime(record.processing_lease_expires_at)
            if status == "processing" and lease_expires_at is not None and lease_expires_at > normalized_now:
                leased_source_items.append(
                    LeasedSourceItemInfo(
                        source_item_id=record.id,
                        use_case=record.use_case,
                        processing_claimed_by=record.processing_claimed_by,
                        processing_claimed_at=self._normalize_datetime(record.processing_claimed_at),
                        processing_lease_expires_at=lease_expires_at,
                    )
                )
            if status == "failed":
                observability_state = self._observability_state_from_metadata(record.metadata_json)
                recent_failures.append(
                    RecentFailureInfo(
                        source_item_id=record.id,
                        use_case=record.use_case,
                        failure_category=(
                            str(observability_state.get("failure_category"))
                            if observability_state.get("failure_category") is not None
                            else None
                        ),
                        processing_error=record.processing_error,
                        processing_attempts=record.processing_attempts or 0,
                        processing_completed_at=self._normalize_datetime(record.processing_completed_at),
                    )
                )

        leased_thread_scopes = [
            LeasedThreadScopeInfo(
                scope_key=record.scope_key,
                use_case=record.use_case,
                container_ref=record.container_ref,
                thread_ref=record.thread_ref,
                visibility_context=self._build_visibility_context(record.visibility_kind, record.visibility_id),
                processing_claimed_by=record.processing_claimed_by,
                processing_claimed_at=self._normalize_datetime(record.processing_claimed_at),
                processing_lease_expires_at=self._normalize_datetime(record.processing_lease_expires_at),
            )
            for record in thread_records
            if record.processing_claimed_by is not None
            and (self._normalize_datetime(record.processing_lease_expires_at) or normalized_now) > normalized_now
        ]
        recent_failures.sort(
            key=lambda item: (item.processing_completed_at or datetime.min.replace(tzinfo=timezone.utc), item.source_item_id),
            reverse=True,
        )
        oldest_pending_age_seconds = None
        if oldest_pending_created_at is not None:
            oldest_pending_age_seconds = max(0, int((normalized_now - oldest_pending_created_at).total_seconds()))
        return QueueHealthSnapshot(
            status_counts=dict(sorted(status_counts.items())),
            oldest_pending_age_seconds=oldest_pending_age_seconds,
            pending_without_use_case_count=pending_without_use_case_count,
            unclaimable_pending_counts=tuple(
                QueueHealthReasonCount(reason=reason, count=count)
                for reason, count in sorted(unclaimable_counts.items())
            ),
            leased_source_items=tuple(
                sorted(
                    leased_source_items,
                    key=lambda item: (
                        item.processing_claimed_at or datetime.min.replace(tzinfo=timezone.utc),
                        item.source_item_id,
                    ),
                )
            ),
            leased_thread_scopes=tuple(
                sorted(
                    leased_thread_scopes,
                    key=lambda item: (
                        item.processing_claimed_at or datetime.min.replace(tzinfo=timezone.utc),
                        item.scope_key,
                    ),
                )
            ),
            recent_failures=tuple(recent_failures[:recent_failure_limit]),
        )

    def _persist_process_result_in_session(self, session: Session, result: ProcessResult) -> None:
        for annotation in result.annotations:
            session.add(
                AnnotationRecord(
                    id=annotation.id,
                    source_item_id=annotation.source_item_id,
                    type=annotation.type,
                    schema_id=annotation.schema_id,
                    schema_version=annotation.schema_version,
                    payload_json=self._dumps(annotation.payload) or "{}",
                    created_at=annotation.created_at,
                )
            )
        for memory_object in result.memory_objects:
            visibility_kind, visibility_id = self._split_visibility_context(memory_object.visibility_context)
            session.add(
                MemoryObjectRecord(
                    id=memory_object.id,
                    type=memory_object.type,
                    schema_id=memory_object.schema_id,
                    schema_version=memory_object.schema_version,
                    payload_json=self._dumps(memory_object.payload) or "{}",
                    lifecycle=memory_object.lifecycle,
                    visibility_kind=visibility_kind,
                    visibility_id=visibility_id,
                    created_at=memory_object.created_at,
                )
            )
        for relation in result.relations:
            session.add(
                RelationRecord(
                    id=relation.id,
                    from_kind=relation.from_kind,
                    from_id=relation.from_id,
                    relation_type=relation.relation_type,
                    to_kind=relation.to_kind,
                    to_id=relation.to_id,
                )
            )
        for index_entry in result.index_entries:
            session.add(
                IndexEntryRecord(
                    id=index_entry.id,
                    target_kind=index_entry.target_kind,
                    target_id=index_entry.target_id,
                    index_type=index_entry.index_type,
                    text_view=index_entry.text_view,
                    text_view_name=index_entry.text_view_name,
                    provider_name=index_entry.provider_name,
                    provider_version=index_entry.provider_version,
                )
            )

    def _apply_supersession_pairs_in_session(self, session: Session, supersession_pairs: list[tuple[str, str]]) -> None:
        for superseded_id, replacement_id in supersession_pairs:
            superseded = session.get(MemoryObjectRecord, superseded_id)
            replacement = session.get(MemoryObjectRecord, replacement_id)
            if superseded is None or replacement is None:
                raise KeyError(superseded_id if superseded is None else replacement_id)
            if superseded.type != replacement.type:
                raise ValueError("Supersession requires matching memory object types")
            if superseded.lifecycle == "superseded":
                continue
            superseded.lifecycle = "superseded"
            session.add(
                RelationRecord(
                    id=new_id(),
                    from_kind="memory_object",
                    from_id=replacement_id,
                    relation_type="supersedes",
                    to_kind="memory_object",
                    to_id=superseded_id,
                )
            )

    def _after_commit_processed_source_item_persist(
        self,
        session: Session,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        return None

    def _apply_source_item_metadata_updates_in_session(
        self,
        session: Session,
        metadata_updates: dict[str, dict[str, object]],
    ) -> None:
        for source_item_id, metadata_patch in metadata_updates.items():
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            existing_metadata = self._loads(record.metadata_json)
            if not isinstance(existing_metadata, dict):
                existing_metadata = {}
            for key, value in metadata_patch.items():
                if isinstance(value, dict) and isinstance(existing_metadata.get(key), dict):
                    merged_value = dict(existing_metadata[key])
                    merged_value.update(value)
                    existing_metadata[key] = merged_value
                else:
                    existing_metadata[key] = value
            record.metadata_json = self._dumps(existing_metadata)

    def _upsert_thread_processing_scope_in_session(
        self,
        session: Session,
        *,
        scope: ThreadProcessingScope,
        requested_at: datetime,
    ) -> None:
        record = session.get(ThreadProcessingLeaseRecord, scope.scope_key)
        if record is None:
            session.add(
                ThreadProcessingLeaseRecord(
                    scope_key=scope.scope_key,
                    use_case=scope.use_case,
                    container_ref=scope.container_ref,
                    thread_ref=scope.thread_ref,
                    visibility_kind=self._split_visibility_context(scope.visibility_context)[0],
                    visibility_id=self._split_visibility_context(scope.visibility_context)[1],
                    requested_at=requested_at,
                    processing_claimed_by=None,
                    processing_claimed_at=None,
                    processing_lease_expires_at=None,
                    processing_completed_at=None,
                    created_at=requested_at,
                    updated_at=requested_at,
                )
            )
            return
        existing_requested_at = self._normalize_datetime(record.requested_at)
        if existing_requested_at is None or requested_at > existing_requested_at:
            record.requested_at = requested_at
        record.updated_at = requested_at

    def _matches_filters(self, target_kind: str, target_id: str, filters: QueryFilters | None) -> bool:
        if target_kind == "memory_object":
            memory_object = self.get_memory_object(target_id)
            if memory_object.lifecycle != "active":
                return False
        if filters is None:
            return True
        if target_kind == "source_item":
            return self._source_item_matches_filters(self.get_source_item(target_id), filters)
        if target_kind == "memory_object":
            evidence = self.get_evidence_for_memory_object(target_id)
            return any(self._evidence_matches_filters(item, filters) for item in evidence)
        return True

    def _target_visibility_context(self, target_kind: str, target_id: str) -> VisibilityContext | None:
        if target_kind == "source_item":
            return self.get_source_item(target_id).visibility_context
        if target_kind == "memory_object":
            return self.get_memory_object(target_id).visibility_context
        return None

    def _source_item_matches_filters(self, source_item: SourceItem, filters: QueryFilters) -> bool:
        if filters.source_type is not None and source_item.source_type != filters.source_type:
            return False
        if filters.role is not None and source_item.role != filters.role:
            return False
        if filters.artifact_kind is not None and source_item.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and source_item.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and source_item.thread_ref != filters.thread_ref:
            return False
        if filters.session_ref is not None and source_item.session_ref != filters.session_ref:
            return False
        return True

    def _evidence_matches_filters(self, evidence: EvidenceReference, filters: QueryFilters) -> bool:
        if filters.source_type is not None and evidence.source_type != filters.source_type:
            return False
        if filters.role is not None and evidence.role != filters.role:
            return False
        if filters.artifact_kind is not None and evidence.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and evidence.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and evidence.thread_ref != filters.thread_ref:
            return False
        if filters.session_ref is not None and evidence.session_ref != filters.session_ref:
            return False
        return True

    def _ensure_source_item_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(source_items)"))
            }
            for column_name, migration_sql in self._SOURCE_ITEM_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_memory_object_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(memory_objects)"))
            }
            for column_name, migration_sql in self._MEMORY_OBJECT_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_index_entry_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(index_entries)"))
            }
            for column_name, migration_sql in self._INDEX_ENTRY_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    @staticmethod
    def _to_source_item(record: SourceItemRecord) -> SourceItem:
        return SourceItem(
            id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            content_type=record.content_type,
            content=record.content,
            metadata=SQLiteStorageProvider._loads(record.metadata_json),
            occurred_at=SQLiteStorageProvider._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            use_case=record.use_case,
            processing_status=record.processing_status or "pending",
            processing_attempts=record.processing_attempts or 0,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=SQLiteStorageProvider._normalize_datetime(record.processing_claimed_at),
            processing_lease_expires_at=SQLiteStorageProvider._normalize_datetime(record.processing_lease_expires_at),
            processing_completed_at=SQLiteStorageProvider._normalize_datetime(record.processing_completed_at),
            processing_error=record.processing_error,
            processing_next_attempt_at=SQLiteStorageProvider._normalize_datetime(record.processing_next_attempt_at),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_annotation(record: AnnotationRecord) -> Annotation:
        return Annotation(
            id=record.id,
            source_item_id=record.source_item_id,
            type=record.type,
            schema_id=record.schema_id,
            schema_version=record.schema_version,
            payload=SQLiteStorageProvider._loads(record.payload_json),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_memory_object(record: MemoryObjectRecord) -> MemoryObject:
        return MemoryObject(
            id=record.id,
            type=record.type,
            schema_id=record.schema_id,
            schema_version=record.schema_version,
            payload=SQLiteStorageProvider._loads(record.payload_json),
            lifecycle=record.lifecycle or "active",
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
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
            occurred_at=SQLiteStorageProvider._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
        )

    @staticmethod
    def _to_thread_processing_lease(record: ThreadProcessingLeaseRecord) -> ThreadProcessingLease:
        requested_at = SQLiteStorageProvider._normalize_datetime(record.requested_at)
        claimed_at = SQLiteStorageProvider._normalize_datetime(record.processing_claimed_at)
        lease_expires_at = SQLiteStorageProvider._normalize_datetime(record.processing_lease_expires_at)
        if requested_at is None or claimed_at is None or lease_expires_at is None or record.processing_claimed_by is None:
            raise ValueError(f"thread processing lease is incomplete for scope {record.scope_key}")
        return ThreadProcessingLease(
            scope_key=record.scope_key,
            use_case=record.use_case,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            requested_at=requested_at,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=claimed_at,
            processing_lease_expires_at=lease_expires_at,
        )

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _split_visibility_context(visibility_context: VisibilityContext | None) -> tuple[str | None, str | None]:
        if visibility_context is None:
            return None, None
        return visibility_context.kind, visibility_context.id

    @staticmethod
    def _build_visibility_context(kind: str | None, visibility_id: str | None) -> VisibilityContext | None:
        if not kind:
            return None
        return VisibilityContext(kind=kind, id=visibility_id)

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

    @staticmethod
    def _observability_state_from_metadata(metadata_json: str | None) -> dict[str, object]:
        metadata = SQLiteStorageProvider._loads(metadata_json)
        state = metadata.get("observability_debug")
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _classify_unclaimable_pending_reason(
        record: SourceItemRecord,
        *,
        now: datetime,
        max_attempts: int,
        known_use_cases: set[str],
        scoped_use_cases: set[str],
    ) -> str | None:
        if (record.processing_status or "pending") != "pending":
            return None
        if not record.use_case:
            return "missing_use_case"
        if (record.processing_attempts or 0) >= max_attempts:
            return "legacy_max_attempts_exhausted_pending"
        next_attempt_at = SQLiteStorageProvider._normalize_datetime(record.processing_next_attempt_at)
        if next_attempt_at is not None and next_attempt_at > now:
            return "retry_backoff_active"
        if record.use_case not in known_use_cases:
            return "unknown_use_case"
        if record.use_case in scoped_use_cases and not record.visibility_kind:
            return "missing_visibility_for_scoped_use_case"
        return None

