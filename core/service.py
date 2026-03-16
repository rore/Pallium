from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from typing import Any

from capabilities.consolidation import ConsolidationCapability, ConsolidationRunGroupResult, ConsolidationRunResult
from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import IngestResult, ItemProcessingResult, PackageQueryOutcome, ProcessResult, QueryResult, build_source_item, resolve_query_filters
from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, build_index_entry
from core.models import MemoryObject, QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace, Relation, SourceItem, utc_now
from core.observability import IntegrationDebugLogger, OBSERVABILITY_METADATA_KEY, serialize_visibility_context
from core.visibility import QueryVisibilityTrace, VisibilityContext, expand_visibility_context, visibility_context_is_visible, visibility_context_matches_exact, visibility_context_label
from providers.llm.base import LLMProviderError
from retrieval.base import RetrievalProvider
from semantic.base import ConsolidationSemanticPlugin, SemanticPlugin, ThreadAggregationSemanticPlugin
from storage.base import QueueHealthSnapshot, RetentionLeaseLostError, RetentionRunStats, StorageProvider, ThreadProcessingLease, ThreadProcessingScope


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
THREAD_CONCLUSION_TYPES = {"decision", "investigation_outcome"}
THREAD_SUMMARY_TYPE = "thread_summary"
DEFAULT_PROCESSING_LEASE_SECONDS = 15 * 60
DEFAULT_PROCESSING_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 5
MAX_RETRY_BACKOFF_SECONDS = 5 * 60
MAX_PROCESSING_ERROR_LENGTH = 1000
FAILURE_CATEGORY_MISSING_USE_CASE = "missing_use_case"
FAILURE_CATEGORY_MISSING_VISIBILITY = "missing_visibility_context"
FAILURE_CATEGORY_UNKNOWN_USE_CASE = "unknown_use_case"
FAILURE_CATEGORY_MALFORMED_PAYLOAD = "malformed_payload"
FAILURE_CATEGORY_EXTRACTOR = "extractor_failure"
FAILURE_CATEGORY_LLM = "llm_failure"
FAILURE_CATEGORY_THREAD_REBUILD = "thread_rebuild_failure"
FAILURE_CATEGORY_STORAGE_COMMIT = "storage_commit_failure"
FAILURE_CATEGORY_UNEXPECTED = "unexpected_runtime_failure"

def _normalize_for_index(text: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(text.lower()))


def _query_tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(TOKEN_PATTERN.findall(text.lower()))))


