from __future__ import annotations

import logging
from typing import Callable

from capabilities.consolidation import ConsolidationCapability, ConsolidationRunGroupResult, ConsolidationRunResult
from core.contracts import ProcessResult
from core.models import MemoryObject, Relation
from core.observability import IntegrationDebugLogger
from core.visibility import visibility_matches_exact
from semantic.base import ConsolidationSemanticPlugin, SemanticPlugin
from storage.base import StorageProvider


class ConsolidationRunner:
    """Runs consolidation passes: candidate selection, grouping, synthesis, and supersession.

    Extracted from PalliumService to reduce its orchestration surface.
    """

    def __init__(
        self,
        storage: StorageProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        observability: IntegrationDebugLogger,
        persist_fn: Callable[[ProcessResult], None],
        supersede_fn: Callable[[str, str], None],
    ) -> None:
        self._storage = storage
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._observability = observability
        self._persist_fn = persist_fn
        self._supersede_fn = supersede_fn
        self._consolidation_capability = ConsolidationCapability()
        self._logger = logging.getLogger(__name__)

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
            self._persist_fn(promoted)

            superseded_ids: list[str] = []
            for memory_object in synthesized.memory_objects:
                for active_memory_id in self._find_active_consolidated_memory_ids(group, memory_object):
                    if active_memory_id == memory_object.id or active_memory_id in superseded_ids:
                        continue
                    self._supersede_fn(active_memory_id, memory_object.id)
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
            if not visibility_matches_exact(memory_object.container_visibility, created_memory_object.container_visibility):
                continue
            provenance = memory_object.payload.get("consolidation_provenance", {})
            if provenance.get("strategy_name") != group.strategy_name:
                continue
            if memory_object.payload.get("group_key") != group.group_key:
                continue
            ids.append(memory_object.id)
        return ids
