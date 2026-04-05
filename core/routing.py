"""Core query routing — delegates to the routing pipeline.

Routing is a Pallium core responsibility. This module provides the
entry point that QueryExecutor calls directly, instead of delegating
to a package's route_query_results() method.

The actual routing pipeline stages live in
semantic/agent_conversation_memory_routing*.py for now. They will be
physically relocated to core/routing/ as a follow-up refactor. This
module establishes the core ownership boundary.
"""
from __future__ import annotations

from core.contracts import PackageQueryOutcome
from core.models import QueryFilters, QueryRuntimeContext
from core.type_registry import TypeRegistry
from semantic.agent_conversation_memory_routing import RoutingOverrides, route_query_results as _route_query_results


def route_query_results(
    *,
    text: str,
    requested_limit: int,
    retrieval_result,
    query_filters: QueryFilters | None = None,
    runtime_context: QueryRuntimeContext | None = None,
    include_trace: bool = False,
    debug_candidate_loader=None,
    routing_overrides: RoutingOverrides | None = None,
    type_registry: TypeRegistry | None = None,
) -> PackageQueryOutcome:
    """Route query results through the scoring/selection pipeline.

    This is the core entry point. Packages do not implement routing —
    they register their types with the TypeRegistry and the core
    routing pipeline handles scoring, selection, and injection.
    """
    # Delegate to the existing routing implementation.
    # The type_registry parameter is accepted but not yet used —
    # the existing implementation reads from hardcoded constants.
    # Future refactoring will replace those constants with registry lookups.
    return _route_query_results(
        text=text,
        requested_limit=requested_limit,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=runtime_context,
        include_trace=include_trace,
        debug_candidate_loader=debug_candidate_loader,
        routing_overrides=routing_overrides,
    )
