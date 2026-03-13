from __future__ import annotations

import re

from capabilities.consolidation import ConsolidationCapability, ConsolidationRunGroupResult, ConsolidationRunResult
from capabilities.thread_aggregation import build_thread_aggregate
from core.contracts import IngestResult, ProcessResult, QueryResult, build_query_filters, build_source_item
from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, build_index_entry
from core.models import MemoryObject, QueryFilters, QueryTrace, Relation, SourceItem
from core.visibility import QueryVisibilityTrace, VisibilityContext, visibility_context_matches_exact
from retrieval.base import RetrievalProvider
from semantic.base import ConsolidationSemanticPlugin, SemanticPlugin, ThreadAggregationSemanticPlugin
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
THREAD_CONCLUSION_TYPES = {"decision", "investigation_outcome"}
THREAD_SUMMARY_TYPE = "thread_summary"


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
            annotations = self._storage.list_annotations_for_source_item(existing_source_item.id)
            memory_objects = self._storage.list_memory_objects_for_source_item(existing_source_item.id)
            relations = self._storage.list_relations_for_source_item(existing_source_item.id)
            index_entries = self._storage.list_index_entries_for_target(
                target_kind="source_item",
                target_id=existing_source_item.id,
            )
            for memory_object in memory_objects:
                index_entries.extend(
                    self._storage.list_index_entries_for_target(
                        target_kind="memory_object",
                        target_id=memory_object.id,
                    )
                )
            return IngestResult(
                source_item_id=existing_source_item.id,
                annotation_ids=[item.id for item in annotations],
                memory_object_ids=[item.id for item in memory_objects],
                relation_ids=[item.id for item in relations],
                index_entry_ids=[item.id for item in index_entries],
            )

        plugin_name = use_case or self._default_use_case
        plugin = self._semantic_plugins[plugin_name]

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
        )
        self._storage.create_source_item(source_item)

        source_index_entry = build_index_entry(
            target_kind="source_item",
            target_id=source_item.id,
            index_type="lexical",
            text_view=_normalize_for_index(source_item.content),
            text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
        )
        self._storage.create_index_entry(source_index_entry)

        derived = ProcessResult(annotations=[], memory_objects=[], relations=[], index_entries=[])
        thread_result = None
        if not (plugin.requires_visibility_context and source_item.visibility_context is None):
            derived = plugin.process_item(source_item)
            self._persist_process_result(derived)
            thread_result = self._maybe_rebuild_thread_summary(plugin=plugin, source_item=source_item)

        annotation_ids = [item.id for item in derived.annotations]
        memory_object_ids = [item.id for item in derived.memory_objects]
        relation_ids = [item.id for item in derived.relations]
        index_entry_ids = [source_index_entry.id, *[item.id for item in derived.index_entries]]
        if thread_result is not None:
            annotation_ids.extend(item.id for item in thread_result.annotations)
            memory_object_ids.extend(item.id for item in thread_result.memory_objects)
            relation_ids.extend(item.id for item in thread_result.relations)
            index_entry_ids.extend(item.id for item in thread_result.index_entries)

        return IngestResult(
            source_item_id=source_item.id,
            annotation_ids=annotation_ids,
            memory_object_ids=memory_object_ids,
            relation_ids=relation_ids,
            index_entry_ids=index_entry_ids,
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

    def _maybe_rebuild_thread_summary(
        self,
        *,
        plugin: SemanticPlugin,
        source_item: SourceItem,
    ) -> ProcessResult | None:
        if not isinstance(plugin, ThreadAggregationSemanticPlugin):
            return None
        if not plugin.supports_thread_aggregation(source_item):
            return None
        if not source_item.container_ref or not source_item.thread_ref:
            return None

        thread_items = [
            item
            for item in self._storage.list_source_items_for_thread(source_item.container_ref, source_item.thread_ref)
            if plugin.supports_thread_aggregation(item)
        ]
        if plugin.requires_visibility_context:
            thread_items = [
                item
                for item in thread_items
                if visibility_context_matches_exact(item.visibility_context, source_item.visibility_context)
            ]
        if not thread_items:
            return None

        active_thread_memory_ids = self._find_active_thread_memory_ids(thread_items)
        aggregate = build_thread_aggregate(thread_items)
        conclusions = self._collect_thread_conclusions(thread_items)
        thread_result = plugin.build_thread_summary(aggregate, conclusions)
        self._persist_process_result(thread_result)

        if thread_result.memory_objects:
            for memory_object in thread_result.memory_objects:
                key = (memory_object.type, memory_object.schema_id)
                for superseded_id in active_thread_memory_ids.get(key, []):
                    if superseded_id != memory_object.id:
                        self.supersede_memory_object(superseded_id, memory_object.id)

        return thread_result

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

    def _collect_thread_conclusions(self, thread_items: list[SourceItem]) -> list[MemoryObject]:
        conclusions: dict[str, MemoryObject] = {}
        for source_item in thread_items:
            for memory_object in self._storage.list_memory_objects_for_source_item(source_item.id):
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