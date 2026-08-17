from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from capabilities.consolidation import ConsolidationRunResult
from capabilities.workstreams import WorkstreamCapability
from core.consolidation_runner import ConsolidationRunner
from core.contracts import IngestResult, ItemProcessingResult, MemoryRetentionPolicy, ProcessResult, QueryResult, build_source_item
from core.errors import ForgetAuthorizationError
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
from core.models import FlagResult, InjectableBlock, MemoryFlag, MemoryObject, QueryRuntimeContext, Relation, SourceItem, new_id, utc_now
from core.observability import IntegrationDebugLogger, QueryStats
from core.visibility import is_visible
from providers.embedding.base import EmbeddingProvider
from retrieval.base import RetrievalProvider
from semantic.agent_conversation_memory_embedding import build_memory_match_text
from semantic.base import SemanticPlugin
from redaction import redact_sensitive
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


def _redact_ingest_value(value, *, visited: set[int] | None = None):
    """Recursively redact string leaves in an arbitrary JSON-like value.

    Universal ingest write barrier (PR 0 step 6). Applied to
    ``content`` and every value in ``metadata`` before the SourceItem
    is constructed — closes the leak channel that let LLM assistant
    output and tool metadata carry credentials into ``source_items``
    and, via the built-off-content lexical index, into
    ``lexical_fts``.

    Rules:
    - Strings pass through :func:`semantic.redaction.redact_sensitive`
      (Tier A + Tier B).
    - Dicts / lists / tuples are walked recursively. Keys are NOT
      redacted (breaks downstream code that keys on names like
      ``command``, ``file_path``). Only values.
    - Non-string leaves (int, float, bool, None, datetime) pass through
      untouched.
    - Circular references (in-process object graphs) are broken via a
      ``visited`` set keyed by ``id(obj)``. JSON-parsed input is
      always a tree; this is defensive.
    - Deliberately preserves container types: a ``tuple`` metadata
      value stays a tuple, a ``list`` stays a list. Downstream code
      that pattern-matches on type does not observe a change from
      redaction.
    """
    if isinstance(value, str):
        return redact_sensitive(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if visited is None:
        visited = set()
    obj_id = id(value)
    if obj_id in visited:
        # Cycle in an in-process object graph — refuse to recurse.
        return "[REDACTED CYCLE]"
    visited.add(obj_id)
    try:
        if isinstance(value, dict):
            return {
                k: _redact_ingest_value(v, visited=visited)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_redact_ingest_value(v, visited=visited) for v in value]
        if isinstance(value, tuple):
            return tuple(_redact_ingest_value(v, visited=visited) for v in value)
    finally:
        visited.discard(obj_id)
    # datetime, bytes, custom classes — leave untouched. Bytes in
    # metadata would round-trip through JSON as a text encoding
    # anyway; we do not attempt to decode them here.
    return value


def _redact_query_result(result: "QueryResult") -> "QueryResult":
    """Retrieval-barrier redaction over a QueryResult.

    Runs at the boundary between the query executor and the caller.
    Redacts every text-carrying field on ``injectable_blocks`` and
    ``results`` (via ``dataclasses.replace`` since both are frozen
    dataclasses). Metadata IDs, scores, and non-text fields are
    passed through unchanged.

    This is defense-in-depth: even if a secret was persisted before
    PR 0's write barrier landed (or slipped past the LLM-response
    wrapper), it never leaves the process unredacted.
    """
    from core.models import InjectableBlock, QueryResultItem  # local import — avoid top-level cycle

    def _redact_block(block: InjectableBlock) -> InjectableBlock:
        return dataclasses.replace(
            block,
            title=redact_sensitive(block.title) if block.title else block.title,
            text=redact_sensitive(block.text) if block.text else block.text,
        )

    def _redact_item(item: QueryResultItem) -> QueryResultItem:
        # Note artifacts bypass redaction — same carveout as the
        # write barrier at ``ingest_item`` and ``get_memory_expand``.
        # A user-explicit note is preserved verbatim on the retrieval
        # surface just as it was on write. Both the source-item
        # ``artifact_kind`` and the memory ``type`` are checked
        # because a note may surface as either shape depending on the
        # retrieval path.
        if item.artifact_kind == "note" or item.type == "note":
            return item
        return dataclasses.replace(
            item,
            excerpt=redact_sensitive(item.excerpt) if item.excerpt else item.excerpt,
            payload=_redact_ingest_value(item.payload) if item.payload else item.payload,
        )

    redacted_blocks = [_redact_block(b) for b in result.injectable_blocks]
    redacted_results = [_redact_item(i) for i in result.results]
    return dataclasses.replace(
        result,
        injectable_blocks=redacted_blocks,
        results=redacted_results,
    )


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
        shadow_subtask_selector=None,
        single_user_trusted_mode: bool = True,
    ) -> None:
        self._storage = storage
        self._single_user_trusted_mode = single_user_trusted_mode
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
            shadow_subtask_selector=shadow_subtask_selector,
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

        # -----------------------------------------------------------------
        # PR 0 step 6: universal write barrier.
        #
        # Every ingest — chat, tool metadata, hook-emitted event, future
        # source_type — passes ``content`` and ``metadata`` through the
        # shared redaction helper BEFORE the SourceItem is constructed.
        # This runs regardless of role or source_type: the barrier's
        # correctness must not depend on caller discipline.
        #
        # DELIBERATE EXCEPTION: ``note`` artifacts (see
        # semantic/agent_conversation_memory_note.py) are the
        # user-explicit "remember this verbatim" surface. Redacting a
        # note silently destroys the placeholder / procedure text the
        # user asked us to preserve (e.g. a runbook containing
        # ``key=NEW_KEY`` as a substitution instruction). Notes are
        # allowed to store raw content on the user's explicit
        # instruction; the tradeoff is documented at the note
        # ingestion path.
        #
        # Consequences:
        # - ``source_items.content`` never persists a raw secret (except
        #   notes explicitly stored by the user).
        # - The lexical index built off ``source_item.content`` at
        #   line 232 below never carries a raw secret into
        #   ``lexical_fts.text_view`` (with the same note exception).
        # - Downstream semantic plugins that read metadata by key see
        #   the same dict shape (only string LEAVES are rewritten).
        #
        # The dedupe check on line 174 above already short-circuits on
        # ``find_source_item`` before we reach here; redacting a
        # duplicate is wasted work but never wrong.
        # -----------------------------------------------------------------
        is_user_note = (artifact_kind == "note")
        if not is_user_note:
            content = redact_sensitive(content) if content else content
            metadata = _redact_ingest_value(metadata) if metadata else metadata

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
        # PR 3 of operational_fact redesign (2026-07-02): the caller-
        # observability response includes candidates. Post-ingest is
        # not an operator surface; the API client reconciles
        # memory_object_ids against index_entries and needs to see
        # every row just written — including ``lifecycle="candidate"``
        # operational_fact rows. Operator surfaces (dashboard, query
        # retrieval) filter candidates via their own defaults.
        memory_objects = self._storage.list_memory_objects_for_source_item(
            source_item.id, include_candidates=True,
        )
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
        source_only: bool = False,
    ) -> QueryResult:
        runtime_context = resolve_runtime_context(
            self._storage,
            thread_ref,
            runtime_context,
        )
        result = self._query_executor.query(
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
            source_only=source_only,
        )
        # PR 0 step 8: retrieval barrier (defense in depth).
        # Even if a secret slips past the write barrier + LLM-response
        # wrapper (e.g. was persisted before PR 0, or a redaction miss),
        # it never reaches the LLM prompt. Redact injectable_blocks and
        # results before returning.
        result = _redact_query_result(result)
        # Historical-lookup reuse funnel: persist a "lookup" event for every
        # source_only search, UNCONDITIONALLY (not gated on query_audit_log).
        # Reads the POST-redaction results so forbidden/forgotten/out-of-scope
        # ids never reach the exposed set, and mints a lookup_event_id that the
        # response surfaces for this path. Best-effort — a telemetry write
        # failure must never fail the query.
        if source_only:
            lookup_event_id: str | None = new_id()
            try:
                # Stable internal source_item_id (joins to source_items.id and
                # matches the expansion path) — NOT the caller-supplied
                # source_id, which is only unique per source_type/container.
                # Built inside the try so a malformed result can never fail the
                # query; getattr keeps it defensive.
                exposed = [
                    {
                        "source_item_id": item.source_item_id,
                        "raw_rank": getattr(item, "raw_rank", None),
                        "score": getattr(item, "score", None),
                    }
                    for item in result.results
                    if getattr(item, "source_item_id", None) is not None
                ]
                self._storage.write_historical_lookup_event_row({
                    "id": lookup_event_id,
                    "created_at": utc_now(),
                    "event_type": "lookup",
                    "session_id": thread_ref,
                    "container_ref": container_ref,
                    "actor_ref": actor_ref,
                    "trigger_origin": trigger_origin,
                    "parent_lookup_id": None,
                    "exposed_json": json.dumps(exposed),
                    "visibility": visibility,
                })
            except Exception:
                self._logger.warning("historical lookup event write failed", exc_info=True)
                # Do not surface an id whose event was never persisted — a
                # caller passing it back as parent_lookup_id (or the PR-b judge
                # joining labels) would reference a non-existent event.
                lookup_event_id = None
            result = dataclasses.replace(result, lookup_event_id=lookup_event_id)
        return result

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

    def forget_source(
        self,
        *,
        source_item_id: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        reason: str,
        actor_ref: str | None = None,
        caller_container_ref: str | None = None,
    ) -> dict:
        """User-requested forgetting of raw source turns (soft + auditable).

        Distinct from ``forget_memory`` (memory objects) and from the TTL
        retention hard-delete. After a forget, the turn no longer appears in
        query ``source_hit``s or in source expansion, but the row + its index
        entries persist with an auditable forgotten marker (who/when/why).

        Two modes (exactly one required):
        - ``source_item_id``: forget a single raw turn.
        - ``container_ref`` (optional ``thread_ref``): point-in-time bulk forget
          of the bounded scope; turns ingested later are unaffected.

        Authorization (both modes, identical rules): ``caller_container_ref`` is
        the caller's authorization scope (distinct from ``container_ref``, the
        bulk-scope target). Forgetting a raw turn is a destructive mutation, so
        the caller's container must match the target:
        - PRESENT caller scope → the target's container must match, else DENY
          (raises :class:`ForgetAuthorizationError`). A supplied-but-mismatched
          scope is ALWAYS denied, even in trusted mode.
        - MISSING caller scope → allowed ONLY in single-user trusted
          (compatibility) mode (the default); DENIED in strict multi-user mode.
        The predicate is enforced atomically inside storage (no ``forgotten_at``
        is written on denial). Untagged (NULL-container) targets are therefore
        deletable only via the missing-scope compatibility path.

        Raises ValueError if neither target is given, or if a single-item
        target is combined with a scope target (the request is ambiguous and
        could silently leave the scope unforgotten).
        """
        if source_item_id is not None and (container_ref is not None or thread_ref is not None):
            raise ValueError(
                "forget_source accepts source_item_id OR container_ref/thread_ref, not both"
            )
        # Resolve the container-scoped authorization expectation shared by both
        # paths. None ⇒ no storage-level check (only reachable via the trusted
        # missing-scope path); a value ⇒ storage enforces the match atomically.
        expected_container_ref = self._resolve_forget_scope(caller_container_ref)
        if source_item_id is not None:
            try:
                forgotten = self._storage.forget_source_item(
                    source_item_id,
                    reason=reason,
                    actor_ref=actor_ref,
                    expected_container_ref=expected_container_ref,
                )
            except PermissionError as exc:
                raise ForgetAuthorizationError(str(exc)) from exc
            return {
                "source_item_id": source_item_id,
                "forgotten": forgotten,
                "count": 1 if forgotten else 0,
            }
        if container_ref is not None:
            try:
                count = self._storage.forget_source_scope(
                    container_ref=container_ref,
                    thread_ref=thread_ref,
                    reason=reason,
                    actor_ref=actor_ref,
                    expected_container_ref=expected_container_ref,
                )
            except PermissionError as exc:
                raise ForgetAuthorizationError(str(exc)) from exc
            return {
                "container_ref": container_ref,
                "thread_ref": thread_ref,
                "count": count,
            }
        raise ValueError("forget_source requires source_item_id or container_ref")

    def _resolve_forget_scope(self, caller_container_ref: str | None) -> str | None:
        """Resolve the container the caller is authorized to forget within.

        Returns the container to enforce against storage, or ``None`` when no
        storage-level check applies (trusted-mode missing-scope path). Raises
        :class:`ForgetAuthorizationError` when caller scope is missing and the
        deployment is in strict multi-user mode. A PRESENT-but-mismatched scope
        is NOT decided here — it is enforced atomically against the target
        inside storage so there is no TOCTOU window.
        """
        if caller_container_ref is None:
            if not self._single_user_trusted_mode:
                raise ForgetAuthorizationError(
                    "forget denied: caller container scope is required in strict "
                    "multi-user mode (single_user_trusted_mode is disabled)"
                )
            return None
        return caller_container_ref

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
    ) -> str:
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
        # vNext P0 (design 015): return the row id as the lookup_event_id so
        # the API can surface it on the response (additive; never gates behavior).
        return row["id"]

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
        # PR 4 of the operational_fact redesign (2026-07-02): route
        # every persist through the storage's atomic ``commit_process_result``
        # so promotion hints are evaluated in the SAME transaction that
        # inserts the candidate row + its ``supported_by`` relations.
        # The evaluator needs to see the just-inserted rows for the
        # slot-count query to include this candidate.
        #
        # ``commit_process_result`` also resolves supersession pairs
        # from ``result.supersession_hints``; if no hints are present
        # it's a plain persist. Preserves the pre-PR-4 semantics for
        # every non-op_fact caller.
        if result.promotion_hints or result.supersession_hints:
            self._storage.commit_process_result(result=result)
            return
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

        PR 0 step 8: retrieval-side redaction is applied here — the
        payload dict, each source item's ``content`` + ``metadata``,
        and the match_text pass through :func:`redact_sensitive`.
        Defense in depth: even if a secret was persisted before the
        write barrier landed, ``pallium_expand`` never returns it raw.
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
            # Fail-closed raw-turn forgetting: a forgotten source turn is never
            # surfaced through expansion (this loop does not run matches_filters,
            # so the exclusion is applied explicitly here, mirroring the
            # per-item is_visible drop below).
            if item.forgotten:
                continue
            effective_actor_ref = query_actor_ref or memory_object.actor_ref
            if is_visible(item.visibility, item.container_ref, effective_container, item.actor_ref, query_actor_ref=effective_actor_ref):
                # Note artifacts bypass redaction — same carveout as
                # the write barrier at ``ingest_item`` (a user-explicit
                # verbatim recall surface).
                if item.artifact_kind != "note":
                    item = dataclasses.replace(
                        item,
                        content=redact_sensitive(item.content) if item.content else item.content,
                        metadata=_redact_ingest_value(item.metadata) if item.metadata else item.metadata,
                    )
                items.append(item)
        match_text = build_memory_match_text(memory_object) or None
        if match_text:
            match_text = redact_sensitive(match_text)
        payload = memory_object.payload
        if payload:
            payload = _redact_ingest_value(payload)
        return payload, items, match_text

    def get_source_context(
        self,
        source_item_id: str,
        *,
        container_ref: str | None = None,
        query_actor_ref: str | None = None,
        before: int = 10,
        after: int = 10,
        max_chars: int = 16000,
        include_supported_memories: bool = False,
        parent_lookup_id: str | None = None,
    ) -> tuple[SourceItem, list[SourceItem], list | None, str | None]:
        """Bounded neighborhood of raw turns around an anchor source item.

        Mirrors ``get_memory_expand`` for visibility/redaction/forgotten/note
        handling, adapted for a raw anchor:
        - Fail-closed anchor gate (mirror the caller-vs-parent container gate at
          ``get_memory_expand``): a forgotten or not-visible anchor yields 404
          (raises KeyError). Source items use ``"public"`` as the cross-container
          carve-out (there is no ``"global"`` for source items).
        - Neighbors are a two-sided, SQL-LIMIT-bounded window (never an unbounded
          transcript walk); each neighbor is individually forgotten-skipped +
          ``is_visible``-checked against the CALLER scope + redacted (note
          carve-out). The anchor is always included and exempt from the size cap;
          neighbors fill nearest-first and the farthest are dropped once the
          ``max_chars`` budget (measured after redaction) is exhausted.
        - Supported memories (reverse ``supported_by``) are returned only when
          ``include_supported_memories`` and each is ``is_visible``-filtered.
        - ``parent_lookup_id`` is carried onto a persisted "expansion" reuse
          event (own minted id) after the visibility/forgotten gates + the
          post-filter neighbor set is known, linking the expansion back to the
          lookup that produced the anchor id. Persisted unconditionally.
        """
        _MAX_SIDE = 25
        before = max(0, min(before, _MAX_SIDE))
        after = max(0, min(after, _MAX_SIDE))

        anchor = self._storage.get_source_item(source_item_id)  # KeyError -> 404
        # Fail-closed anchor gate. Forgotten anchor -> no context. Cross-container
        # gate mirrors get_memory_expand: a caller-supplied container_ref that
        # doesn't match a non-public anchor's container is denied (404, no
        # existence leak).
        if anchor.forgotten:
            raise KeyError(source_item_id)
        if container_ref is not None and anchor.visibility != "public" and anchor.container_ref != container_ref:
            raise KeyError(source_item_id)
        effective_container = container_ref or anchor.container_ref
        effective_actor_ref = query_actor_ref or anchor.actor_ref
        if not is_visible(
            anchor.visibility, anchor.container_ref, effective_container,
            anchor.actor_ref, query_actor_ref=effective_actor_ref,
        ):
            raise KeyError(source_item_id)

        def _redact(item: SourceItem) -> SourceItem:
            if item.artifact_kind == "note":
                return item
            return dataclasses.replace(
                item,
                content=redact_sensitive(item.content) if item.content else item.content,
                metadata=_redact_ingest_value(item.metadata) if item.metadata else item.metadata,
            )

        anchor_out = _redact(anchor)

        neighbors: list[SourceItem] = []
        if anchor.thread_ref is not None and anchor.container_ref is not None and (before or after):
            preceding, following = self._storage.list_source_item_neighbors(
                anchor.container_ref, anchor.thread_ref,
                anchor_created_at=anchor.created_at, anchor_id=anchor.id,
                before=before, after=after,
            )

            def _keep(item: SourceItem) -> SourceItem | None:
                if item.forgotten:
                    return None
                if not is_visible(
                    item.visibility, item.container_ref, effective_container,
                    item.actor_ref, query_actor_ref=effective_actor_ref,
                ):
                    return None
                return _redact(item)

            pre = [x for x in (_keep(i) for i in preceding) if x is not None]
            fol = [x for x in (_keep(i) for i in following) if x is not None]

            # Nearest-first fill under a char budget; anchor is exempt (always
            # returned). Once a side's next-nearest neighbor doesn't fit, that
            # side stops (its farther neighbors are dropped).
            budget = max_chars - len(anchor_out.content or "")
            pre_near = list(reversed(pre))  # closest-before first
            kept_pre: list[SourceItem] = []
            kept_fol: list[SourceItem] = []
            pi = fi = 0
            while pi < len(pre_near) or fi < len(fol):
                took = False
                if pi < len(pre_near):
                    c = pre_near[pi]
                    length = len(c.content or "")
                    if length <= budget:
                        kept_pre.append(c)
                        budget -= length
                        pi += 1
                        took = True
                    else:
                        pi = len(pre_near)
                if fi < len(fol):
                    c = fol[fi]
                    length = len(c.content or "")
                    if length <= budget:
                        kept_fol.append(c)
                        budget -= length
                        fi += 1
                        took = True
                    else:
                        fi = len(fol)
                if not took:
                    break
            neighbors = list(reversed(kept_pre)) + kept_fol  # ascending order

        supported: list | None = None
        if include_supported_memories:
            supported = [
                m for m in self._storage.list_memory_objects_for_source_item(source_item_id)
                if is_visible(
                    m.visibility, m.container_ref, effective_container,
                    getattr(m, "actor_ref", None), query_actor_ref=effective_actor_ref,
                )
            ]

        # Historical-lookup reuse funnel: persist an "expansion" event
        # carrying the incoming parent_lookup_id. Runs AFTER the anchor gates
        # and the per-neighbor visibility/forgotten/redaction filter, so the
        # exposed set is the post-gate neighbor ids only (no leak). Mints its
        # own id; persisted unconditionally. Best-effort — a telemetry write
        # failure must never fail the expansion.
        exposed = [{"source_item_id": n.id, "raw_rank": None, "score": None} for n in neighbors]
        try:
            self._storage.write_historical_lookup_event_row({
                "id": new_id(),
                "created_at": utc_now(),
                "event_type": "expansion",
                "session_id": anchor.thread_ref,
                "container_ref": effective_container,
                "actor_ref": effective_actor_ref,
                "trigger_origin": None,
                "parent_lookup_id": parent_lookup_id,
                "exposed_json": json.dumps(exposed),
                "visibility": anchor.visibility,
            })
        except Exception:
            self._logger.warning("historical expansion event write failed", exc_info=True)

        return anchor_out, neighbors, supported, parent_lookup_id
