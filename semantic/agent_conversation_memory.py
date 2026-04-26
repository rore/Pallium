from __future__ import annotations

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import MemoryRetentionPolicy, PackageQueryOutcome, ProcessResult
from core.models import MemoryObject, QueryFilters, QueryRuntimeContext, SourceItem
from core.type_registry import TypeRegistration, TypeRegistry
from providers.llm.base import LLMProvider
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects, _apply_direct_memory_envelopes, build_supersession_hints
from semantic.agent_conversation_memory_routing import RoutingOverrides, route_query_results
from semantic.agent_conversation_memory_threads import _supports_thread_aggregation, build_consolidated_memory, build_pattern_memory, build_thread_summary


class AgentConversationMemoryPlugin(ThreadAggregationSemanticPlugin, ConsolidationSemanticPlugin):
    name = 'agent_conversation_memory'

    @property
    def requires_visibility_context(self) -> bool:
        return True

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_variant: str,
        consolidation_config: ConsolidationPolicy | None = None,
        routing_overrides: RoutingOverrides | None = None,
        providers_by_role: dict[str, LLMProvider] | None = None,
    ) -> None:
        self._provider = provider
        self._providers_by_role = providers_by_role or {}
        write_extraction_provider = self._provider_for_role("write_extraction")
        self._delegate = LLMAgentMemoryPlugin(provider=write_extraction_provider, prompt_variant=prompt_variant)
        self._consolidation_config = consolidation_config
        self._routing_overrides = routing_overrides

    def _provider_for_role(self, role: str) -> LLMProvider:
        if self._providers_by_role and role in self._providers_by_role:
            return self._providers_by_role[role]
        return self._provider

    @property
    def prompt_variant(self) -> str:
        return self._delegate.prompt_variant

    @property
    def thread_summary_schema_id(self) -> str:
        return 'agent_conversation_memory.thread_summary'

    @property
    def thread_conclusion_types(self) -> frozenset[str]:
        return frozenset({"decision", "investigation_outcome"})

    @property
    def consolidation_policy(self) -> ConsolidationPolicy | None:
        return self._consolidation_config

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy:
        return MemoryRetentionPolicy(
            durable_types=frozenset({"decision", "investigation_outcome"}),
            working_types=frozenset({"thread_summary", "task_checkpoint", "continuity_memory", "pattern_memory"}),
            orphan_delete_types=frozenset({"discussion_summary"}),
        )

    @property
    def pattern_memory_schema_id(self) -> str:
        return 'agent_conversation_memory.pattern_memory'

    @property
    def continuity_memory_schema_id(self) -> str:
        return 'agent_conversation_memory.continuity_memory'

    @property
    def task_checkpoint_schema_id(self) -> str:
        return 'agent_conversation_memory.task_checkpoint'

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        direct_trace = self._delegate.analyze_item(source_item)
        direct_result = direct_trace.process_result
        direct_result = _append_typed_constraint_memory_objects(
            direct_result,
            source_item=source_item,
            extraction=direct_trace.extraction,
        )
        direct_result = _apply_direct_memory_envelopes(
            direct_result,
            source_item=source_item,
            extraction=direct_trace.extraction,
        )
        return ProcessResult(
            memory_objects=direct_result.memory_objects,
            relations=direct_result.relations,
            index_entries=direct_result.index_entries,
            source_item_metadata_updates=direct_result.source_item_metadata_updates,
            thread_rebuild_requested=direct_result.thread_rebuild_requested,
            supersession_hints=build_supersession_hints(source_item, direct_result),
        )

    def source_item_embedding_text(self, source_item: SourceItem) -> str | None:
        from semantic.agent_conversation_memory_embedding import source_item_embedding_text
        return source_item_embedding_text(source_item)

    def route_query_results(
        self,
        *,
        text: str,
        requested_limit: int,
        retrieval_result,
        query_filters: QueryFilters | None = None,
        runtime_context: QueryRuntimeContext | None = None,
        include_trace: bool = False,
        debug_candidate_loader=None,
    ) -> PackageQueryOutcome:
        return route_query_results(
            text=text,
            requested_limit=requested_limit,
            retrieval_result=retrieval_result,
            query_filters=query_filters,
            runtime_context=runtime_context,
            include_trace=include_trace,
            debug_candidate_loader=debug_candidate_loader,
            routing_overrides=self._routing_overrides,
        )

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        if not source_item.container_ref:
            return False
        return _supports_thread_aggregation(source_item)

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        return memory_object.type in {'thread_summary', 'decision', 'investigation_outcome', 'atomic_fact'}

    def build_thread_summary(self, aggregate: ThreadAggregate, conclusions: list[MemoryObject]) -> ProcessResult:
        return build_thread_summary(
            provider=self._provider_for_role("thread_aggregation"),
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            thread_summary_schema_id=self.thread_summary_schema_id,
            task_checkpoint_schema_id=self.task_checkpoint_schema_id,
            aggregate=aggregate,
            conclusions=conclusions,
        )

    def build_consolidated_memory(self, group: ConsolidationGroup) -> ProcessResult:
        return build_consolidated_memory(
            provider=self._provider_for_role("consolidation"),
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            pattern_memory_schema_id=self.pattern_memory_schema_id,
            continuity_memory_schema_id=self.continuity_memory_schema_id,
            group=group,
        )

    def build_pattern_memory(self, group: ConsolidationGroup) -> ProcessResult:
        return build_pattern_memory(
            provider=self._provider_for_role("consolidation"),
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            pattern_memory_schema_id=self.pattern_memory_schema_id,
            group=group,
        )

    def register_routing_types(self, registry: TypeRegistry) -> None:
        """Register this package's memory types with the core type registry."""
        _TYPES = [
            TypeRegistration(
                type_name="decision", layer_name="decision",
                weight_by_intent={"recall": 150, "structured_recall": 220, "work_resumption": 145, "evidence_trace": 180},
                default_weight=150, block_title="Prior Decision", block_text_field="rationale", high_value=True,
            ),
            TypeRegistration(
                type_name="investigation_outcome", layer_name="investigation_outcome",
                weight_by_intent={"recall": 160, "structured_recall": 230, "work_resumption": 150, "evidence_trace": 190},
                default_weight=160, block_title="Prior Investigation", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="task_checkpoint", layer_name="task_checkpoint",
                weight_by_intent={"recall": 70, "structured_recall": 50, "work_resumption": 235, "evidence_trace": 45},
                default_weight=70, block_title="Task Checkpoint", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="pattern_memory", layer_name="pattern_memory",
                weight_by_intent={"recall": 130, "structured_recall": 35, "work_resumption": 35, "evidence_trace": 20},
                default_weight=80, block_title="Pattern Memory", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="continuity_memory", layer_name="continuity_memory",
                weight_by_intent={"recall": 145, "structured_recall": 60, "work_resumption": 90, "evidence_trace": 60},
                default_weight=90, block_title="Carry Forward", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="thread_summary", layer_name="thread_summary",
                weight_by_intent={"recall": 60, "structured_recall": 80, "work_resumption": 65, "evidence_trace": 60},
                default_weight=60, block_title="Thread Summary", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="discussion_summary", layer_name="discussion_summary",
                weight_by_intent={"recall": 40, "structured_recall": 50, "work_resumption": 35, "evidence_trace": 40},
                default_weight=40, block_title="Discussion Summary", block_text_field="summary", high_value=False,
            ),
            TypeRegistration(
                type_name="interest", layer_name="interest",
                weight_by_intent={"recall": 50, "structured_recall": 50, "work_resumption": 50, "evidence_trace": 43},
                default_weight=50, block_title="Interest", block_text_field="summary", high_value=True,
            ),
            TypeRegistration(
                type_name="constraint_memory", layer_name="constraint_memory",
                weight_by_intent={"recall": 200, "structured_recall": 120, "work_resumption": 245, "evidence_trace": 55},
                default_weight=120, block_title="Active Constraint", block_text_field="constraint", high_value=True,
            ),
        ]
        for t in _TYPES:
            registry.register(t)
