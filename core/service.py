from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from capabilities.consolidation import ConsolidationRunResult
from capabilities.workstreams import WorkstreamCapability
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
from core.vector_index_holder import VectorIndexHolder
from core.models import FlagResult, InjectableBlock, MemoryFlag, MemoryObject, QueryRuntimeContext, Relation, SourceItem, utc_now
from core.observability import IntegrationDebugLogger, QueryStats
from core.visibility import is_visible
from providers.embedding.base import EmbeddingProvider
from retrieval.base import RetrievalProvider
from semantic.base import SemanticPlugin
from semantic.agent_conversation_memory_embedding import build_memory_match_text
from storage.base import QueueHealthSnapshot, RetentionLeaseLostError, RetentionRunStats, StorageProvider, ThreadProcessingLease
from storage.vector_index import VectorIndex
from core.text import normalize_for_index as _normalize_for_index


def _build_workstream_capability(storage) -> WorkstreamCapability | None:
    """Wire a SQLite-backed WorkstreamCapability when the storage exposes a
    session factory. Returns ``None`` for non-SQLite/in-memory backends so
    Phase 4A is purely additive — the capability never breaks existing code.
    """
    session_factory = getattr(storage, "_session_factory", None)
    if session_factory is None:
        return None
    try:
        from storage.sqlite_workstream import SQLiteWorkstreamStore
    except Exception:
        return None
    return WorkstreamCapability(SQLiteWorkstreamStore(session_factory))


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
        index_holder: VectorIndexHolder | None = None,
        type_registry: TypeRegistry | None = None,
        routing_overrides=None,
        query_stats: QueryStats | None = None,
        metrics_store=None,
        metrics_retention_days: int = 0,
        injection_policy=None,
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
        self._index_holder = index_holder or VectorIndexHolder()
        self._type_registry = type_registry
        self._vector_embedder = VectorEmbedder(storage, embedding_provider, index_holder=self._index_holder)
        self._query_stats = query_stats
        self._workstream_capability = _build_workstream_capability(storage)
        self._query_executor = QueryExecutor(
            storage, retrieval, semantic_plugins, default_use_case,
            type_registry=type_registry,
            routing_overrides=routing_overrides,
            query_stats=query_stats,
            injection_policy=injection_policy,
        )
        self._thread_rebuilder = ThreadRebuilder(
            storage=storage,
            semantic_plugins=semantic_plugins,
            vector_embedder=self._vector_embedder,
            observability=self._observability,
            persist_fn=self._persist_process_result,
            supersede_fn=self.supersede_memory_object,
            consolidation_fn=self._run_targeted_fact_consolidation,
            workstream_capability=self._workstream_capability,
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
            get_item_processing_summary_fn=self.get_item_processing_summary,
            metrics_store=metrics_store,
        )
        self._consolidation_runner = ConsolidationRunner(
            storage=storage,
            semantic_plugins=semantic_plugins,
            default_use_case=default_use_case,
            observability=self._observability,
            persist_fn=self._persist_process_result,
            supersede_fn=self.supersede_memory_object,
            workstream_capability=self._workstream_capability,
            metrics_store=metrics_store,
        )
        self._logger = logging.getLogger(__name__)
        self._metrics_store = metrics_store
        self._metrics_retention_days = metrics_retention_days

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

    @property
    def _vector_index(self) -> VectorIndex | None:
        """Backward-compat property for app/main.py health/status checks."""
        return self._index_holder.index

    @property
    def workstream_capability(self) -> WorkstreamCapability | None:
        """Phase 4A (design 014): expose the workstream capability for debug
        consumers (e.g. ``/query/debug``)."""
        return self._workstream_capability

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
        # Multi-package tracking: determine packages before creating the item.
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

        # Atomic creation: source item + PPS rows in one transaction to prevent
        # the processor from claiming via the legacy path before PPS rows exist.
        try:
            self._storage.create_source_item_with_packages(
                source_item,
                active_packages,
                skip_packages=skip_packages,
            )
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

        return self._build_ingest_result(self._storage.get_source_item(source_item.id))

    def get_item_processing(self, source_item_id: str) -> ItemProcessingResult:
        return self._build_processing_result(self._storage.get_source_item(source_item_id))

    def get_item_processing_summary(self, source_item_id: str) -> ItemProcessingResult:
        return self._build_processing_summary_result(self._storage.get_source_item(source_item_id))

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
            # Record retention_run metric (fire-and-forget)
            if self._metrics_store is not None:
                try:
                    self._metrics_store.record(
                        "system", "retention_run",
                        payload={
                            "deleted_source_items": stats.deleted_source_items,
                            "deleted_memory_objects": stats.deleted_memory_objects,
                        },
                    )
                except Exception:
                    pass
            # Metrics retention cleanup
            if self._metrics_store is not None and self._metrics_retention_days > 0:
                try:
                    self._metrics_store.cleanup(self._metrics_retention_days)
                except Exception:
                    pass
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

    def process_next_source_item_summary(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
    ) -> ItemProcessingResult | None:
        return self._processor.process_next_source_item_summary(
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

    def _build_processing_summary_result(self, source_item: SourceItem) -> ItemProcessingResult:
        observability = _observability_state(source_item)
        return ItemProcessingResult(
            source_item_id=source_item.id,
            use_case=source_item.use_case,
            processing_status=source_item.processing_status,
            processing_attempts=source_item.processing_attempts,
            processing_claimed_at=source_item.processing_claimed_at,
            processing_completed_at=source_item.processing_completed_at,
            processing_error=source_item.processing_error,
            memory_object_ids=[],
            relation_ids=[],
            index_entry_ids=[],
            failure_category=observability.get("failure_category"),
            memory_object_types=list(observability.get("memory_object_types", [])),
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
        work_refs: tuple[str, ...] = (),
        visibility: str | None = None,
        runtime_context: QueryRuntimeContext | None = None,
        include_trace: bool = False,
        trigger_origin: str | None = None,
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
            work_refs=work_refs,
            visibility=visibility,
            runtime_context=runtime_context,
            include_trace=include_trace,
            trigger_origin=trigger_origin,
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

    FLAG_SUPPRESSION_THRESHOLD = 2
    FLAG_WINDOW_DAYS = 30

    def flag_memory_object(
        self,
        memory_object_id: str,
        reason: str,
        source_ref: str,
        immediate: bool = False,
    ) -> FlagResult:
        flag = MemoryFlag(
            memory_object_id=memory_object_id,
            reason=reason,
            source_ref=source_ref,
        )
        self._storage.store_memory_flag(flag)

        memory = self._storage.get_memory_object(memory_object_id)
        suppressed = memory.lifecycle == "suppressed"

        if not suppressed and memory.lifecycle == "active":
            if immediate:
                self._storage.update_memory_object_lifecycle(memory_object_id, "suppressed")
                suppressed = True
            else:
                unique_sources = self._storage.count_unique_flag_sources(
                    memory_object_id, self.FLAG_WINDOW_DAYS
                )
                if unique_sources >= self.FLAG_SUPPRESSION_THRESHOLD:
                    self._storage.update_memory_object_lifecycle(memory_object_id, "suppressed")
                    suppressed = True

        result = FlagResult(
            memory_object_id=memory_object_id,
            flag_count=self._storage.count_total_flags(memory_object_id),
            unique_sources=self._storage.count_unique_flag_sources(
                memory_object_id, self.FLAG_WINDOW_DAYS
            ),
            suppressed=suppressed,
        )
        if self._query_stats is not None:
            self._query_stats.record_flag(suppressed=result.suppressed)
        return result

    def record_memory_feedback(
        self,
        memory_object_id: str,
        rating: str,
        reason: str | None,
        query_context: str | None,
        query_audit_log_id: str | None,
        rater_ref: str | None,
        thread_ref: str | None = None,
        container_ref: str | None = None,
    ) -> str:
        """Record a relevance feedback judgment for an injected memory.

        Returns the feedback record id. Always succeeds — 200 even for deleted memories.
        """
        return self._storage.record_memory_feedback(
            memory_object_id=memory_object_id,
            rating=rating,
            reason=reason,
            query_context=query_context,
            query_audit_log_id=query_audit_log_id,
            rater_ref=rater_ref,
            thread_ref=thread_ref,
            container_ref=container_ref,
        )

    # ── W3 explicit memory-write service methods ─────────────────────
    #
    # Thin wrappers on top of the storage-layer methods added in the W3
    # storage-methods PR. Purpose here: build MemoryObject envelopes for
    # remember/supersede, record origin provenance, and (later) hook into
    # the query-stats surface if we decide to count explicit writes.
    #
    # Invariant 1 (docs/context/lessons.md): none of these methods update
    # retrieval ranking or accessibility state. confidence is stored via
    # payload; the storage layer never reads it for ranking.

    # The five type ids the initial version accepts. Extraction pipeline
    # already writes to these types via the same table; we validate at the
    # tool boundary so the agent doesn't invent new memory types by accident.
    _W3_ALLOWED_MEMORY_TYPES = frozenset(
        {"decision", "investigation_outcome", "constraint_memory", "operational_fact", "note"}
    )

    def _w3_memory_text_view_name(self, memory_type: str) -> str:
        """Text-view name for an explicit-write memory's lexical index entry.

        Mirrors semantic/common.py::_memory_text_view_name so that
        agent-explicit memories index into the same text views the
        extraction pipeline uses. Retrieval treats explicit-write and
        inferred memories identically once indexed.
        """
        if memory_type == "decision":
            return "memory_object.decision_context"
        if memory_type == "investigation_outcome":
            return "memory_object.investigation_context"
        return "memory_object.summary"

    def _index_explicit_write(
        self,
        memory_object_id: str,
        memory_type: str,
        text: str,
    ) -> None:
        """Emit lexical + (best-effort) vector index entries for an
        explicit-write memory so it is retrievable immediately.

        The extraction pipeline goes through _persist_process_result which
        writes index entries alongside the memory; explicit writes take a
        different code path (single storage.create_memory_object call), so
        we index here explicitly. Without this the memory exists but is
        invisible to /query — see scenario 5 wiring.
        """
        # Local import — avoid circular / heavy import at module load.
        from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
        from semantic.common import normalize_for_index  # type: ignore

        text_view = normalize_for_index(text)
        self._storage.create_index_entry(
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object_id,
                index_type="lexical",
                text_view=text_view,
                text_view_name=self._w3_memory_text_view_name(memory_type),
            )
        )
        # Vector index is best-effort. If no embedding provider is
        # configured, skip silently — the memory remains retrievable via
        # lexical search which is enough for scenario 5's assertion.
        try:
            from semantic.agent_conversation_memory_embedding import (  # type: ignore
                VECTOR_EMBEDDING_PROVIDER_NAME,
                VECTOR_EMBEDDING_PROVIDER_VERSION,
            )
            self._storage.create_index_entry(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_object_id,
                    index_type=VECTOR_INDEX_TYPE,
                    text_view=text,
                    text_view_name=f"{self._w3_memory_text_view_name(memory_type)}.embedding",
                    provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                    provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
                )
            )
        except Exception:  # noqa: BLE001 -- vector index is best-effort
            logger.debug("W3 explicit write: skipping vector index entry", exc_info=True)

    def remember_memory(
        self,
        *,
        text: str,
        type: str,
        confidence: float | None = None,
        evidence: list[str] | None = None,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        thread_ref: str | None = None,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> MemoryObject:
        """pallium_remember: agent explicitly stores a durable fact.

        Creates a memory with origin='agent_explicit' and the given
        provenance. Confidence is stored in payload for audit only —
        Invariant 1 forbids ranking from using it directly.
        """
        if type not in self._W3_ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"type must be one of {sorted(self._W3_ALLOWED_MEMORY_TYPES)}, got {type!r}"
            )
        payload: dict[str, object] = {"statement": text}
        if confidence is not None:
            payload["confidence"] = confidence
        if evidence:
            payload["evidence"] = list(evidence)
        payload["source"] = "agent_explicit_write"

        memory = MemoryObject(
            type=type,
            schema_id=f"{type}.agent_explicit.v1",
            schema_version="1",
            payload=payload,
            container_ref=container_ref,
            actor_ref=actor_ref,
        )
        self._storage.create_memory_object(memory)
        self._storage.mark_memory_origin(
            memory.id,
            origin="agent_explicit",
            origin_session_id=origin_session_id,
            origin_agent_id=origin_agent_id,
        )
        # Emit index entries so the memory is retrievable via /query
        # right away, without waiting for a downstream re-indexer. Match
        # the shape the extraction pipeline uses.
        self._index_explicit_write(memory.id, type, text)
        return memory

    def correct_memory(
        self,
        memory_object_id: str,
        *,
        corrected_text: str,
        reason: str,
    ) -> bool:
        """pallium_correct: in-place fix. Returns True on success.

        Raises SupersessionConflictError (surfaces as 409) if the memory
        is not currently active — corrections must target the head of the
        supersession chain, not a stale entry.
        """
        existing = self._storage.get_memory_object(memory_object_id)
        new_payload = dict(existing.payload)
        new_payload["statement"] = corrected_text
        new_payload["source"] = "agent_explicit_correction"
        self._storage.correct_memory_payload(
            memory_object_id,
            new_payload=new_payload,
            correction_reason=reason,
        )
        return True

    def supersede_memory(
        self,
        *,
        new_text: str,
        supersedes_id: str,
        reason: str | None = None,
        type: str | None = None,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        thread_ref: str | None = None,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> tuple[str, str]:
        """pallium_supersede: explicit chain — new memory replaces old.

        Returns (old_id, new_id). If `type` / `container_ref` / `actor_ref`
        are None, defaults are taken from the old memory. Raises
        SupersessionConflictError if the old memory is not currently
        active (surfaces as 409 to the MCP caller).
        """
        old = self._storage.get_memory_object(supersedes_id)
        resolved_type = type or old.type
        if resolved_type not in self._W3_ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"type must be one of {sorted(self._W3_ALLOWED_MEMORY_TYPES)}, got {resolved_type!r}"
            )
        payload: dict[str, object] = {
            "statement": new_text,
            "source": "agent_explicit_supersede",
            "supersedes_id": supersedes_id,
        }
        new_memory = MemoryObject(
            type=resolved_type,
            schema_id=f"{resolved_type}.agent_explicit.v1",
            schema_version="1",
            payload=payload,
            container_ref=container_ref or old.container_ref,
            actor_ref=actor_ref or old.actor_ref,
        )
        self._storage.create_memory_object(new_memory)
        self._storage.mark_memory_origin(
            new_memory.id,
            origin="agent_explicit",
            origin_session_id=origin_session_id,
            origin_agent_id=origin_agent_id,
        )
        # Same as remember_memory: index the new memory so it's
        # retrievable immediately. The old memory's index entries remain
        # in place; retrieval filters superseded rows out via lifecycle.
        self._index_explicit_write(new_memory.id, resolved_type, new_text)
        self._storage.link_supersession(
            supersedes_id,
            new_memory.id,
            correction_reason=reason,
        )
        return (supersedes_id, new_memory.id)

    def forget_memory(self, memory_object_id: str, *, reason: str) -> bool:
        """pallium_forget: soft-delete with tombstone.

        Idempotent: returns True on first call, False if the memory was
        already soft-deleted.
        """
        return self._storage.soft_delete_memory(memory_object_id, reason=reason)

    def record_procedure_outcome(
        self,
        *,
        procedure_id: str,
        outcome: str,
        evidence: list[str] | None = None,
        note: str | None = None,
        container_ref: str | None = None,
        actor_ref: str | None = None,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> bool:
        """pallium_record_outcome: attach an outcome to an operational-fact
        procedure. Feeds W4 success/failure counters.

        v1 stores the outcome as an agent_explicit `note` memory linked
        by payload; a proper counter-update path lands with W4.
        """
        if outcome not in ("success", "failure", "inconclusive"):
            raise ValueError(
                f"outcome must be success | failure | inconclusive, got {outcome!r}"
            )
        # Confirm the procedure exists so we don't accept dangling references.
        try:
            self._storage.get_memory_object(procedure_id)
        except KeyError as exc:
            raise KeyError(f"procedure_id {procedure_id!r} not found") from exc

        payload: dict[str, object] = {
            "statement": f"Procedure outcome: {outcome}",
            "procedure_id": procedure_id,
            "outcome": outcome,
            "source": "agent_explicit_outcome",
        }
        if evidence:
            payload["evidence"] = list(evidence)
        if note:
            payload["note"] = note

        outcome_memory = MemoryObject(
            type="note",
            schema_id="note.agent_explicit.outcome.v1",
            schema_version="1",
            payload=payload,
            container_ref=container_ref,
            actor_ref=actor_ref,
        )
        self._storage.create_memory_object(outcome_memory)
        self._storage.mark_memory_origin(
            outcome_memory.id,
            origin="agent_explicit",
            origin_session_id=origin_session_id,
            origin_agent_id=origin_agent_id,
        )
        return True

    # ── /W3 explicit memory-write service methods ────────────────────

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
        ranked_candidates: list[dict] | None = None,
        injection_method: str | None = None,
        trigger_origin: str | None = None,
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
                "memory_object_id": getattr(matched, 'memory_object_id', None) if matched else block.memory_object_id,
                "title_preview": (block.title or "")[:120],
            })

        # Serialize top-20 candidate scores for diagnostics
        candidate_scores_json = None
        # Phase 4A: per-candidate workstream_id lookup (one DB read).
        candidate_ws_map: dict[str, str] = {}
        if ranked_candidates is not None:
            try:
                memory_object_ids = [
                    getattr(c["item"], "memory_object_id", None)
                    for c in ranked_candidates[:20]
                ]
                memory_object_ids = [m for m in memory_object_ids if m]
                if memory_object_ids and self._workstream_capability is not None:
                    store = getattr(self._workstream_capability, "_store", None)
                    batch_lookup = getattr(store, "get_memory_workstream_ids", None)
                    if callable(batch_lookup):
                        candidate_ws_map = batch_lookup(memory_object_ids)
                    else:
                        for mid in memory_object_ids:
                            looked_up = self._workstream_capability.lookup_memory(mid)
                            if looked_up:
                                candidate_ws_map[mid] = looked_up
            except Exception:
                self._logger.warning("candidate workstream lookup failed", exc_info=True)
                candidate_ws_map = {}
        if ranked_candidates is not None:
            try:
                injectable_result_ids = {block.result_id for block in injectable_blocks}
                snapshot = []
                for candidate in ranked_candidates[:20]:
                    item = candidate["item"]
                    result_id = getattr(item, "result_id", None)
                    mid = getattr(item, "memory_object_id", None)
                    snapshot.append({
                        "memory_object_id": mid,
                        "memory_type": getattr(item, "type", None),
                        "routing_score": candidate.get("routing_score"),
                        "lexical_score": candidate.get("lexical_score"),
                        "vector_score": candidate.get("vector_score"),
                        "routing_rank": candidate.get("routing_rank"),
                        "layer": candidate.get("layer"),
                        "support_grade": candidate.get("support_grade"),
                        "suppression_reason_code": candidate.get("suppression_reason_code"),
                        "excluded_reason_code": candidate.get("excluded_reason_code"),
                        "post_routing_drop_reason": candidate.get("post_routing_drop_reason"),
                        "injected": result_id in injectable_result_ids if result_id else False,
                        "workstream_id": candidate_ws_map.get(mid) if mid else None,
                        # Phase 0.5: result `score` (the field the abstention
                        # policy gates on, matching injected_blocks_json[*].score)
                        # and retrieval_source. See
                        # docs/specs/2026-06-27-injection-policy-abstention.md
                        "score": getattr(item, "score", None),
                        "retrieval_source": getattr(item, "retrieval_source", None),
                    })
                candidate_scores_json = json.dumps(snapshot)
            except Exception:
                self._logger.warning("candidate scores serialization failed", exc_info=True)
                candidate_scores_json = None

        # Phase 4A: row-level query workstream_id from the most-recent
        # source_item_workstreams row for the query's source_item_id.
        query_workstream_id: str | None = None
        if source_item_id and self._workstream_capability is not None:
            try:
                query_workstream_id = self._workstream_capability.lookup_query_source_item(source_item_id)
            except Exception:
                self._logger.warning("query workstream_id lookup failed", exc_info=True)
                query_workstream_id = None

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
            "candidate_scores_json": candidate_scores_json,
            "injection_method": injection_method,
            "query_workstream_id": query_workstream_id,
            # Phase 4 (2026-06-27): which deterministic trigger fired this
            # query, if any. None for legacy / proactive default queries.
            "trigger_origin": trigger_origin,
        }
        self._storage.write_query_audit_row(row)
        # Phase 5: write one memory_usage_audit row per injected block
        # alongside the audit-log row. The populator (Phase 5b) fills in
        # referenced_in_next_turn / reference_kind asynchronously. See
        # docs/specs/2026-06-27-injection-policy-abstention.md.
        try:
            self._storage.write_memory_usage_audit_rows(
                query_audit_log_id=row["id"],
                injected_blocks=blocks_json_list,
                container_ref=container_ref,
                thread_ref=thread_ref,
                trigger_origin=trigger_origin,
            )
        except Exception:
            self._logger.warning(
                "memory_usage_audit write failed", exc_info=True
            )

    def list_memory_usage_audit(self, query_audit_log_id: str) -> list[dict]:
        """Phase 5: list usage-audit rows for a given query.

        Used by the integration-side populator (Phase 5b) to discover
        the rows it must update after observing the agent's next turns.
        """
        return self._storage.list_memory_usage_audit_rows(query_audit_log_id)

    def list_pending_memory_usage_audit_by_thread(
        self,
        thread_ref: str,
        *,
        limit: int = 20,
    ) -> list[dict]:
        """Phase 5b: list pending (populated_at IS NULL) usage-audit rows
        for a thread, newest first. Hard-capped at 100 rows server-side.

        Used by the Stop-hook populator which doesn't know individual
        query_audit_log_ids — it only knows which thread it's running
        in. See docs/specs/2026-06-27-injection-policy-abstention.md
        (Phase 5b).
        """
        return self._storage.list_pending_memory_usage_audit_rows_by_thread(
            thread_ref, limit=limit,
        )

    def update_memory_usage_audit(
        self,
        *,
        audit_row_id: str,
        referenced_in_next_turn: bool,
        reference_kind: str | None,
        observation_window_turns: int | None,
    ) -> bool:
        """Phase 5: idempotent update of a single usage-audit row.

        Returns True if the row was updated, False if it was already
        populated (no-op) or did not exist.
        """
        return self._storage.update_memory_usage_audit_row(
            audit_row_id=audit_row_id,
            referenced_in_next_turn=referenced_in_next_turn,
            reference_kind=reference_kind,
            observation_window_turns=observation_window_turns,
        )

    def _persist_process_result(self, result: ProcessResult) -> None:
        for memory_object in result.memory_objects:
            self._storage.create_memory_object(memory_object)
        for relation in result.relations:
            self._storage.create_relation(relation)
        for index_entry in result.index_entries:
            self._storage.create_index_entry(index_entry)

    def get_memory_expand(
        self, memory_object_id: str, *, container_ref: str | None = None, query_actor_ref: str | None = None,
    ) -> tuple[dict | None, list[SourceItem], str | None]:
        """Return structured payload, source items, and a Phase-5b match-text view.

        The ``match_text`` (3rd tuple element) is the per-type text the
        usage-audit populator should compare against the assistant's
        response. It uses the same per-type field map as the embedding
        text view but without the 40-char floor or ``[type]`` prefix
        (see ``semantic.agent_conversation_memory_embedding``
        ``build_memory_match_text``). None when the type has no per-type
        text view or no fields are populated.
        """
        memory_object = self._storage.get_memory_object(memory_object_id)
        effective_container = container_ref or memory_object.container_ref
        if container_ref and memory_object.visibility != "global" and memory_object.container_ref != container_ref:
            raise KeyError(memory_object_id)
        refs = self._storage.get_evidence_for_memory_object(memory_object_id)
        items: list[SourceItem] = []
        for ref in refs:
            try:
                item = self._storage.get_source_item(ref.source_item_id)
            except KeyError:
                continue
            effective_actor_ref = query_actor_ref or memory_object.actor_ref
            if is_visible(item.visibility, item.container_ref, effective_container, item.actor_ref, query_actor_ref=effective_actor_ref):
                items.append(item)
        match_text = build_memory_match_text(memory_object) or None
        return memory_object.payload, items, match_text
