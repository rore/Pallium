from __future__ import annotations

import json
import re
from datetime import timedelta

from capabilities.consolidation import ConsolidationCapability, ConsolidationRunGroupResult, ConsolidationRunResult
from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import IngestResult, ItemProcessingResult, ProcessResult, QueryResult, build_query_filters, build_source_item
from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, build_index_entry
from core.models import MemoryObject, QueryFilters, QueryTrace, Relation, SourceItem
from core.visibility import QueryVisibilityTrace, VisibilityContext, visibility_context_matches_exact
from retrieval.base import RetrievalProvider
from semantic.base import ConsolidationSemanticPlugin, SemanticPlugin, ThreadAggregationSemanticPlugin
from storage.base import StorageProvider, ThreadProcessingLease, ThreadProcessingScope


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
THREAD_CONCLUSION_TYPES = {"decision", "investigation_outcome"}
THREAD_SUMMARY_TYPE = "thread_summary"
DEFAULT_PROCESSING_LEASE_SECONDS = 15 * 60
DEFAULT_PROCESSING_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 5
MAX_RETRY_BACKOFF_SECONDS = 5 * 60
MAX_PROCESSING_ERROR_LENGTH = 1000


def _normalize_for_index(text: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(text.lower()))


def _query_tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(TOKEN_PATTERN.findall(text.lower()))))


class PalliumService:
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._consolidation_capability = ConsolidationCapability()

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
        plugin_name = source_item.use_case or self._default_use_case
        worker_label = worker_id or source_item.processing_claimed_by or "source-item-worker"
        try:
            plugin = self._semantic_plugins[plugin_name]
            if plugin.requires_visibility_context and source_item.visibility_context is None:
                self._storage.fail_source_item_processing(
                    source_item.id,
                    error="visibility_context_required",
                    next_attempt_at=None,
                    final=True,
                )
                return

            direct_result = plugin.process_item(source_item)
            thread_rebuild_scope = self._build_thread_processing_scope(
                plugin_name=plugin_name,
                plugin=plugin,
                source_item=source_item,
            )
            self._storage.commit_processed_source_item(
                source_item_id=source_item.id,
                result=direct_result,
                supersession_pairs=[],
                thread_rebuild_scope=thread_rebuild_scope,
            )
        except Exception as exc:
            error = self._truncate_processing_error(exc)
            if source_item.processing_attempts >= max_attempts:
                self._storage.fail_source_item_processing(
                    source_item.id,
                    error=error,
                    next_attempt_at=None,
                    final=True,
                )
                return
            backoff_seconds = self._queue_backoff_seconds(source_item.processing_attempts)
            self._storage.fail_source_item_processing(
                source_item.id,
                error=error,
                next_attempt_at=source_item.processing_claimed_at + timedelta(seconds=backoff_seconds)
                if source_item.processing_claimed_at is not None
                else None,
                final=False,
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
        include_trace: bool = False,
    ) -> QueryResult:
        filters: QueryFilters | None = build_query_filters(
            source_type=source_type,
            role=role,
            artifact_kind=artifact_kind,
            container_ref=container_ref,
            thread_ref=thread_ref,
            session_ref=session_ref,
        )
        plugin = self._semantic_plugins[self._default_use_case]
        if plugin.requires_visibility_context and visibility_context is None:
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=_query_tokens(text),
                    limit=limit,
                    filters=filters,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_visibility_context=None,
                        expanded_visibility_contexts=tuple(),
                        fail_closed_reason="query_visibility_context_required",
                    ),
                )
            return QueryResult(results=[], trace=trace)

        route_query_results = getattr(plugin, "route_query_results", None)
        retrieval_limit = limit
        if callable(route_query_results):
            retrieval_limit = min(max(limit * 4, 12), 50)
        retrieval_result = self._retrieval.query(
            text=text,
            limit=retrieval_limit,
            filters=filters,
            visibility_context=visibility_context if plugin.requires_visibility_context else None,
            include_trace=include_trace,
        )
        if callable(route_query_results):
            routed_results, routed_trace = route_query_results(
                text=text,
                requested_limit=limit,
                retrieval_result=retrieval_result,
                query_filters=filters,
            )
            return QueryResult(results=routed_results, trace=routed_trace)
        return QueryResult(results=retrieval_result.results, trace=retrieval_result.trace)

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
            try:
                thread_result, supersede_plan = self._maybe_rebuild_thread_summary(
                    plugin=plugin,
                    thread_scope=current_lease.as_scope(),
                )
                if thread_result is not None:
                    supersession_pairs = [
                        (superseded_id, replacement_id)
                        for replacement_id, superseded_ids in supersede_plan.items()
                        for superseded_id in superseded_ids
                    ]
                    self._storage.commit_process_result(
                        result=thread_result,
                        supersession_pairs=supersession_pairs,
                    )
            except Exception:
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
    ) -> tuple[ProcessResult | None, dict[str, list[str]]]:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None, {}

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
            return None, {}

        active_thread_memory_ids = self._find_active_thread_memory_ids(thread_items)
        aggregate = build_thread_aggregate(thread_items)
        conclusions = self._collect_thread_conclusions(thread_items)
        thread_result = plugin.build_thread_summary(aggregate, conclusions)
        supersede_plan: dict[str, list[str]] = {}
        for memory_object in thread_result.memory_objects:
            key = (memory_object.type, memory_object.schema_id)
            supersede_plan[memory_object.id] = [
                superseded_id
                for superseded_id in active_thread_memory_ids.get(key, [])
                if superseded_id != memory_object.id
            ]
        return thread_result, supersede_plan

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