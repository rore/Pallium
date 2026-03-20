from __future__ import annotations

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import PackageQueryOutcome, ProcessResult
from core.models import MemoryObject, QueryFilters, QueryRuntimeContext, SourceItem
from providers.llm.base import LLMProvider
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from semantic.agent_conversation_memory_constraints import (
    _build_constraint_state,
    _structured_constraint_profile_from_payload,
    _structured_text_conflicts_with_constraint,
    reconcile_process_result_against_active_constraints,
)
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
        resolver_config: dict[str, object] | None = None,
        routing_overrides: RoutingOverrides | None = None,
    ) -> None:
        self._provider = provider
        self._delegate = LLMAgentMemoryPlugin(provider=provider, prompt_variant=prompt_variant)
        self._consolidation_config = consolidation_config
        self._resolver_config = resolver_config
        self._routing_overrides = routing_overrides

    @property
    def prompt_variant(self) -> str:
        return self._delegate.prompt_variant

    @property
    def thread_summary_schema_id(self) -> str:
        return 'agent_conversation_memory.thread_summary'

    @property
    def consolidation_policy(self) -> ConsolidationPolicy | None:
        return self._consolidation_config

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
        direct_result = _append_typed_constraint_memory_objects(
            direct_trace.process_result,
            source_item=source_item,
            extraction=direct_trace.extraction,
        )
        direct_result = _apply_direct_memory_envelopes(
            direct_result,
            source_item=source_item,
            extraction=direct_trace.extraction,
        )
        return ProcessResult(
            annotations=direct_result.annotations,
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

    def reconcile_process_result(
        self,
        result: ProcessResult,
        *,
        storage,
        container_ref: str | None,
        visibility_context,
    ) -> ProcessResult:
        return reconcile_process_result_against_active_constraints(
            result,
            storage=storage,
            container_ref=container_ref,
            visibility_context=visibility_context,
        )

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
            resolver_config=self._resolver_config,
            routing_overrides=self._routing_overrides,
        )

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        if not source_item.thread_ref or not source_item.container_ref:
            return False
        if source_item.visibility_context is None:
            return False
        return _supports_thread_aggregation(source_item)

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        return memory_object.visibility_context is not None and memory_object.type in {'thread_summary', 'decision', 'investigation_outcome'}

    def build_thread_summary(self, aggregate: ThreadAggregate, conclusions: list[MemoryObject]) -> ProcessResult:
        return build_thread_summary(
            provider=self._provider,
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            thread_summary_schema_id=self.thread_summary_schema_id,
            task_checkpoint_schema_id=self.task_checkpoint_schema_id,
            aggregate=aggregate,
            conclusions=conclusions,
        )

    def build_consolidated_memory(self, group: ConsolidationGroup) -> ProcessResult:
        return build_consolidated_memory(
            provider=self._provider,
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            pattern_memory_schema_id=self.pattern_memory_schema_id,
            continuity_memory_schema_id=self.continuity_memory_schema_id,
            group=group,
        )

    def build_pattern_memory(self, group: ConsolidationGroup) -> ProcessResult:
        return build_pattern_memory(
            provider=self._provider,
            prompt_variant=self.prompt_variant,
            plugin_name=self.name,
            pattern_memory_schema_id=self.pattern_memory_schema_id,
            group=group,
        )
