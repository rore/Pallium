from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from core.contracts import MemoryRetentionPolicy, ProcessResult
from core.models import Annotation, EvidenceReference, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem
from core.turn_inference import ThreadStats
from core.visibility import VisibilityExclusion


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
    visibility: str = "private"


@dataclass(frozen=True)
class ThreadProcessingLease:
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str
    visibility: str = "private"
    requested_at: datetime | None = None
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None

    def as_scope(self) -> ThreadProcessingScope:
        return ThreadProcessingScope(
            scope_key=self.scope_key,
            use_case=self.use_case,
            container_ref=self.container_ref,
            thread_ref=self.thread_ref,
            visibility=self.visibility,
        )


@dataclass(frozen=True)
class RetentionLease:
    key: str
    claimed_by: str
    claimed_at: datetime
    lease_expires_at: datetime


class RetentionLeaseLostError(RuntimeError):
    pass


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
    visibility: str = "private"
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None


@dataclass(frozen=True)
class RecentFailureInfo:
    source_item_id: str
    use_case: str | None
    failure_category: str | None
    processing_error: str | None
    processing_attempts: int
    processing_completed_at: datetime | None


@dataclass(frozen=True)
class RetentionRunStats:
    deleted_source_items: int = 0
    deleted_memory_objects: int = 0
    deleted_relations: int = 0
    deleted_index_entries: int = 0
    stripped_debug_metadata: int = 0
    skipped_protected_source_items: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "deleted_source_items": self.deleted_source_items,
            "deleted_memory_objects": self.deleted_memory_objects,
            "deleted_relations": self.deleted_relations,
            "deleted_index_entries": self.deleted_index_entries,
            "stripped_debug_metadata": self.stripped_debug_metadata,
            "skipped_protected_source_items": self.skipped_protected_source_items,
        }


@dataclass(frozen=True)
class RetentionHealthSnapshot:
    enabled: bool
    last_run_started_at: datetime | None
    last_run_completed_at: datetime | None
    last_deleted_source_items: int = 0
    last_deleted_memory_objects: int = 0
    last_deleted_relations: int = 0
    last_deleted_index_entries: int = 0
    last_stripped_debug_metadata: int = 0
    last_skipped_protected_source_items: int = 0


@dataclass(frozen=True)
class QueueHealthSnapshot:
    status_counts: dict[str, int]
    oldest_pending_age_seconds: int | None
    pending_without_use_case_count: int
    unclaimable_pending_counts: tuple[QueueHealthReasonCount, ...]
    leased_source_items: tuple[LeasedSourceItemInfo, ...]
    leased_thread_scopes: tuple[LeasedThreadScopeInfo, ...]
    recent_failures: tuple[RecentFailureInfo, ...]
    retention: RetentionHealthSnapshot


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
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> list[tuple[str, str]]:
        """Commit a processed source item result, resolving supersession hints atomically.

        Returns the resolved supersession pairs (for observability).
        """
        raise NotImplementedError

    @abstractmethod
    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str]]:
        """Commit a process result, resolving supersession hints atomically.

        If supersession_pairs is provided, those are applied directly in addition to
        any pairs resolved from result.supersession_hints.

        Returns the resolved supersession pairs (for observability).
        """
        raise NotImplementedError

    @abstractmethod
    def commit_process_result_and_complete_scope(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
    ) -> bool:
        """Atomically commit a process result and complete the thread processing scope.

        Returns True if there are pending items after completion (new requests arrived
        during processing), False otherwise.
        """
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
    def claim_retention_lease(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RetentionLease | None:
        raise NotImplementedError

    @abstractmethod
    def renew_retention_lease(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RetentionLease | None:
        raise NotImplementedError

    @abstractmethod
    def complete_retention_pass(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None,
        stats: RetentionRunStats,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fail_retention_pass(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def run_retention_pass(
        self,
        *,
        now: datetime,
        batch_size: int,
        lease: RetentionLease | None = None,
        lease_seconds: int | None = None,
        lease_now: datetime | None = None,
        retention_policy: MemoryRetentionPolicy | None = None,
    ) -> RetentionRunStats:
        raise NotImplementedError

    @abstractmethod
    def create_annotation(self, annotation: Annotation) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_source_items_for_thread(self, container_ref: str, thread_ref: str) -> list[SourceItem]:
        raise NotImplementedError

    @abstractmethod
    def get_thread_stats(self, thread_ref: str, *, exclude_item_id: str | None = None) -> ThreadStats:
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
    def refresh_memory_object_freshness(self, memory_object_id: str) -> datetime | None:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None) -> list[MemoryObject]:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects_for_source_item(self, source_item_id: str) -> list[MemoryObject]:
        raise NotImplementedError

    def list_memory_objects_for_source_items(self, source_item_ids: list[str]) -> dict[str, list[MemoryObject]]:
        """Batch variant: returns {source_item_id: [MemoryObject, ...]} for all given IDs.

        Default implementation calls the per-item method in a loop.
        Backends may override with a single-query implementation.
        """
        result: dict[str, list[MemoryObject]] = {}
        for sid in source_item_ids:
            result[sid] = self.list_memory_objects_for_source_item(sid)
        return result

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
    def get_index_entry(self, index_entry_id: str) -> IndexEntry:
        """Get a single index entry by ID. Used by VectorRetrievalProvider to hydrate hits."""
        raise NotImplementedError

    @abstractmethod
    def find_index_entry(
        self, target_kind: str, target_id: str, index_type: str, text_view_name: str
    ) -> IndexEntry | None:
        """Find an existing index entry by target+type+view. Returns None if not found."""
        raise NotImplementedError

    @abstractmethod
    def list_index_entries_by_type(self, index_type: str) -> list[IndexEntry]:
        """List all index entries of a given type (e.g., 'vector')."""
        raise NotImplementedError

    @abstractmethod
    def count_index_entries_by_type(self, index_type: str) -> int:
        """Count index entries of a given type."""
        raise NotImplementedError

    @abstractmethod
    def update_index_entry_provider(self, index_entry_id: str, provider_name: str, provider_version: str) -> None:
        """Update the provider metadata on an index entry (used after embedding)."""
        raise NotImplementedError

    @abstractmethod
    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        query_container_ref: str | None = None,
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
        retention_enabled: bool,
        recent_failure_limit: int = 10,
    ) -> QueueHealthSnapshot:
        raise NotImplementedError
