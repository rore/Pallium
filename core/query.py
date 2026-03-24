from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from typing import Any

from core.contracts import PackageQueryOutcome, QueryResult, resolve_query_filters
from core.models import QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace
from core.visibility import QueryVisibilityTrace, is_visible
from retrieval.base import RetrievalProvider
from semantic.base import SemanticPlugin
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _query_tokens(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(TOKEN_PATTERN.findall(text.lower()))))


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
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case

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
                    query_tokens=_query_tokens(text),
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
                    visibility=visibility if plugin.requires_visibility_context else None,
                    query_container_ref=container_ref if plugin.requires_visibility_context else None,
                    require_visibility=plugin.requires_visibility_context,
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
                        envelope=memory_object.envelope,
                        score=0,
                        evidence=evidence,
                        visibility=memory_object.visibility,
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
        return True
