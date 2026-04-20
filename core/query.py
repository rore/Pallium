from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from core.contracts import PackageQueryOutcome, QueryResult, resolve_query_filters
from core.filters import matches_filters
from core.models import QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace
from core.observability import QueryStats
from core.type_registry import TypeRegistry
from core.visibility import QueryVisibilityTrace, is_visible
from retrieval.base import RetrievalProvider
from retrieval.lexical import tokenize_query
from semantic.base import SemanticPlugin
from storage.base import StorageProvider


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


class QueryExecutor:
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
        type_registry: TypeRegistry | None = None,
        routing_overrides=None,
        query_stats: QueryStats | None = None,
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case
        self._type_registry = type_registry
        self._routing_overrides = routing_overrides
        self._query_stats = query_stats

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
    ) -> QueryResult:
        filter_resolution = resolve_query_filters(
            source_type=source_type,
            role=role,
            artifact_kind=artifact_kind,
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=actor_ref,
            work_refs=work_refs,
            runtime_context=runtime_context,
        )
        requested_filters = filter_resolution.requested_filters
        effective_filters = filter_resolution.effective_filters
        plugin = self._semantic_plugins[self._default_use_case]
        if plugin.requires_visibility_context and (container_ref is None or visibility is None):
            trace = None
            if include_trace:
                trace = QueryTrace(
                    query_text=text,
                    query_tokens=tokenize_query(text),
                    limit=limit,
                    filters=effective_filters,
                    requested_filters=requested_filters,
                    filter_scope_relaxed=filter_resolution.filter_scope_relaxed,
                    filter_scope_reason=filter_resolution.filter_scope_reason,
                    stages=tuple(),
                    visibility=QueryVisibilityTrace(
                        query_visibility=visibility,
                        query_container_ref=container_ref,
                        fail_closed_reason="query_visibility_context_required",
                    ),
                )
                trace = replace(trace, result_summary=_build_query_result_summary([]))
            result = QueryResult(
                results=[],
                trace=trace,
                should_inject=False,
                decision_reason="no_relevant_memory",
                injectable_blocks=[],
            )
            if self._query_stats is not None:
                self._query_stats.record_query(result)
            return result

        # Routing is a core responsibility. Call it directly when a
        # routing-capable plugin is the default (requires visibility context).
        # Plugins that don't require visibility (e.g., demo) skip routing.
        has_routing = hasattr(plugin, "route_query_results") or self._type_registry is not None
        retrieval_limit = limit
        if has_routing:
            retrieval_limit = min(max(limit * 4, 12), 50)
        retrieval_result = self._retrieval.query(
            text=text,
            limit=retrieval_limit,
            filters=effective_filters,
            visibility=visibility if plugin.requires_visibility_context else None,
            query_container_ref=container_ref if plugin.requires_visibility_context else None,
            include_trace=include_trace,
            require_visibility=plugin.requires_visibility_context,
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
        if has_routing:
            from core.routing import route_query_results as core_route
            outcome = core_route(
                text=text,
                requested_limit=limit,
                retrieval_result=retrieval_result,
                query_filters=requested_filters,
                runtime_context=runtime_context,
                include_trace=include_trace,
                debug_candidate_loader=self._make_debug_candidate_loader(
                    filters=effective_filters,
                    visibility=visibility if plugin.requires_visibility_context else None,
                    query_container_ref=container_ref if plugin.requires_visibility_context else None,
                    require_visibility=plugin.requires_visibility_context,
                ),
                routing_overrides=self._routing_overrides,
                type_registry=self._type_registry,
            )
            if not isinstance(outcome, PackageQueryOutcome):
                raise TypeError("route_query_results must return PackageQueryOutcome")
            routed_trace = outcome.trace
            if routed_trace is not None:
                routed_trace = replace(routed_trace, result_summary=_build_query_result_summary(outcome.results))
            result = QueryResult(
                results=outcome.results,
                trace=routed_trace,
                should_inject=outcome.should_inject,
                decision_reason=outcome.decision_reason,
                injectable_blocks=outcome.injectable_blocks,
            )
            if self._query_stats is not None:
                self._query_stats.record_query(result)
            return result
        trace = retrieval_result.trace
        if trace is not None:
            trace = replace(trace, result_summary=_build_query_result_summary(retrieval_result.results))
        result = QueryResult(
            results=retrieval_result.results,
            trace=trace,
            should_inject=False,
            decision_reason="injection_policy_unavailable",
            injectable_blocks=[],
        )
        if self._query_stats is not None:
            self._query_stats.record_query(result)
        return result

    def _make_debug_candidate_loader(
        self,
        *,
        filters: QueryFilters | None,
        visibility: str | None,
        query_container_ref: str | None,
        require_visibility: bool = False,
    ):
        if require_visibility and query_container_ref is None:
            def load_candidates(*, memory_types: list[str] | None = None) -> list[QueryResultItem]:
                return []
            return load_candidates

        def load_candidates(*, memory_types: list[str] | None = None) -> list[QueryResultItem]:
            results: list[QueryResultItem] = []
            for memory_object in self._storage.list_memory_objects(memory_types=memory_types, lifecycle="active"):
                if require_visibility and not is_visible(memory_object.visibility, memory_object.container_ref, query_container_ref, getattr(memory_object, 'actor_ref', None)):
                    continue
                # Use the canonical matches_filters to stay consistent with
                # the retrieval path (handles lifecycle, thread_ref relaxation,
                # public visibility exception, and shared-memory actor_ref
                # relaxation).  The lifecycle="active" pre-filter above makes
                # the lifecycle re-check inside matches_filters redundant but
                # harmless — this only runs on /query/debug.
                if not matches_filters(
                    self._storage.get_memory_object,
                    self._storage.get_source_item,
                    self._storage.get_evidence_for_memory_object,
                    "memory_object",
                    memory_object.id,
                    filters,
                ):
                    continue
                evidence = self._storage.get_evidence_for_memory_object(memory_object.id)
                results.append(
                    QueryResultItem(
                        result_kind="memory_hit",
                        memory_object_id=memory_object.id,
                        type=memory_object.type,
                        payload=memory_object.payload,
                        freshness_at=memory_object.freshness_at,
                        envelope=memory_object.envelope,
                        score=0,
                        evidence=evidence,
                        visibility=memory_object.visibility,
                    )
                )
            return results

        return load_candidates
