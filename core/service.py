from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from capabilities.consolidation import ConsolidationRunResult
from core.consolidation_runner import ConsolidationRunner
from core.contracts import IngestResult, ItemProcessingResult, MemoryRetentionPolicy, ProcessResult, QueryResult, build_source_item
from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, build_index_entry
from core.processing import (
    DEFAULT_PROCESSING_LEASE_SECONDS,
    DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ItemProcessor,
    _observability_state,
)
from core.query import QueryExecutor
from core.thread_rebuild import ThreadRebuilder, truncate_processing_error
from core.turn_inference import resolve_runtime_context
from core.type_registry import TypeRegistry
from core.vector_embed import VectorEmbedder
from core.models import InjectableBlock, QueryRuntimeContext, Relation, SourceItem, utc_now
from core.observability import IntegrationDebugLogger
from core.visibility import is_visible
from providers.embedding.base import EmbeddingProvider
from retrieval.base import RetrievalProvider
from semantic.base import SemanticPlugin
from storage.base import QueueHealthSnapshot, RetentionLeaseLostError, RetentionRunStats, StorageProvider, ThreadProcessingLease
from storage.vector_index import VectorIndex
from core.text import normalize_for_index as _normalize_for_index


class PalliumService:
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        observability: IntegrationDebugLogger | None = None,
        *,
        retention_enabled: bool = False,
        retention_lease_seconds: int = 300,
        retention_batch_size: int = 200,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: VectorIndex | None = None,
        type_registry: TypeRegistry | None = None,
        routing_overrides=None,
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._observability = observability or IntegrationDebugLogger(enabled=False)
        self._retention_enabled = retention_enabled
        self._retention_lease_seconds = retention_lease_seconds
        self._retention_batch_size = retention_batch_size
        self._embedding_provider = embedding_provider
        self._vector_index = vector_index
        self._type_registry = type_registry
        self._vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)
        self._query_executor = QueryExecutor(
            storage, retrieval, semantic_plugins, default_use_case,
            type_registry=type_registry,
            routing_overrides=routing_overrides,
        )
        self._thread_rebuilder = ThreadRebuilder(
            storage=storage,
            semantic_plugins=semantic_plugins,
            vector_embedder=self._vector_embedder,
            observability=self._observability,
            persist_fn=self._persist_process_result,
            supersede_fn=self.supersede_memory_object,
            consolidation_fn=self._run_targeted_fact_consolidation,
        )
        self._processor = ItemProcessor(
            storage=storage,
            semantic_plugins=semantic_plugins,
            default_use_case=default_use_case,
            vector_embedder=self._vector_embedder,
            thread_rebuilder=self._thread_rebuilder,
            observability=self._observability,
            persist_fn=self._persist_process_result,
            supersede_fn=self.supersede_memory_object,
            get_item_processing_fn=self.get_item_processing,
        )
        self._consolidation_runner = ConsolidationRunner(
            storage=storage,
            semantic_plugins=semantic_plugins,
            default_use_case=default_use_case,
            observability=self._observability,
            persist_fn=self._persist_process_result,
            supersede_fn=self.supersede_memory_object,
        )
        self._logger = logging.getLogger(__name__)

        merged_retention = MemoryRetentionPolicy()
        for plugin in self._semantic_plugins.values():
            plugin_policy = plugin.memory_retention_policy
            if plugin_policy is not None:
                merged_retention = MemoryRetentionPolicy(
                    durable_types=merged_retention.durable_types | plugin_policy.durable_types,
                    working_types=merged_retention.working_types | plugin_policy.working_types,
                    orphan_delete_types=merged_retention.orphan_delete_types | plugin_policy.orphan_delete_types,
                )
        self._retention_policy = merged_retention

    def ingest_item(
        self,
        source_type: str,
        source_id: str,
        content_type: str,
        content: str,
        metadata: dict | None,
        use_case: str | None,
        *,
        occurred_at=None,
        actor_ref: str | None = None,
        agent_ref: str | None = None,
        role: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        source_ref: str | None = None,
        artifact_kind: str | None = None,
        visibility: str | None = None,
    ) -> IngestResult:
        existing_source_item = self._storage.find_source_item(source_type=source_type, source_id=source_id)
        if existing_source_item is not None:
            return self._build_ingest_result(existing_source_item)

        # Resolve which package name to store on source_item for backward compat
        plugin_name = use_case or self._default_use_case
        plugin = self._semantic_plugins[plugin_name]
        processing_status = "pending"
        processing_error = None
        if plugin.requires_visibility_context and (container_ref is None or visibility is None):
            processing_status = "skipped"
            processing_error = "visibility_context_required"

        source_item = build_source_item(
            source_type=source_type,
            source_id=source_id,
            content_type=content_type,
            content=content,
            metadata=metadata,
            occurred_at=occurred_at,
            actor_ref=actor_ref,
            agent_ref=agent_ref,
            role=role,
            container_ref=container_ref,
            thread_ref=thread_ref,
            source_ref=source_ref,
            artifact_kind=artifact_kind,
            visibility=visibility,
            use_case=plugin_name,
            processing_status=processing_status,
            processing_error=processing_error,
        )
        try:
            self._storage.create_source_item(source_item)
        except IntegrityError:
            existing = self._storage.find_source_item(source_type=source_type, source_id=source_id)
            if existing is not None:
                return self._build_ingest_result(existing)
            raise
        self._storage.create_index_entry(
            build_index_entry(
                target_kind="source_item",
                target_id=source_item.id,
                index_type="lexical",
                text_view=_normalize_for_index(source_item.content),
                text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
            )
        )

        # Multi-package tracking: create per-package processing records.
        # Start with the item's assigned package, then add any packages that
        # opt into parallel processing (e.g., fact extraction).
        active_packages = [plugin_name]
        for pkg_name, pkg_plugin in self._semantic_plugins.items():
            if pkg_name == plugin_name:
                continue
            if pkg_plugin.parallel_processing:
                active_packages.append(pkg_name)
        skip_packages: list[str] = []
        for pkg_name in active_packages:
            pkg_plugin = self._semantic_plugins.get(pkg_name)
            if pkg_plugin and pkg_plugin.requires_visibility_context and (container_ref is None or visibility is None):
                skip_packages.append(pkg_name)
        self._storage.create_package_processing_records(
            source_item.id,
            active_packages,
            skip_packages=skip_packages,
        )

        return self._build_ingest_result(self._storage.get_source_item(source_item.id))

    def get_item_processing(self, source_item_id: str) -> ItemProcessingResult:
        return self._build_processing_result(self._storage.get_source_item(source_item_id))

    def get_queue_health(
        self,
        *,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ) -> QueueHealthSnapshot:
        scoped_use_cases = tuple(
            sorted(
                name
                for name, plugin in self._semantic_plugins.items()
                if plugin.requires_visibility_context
            )
        )
        return self._storage.get_queue_health_snapshot(
            now=utc_now(),
            max_attempts=max_attempts,
            known_use_cases=tuple(sorted(self._semantic_plugins.keys())),
            scoped_use_cases=scoped_use_cases,
            retention_enabled=self._retention_enabled,
        )

    def run_retention_pass(
        self,
        *,
        worker_id: str,
        now=None,
        lease_seconds: int | None = None,
        batch_size: int | None = None,
    ) -> RetentionRunStats | None:
        if not self._retention_enabled:
            return None
        claimed_at = now or utc_now()
        resolved_lease_seconds = lease_seconds or self._retention_lease_seconds
        resolved_batch_size = batch_size or self._retention_batch_size
        lease = self._storage.claim_retention_lease(
            worker_id=worker_id,
            lease_seconds=resolved_lease_seconds,
            now=claimed_at,
        )
        if lease is None:
            return None
        self._observability.emit(
            "retention_pass_started",
            worker_id=worker_id,
            maintenance_key=lease.key,
            claimed_at=lease.claimed_at,
            lease_expires_at=lease.lease_expires_at,
        )
        try:
            stats = self._storage.run_retention_pass(
                now=lease.claimed_at,
                batch_size=resolved_batch_size,
                lease=lease,
                lease_seconds=resolved_lease_seconds,
                lease_now=lease.claimed_at if now is not None else None,
                retention_policy=self._retention_policy,
            )
            completed = self._storage.complete_retention_pass(
                worker_id=worker_id,
                claimed_at=lease.claimed_at,
                completed_at=lease.claimed_at if now is not None else utc_now(),
                stats=stats,
            )
            if not completed:
                raise RetentionLeaseLostError("retention lease lost before completion")
            self._observability.emit(
                "retention_pass_completed",
                worker_id=worker_id,
                maintenance_key=lease.key,
                claimed_at=lease.claimed_at,
                stats=stats.as_dict(),
            )
            return stats
        except Exception as exc:
            released = self._storage.fail_retention_pass(worker_id=worker_id, claimed_at=lease.claimed_at)
            failure_reason = "lease_lost" if isinstance(exc, RetentionLeaseLostError) else "exception"
            error_message = "retention lease lost before completion" if isinstance(exc, RetentionLeaseLostError) else truncate_processing_error(exc)
            self._observability.emit(
                "retention_pass_failed",
                worker_id=worker_id,
                maintenance_key=lease.key,
                claimed_at=lease.claimed_at,
                error=error_message,
                failure_reason=failure_reason,
                lease_release_succeeded=released,
            )
            raise

    def process_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ) -> ItemProcessingResult | None:
        return self._processor.process_next_source_item(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )

    def process_next_thread_rebuild(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
    ) -> ThreadProcessingLease | None:
        return self._thread_rebuilder.process_next_thread_rebuild(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )

    def reconcile_vector_index(self) -> int:
        """Reconcile SQLite ↔ usearch vector index gaps. Returns count of changes."""
        return self._vector_embedder.reconcile()

    def drain_processing_queue(
        self,
        *,
        worker_id: str = "local-drain",
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
        limit: int | None = None,
    ) -> list[ItemProcessingResult]:
        return self._processor.drain_processing_queue(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            limit=limit,
        )

    # ── Internal delegation for backward compatibility with tests ───────────
    # These private methods moved to ItemProcessor / ThreadRebuilder but are
    # accessed by existing tests via service._<method>.

    _MAX_THREAD_REBUILD_ITERATIONS = ThreadRebuilder._MAX_THREAD_REBUILD_ITERATIONS

    def _process_source_item(
        self,
        source_item: SourceItem,
        *,
        max_attempts: int,
        worker_id: str | None = None,
        package_name: str | None = None,
        package_attempts: int | None = None,
    ) -> None:
        return self._processor._process_source_item(
            source_item, max_attempts=max_attempts, worker_id=worker_id,
            package_name=package_name, package_attempts=package_attempts,
        )

    def _process_thread_rebuild_lease(
        self,
        lease: ThreadProcessingLease,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        return self._thread_rebuilder._process_thread_rebuild_lease(
            lease, worker_id=worker_id, lease_seconds=lease_seconds,
        )

    def _build_ingest_result(self, source_item: SourceItem) -> IngestResult:
        processing = self._build_processing_result(source_item)
        return IngestResult(
            source_item_id=processing.source_item_id,
            memory_object_ids=processing.memory_object_ids,
            relation_ids=processing.relation_ids,
            index_entry_ids=processing.index_entry_ids,
            processing_status=processing.processing_status,
            processing_attempts=processing.processing_attempts,
            processing_error=processing.processing_error,
        )

    def _build_processing_result(self, source_item: SourceItem) -> ItemProcessingResult:
        memory_objects = self._storage.list_memory_objects_for_source_item(source_item.id)
        relations = self._storage.list_relations_for_source_item(source_item.id)
        index_entries = self._storage.list_index_entries_for_target(
            target_kind="source_item",
            target_id=source_item.id,
        )
        for memory_object in memory_objects:
            index_entries.extend(
                self._storage.list_index_entries_for_target(
                    target_kind="memory_object",
                    target_id=memory_object.id,
                )
            )
        observability = _observability_state(source_item)
        return ItemProcessingResult(
            source_item_id=source_item.id,
            use_case=source_item.use_case,
            processing_status=source_item.processing_status,
            processing_attempts=source_item.processing_attempts,
            processing_claimed_at=source_item.processing_claimed_at,
            processing_completed_at=source_item.processing_completed_at,
            processing_error=source_item.processing_error,
            memory_object_ids=[item.id for item in memory_objects],
            relation_ids=[item.id for item in relations],
            index_entry_ids=[item.id for item in index_entries],
            failure_category=observability.get("failure_category"),
            memory_object_types=list(observability.get("memory_object_types", [item.type for item in memory_objects])),
            thread_rebuild_requested=bool(observability.get("thread_rebuild_requested", False)),
            thread_rebuild_completed=bool(observability.get("thread_rebuild_completed", False)),
            produced_memory_provenance=list(observability.get("produced_memory_provenance", [])),
        )

    def query(
        self,
        text: str,
        limit: int,
        *,
        source_type: str | None = None,
        role: str | None = None,
        artifact_kind: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        actor_ref: str | None = None,
        visibility: str | None = None,
        runtime_context: QueryRuntimeContext | None = None,
        include_trace: bool = False,
    ) -> QueryResult:
        runtime_context = resolve_runtime_context(
            self._storage,
            thread_ref,
            runtime_context,
        )
        return self._query_executor.query(
            text,
            limit,
            source_type=source_type,
            role=role,
            artifact_kind=artifact_kind,
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            visibility=visibility,
            runtime_context=runtime_context,
            include_trace=include_trace,
        )

    def run_consolidation_pass(
        self,
        *,
        use_case: str | None = None,
        strategy_name: str | None = None,
        container_ref: str | None = None,
    ) -> ConsolidationRunResult | None:
        return self._consolidation_runner.run_consolidation_pass(
            use_case=use_case,
            strategy_name=strategy_name,
            container_ref=container_ref,
        )

    def supersede_memory_object(self, superseded_id: str, replacement_id: str) -> None:
        superseded = self._storage.get_memory_object(superseded_id)
        replacement = self._storage.get_memory_object(replacement_id)
        if superseded.type != replacement.type:
            raise ValueError("Supersession requires matching memory object types")
        if superseded.lifecycle == "superseded":
            return
        self._storage.update_memory_object_lifecycle(superseded_id, "superseded")
        self._storage.create_relation(
            Relation(
                from_kind="memory_object",
                from_id=replacement_id,
                relation_type="supersedes",
                to_kind="memory_object",
                to_id=superseded_id,
            )
        )

    def _run_targeted_fact_consolidation(self, use_case: str, container_ref: str, subjects: list[str]) -> None:
        """Callback for ThreadRebuilder: run fact consolidation for specific subjects."""
        self._consolidation_runner.run_targeted_consolidation(use_case, container_ref, subjects)

    def write_query_audit(
        self,
        *,
        source_item_id: str,
        source_id: str,
        thread_ref: str | None,
        container_ref: str | None,
        actor_ref: str | None,
        visibility: str | None,
        query_text: str,
        should_inject: bool,
        decision_reason: str,
        injectable_blocks: list[InjectableBlock],
        results: list,
    ) -> None:
        result_lookup = {}
        for item in results:
            rid = getattr(item, 'result_id', None)
            if rid is not None:
                result_lookup[rid] = item

        blocks_json_list = []
        for block in injectable_blocks:
            matched = result_lookup.get(block.result_id)
            blocks_json_list.append({
                "result_id": block.result_id,
                "memory_type": block.memory_type,
                "block_type": block.block_type,
                "score": getattr(matched, 'score', 0.0) if matched else 0.0,
                "retrieval_source": getattr(matched, 'retrieval_source', None) if matched else None,
                "memory_object_id": getattr(matched, 'memory_object_id', None) if matched else None,
                "title_preview": (block.title or "")[:120],
            })

        row = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc),
            "source_item_id": source_item_id,
            "source_id": source_id,
            "thread_ref": thread_ref,
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": visibility,
            "query_text": query_text,
            "should_inject": 1 if should_inject else 0,
            "decision_reason": decision_reason,
            "injected_blocks_json": json.dumps(blocks_json_list),
        }
        self._storage.write_query_audit_row(row)

    def _persist_process_result(self, result: ProcessResult) -> None:
        for memory_object in result.memory_objects:
            self._storage.create_memory_object(memory_object)
        for relation in result.relations:
            self._storage.create_relation(relation)
        for index_entry in result.index_entries:
            self._storage.create_index_entry(index_entry)

    def get_memory_evidence(
        self, memory_object_id: str, *, container_ref: str,
    ) -> list[SourceItem]:
        """Return source items linked to a memory object, with access control.

        Validates that the memory object belongs to the requested container,
        then filters individual evidence items through visibility rules.
        Raises KeyError if the memory object doesn't exist or doesn't belong
        to the requested container (404-safe: no existence confirmation).
        """
        memory_object = self._storage.get_memory_object(memory_object_id)
        if memory_object.container_ref != container_ref:
            raise KeyError(memory_object_id)
        refs = self._storage.get_evidence_for_memory_object(memory_object_id)
        items: list[SourceItem] = []
        for ref in refs:
            try:
                item = self._storage.get_source_item(ref.source_item_id)
            except KeyError:
                continue
            if is_visible(item.visibility, item.container_ref, container_ref, item.actor_ref):
                items.append(item)
        return items
