from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from core.contracts import ProcessResult
from core.models import Annotation, EvidenceReference, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem
from core.visibility import VisibilityContext, VisibilityExclusion


@dataclass(frozen=True)
class IndexSearchHit:
    target_kind: str
    target_id: str
    index_entry_id: str
    index_type: str
    text_view_name: str
    score: int
    matched_tokens: tuple[str, ...]
    provider_name: str | None = None
    provider_version: str | None = None


@dataclass(frozen=True)
class IndexSearchResult:
    hits: list[IndexSearchHit]
    visibility_exclusions: tuple[VisibilityExclusion, ...] = ()
    total_hits_before_visibility: int = 0
    total_hits_after_visibility: int = 0


@dataclass(frozen=True)
class ThreadProcessingScope:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str
    visibility_context: VisibilityContext | None


@dataclass(frozen=True)
class ThreadProcessingLease:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str
    visibility_context: VisibilityContext | None
    requested_at: datetime
    processing_claimed_by: str
    processing_claimed_at: datetime
    processing_lease_expires_at: datetime

    def as_scope(self) -> ThreadProcessingScope:
        return ThreadProcessingScope(
            scope_key=self.scope_key,
            use_case=self.use_case,
            container_ref=self.container_ref,
            thread_ref=self.thread_ref,
            visibility_context=self.visibility_context,
        )


@dataclass(frozen=True)
class QueueHealthReasonCount:
    reason: str
    count: int


@dataclass(frozen=True)
class LeasedSourceItemInfo:
    source_item_id: str
    use_case: str | None
    processing_claimed_by: str | None
    processing_claimed_at: datetime | None
    processing_lease_expires_at: datetime | None


@dataclass(frozen=True)
class LeasedThreadScopeInfo:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str
    visibility_context: VisibilityContext | None
    processing_claimed_by: str | None
    processing_claimed_at: datetime | None
    processing_lease_expires_at: datetime | None


@dataclass(frozen=True)
class RecentFailureInfo:
    source_item_id: str
    use_case: str | None
    failure_category: str | None
    processing_error: str | None
    processing_attempts: int
    processing_completed_at: datetime | None


@dataclass(frozen=True)
class QueueHealthSnapshot:
    status_counts: dict[str, int]
    oldest_pending_age_seconds: int | None
    pending_without_use_case_count: int
    unclaimable_pending_counts: tuple[QueueHealthReasonCount, ...]
    leased_source_items: tuple[LeasedSourceItemInfo, ...]
    leased_thread_scopes: tuple[LeasedThreadScopeInfo, ...]
    recent_failures: tuple[RecentFailureInfo, ...]


class StorageProvider(ABC):
    @abstractmethod
    def find_source_item(self, source_type: str, source_id: str) -> SourceItem | None:
        raise NotImplementedError

    @abstractmethod
    def create_source_item(self, source_item: SourceItem) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_source_item(self, source_item_id: str) -> SourceItem:
        raise NotImplementedError

    @abstractmethod
    def claim_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> SourceItem | None:
        raise NotImplementedError

    @abstractmethod
    def complete_source_item_processing(self, source_item_id: str, *, completed_at: datetime | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def fail_source_item_processing(
        self,
        source_item_id: str,
        *,
        error: str,
        next_attempt_at: datetime | None,
        final: bool,
        metadata_updates: dict[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def commit_processed_source_item(
        self,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def claim_thread_processing_scope(
        self,
        *,
        scope: ThreadProcessingScope,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        raise NotImplementedError

    @abstractmethod
    def claim_next_thread_processing_scope(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        raise NotImplementedError

    @abstractmethod
    def complete_thread_processing_scope(
        self,
        *,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_annotation(self, annotation: Annotation) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_source_items_for_thread(self, container_ref: str, thread_ref: str) -> list[SourceItem]:
        raise NotImplementedError

    @abstractmethod
    def get_annotation(self, annotation_id: str) -> Annotation:
        raise NotImplementedError

    @abstractmethod
    def list_annotations_for_source_item(self, source_item_id: str) -> list[Annotation]:
        raise NotImplementedError

    @abstractmethod
    def create_memory_object(self, memory_object: MemoryObject) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_memory_object(self, memory_object_id: str) -> MemoryObject:
        raise NotImplementedError

    @abstractmethod
    def update_memory_object_lifecycle(self, memory_object_id: str, lifecycle: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None) -> list[MemoryObject]:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects_for_source_item(self, source_item_id: str) -> list[MemoryObject]:
        raise NotImplementedError

    @abstractmethod
    def create_relation(self, relation: Relation) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        raise NotImplementedError

    @abstractmethod
    def create_index_entry(self, index_entry: IndexEntry) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        raise NotImplementedError

    @abstractmethod
    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility_contexts: tuple[VisibilityContext, ...] | None = None,
        include_visibility_trace: bool = False,
    ) -> IndexSearchResult:
        raise NotImplementedError

    @abstractmethod
    def get_evidence_for_memory_object(self, memory_object_id: str) -> list[EvidenceReference]:
        raise NotImplementedError

    @abstractmethod
    def get_queue_health_snapshot(
        self,
        *,
        now: datetime,
        max_attempts: int,
        known_use_cases: tuple[str, ...],
        scoped_use_cases: tuple[str, ...],
        recent_failure_limit: int = 10,
    ) -> QueueHealthSnapshot:
        raise NotImplementedError
