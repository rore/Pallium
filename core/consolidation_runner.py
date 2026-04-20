from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from capabilities.consolidation import ConsolidationCapability, ConsolidationGroup, ConsolidationRunGroupResult, ConsolidationRunResult
from core.contracts import ProcessResult
from core.models import MemoryObject, Relation
from core.observability import IntegrationDebugLogger
from core.visibility import visibility_matches_exact, visibility_label
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
        container_ref: str | None = None,
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
            container_ref=container_ref,
        )
        groups = self._consolidation_capability.group_candidates(
            strategy=strategy,
            candidates=candidates,
            policy=policy,
        )

        if not groups:
            return None

        group_results: list[ConsolidationRunGroupResult] = []
        for group in groups:
            created_ids, created_types, superseded_ids = self._process_consolidation_group(plugin, group)

            group_results.append(
                ConsolidationRunGroupResult(
                    strategy_name=group.strategy_name,
                    strategy_version=group.strategy_version,
                    group_key=group.group_key,
                    selected_candidate_ids=group.candidate_ids,
                    selected_source_item_ids=group.supporting_source_ids,
                    candidate_thread_refs=tuple(candidate.thread_ref for candidate in group.candidates),
                    created_memory_ids=tuple(created_ids),
                    created_memory_types=tuple(created_types),
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

    def run_targeted_consolidation(
        self,
        use_case: str,
        container_ref: str,
        subjects: list[str],
    ) -> None:
        """Run fact consolidation for specific subjects after a thread rebuild.

        Loads only facts/summaries for the given subjects in the given container,
        builds groups directly (bypassing MIN_GROUP_SIZE/MIN_DISTINCT_THREADS since
        the trigger already confirmed cross-thread relevance), and runs the
        consolidation LLM call per group.
        """
        plugin_name = use_case
        plugin = self._semantic_plugins.get(plugin_name)
        if plugin is None or not isinstance(plugin, ConsolidationSemanticPlugin):
            return

        # Targeted candidate selection: only facts for these subjects in this container
        memory_objects = self._storage.list_memory_objects(
            memory_types=["atomic_fact", "fact_summary"],
            lifecycle="active",
            container_ref=container_ref,
            subject_in=subjects,
        )
        candidates = [
            self._consolidation_capability.build_candidate(self._storage, mo)
            for mo in memory_objects
            if plugin.supports_consolidation(mo)
        ]
        candidates = [c for c in candidates if c is not None]
        if len(candidates) < 2:
            return

        # Build groups directly by (subject, category), bypassing strategy's
        # MIN_GROUP_SIZE and MIN_DISTINCT_THREADS. The trigger already confirmed
        # cross-thread relevance; a fact_summary (thread_ref=None) + new atomic_fact
        # from one thread is a valid group for re-consolidation.
        groups = self._build_targeted_groups(candidates, container_ref)

        for group in groups:
            self._process_consolidation_group(plugin, group)

    TARGETED_MAX_GROUP_SIZE = 8

    def _build_targeted_groups(
        self,
        candidates: list,
        container_ref: str | None,
    ) -> list[ConsolidationGroup]:
        """Build consolidation groups by (subject, category) without min-size/thread checks."""
        from capabilities.consolidation import _sort_candidates

        grouped: dict[tuple[str, str, str], list] = defaultdict(list)
        for candidate in candidates:
            payload = candidate.memory_object.payload
            subject = str(payload.get("subject", "")).strip().lower()
            category = str(payload.get("category", "")).strip().lower()
            visibility = candidate.visibility
            if not subject or not category:
                continue
            grouped[(subject, category, visibility)].append(candidate)

        groups: list[ConsolidationGroup] = []
        for (subject, category, visibility), members in grouped.items():
            if len(members) < 2:
                continue
            ordered = list(_sort_candidates(members))
            original_subject = str(ordered[0].memory_object.payload.get("subject", "")).strip()
            original_category = str(ordered[0].memory_object.payload.get("category", "")).strip()
            group_key = f"fact_consolidation:{visibility_label(visibility)}:{container_ref or 'none'}:{subject}:{category}"

            if len(ordered) <= self.TARGETED_MAX_GROUP_SIZE:
                latest = max(c.latest_occurred_at for c in ordered)
                groups.append(
                    ConsolidationGroup(
                        strategy_name="fact_consolidation",
                        strategy_version="v1",
                        group_key=group_key,
                        candidates=tuple(ordered),
                        container_ref=container_ref,
                        thread_ref=None,
                        latest_occurred_at=latest,
                        visibility=visibility,
                        merge_rationale={
                            "grouping_mode": "fact_consolidation",
                            "container_ref": container_ref,
                            "subject": original_subject,
                            "category": original_category,
                            "fact_count": len(ordered),
                        },
                    )
                )
            else:
                # Split oversized groups: exclude prior fact_summaries, split
                # atomic_facts into sub-groups by recency.
                atomic_facts = [c for c in ordered if c.memory_object.type != "fact_summary"]
                prior_summaries = [c for c in ordered if c.memory_object.type == "fact_summary"]
                # First sub-group: prior summaries + as many atomic_facts as fit
                if prior_summaries:
                    first_batch_size = max(1, self.TARGETED_MAX_GROUP_SIZE - len(prior_summaries))
                    first_batch = prior_summaries + atomic_facts[:first_batch_size]
                    remaining_facts = atomic_facts[first_batch_size:]
                else:
                    first_batch = atomic_facts[:self.TARGETED_MAX_GROUP_SIZE]
                    remaining_facts = atomic_facts[self.TARGETED_MAX_GROUP_SIZE:]

                if len(first_batch) >= 2:
                    latest = max(c.latest_occurred_at for c in first_batch)
                    groups.append(
                        ConsolidationGroup(
                            strategy_name="fact_consolidation",
                            strategy_version="v1",
                            group_key=group_key,
                            candidates=tuple(first_batch),
                            container_ref=container_ref,
                            thread_ref=None,
                            latest_occurred_at=latest,
                            visibility=visibility,
                            merge_rationale={
                                "grouping_mode": "fact_consolidation",
                                "grouping_note": "split_first_batch",
                                "container_ref": container_ref,
                                "subject": original_subject,
                                "category": original_category,
                                "fact_count": len(first_batch),
                            },
                        )
                    )

                # Remaining sub-groups: atomic_facts only, max_group_size each
                for i in range(0, len(remaining_facts), self.TARGETED_MAX_GROUP_SIZE):
                    batch = remaining_facts[i:i + self.TARGETED_MAX_GROUP_SIZE]
                    if len(batch) < 2:
                        continue
                    latest = max(c.latest_occurred_at for c in batch)
                    groups.append(
                        ConsolidationGroup(
                            strategy_name="fact_consolidation",
                            strategy_version="v1",
                            group_key=group_key,
                            candidates=tuple(batch),
                            container_ref=container_ref,
                            thread_ref=None,
                            latest_occurred_at=latest,
                            visibility=visibility,
                            merge_rationale={
                                "grouping_mode": "fact_consolidation",
                                "grouping_note": "split_overflow_batch",
                                "container_ref": container_ref,
                                "subject": original_subject,
                                "category": original_category,
                                "fact_count": len(batch),
                            },
                        )
                    )

        return groups

    def _process_consolidation_group(
        self,
        plugin: ConsolidationSemanticPlugin,
        group: ConsolidationGroup,
    ) -> tuple[list[str], list[str], list[str]]:
        """Synthesize a consolidation group, persist result, and supersede inputs.

        Returns (created_memory_ids, created_memory_types, superseded_ids).
        """
        synthesized = self._consolidation_capability.synthesize_group(plugin=plugin, group=group)
        if not synthesized.memory_objects:
            return [], [], []
        promoted = ProcessResult(
            memory_objects=synthesized.memory_objects,
            relations=[
                *synthesized.relations,
                *self._build_consolidation_relations(group, synthesized.memory_objects),
            ],
            index_entries=synthesized.index_entries,
        )
        self._persist_fn(promoted)

        superseded_ids: set[str] = set()
        created_memory_ids = {mo.id for mo in synthesized.memory_objects}

        # Supersede prior fact_summaries with the same group_key (same-type)
        for memory_object in synthesized.memory_objects:
            for active_memory_id in self._find_active_consolidated_memory_ids(group, memory_object):
                if active_memory_id == memory_object.id or active_memory_id in superseded_ids:
                    continue
                self._supersede_fn(active_memory_id, memory_object.id)
                superseded_ids.add(active_memory_id)
                self._storage.retarget_index_entries_for_target(
                    "memory_object", active_memory_id, memory_object.id,
                )

        # For fact_consolidation: supersede ALL input candidates because the
        # fact_summary replaces all inputs as the canonical representation.
        # Other strategies (thread_summary_anchored, etc.) keep their inputs active.
        if group.strategy_name == "fact_consolidation":
            replacement_id = synthesized.memory_objects[0].id
            for candidate_id in group.candidate_ids:
                if candidate_id in superseded_ids or candidate_id in created_memory_ids:
                    continue
                try:
                    candidate = self._storage.get_memory_object(candidate_id)
                except KeyError:
                    continue
                if candidate.lifecycle == "superseded":
                    continue
                # Cross-type supersession (fact_summary supersedes atomic_fact):
                # uses storage directly because supersede_fn requires matching types.
                self._storage.update_memory_object_lifecycle(candidate_id, "superseded")
                self._storage.create_relation(
                    Relation(
                        from_kind="memory_object",
                        from_id=replacement_id,
                        relation_type="supersedes",
                        to_kind="memory_object",
                        to_id=candidate_id,
                    )
                )
                self._storage.retarget_index_entries_for_target(
                    "memory_object", candidate_id, replacement_id,
                )
                superseded_ids.add(candidate_id)

        created_ids = [mo.id for mo in synthesized.memory_objects]
        created_types = [mo.type for mo in synthesized.memory_objects]
        return created_ids, created_types, list(superseded_ids)

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
        group_candidate_ids = set(group.candidate_ids)
        ids: list[str] = []
        for memory_object in self._storage.list_memory_objects(
            memory_types=[created_memory_object.type],
            lifecycle="active",
            container_ref=group.container_ref,
        ):
            if memory_object.schema_id != created_memory_object.schema_id:
                continue
            if not visibility_matches_exact(memory_object.visibility, created_memory_object.visibility):
                continue
            provenance = memory_object.payload.get("consolidation_provenance", {})
            if provenance.get("strategy_name") != group.strategy_name:
                continue
            if memory_object.payload.get("group_key") != group.group_key:
                continue
            # For fact_consolidation, only supersede summaries that were
            # candidates in this group. This protects frozen summaries that
            # were excluded from candidacy by the package's
            # supports_consolidation guard.
            if group.strategy_name == "fact_consolidation" and memory_object.id not in group_candidate_ids:
                continue
            ids.append(memory_object.id)
        return ids
