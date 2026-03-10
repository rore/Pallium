from __future__ import annotations

import json
import re
from datetime import timezone

from sqlalchemy import Column, DateTime, String, Text, create_engine, select, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from core.models import Annotation, EvidenceReference, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem
from storage.base import IndexSearchHit, StorageProvider


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
    }
    _MEMORY_OBJECT_MIGRATIONS = {
        "lifecycle": "ALTER TABLE memory_objects ADD COLUMN lifecycle VARCHAR DEFAULT 'active'",
    }

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, class_=Session)
        Base.metadata.create_all(self._engine)
        self._ensure_source_item_columns()
        self._ensure_memory_object_columns()

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
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            session_ref=source_item.session_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
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
                select(SourceItemRecord).where(
                    SourceItemRecord.container_ref == container_ref,
                    SourceItemRecord.thread_ref == thread_ref,
                )
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
        record = MemoryObjectRecord(
            id=memory_object.id,
            type=memory_object.type,
            schema_id=memory_object.schema_id,
            schema_version=memory_object.schema_version,
            payload_json=self._dumps(memory_object.payload) or "{}",
            lifecycle=memory_object.lifecycle,
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

    def search_index_entries(self, tokens: list[str], limit: int, filters: QueryFilters | None = None) -> list[IndexSearchHit]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == "lexical")
            ).all()
        hits: list[IndexSearchHit] = []
        unique_tokens = set(tokens)
        for record in records:
            if not self._matches_filters(record.target_kind, record.target_id, filters):
                continue
            text_tokens = set(TOKEN_PATTERN.findall(record.text_view.lower()))
            score = len(unique_tokens.intersection(text_tokens))
            if score > 0:
                hits.append(
                    IndexSearchHit(
                        target_kind=record.target_kind,
                        target_id=record.target_id,
                        score=score,
                    )
                )
        hits.sort(key=lambda item: (item.score, 1 if item.target_kind == "memory_object" else 0), reverse=True)
        return hits[:limit]

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

    @staticmethod
    def _to_source_item(record: SourceItemRecord) -> SourceItem:
        occurred_at = record.occurred_at
        if occurred_at is not None and occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        return SourceItem(
            id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            content_type=record.content_type,
            content=record.content,
            metadata=SQLiteStorageProvider._loads(record.metadata_json),
            occurred_at=occurred_at,
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            created_at=record.created_at,
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
            created_at=record.created_at,
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
            created_at=record.created_at,
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
        )

    @staticmethod
    def _to_evidence_reference(record: SourceItemRecord) -> EvidenceReference:
        occurred_at = record.occurred_at
        if occurred_at is not None and occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        return EvidenceReference(
            source_item_id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            occurred_at=occurred_at,
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
        )

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

