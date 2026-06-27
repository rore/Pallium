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
from semantic.agent_conversation_memory_routing_constants import ROUTING_LAYER_WEIGHTS


def _merge_registry_weights(
    base_weights: dict[str, dict[str, int]],
    registry: TypeRegistry,
) -> dict[str, dict[str, int]]:
    """Merge type-registry weights into the base layer weights.

    For each intent in the base weights, adds any registry-provided
    types that are not already present. This ensures new packages'
    types are automatically visible to routing without manual patches
    to the constants module.
    """
    merged = {intent: dict(weights) for intent, weights in base_weights.items()}
    for reg in registry.all_types():
        for intent, intent_weights in merged.items():
            if reg.type_name not in intent_weights:
                intent_weights[reg.type_name] = reg.weight_by_intent.get(intent, reg.default_weight)
    return merged


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
    injection_policy=None,
) -> PackageQueryOutcome:
    """Route query results through the scoring/selection pipeline.

    This is the core entry point. Packages do not implement routing —
    they register their types with the TypeRegistry and the core
    routing pipeline handles scoring, selection, and injection.

    `injection_policy` is an optional InjectionPolicyConfig (from
    app/config.py). When None or empty, behavior is unchanged
    (Phase 3a default). See
    docs/specs/2026-06-27-injection-policy-abstention.md.
    """
    effective_overrides = dict(routing_overrides) if routing_overrides else {}

    # Merge registry-provided weights into the layer weights so new
    # memory types are automatically scored by routing.
    if type_registry is not None and len(type_registry) > 0:
        base_weights = effective_overrides.get("layer_weights") or ROUTING_LAYER_WEIGHTS
        effective_overrides["layer_weights"] = _merge_registry_weights(base_weights, type_registry)

    return _route_query_results(
        text=text,
        requested_limit=requested_limit,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=runtime_context,
        include_trace=include_trace,
        debug_candidate_loader=debug_candidate_loader,
        routing_overrides=effective_overrides or None,
        injection_policy=injection_policy,
    )
