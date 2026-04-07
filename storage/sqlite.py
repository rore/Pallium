from __future__ import annotations

import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from core.contracts import ProcessResult
from core.models import EvidenceReference, IndexEntry, MemoryObject, Relation, SourceItem
from core.turn_inference import ThreadStats
from storage.base import StorageProvider
from storage.sqlite_codec import SQLiteCodecMixin
from storage.sqlite_codec import extract_memory_subject
from storage.sqlite_queue import SQLiteQueueMixin
from storage.sqlite_retention import SQLiteRetentionMixin
from storage.sqlite_schema import (
    Base,
    IndexEntryRecord,
    MaintenanceStateRecord,
    MemoryObjectRecord,
    RelationRecord,
    SQLiteSchemaMixin,
    SourceItemRecord,
    ThreadProcessingLeaseRecord,
    insert_lexical_fts_row,
)
from storage.sqlite_search import SQLiteSearchMixin


class SQLiteStorageProvider(
    SQLiteSearchMixin,
    SQLiteQueueMixin,
    SQLiteRetentionMixin,
    SQLiteSchemaMixin,
    SQLiteCodecMixin,
    StorageProvider,
):
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, class_=Session)
        self._initialize_schema()

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
        record = SourceItemRecord(
            id=source_item.id,
            source_type=source_item.source_type,
            source_id=source_item.source_id,
            content_type=source_item.content_type,
            content=source_item.content,
            metadata_json=self._dumps(source_item.metadata),
            occurred_at=source_item.occurred_at,
            actor_ref=source_item.actor_ref,
            agent_ref=source_item.agent_ref,
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
            visibility=source_item.visibility,
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

    def get_thread_stats(self, thread_ref: str, *, exclude_item_id: str | None = None) -> ThreadStats:
        with self._session_factory() as session:
            query = select(
                func.count(SourceItemRecord.id),
                func.max(SourceItemRecord.created_at),
            ).where(SourceItemRecord.thread_ref == thread_ref)
            if exclude_item_id is not None:
                query = query.where(SourceItemRecord.id != exclude_item_id)
            row = session.execute(query).one()
            return ThreadStats(item_count=row[0], latest_created_at=row[1])

    def create_memory_object(self, memory_object: MemoryObject) -> None:
        record = MemoryObjectRecord(
            id=memory_object.id,
            type=memory_object.type,
            schema_id=memory_object.schema_id,
            schema_version=memory_object.schema_version,
            payload_json=self._dumps(memory_object.payload) or "{}",
            envelope_json=self._dump_memory_envelope(memory_object.envelope),
            lifecycle=memory_object.lifecycle,
            visibility=memory_object.visibility,
            container_ref=memory_object.container_ref,
            actor_ref=memory_object.actor_ref,
            freshness_at=self._normalize_datetime(memory_object.freshness_at) or memory_object.created_at,
            subject=extract_memory_subject(memory_object),
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

    def refresh_memory_object_freshness(self, memory_object_id: str):
        with self._session_factory.begin() as session:
            return self._refresh_memory_object_freshness_in_session(session, memory_object_id)

    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None, container_ref: str | None = None, subject_in: list[str] | None = None) -> list[MemoryObject]:
        with self._session_factory() as session:
            statement = select(MemoryObjectRecord)
            if memory_types:
                statement = statement.where(MemoryObjectRecord.type.in_(memory_types))
            if lifecycle is not None:
                statement = statement.where(MemoryObjectRecord.lifecycle == lifecycle)
            if container_ref is not None:
                statement = statement.where(MemoryObjectRecord.container_ref == container_ref)
            if subject_in is not None:
                statement = statement.where(MemoryObjectRecord.subject.in_(subject_in))
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

    def list_memory_objects_for_source_items(self, source_item_ids: list[str]) -> dict[str, list[MemoryObject]]:
        if not source_item_ids:
            return {}
        with self._session_factory() as session:
            relation_records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id.in_(source_item_ids),
                    RelationRecord.from_kind == "memory_object",
                )
            ).all()
            source_to_memory_ids: dict[str, list[str]] = {}
            all_memory_ids: set[str] = set()
            for rel in relation_records:
                source_to_memory_ids.setdefault(rel.to_id, []).append(rel.from_id)
                all_memory_ids.add(rel.from_id)
            if not all_memory_ids:
                return {sid: [] for sid in source_item_ids}
            memory_records = session.scalars(
                select(MemoryObjectRecord).where(MemoryObjectRecord.id.in_(list(all_memory_ids)))
            ).all()
            memory_by_id = {record.id: self._to_memory_object(record) for record in memory_records}
        result: dict[str, list[MemoryObject]] = {}
        for sid in source_item_ids:
            result[sid] = [memory_by_id[mid] for mid in source_to_memory_ids.get(sid, []) if mid in memory_by_id]
        return result

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
            if relation.from_kind == "memory_object":
                session.flush()
                self._refresh_memory_object_freshness_in_session(session, relation.from_id)

    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                )
            ).all()
        return [self._to_relation(record) for record in records]

    def _resolve_container_ref_in_session(
        self, session, target_kind: str, target_id: str,
    ) -> str | None:
        """Resolve container_ref for an index target within an existing session."""
        if target_kind == "source_item":
            record = session.get(SourceItemRecord, target_id)
            return record.container_ref if record else None
        if target_kind == "memory_object":
            record = session.get(MemoryObjectRecord, target_id)
            if record is None:
                return None
            if record.container_ref is not None:
                return record.container_ref
            # Fallback: envelope_json → scope.container_ref
            if record.envelope_json:
                try:
                    envelope = json.loads(record.envelope_json)
                    return envelope.get("scope", {}).get("container_ref")
                except (json.JSONDecodeError, TypeError):
                    return None
            return None
        return None

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
            if index_entry.index_type == "lexical":
                container_ref = self._resolve_container_ref_in_session(
                    session, index_entry.target_kind, index_entry.target_id,
                )
                insert_lexical_fts_row(
                    session,
                    index_entry_id=index_entry.id,
                    target_kind=index_entry.target_kind,
                    target_id=index_entry.target_id,
                    text_view=index_entry.text_view,
                    text_view_name=index_entry.text_view_name,
                    container_ref=container_ref,
                )

    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                )
            ).all()
        return [self._to_index_entry(record) for record in records]

    def get_index_entry(self, index_entry_id: str) -> IndexEntry:
        with self._session_factory() as session:
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            return self._to_index_entry(record)

    def find_index_entry(self, target_kind, target_id, index_type, text_view_name):
        with self._session_factory() as session:
            row = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                    IndexEntryRecord.index_type == index_type,
                    IndexEntryRecord.text_view_name == text_view_name,
                )
            ).first()
            return self._to_index_entry(row) if row else None

    def list_index_entries_by_type(self, index_type: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == index_type)
            ).all()
        return [self._to_index_entry(record) for record in records]

    def count_index_entries_by_type(self, index_type: str) -> int:
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count()).select_from(IndexEntryRecord).where(
                    IndexEntryRecord.index_type == index_type
                )
            )
        return count or 0

    def update_index_entry_provider(self, index_entry_id: str, provider_name: str, provider_version: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            record.provider_name = provider_name
            record.provider_version = provider_version

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

    def _after_commit_processed_source_item_persist(
        self,
        session: Session,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        return None