def _observability_state(source_item: SourceItem) -> dict[str, Any]:
    metadata = source_item.metadata or {}
    if not isinstance(metadata, dict):
        return {}
    state = metadata.get(OBSERVABILITY_METADATA_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _with_observability_metadata(
    existing_updates: dict[str, dict[str, Any]],
    source_item_id: str,
    patch: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    merged_updates = dict(existing_updates)
    source_updates = dict(merged_updates.get(source_item_id, {}))
    existing_observability = source_updates.get(OBSERVABILITY_METADATA_KEY)
    observability_state = dict(existing_observability) if isinstance(existing_observability, dict) else {}
    observability_state.update(patch)
    source_updates[OBSERVABILITY_METADATA_KEY] = observability_state
    merged_updates[source_item_id] = source_updates
    return merged_updates


def _build_memory_provenance(
    result: ProcessResult,
    *,
    default_source_item_id: str | None = None,
    supersession_pairs: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    supported_by: dict[str, list[str]] = {}
    superseded_by_replacement: dict[str, list[str]] = {}
    for relation in result.relations:
        if relation.from_kind != "memory_object":
            continue
        if relation.relation_type == "supported_by" and relation.to_kind == "source_item":
            supported_by.setdefault(relation.from_id, []).append(relation.to_id)
        elif relation.relation_type == "supersedes" and relation.to_kind == "memory_object":
            superseded_by_replacement.setdefault(relation.from_id, []).append(relation.to_id)
    for superseded_id, replacement_id in supersession_pairs or []:
        superseded_by_replacement.setdefault(replacement_id, []).append(superseded_id)

    provenance: list[dict[str, Any]] = []
    for memory_object in result.memory_objects:
        source_item_ids = supported_by.get(memory_object.id, [])
        if not source_item_ids and default_source_item_id is not None:
            source_item_ids = [default_source_item_id]
        provenance.append(
            {
                "memory_object_id": memory_object.id,
                "memory_kind": memory_object.type,
                "source_item_ids": sorted(dict.fromkeys(source_item_ids)),
                "superseded_memory_ids": sorted(dict.fromkeys(superseded_by_replacement.get(memory_object.id, []))),
            }
        )
    return provenance


def _build_query_result_summary(results: list[Any]) -> dict[str, Any]:
    kind_counts = Counter(getattr(item, "result_kind", "unknown") for item in results)
    return {
        "returned_result_count": len(results),
        "returned_result_kinds": dict(sorted(kind_counts.items())),
        "returned_origins": {
            "memory": sum(1 for item in results if getattr(item, "result_kind", None) == "memory_hit"),
            "source": sum(1 for item in results if getattr(item, "result_kind", None) == "source_hit"),
        },
    }


def _classify_failure(error: Exception, *, phase: str) -> str:
    if isinstance(error, LLMProviderError):
        return FAILURE_CATEGORY_LLM
    if isinstance(error, (json.JSONDecodeError, ValueError, TypeError)):
        return FAILURE_CATEGORY_MALFORMED_PAYLOAD
    if phase == "thread_rebuild":
        return FAILURE_CATEGORY_THREAD_REBUILD
    if phase == "process_item":
        return FAILURE_CATEGORY_EXTRACTOR
    return FAILURE_CATEGORY_UNEXPECTED


def _preferred_active_summary_ref(memory_objects: list[MemoryObject]) -> dict[str, str] | None:
    if not memory_objects:
        return None
    priority = {
        THREAD_SUMMARY_TYPE: 0,
        "task_checkpoint": 1,
        "continuity_memory": 2,
        "pattern_memory": 3,
    }
    preferred = min(
        memory_objects,
        key=lambda item: (priority.get(item.type, 10), item.created_at, item.id),
    )
    return {"kind": preferred.type, "id": preferred.id}


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
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._consolidation_capability = ConsolidationCapability()
        self._observability = observability or IntegrationDebugLogger(enabled=False)
        self._retention_enabled = retention_enabled
        self._retention_lease_seconds = retention_lease_seconds
        self._retention_batch_size = retention_batch_size

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
        role: str | None = None,
        container_ref: str | None = None,
        thread_ref: str | None = None,
        session_ref: str | None = None,
        source_ref: str | None = None,
        artifact_kind: str | None = None,
        visibility_context: VisibilityContext | None = None,
    ) -> IngestResult:
        existing_source_item = self._storage.find_source_item(source_type=source_type, source_id=source_id)
        if existing_source_item is not None:
            return self._build_ingest_result(existing_source_item)

        plugin_name = use_case or self._default_use_case
        plugin = self._semantic_plugins[plugin_name]
        processing_status = "pending"
        processing_error = None
        if plugin.requires_visibility_context and visibility_context is None:
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
            role=role,
            container_ref=container_ref,
            thread_ref=thread_ref,
            session_ref=session_ref,
            source_ref=source_ref,
            artifact_kind=artifact_kind,
            visibility_context=visibility_context,
            use_case=plugin_name,
            processing_status=processing_status,
            processing_error=processing_error,
        )
        self._storage.create_source_item(source_item)
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
            error_message = "retention lease lost before completion" if isinstance(exc, RetentionLeaseLostError) else self._truncate_processing_error(exc)
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
        source_item = self._storage.claim_next_source_item(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )
        if source_item is None:
            return None
        self._process_source_item(
            source_item,
            max_attempts=max_attempts,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        return self.get_item_processing(source_item.id)

    def process_next_thread_rebuild(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
    ) -> ThreadProcessingLease | None:
        lease = self._storage.claim_next_thread_processing_scope(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if lease is None:
            return None
        self._process_thread_rebuild_lease(lease, worker_id=worker_id, lease_seconds=lease_seconds)
        return lease

    def drain_processing_queue(
        self,
        *,
        worker_id: str = "local-drain",
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
        max_attempts: int = DEFAULT_PROCESSING_MAX_ATTEMPTS,
        limit: int | None = None,
    ) -> list[ItemProcessingResult]:
        results: list[ItemProcessingResult] = []
        while limit is None or len(results) < limit:
            result = self.process_next_source_item(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
            )
            if result is not None:
                results.append(result)
                continue
            thread_lease = self.process_next_thread_rebuild(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            if thread_lease is None:
                break
        return results

    def _process_source_item(
        self,
        source_item: SourceItem,
        *,
        max_attempts: int,
        worker_id: str | None = None,
        lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
    ) -> None:
        worker_label = worker_id or source_item.processing_claimed_by or "source-item-worker"
        plugin_name = source_item.use_case or self._default_use_case
        if source_item.use_case is None and not self._default_use_case:
            failure_category = FAILURE_CATEGORY_MISSING_USE_CASE
            error = "missing_use_case"
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=None,
                final=True,
                metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
            )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        plugin = self._semantic_plugins.get(plugin_name)
        if plugin is None:
            failure_category = FAILURE_CATEGORY_UNKNOWN_USE_CASE
            error = f"unknown_use_case:{plugin_name}"
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=None,
                final=True,
                metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
            )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        if plugin.requires_visibility_context and source_item.visibility_context is None:
            failure_category = FAILURE_CATEGORY_MISSING_VISIBILITY
            error = "visibility_context_required"
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=None,
                final=True,
                metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
            )
            self._emit_processing_failure(source_item, worker_id=worker_label, failure_category=failure_category, error=error)
            return

        try:
            direct_result = plugin.process_item(source_item)
            reconcile_process_result = getattr(plugin, "reconcile_process_result", None)
            if callable(reconcile_process_result):
                direct_result = reconcile_process_result(
                    direct_result,
                    storage=self._storage,
                    container_ref=source_item.container_ref,
                    visibility_context=source_item.visibility_context,
                )
            thread_rebuild_scope = None
            if direct_result.thread_rebuild_requested:
                thread_rebuild_scope = self._build_thread_processing_scope(
                    plugin_name=plugin_name,
                    plugin=plugin,
                    source_item=source_item,
                )
            supersession_pairs = self._resolve_supersession_pairs(direct_result)
            memory_provenance = _build_memory_provenance(
                direct_result,
                default_source_item_id=source_item.id,
                supersession_pairs=supersession_pairs,
            )
            metadata_updates = _with_observability_metadata(
                direct_result.source_item_metadata_updates,
                source_item.id,
                {
                    "annotation_count": len(direct_result.annotations),
                    "memory_object_types": [memory_object.type for memory_object in direct_result.memory_objects],
                    "produced_memory_provenance": memory_provenance,
                    "thread_rebuild_requested": thread_rebuild_scope is not None,
                    "thread_rebuild_completed": False,
                    "failure_category": None,
                },
            )
            direct_result = ProcessResult(
                annotations=direct_result.annotations,
                memory_objects=direct_result.memory_objects,
                relations=direct_result.relations,
                index_entries=direct_result.index_entries,
                source_item_metadata_updates=metadata_updates,
                thread_rebuild_requested=direct_result.thread_rebuild_requested,
                supersession_hints=direct_result.supersession_hints,
            )
            self._storage.commit_processed_source_item(
                source_item_id=source_item.id,
                result=direct_result,
                supersession_pairs=supersession_pairs,
                thread_rebuild_scope=thread_rebuild_scope,
            )
            self._emit_processing_outcome(
                source_item=source_item,
                result=direct_result,
                thread_rebuild_scope=thread_rebuild_scope,
            )
            self._emit_memory_creation_provenance(
                source_item=source_item,
                provenance=memory_provenance,
            )
        except Exception as exc:
            failure_category = _classify_failure(exc, phase="process_item")
            error = self._truncate_processing_error(exc)
            final_failure = source_item.processing_attempts >= max_attempts
            next_attempt_at = None
            if not final_failure and source_item.processing_claimed_at is not None:
                backoff_seconds = self._queue_backoff_seconds(source_item.processing_attempts)
                next_attempt_at = source_item.processing_claimed_at + timedelta(seconds=backoff_seconds)
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=next_attempt_at,
                final=final_failure,
                metadata_updates={OBSERVABILITY_METADATA_KEY: {"failure_category": failure_category}},
            )
            self._emit_processing_failure(
                source_item,
                worker_id=worker_label,
                failure_category=failure_category,
                error=error,
            )
            return

        if thread_rebuild_scope is None:
            return

        lease = self._storage.claim_thread_processing_scope(
            scope=thread_rebuild_scope,
            worker_id=worker_label,
            lease_seconds=lease_seconds,
        )
        if lease is None:
            return
        self._process_thread_rebuild_lease(lease, worker_id=worker_label, lease_seconds=lease_seconds)
    def _build_ingest_result(self, source_item: SourceItem) -> IngestResult:
        processing = self._build_processing_result(source_item)
        return IngestResult(
            source_item_id=processing.source_item_id,
            annotation_ids=processing.annotation_ids,
            memory_object_ids=processing.memory_object_ids,
            relation_ids=processing.relation_ids,
            index_entry_ids=processing.index_entry_ids,
            processing_status=processing.processing_status,
            processing_attempts=processing.processing_attempts,
            processing_error=processing.processing_error,
        )

    def _build_processing_result(self, source_item: SourceItem) -> ItemProcessingResult:
        annotations = self._storage.list_annotations_for_source_item(source_item.id)
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
        observability_state = _observability_state(source_item)
        return ItemProcessingResult(
            source_item_id=source_item.id,
            use_case=source_item.use_case,
            processing_status=source_item.processing_status,
            processing_attempts=source_item.processing_attempts,
            processing_claimed_at=source_item.processing_claimed_at,
            processing_completed_at=source_item.processing_completed_at,
            processing_error=source_item.processing_error,
            annotation_ids=[item.id for item in annotations],
            memory_object_ids=[item.id for item in memory_objects],
            relation_ids=[item.id for item in relations],
            index_entry_ids=[item.id for item in index_entries],
            failure_category=observability_state.get("failure_category"),
            annotation_count=int(observability_state.get("annotation_count", len(annotations))),
            memory_object_types=list(observability_state.get("memory_object_types", [item.type for item in memory_objects])),
            thread_rebuild_requested=bool(observability_state.get("thread_rebuild_requested", False)),
            thread_rebuild_completed=bool(observability_state.get("thread_rebuild_completed", False)),
            produced_memory_provenance=list(observability_state.get("produced_memory_provenance", [])),
        )
    @staticmethod
    def _queue_backoff_seconds(attempt_count: int) -> int:
        return min(MAX_RETRY_BACKOFF_SECONDS, DEFAULT_RETRY_BACKOFF_SECONDS * (2 ** max(attempt_count - 1, 0)))

    @staticmethod
    def _truncate_processing_error(error: Exception) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:MAX_PROCESSING_ERROR_LENGTH]

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
        session_ref: str | None = None,
        visibility_context: VisibilityContext | None = None,
        runtime_context: QueryRuntimeContext | None = None,
        include_trace: bool = False,
    ) -> QueryResult:
        filter_resolution = resolve_query_filters(
            source_type=source_type,
            role=role,
            artifact_kind=artifact_kind,
            container_ref=container_ref,
            thread_ref=thread_ref,
            session_ref=session_ref,
            runtime_context=runtime_context,
        )
        requested_filters = filter_resolution.requested_filters
        effective_filters = filter_resolution.effective_filters
        plugin = self._semantic_plugins[self._default_use_case]
        if plugin.requires_visibility_context and visibility_context is None:
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=_query_tokens(text),
                    limit=limit,
                    filters=effective_filters,
                    requested_filters=requested_filters,
                    filter_scope_relaxed=filter_resolution.filter_scope_relaxed,
                    filter_scope_reason=filter_resolution.filter_scope_reason,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_visibility_context=None,
                        expanded_visibility_contexts=tuple(),
                        fail_closed_reason="query_visibility_context_required",
                    ),
                )
                trace = replace(trace, result_summary=_build_query_result_summary([]))
            return QueryResult(
                results=[],
                trace=trace,
                should_inject=False,
                decision_reason="no_relevant_memory",
                injectable_blocks=[],
            )

        route_query_results = getattr(plugin, "route_query_results", None)
        retrieval_limit = limit
        if callable(route_query_results):
            retrieval_limit = min(max(limit * 4, 12), 50)
        retrieval_result = self._retrieval.query(
            text=text,
            limit=retrieval_limit,
            filters=effective_filters,
            visibility_context=visibility_context if plugin.requires_visibility_context else None,
            include_trace=include_trace,
        )
        if retrieval_result.trace is not None:
            retrieval_result = replace(
                retrieval_result,
                trace=replace(
                    retrieval_result.trace,
                    requested_filters=requested_filters,
                    filter_scope_relaxed=filter_resolution.filter_scope_relaxed,
                    filter_scope_reason=filter_resolution.filter_scope_reason,
                ),
            )
        if callable(route_query_results):
            outcome = route_query_results(
                text=text,
                requested_limit=limit,
                retrieval_result=retrieval_result,
                query_filters=requested_filters,
                runtime_context=runtime_context,
                include_trace=include_trace,
                debug_candidate_loader=self._make_debug_candidate_loader(
                    filters=effective_filters,
                    visibility_context=visibility_context if plugin.requires_visibility_context else None,
                ),
            )
            if not isinstance(outcome, PackageQueryOutcome):
                raise TypeError("route_query_results must return PackageQueryOutcome")
            routed_trace = outcome.trace
            if routed_trace is not None:
                routed_trace = replace(routed_trace, result_summary=_build_query_result_summary(outcome.results))
            return QueryResult(
                results=outcome.results,
                trace=routed_trace,
                should_inject=outcome.should_inject,
                decision_reason=outcome.decision_reason,
                injectable_blocks=outcome.injectable_blocks,
            )
        trace = retrieval_result.trace
        if trace is not None:
            trace = replace(trace, result_summary=_build_query_result_summary(retrieval_result.results))
        return QueryResult(
            results=retrieval_result.results,
            trace=trace,
            should_inject=False,
            decision_reason="injection_policy_unavailable",
            injectable_blocks=[],
        )

    def _resolve_supersession_pairs(self, result: ProcessResult) -> list[tuple[str, str]]:
        if not result.supersession_hints:
            return []
        replacements = {memory_object.id: memory_object for memory_object in result.memory_objects}
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for hint in result.supersession_hints:
            replacement = replacements.get(hint.replacement_memory_id)
            if replacement is None:
                continue
            if not hint.container_ref or not hint.thread_ref or not hint.canonical_key:
                continue
            thread_items = self._storage.list_source_items_for_thread(hint.container_ref, hint.thread_ref)
            for thread_item in thread_items:
                if not visibility_context_matches_exact(thread_item.visibility_context, hint.visibility_context):
                    continue
                for candidate in self._storage.list_memory_objects_for_source_item(thread_item.id):
                    if candidate.id == replacement.id:
                        continue
                    if candidate.lifecycle != "active" or candidate.type != hint.memory_type:
                        continue
                    if not visibility_context_matches_exact(candidate.visibility_context, hint.visibility_context):
                        continue
                    candidate_key = str(candidate.payload.get("canonical_key") or "").strip()
                    if candidate_key != hint.canonical_key:
                        continue
                    pair = (candidate.id, replacement.id)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    pairs.append(pair)
        return pairs

    def _make_debug_candidate_loader(
        self,
        *,
        filters: QueryFilters | None,
        visibility_context: VisibilityContext | None,
    ):
        visible_contexts = expand_visibility_context(visibility_context) if visibility_context is not None else None

        def load_candidates(*, memory_types: list[str] | None = None) -> list[QueryResultItem]:
            results: list[QueryResultItem] = []
            for memory_object in self._storage.list_memory_objects(memory_types=memory_types, lifecycle="active"):
                if not visibility_context_is_visible(memory_object.visibility_context, visible_contexts):
                    continue
                evidence = self._storage.get_evidence_for_memory_object(memory_object.id)
                if filters is not None and not any(self._evidence_matches_filters(item, filters) for item in evidence):
                    continue
                results.append(
                    QueryResultItem(
                        result_kind="memory_hit",
                        memory_object_id=memory_object.id,
                        type=memory_object.type,
                        payload=memory_object.payload,
                        freshness_at=memory_object.freshness_at,
                        score=0,
                        evidence=evidence,
                        visibility_context=memory_object.visibility_context,
                    )
                )
            return results

        return load_candidates

    @staticmethod
    def _evidence_matches_filters(evidence, filters: QueryFilters) -> bool:
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
    def run_consolidation_pass(
        self,
        *,
        use_case: str | None = None,
        strategy_name: str | None = None,
    ) -> ConsolidationRunResult | None:
        plugin_name = use_case or self._default_use_case
        plugin = self._semantic_plugins[plugin_name]
        if not isinstance(plugin, ConsolidationSemanticPlugin):
            return None
        policy = plugin.consolidation_policy
        if policy is None:
            return None

        resolved_strategy_name = strategy_name or policy.default_strategy
        if resolved_strategy_name not in policy.enabled_strategies:
            raise ValueError(f"Strategy '{resolved_strategy_name}' is not enabled for package '{plugin_name}'")

        strategy = self._consolidation_capability.resolve_strategy(resolved_strategy_name)
        candidates = self._consolidation_capability.select_candidates(
            storage=self._storage,
            plugin=plugin,
            strategy=strategy,
            policy=policy,
        )
        groups = self._consolidation_capability.group_candidates(
            strategy=strategy,
            candidates=candidates,
            policy=policy,
        )

        group_results: list[ConsolidationRunGroupResult] = []
        for group in groups:
            synthesized = self._consolidation_capability.synthesize_group(plugin=plugin, group=group)
            if not synthesized.memory_objects:
                continue
            promoted = ProcessResult(
                annotations=synthesized.annotations,
                memory_objects=synthesized.memory_objects,
                relations=[
                    *synthesized.relations,
                    *self._build_consolidation_relations(group, synthesized.memory_objects),
                ],
                index_entries=synthesized.index_entries,
            )
            self._persist_process_result(promoted)

            superseded_ids: list[str] = []
            for memory_object in synthesized.memory_objects:
                for active_memory_id in self._find_active_consolidated_memory_ids(group, memory_object):
                    if active_memory_id == memory_object.id or active_memory_id in superseded_ids:
                        continue
                    self.supersede_memory_object(active_memory_id, memory_object.id)
                    superseded_ids.append(active_memory_id)

            group_results.append(
                ConsolidationRunGroupResult(
                    strategy_name=group.strategy_name,
                    strategy_version=group.strategy_version,
                    group_key=group.group_key,
                    selected_candidate_ids=group.candidate_ids,
                    selected_source_item_ids=group.supporting_source_ids,
                    candidate_thread_refs=tuple(candidate.thread_ref for candidate in group.candidates),
                    created_memory_ids=tuple(memory.id for memory in synthesized.memory_objects),
                    created_memory_types=tuple(memory.type for memory in synthesized.memory_objects),
                    superseded_memory_ids=tuple(superseded_ids),
                    merge_rationale=group.merge_rationale,
                )
            )

        return ConsolidationRunResult(
            package_name=plugin_name,
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            candidate_count=len(candidates),
            selected_candidate_ids=tuple(candidate.memory_object.id for candidate in candidates),
            groups=tuple(group_results),
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

    def _persist_process_result(self, result: ProcessResult) -> None:
        for annotation in result.annotations:
            self._storage.create_annotation(annotation)
        for memory_object in result.memory_objects:
            self._storage.create_memory_object(memory_object)
        for relation in result.relations:
            self._storage.create_relation(relation)
        for index_entry in result.index_entries:
            self._storage.create_index_entry(index_entry)

    def _build_thread_processing_scope(
        self,
        *,
        plugin_name: str,
        plugin: SemanticPlugin,
        source_item: SourceItem,
    ) -> ThreadProcessingScope | None:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None
        if not plugin.supports_thread_aggregation(source_item):
            return None
        if not source_item.container_ref or not source_item.thread_ref:
            return None
        visibility_context = source_item.visibility_context
        scope_key = json.dumps(
            {
                "use_case": plugin_name,
                "container_ref": source_item.container_ref,
                "thread_ref": source_item.thread_ref,
                "visibility_kind": visibility_context.kind if visibility_context is not None else None,
                "visibility_id": visibility_context.id if visibility_context is not None else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return ThreadProcessingScope(
            scope_key=scope_key,
            use_case=plugin_name,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            visibility_context=visibility_context,
        )

    def _process_thread_rebuild_lease(
        self,
        lease: ThreadProcessingLease,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        current_lease = lease
        while True:
            plugin = self._semantic_plugins[current_lease.use_case]
            thread_items: list[SourceItem] = []
            thread_result: ProcessResult | None = None
            supersession_pairs: list[tuple[str, str]] = []
            try:
                thread_result, supersede_plan, thread_items = self._maybe_rebuild_thread_summary(
                    plugin=plugin,
                    thread_scope=current_lease.as_scope(),
                )
                if thread_result is not None:
                    supersession_pairs = [
                        (superseded_id, replacement_id)
                        for replacement_id, superseded_ids in supersede_plan.items()
                        for superseded_id in superseded_ids
                    ]
                    metadata_updates = dict(thread_result.source_item_metadata_updates)
                    for thread_item in thread_items:
                        metadata_updates = _with_observability_metadata(
                            metadata_updates,
                            thread_item.id,
                            {"thread_rebuild_completed": True},
                        )
                    thread_result = ProcessResult(
                        annotations=thread_result.annotations,
                        memory_objects=thread_result.memory_objects,
                        relations=thread_result.relations,
                        index_entries=thread_result.index_entries,
                        source_item_metadata_updates=metadata_updates,
                    )
                    self._storage.commit_process_result(
                        result=thread_result,
                        supersession_pairs=supersession_pairs,
                    )
                self._emit_thread_rebuild_outcome(
                    lease=current_lease,
                    thread_items=thread_items,
                    result=thread_result,
                    supersession_pairs=supersession_pairs,
                )
            except Exception as exc:
                self._observability.emit(
                    "thread_rebuild_outcome",
                    thread_ref=current_lease.thread_ref,
                    visibility_scope=visibility_context_label(current_lease.visibility_context),
                    visibility_context=serialize_visibility_context(current_lease.visibility_context),
                    processing_status="failed",
                    failure_category=_classify_failure(exc, phase="thread_rebuild"),
                    error=self._truncate_processing_error(exc),
                )
                return

            has_pending = self._storage.complete_thread_processing_scope(
                scope_key=current_lease.scope_key,
                worker_id=worker_id,
                claimed_at=current_lease.processing_claimed_at,
            )
            if not has_pending:
                return
            next_lease = self._storage.claim_thread_processing_scope(
                scope=current_lease.as_scope(),
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            if next_lease is None:
                return
            current_lease = next_lease

    def _maybe_rebuild_thread_summary(
        self,
        *,
        plugin: SemanticPlugin,
        thread_scope: ThreadProcessingScope,
    ) -> tuple[ProcessResult | None, dict[str, list[str]], list[SourceItem]]:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None, {}, []

        thread_items = [
            item
            for item in self._storage.list_source_items_for_thread(thread_scope.container_ref, thread_scope.thread_ref)
            if plugin.supports_thread_aggregation(item)
        ]
        if plugin.requires_visibility_context:
            thread_items = [
                item
                for item in thread_items
                if visibility_context_matches_exact(item.visibility_context, thread_scope.visibility_context)
            ]
        if not thread_items:
            return None, {}, []

        active_thread_memory_ids = self._find_active_thread_memory_ids(thread_items)
        aggregate = build_thread_aggregate(thread_items)
        conclusions = self._collect_thread_conclusions(thread_items)
        thread_result = plugin.build_thread_summary(aggregate, conclusions)
        reconcile_process_result = getattr(plugin, "reconcile_process_result", None)
        if callable(reconcile_process_result) and thread_result is not None:
            thread_result = reconcile_process_result(
                thread_result,
                storage=self._storage,
                container_ref=thread_scope.container_ref,
                visibility_context=thread_scope.visibility_context,
            )
        supersede_plan: dict[str, list[str]] = {}
        for memory_object in thread_result.memory_objects:
            key = (memory_object.type, memory_object.schema_id)
            supersede_plan[memory_object.id] = [
                superseded_id
                for superseded_id in active_thread_memory_ids.get(key, [])
                if superseded_id != memory_object.id
            ]
        return thread_result, supersede_plan, thread_items

    def _find_active_thread_memory_ids(
        self,
        thread_items: list[SourceItem],
    ) -> dict[tuple[str, str], list[str]]:
        seen: set[str] = set()
        ids: dict[tuple[str, str], list[str]] = {}
        for source_item in thread_items:
            for memory_object in self._storage.list_memory_objects_for_source_item(source_item.id):
                if memory_object.lifecycle != "active":
                    continue
                if memory_object.id in seen:
                    continue
                seen.add(memory_object.id)
                ids.setdefault((memory_object.type, memory_object.schema_id), []).append(memory_object.id)
        return ids

    def _collect_thread_conclusions(
        self,
        thread_items: list[SourceItem],
    ) -> list[MemoryObject]:
        conclusions: dict[str, MemoryObject] = {}
        for source_item in thread_items:
            memory_objects = self._storage.list_memory_objects_for_source_item(source_item.id)
            for memory_object in memory_objects:
                if memory_object.lifecycle != "active":
                    continue
                if memory_object.type not in THREAD_CONCLUSION_TYPES:
                    continue
                conclusions[memory_object.id] = memory_object
        return list(conclusions.values())

    def _build_consolidation_relations(
        self,
        group,
        memory_objects: list[MemoryObject],
    ) -> list[Relation]:
        relations: list[Relation] = []
        for memory_object in memory_objects:
            relations.extend(
                Relation(
                    from_kind="memory_object",
                    from_id=memory_object.id,
                    relation_type="supported_by",
                    to_kind="source_item",
                    to_id=source_item_id,
                )
                for source_item_id in group.supporting_source_ids
            )
            relations.extend(
                Relation(
                    from_kind="memory_object",
                    from_id=memory_object.id,
                    relation_type="consolidates",
                    to_kind="memory_object",
                    to_id=candidate_id,
                )
                for candidate_id in group.candidate_ids
            )
        return relations

    def _find_active_consolidated_memory_ids(
        self,
        group,
        created_memory_object: MemoryObject,
    ) -> list[str]:
        ids: list[str] = []
        for memory_object in self._storage.list_memory_objects(
            memory_types=[created_memory_object.type],
            lifecycle="active",
        ):
            if memory_object.schema_id != created_memory_object.schema_id:
                continue
            if not visibility_context_matches_exact(memory_object.visibility_context, created_memory_object.visibility_context):
                continue
            provenance = memory_object.payload.get("consolidation_provenance", {})
            if provenance.get("strategy_name") != group.strategy_name:
                continue
            if memory_object.payload.get("group_key") != group.group_key:
                continue
            ids.append(memory_object.id)
        return ids

    def _emit_processing_outcome(
        self,
        *,
        source_item: SourceItem,
        result: ProcessResult,
        thread_rebuild_scope: ThreadProcessingScope | None,
    ) -> None:
        self._observability.emit(
            "source_item_processing_outcome",
            source_item_id=source_item.id,
            source_type=source_item.source_type,
            artifact_kind=source_item.artifact_kind,
            use_case=source_item.use_case,
            processing_status="completed",
            produced_annotation_count=len(result.annotations),
            produced_memory_kinds=[memory_object.type for memory_object in result.memory_objects],
            thread_rebuild_ran=thread_rebuild_scope is not None,
        )

    def _emit_processing_failure(
        self,
        source_item: SourceItem,
        *,
        worker_id: str,
        failure_category: str,
        error: str,
    ) -> None:
        self._observability.emit(
            "source_item_processing_failure",
            source_item_id=source_item.id,
            source_type=source_item.source_type,
            artifact_kind=source_item.artifact_kind,
            use_case=source_item.use_case,
            processing_status="failed",
            worker_id=worker_id,
            failure_category=failure_category,
            error=error,
        )

    def _emit_memory_creation_provenance(
        self,
        *,
        source_item: SourceItem,
        provenance: list[dict[str, Any]],
    ) -> None:
        for entry in provenance:
            self._observability.emit(
                "memory_creation_provenance",
                source_item_id=source_item.id,
                memory_object_id=entry["memory_object_id"],
                memory_kind=entry["memory_kind"],
                source_item_ids=entry["source_item_ids"],
                superseded_memory_ids=entry["superseded_memory_ids"],
            )

    def _emit_thread_rebuild_outcome(
        self,
        *,
        lease: ThreadProcessingLease,
        thread_items: list[SourceItem],
        result: ProcessResult | None,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        created_memory_kinds = [memory_object.type for memory_object in result.memory_objects] if result is not None else []
        active_summary_ref = _preferred_active_summary_ref(result.memory_objects if result is not None else [])
        self._observability.emit(
            "thread_rebuild_outcome",
            thread_ref=lease.thread_ref,
            visibility_scope=visibility_context_label(lease.visibility_context),
            visibility_context=serialize_visibility_context(lease.visibility_context),
            input_item_count_considered=len(thread_items),
            created_or_updated_memory_kinds=created_memory_kinds,
            superseded_memory_ids=[superseded_id for superseded_id, _replacement_id in supersession_pairs],
            superseded_memory_count=len(supersession_pairs),
            final_active_summary_kind=active_summary_ref["kind"] if active_summary_ref is not None else None,
            final_active_summary_id=active_summary_ref["id"] if active_summary_ref is not None else None,
            processing_status="completed",
        )

