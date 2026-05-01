from __future__ import annotations

from core.contracts import PackageQueryOutcome
from core.models import QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace
from semantic.agent_conversation_memory_anchors import (
    _classify_memory_candidate_anchor_state,
    _infer_selected_query_anchor,
    _serialize_subject_anchor,
    _serialize_subject_anchors,
)
from semantic.agent_conversation_memory_routing_constants import (
    ANCHOR_SECONDARY_TIER_PENALTY,
    RECALL_MODE_WEIGHTS,
    ROUTING_FALLBACK_MARGIN,
    ROUTING_FAMILY_ALLOWED_ENVELOPE_KINDS,
    ROUTING_FOCUS_BOOST,
    ROUTING_LAYER_WEIGHTS,
    ROUTING_POLICY_NAME,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_SUPPORT_THRESHOLD,
    PolicySelectedContext,
    RoutingOverrides,
    _candidate_work_refs,
    _routing_query_tokens,
    _routing_result_id,
)
from semantic.agent_conversation_memory_routing_trace import (
    _build_lane_narrowing_trace,
    _build_routing_trace,
    _build_sharp_candidate_diagnostics,
    _build_signal_envelope_trace,
    _routing_reason,
)
from semantic.agent_conversation_memory_routing_signals import (
    _build_policy_evidence,
    _compute_typed_candidate_evidence,
    _derive_query_signal_envelope,
    _policy_family_from_signal_envelope,
    _select_recall_mode,
)
from semantic.agent_conversation_memory_routing_policy import (
    _determine_eligible_lanes,
)
from semantic.agent_conversation_memory_routing_scoring import (
    _ANCHOR_SECONDARY_STATUSES,
    _fresh_session_component,
    _freshness_component,
    _infer_query_intent,
    _routing_focus_adjustment,
    _score_routed_candidate,
    _select_routing_focus,
    _summarize_routing_layers,
    _usefulness_adjustment,
)
from semantic.agent_conversation_memory_routing_selection import (
    _annotate_excluded_candidates,
    _build_injectable_blocks,
    _candidate_is_injection_eligible,
    _select_final_candidates,
)
from semantic.agent_conversation_memory_routing_floor import apply_relevance_floor
from semantic.agent_conversation_memory_routing_suppression import apply_suppression
from semantic.agent_conversation_memory_routing_annotations import (
    annotate_freshness_ranks,
    annotate_work_resumption_context,
    compute_structured_support_ratio,
)

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility.
# Test files and eval scripts import these names from this module.
# Only names that are actually imported externally are listed here.
# ---------------------------------------------------------------------------
from semantic.agent_conversation_memory_routing_constants import (  # noqa: F401
    CONSTRAINT_MEMORY_TYPE,
    LaneEligibility,
    LaneNarrowingResult,
    PASSTHROUGH_POLICY,
    POLICY_SUPPORT_THRESHOLD,
    QUERY_POLICY_FAMILY_ALLOWED_INTENTS,
    QuerySignalEnvelope,
    is_query_topic_signal_empty,
)
from semantic.agent_conversation_memory_routing_signals import (  # noqa: F401
    _check_evidence_trace_override,
    _work_state_evidence_gate_passes,
)
from semantic.agent_conversation_memory_routing_policy import (  # noqa: F401
    _apply_policy_intent_restriction,
    _build_ambiguity_options,
    _classify_query_policy_family,
)

from dataclasses import replace as _dc_replace
from semantic.llm_agent_memory import _normalize_work_ref


def _detect_query_work_refs(
    query_text: str,
    candidates: list[QueryResultItem],
    query_filters: QueryFilters | None,
) -> QueryFilters | None:
    """Data-driven work_ref detection: check if candidate work_refs appear in query text.

    If query_filters already has work_refs (provided by integrating agent), return as-is.
    Otherwise, collect work_refs from candidates and check which ones appear as substrings
    in the normalized query text. Augment query_filters with detected refs.
    """
    if query_filters is not None and query_filters.work_refs:
        return query_filters
    # Collect all distinct work_refs from candidates
    candidate_refs: set[str] = set()
    for item in candidates:
        candidate_refs.update(_candidate_work_refs(item))
    if not candidate_refs:
        return query_filters
    # Normalize query text with the same separator collapse used for work_refs
    normalized_query = _normalize_work_ref(query_text) or ""
    if not normalized_query:
        return query_filters
    # Check which candidate work_refs appear as substrings in normalized query
    detected: list[str] = [ref for ref in candidate_refs if ref in normalized_query]
    if not detected:
        return query_filters
    # Augment query_filters with detected work_refs
    if query_filters is None:
        return QueryFilters(work_refs=tuple(sorted(detected)))
    return _dc_replace(query_filters, work_refs=tuple(sorted(detected)))


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
) -> PackageQueryOutcome:
        _ov = routing_overrides or {}
        _layer_weights: dict[str, dict[str, int]] = _ov.get("layer_weights") or ROUTING_LAYER_WEIGHTS
        _focus_boost: int = _ov.get("focus_boost", ROUTING_FOCUS_BOOST)  # type: ignore[assignment]
        _fallback_margin: int = _ov.get("fallback_margin", ROUTING_FALLBACK_MARGIN)  # type: ignore[assignment]
        _support_threshold: dict[str, int] = _ov.get("support_threshold") or ROUTING_SUPPORT_THRESHOLD
        query_tokens = _routing_query_tokens(text)
        # Step 0: Relevance floor — drop weak candidates before routing
        floor_result = apply_relevance_floor(retrieval_result.results)
        if not floor_result.survivors and retrieval_result.results:
            # All candidates filtered — substantive query but nothing matches well
            empty_trace = None
            if include_trace and retrieval_result.trace is not None:
                empty_trace = QueryTrace(
                    query_text=retrieval_result.trace.query_text,
                    query_tokens=retrieval_result.trace.query_tokens,
                    limit=requested_limit,
                    filters=retrieval_result.trace.filters,
                    stages=retrieval_result.trace.stages,
                    visibility=retrieval_result.trace.visibility,
                    requested_filters=retrieval_result.trace.requested_filters,
                    filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                    filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                    routing={"policy_name": ROUTING_POLICY_NAME,
                             "decision_reason": "no_candidates_above_floor",
                             "floor_filtered_count": floor_result.filtered_count,
                             "floor_filtered_score_ranges": floor_result.filtered_score_ranges},
                )
            return PackageQueryOutcome(
                results=[],
                trace=empty_trace,
                should_inject=False,
                decision_reason="no_candidates_above_floor",
                injectable_blocks=[],
                sharp_candidate_diagnostics=[],
            )
        floor_candidates = floor_result.survivors if floor_result.survivors else retrieval_result.results
        # Step 0b: Detect work_refs from candidates if not provided by integrating agent
        query_filters = _detect_query_work_refs(text, floor_candidates, query_filters)
        # Step 1: Family-independent anchor prefilter
        anchor_prefiltered_candidates, anchor_prefilter_summary, anchor_prefilter_states = _anchor_prefilter_candidates(
            floor_candidates,
            query_tokens=query_tokens,
        )
        # Step 2: Policy evidence + typed candidate evidence (language-agnostic)
        policy_evidence = _build_policy_evidence(anchor_prefiltered_candidates)
        candidate_evidence = _compute_typed_candidate_evidence(anchor_prefiltered_candidates, query_filters)
        # Step 3: Derive canonical signal envelope
        signal_envelope = _derive_query_signal_envelope(
            text=text,
            query_tokens=query_tokens,
            policy_evidence=policy_evidence,
            candidate_evidence=candidate_evidence,
            anchor_prefiltered_candidates=anchor_prefiltered_candidates,
            runtime_context=runtime_context,
        )
        # Step 3a: Noise short-circuit (from envelope)
        if signal_envelope.low_value:
            empty_trace = None
            if include_trace and retrieval_result.trace is not None:
                empty_trace = QueryTrace(
                    query_text=retrieval_result.trace.query_text,
                    query_tokens=retrieval_result.trace.query_tokens,
                    limit=requested_limit,
                    filters=retrieval_result.trace.filters,
                    stages=retrieval_result.trace.stages,
                    visibility=retrieval_result.trace.visibility,
                    requested_filters=retrieval_result.trace.requested_filters,
                    filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                    filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                    routing={"policy_name": ROUTING_POLICY_NAME, "query_policy_family": "noise", "query_intent": "noise", "query_family": "noise",
                             "query_signal_envelope": _build_signal_envelope_trace(signal_envelope)},
                )
            return PackageQueryOutcome(
                results=[],
                trace=empty_trace,
                should_inject=False,
                decision_reason="low_value_query",
                injectable_blocks=[],
                sharp_candidate_diagnostics=[],
            )
        # Step 3b: removed — source_ratio_override was circular with
        # multi-package indexing. Evidence_trace intent should only be set
        # from runtime_context or the resolver, not inferred from retrieval
        # composition. See LoCoMo benchmark investigation 2026-04-06.
        # Step 4: Lane narrowing (consumes envelope via compatible shape tags)
        _envelope_shape_tags: list[str] = []
        if signal_envelope.resume_state:
            _envelope_shape_tags.append("resume_state")
        if signal_envelope.evidence_request:
            _envelope_shape_tags.append("evidence_request")
        lane_result = _determine_eligible_lanes(
            text=text,
            query_shape_tags=_envelope_shape_tags,
            policy_evidence=policy_evidence,
            anchor_prefiltered_candidates=anchor_prefiltered_candidates,
            family_inference={},
            runtime_context=runtime_context,
        )
        if lane_result.selection_mode == "abstain":
            abstain_trace = None
            if include_trace and retrieval_result.trace is not None:
                abstain_trace = QueryTrace(
                    query_text=retrieval_result.trace.query_text,
                    query_tokens=retrieval_result.trace.query_tokens,
                    limit=requested_limit,
                    filters=retrieval_result.trace.filters,
                    stages=retrieval_result.trace.stages,
                    visibility=retrieval_result.trace.visibility,
                    requested_filters=retrieval_result.trace.requested_filters,
                    filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                    filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                    routing={
                        "policy_name": ROUTING_POLICY_NAME,
                        "query_policy_family": "abstain",
                        "query_intent": "abstain",
                        "query_family": "abstain",
                        "lane_narrowing": _build_lane_narrowing_trace(lane_result, final_intent_used=False),
                        "query_signal_envelope": _build_signal_envelope_trace(signal_envelope),
                    },
                )
            return PackageQueryOutcome(
                results=[],
                trace=abstain_trace,
                should_inject=False,
                decision_reason=lane_result.abstain_reason or "lane_ambiguity",
                injectable_blocks=[],
                sharp_candidate_diagnostics=[],
            )
        recall_mode = "default"
        if lane_result.selection_mode == "single_lane_bypass" and lane_result.mapped_intent:
            intent = lane_result.mapped_intent
            policy_ctx = PolicySelectedContext(
                query_policy_family=lane_result.mapped_policy_family or "recall_fact",
                allowed_query_intents=frozenset({intent}),
            )
            final_intent_used = False
        else:
            # Residual fallthrough — envelope-driven routing + recall mode from candidate evidence
            envelope_policy = _policy_family_from_signal_envelope(signal_envelope)
            if envelope_policy == "noise":
                # Shouldn't reach here (caught above), but safety
                empty_trace = None
                if include_trace and retrieval_result.trace is not None:
                    empty_trace = QueryTrace(
                        query_text=retrieval_result.trace.query_text,
                        query_tokens=retrieval_result.trace.query_tokens,
                        limit=requested_limit,
                        filters=retrieval_result.trace.filters,
                        stages=retrieval_result.trace.stages,
                        visibility=retrieval_result.trace.visibility,
                        requested_filters=retrieval_result.trace.requested_filters,
                        filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                        filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                        routing={"policy_name": ROUTING_POLICY_NAME, "query_policy_family": "noise", "query_intent": "noise", "query_family": "noise",
                                 "query_signal_envelope": _build_signal_envelope_trace(signal_envelope)},
                    )
                return PackageQueryOutcome(
                    results=[],
                    trace=empty_trace,
                    should_inject=False,
                    decision_reason="low_value_query",
                    injectable_blocks=[],
                    sharp_candidate_diagnostics=[],
                )
            # Hard routes from envelope that didn't go through lane narrowing bypass
            if envelope_policy == "resume_work":
                intent = "work_resumption"
                recall_mode = "default"
                policy_ctx = PolicySelectedContext(
                    query_policy_family="resume_work",
                    allowed_query_intents=frozenset({"work_resumption"}),
                )
                final_intent_used = False
            else:
                # Pure recall — use recall mode from candidate evidence
                recall_mode = _select_recall_mode(candidate_evidence)
                _mode_weights = RECALL_MODE_WEIGHTS.get(recall_mode, ROUTING_LAYER_WEIGHTS["recall"])
                _layer_weights = {intent_name: _mode_weights for intent_name in ROUTING_LAYER_WEIGHTS}
                # Map recall mode to compatible intent for downstream scoring/shaping.
                # Note: this means modes influence some downstream gates (envelope filtering,
                # injection eligibility) through the mapped intent. This is a known trade-off
                # until downstream code is refactored to branch on mode directly.
                # The mode selector is conservative (only fires for dominant single-type
                # candidate sets), so the risk of wrong gate activation is bounded.
                _mode_intent_map = {
                    "default": "recall",
                    "continuity_preference": "recall",
                    "sharp_fact_preference": "recall",
                    "investigation_preference": "recall",
                }
                intent = _mode_intent_map.get(recall_mode, "recall")
                policy_ctx = PolicySelectedContext(
                    query_policy_family=envelope_policy,
                    allowed_query_intents=frozenset({intent}),
                )
                final_intent_used = False
        # Verbose routing context for injection debugging
        from semantic.agent_conversation_memory_routing_injection import _VERBOSE as _INJ_VERBOSE, _verbose as _inj_verbose
        if _INJ_VERBOSE:
            _lane_mode = lane_result.selection_mode
            _lane_intent = lane_result.mapped_intent
            _env_resume = signal_envelope.resume_state
            _env_evidence = signal_envelope.evidence_request
            _env_derivation = signal_envelope.derivation_signals
            _inj_verbose(
                f"ROUTING query={text[:80]!r} | intent={intent} lane_mode={_lane_mode} "
                f"lane_intent={_lane_intent} envelope_resume={_env_resume} "
                f"envelope_evidence={_env_evidence} derivation={_env_derivation}"
            )
        # Post-routing: run _infer_query_intent() for shaping compatibility
        family_inference = _infer_query_intent(
            text=text,
            query_tokens=query_tokens,
            retrieved_candidates=retrieval_result.results,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        query_shape_tags = list(family_inference["query_shape_tags"]) if isinstance(family_inference.get("query_shape_tags"), (list, tuple)) else []
        preferred_layers = ROUTING_PREFERRED_LAYERS[intent]
        # Step 5: Kind prefilter AFTER policy intent restriction
        kind_filtered_candidates, kind_prefilter_summary, kind_prefilter_states = _kind_prefilter_candidates(
            anchor_prefiltered_candidates,
            intent=intent,
        )
        scored_candidates = [
            _score_routed_candidate(
                item,
                intent,
                recall_mode=recall_mode,
                query_text=text,
                query_tokens=query_tokens,
                lexical_rank=index,
                query_filters=query_filters,
                layer_weights=_layer_weights,
                support_threshold=_support_threshold,
            )
            for index, item in enumerate(kind_filtered_candidates, start=1)
        ]
        # Merge prefilter states + apply anchor penalty inline
        for candidate in scored_candidates:
            result_id = _routing_result_id(candidate["item"])
            candidate.update(kind_prefilter_states.get(result_id, {}))
            candidate.update(anchor_prefilter_states.get(result_id, {}))
            # Anchor tier penalty (was separate stage, now inline)
            status = str(candidate.get("anchor_prefilter_status") or "")
            penalty = ANCHOR_SECONDARY_TIER_PENALTY if status in _ANCHOR_SECONDARY_STATUSES else 0
            candidate["anchor_tier_penalty"] = penalty
            if penalty:
                candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
            # Unified suppression
            apply_suppression(candidate, intent=intent, query_text=text)

        # Pre-computation annotations
        if scored_candidates:
            annotate_freshness_ranks(scored_candidates)
            annotate_work_resumption_context(scored_candidates, query_filters=query_filters)

            # Second scoring pass: components that need cross-candidate annotations
            structured_support = compute_structured_support_ratio(scored_candidates)
            structured_dominates = structured_support["structured_dominates"]
            for candidate in scored_candidates:
                adjustment = (
                    _freshness_component(candidate.get("freshness_rank_in_type"), intent)
                    + _usefulness_adjustment(candidate, intent)
                    + _fresh_session_component(runtime_context, str(candidate["layer"]), structured_dominates)
                )
                if adjustment:
                    candidate["base_routing_score"] = int(candidate["base_routing_score"]) + adjustment
                    candidate["routing_score"] = candidate["base_routing_score"]

        packaging_summary = None  # work_resumption_packaging is now in scoring
        layer_summary = _summarize_routing_layers(scored_candidates)
        routing_focus = _select_routing_focus(
            intent=intent,
            preferred_layers=preferred_layers,
            layer_summary=layer_summary,
            fallback_margin=_fallback_margin,
        )
        for candidate in scored_candidates:
            candidate["routing_score"] = int(candidate["base_routing_score"]) + _routing_focus_adjustment(
                layer=str(candidate["layer"]),
                selected_layer=str(routing_focus["selected_layer"]),
                primary_layer=preferred_layers[0],
                fallback_applied=bool(routing_focus["applied"]),
                focus_boost=_focus_boost,
            )
            candidate["reason"] = _routing_reason(
                intent=intent,
                layer=str(candidate["layer"]),
                support_grade=str(candidate["support_grade"]),
                routing_focus=routing_focus,
                packaging_reasons=list(candidate["packaging_reasons"]),
            )
        ranked_candidates = sorted(
            scored_candidates,
            key=lambda candidate: (candidate["routing_score"], candidate["retrieval_score"]),
            reverse=True,
        )
        for routing_rank, candidate in enumerate(ranked_candidates, start=1):
            candidate["routing_rank"] = routing_rank
        if _INJ_VERBOSE:
            _inj_verbose(f"ROUTING query={text[:80]!r} | scored={len(scored_candidates)} ranked={len(ranked_candidates)}")
            for c in ranked_candidates[:6]:
                item = c["item"]
                _inj_verbose(
                    f"  rank={c.get('routing_rank')} id={getattr(item, 'result_id', '?')[:35]} "
                    f"kind={getattr(item, 'result_kind', '?')} type={getattr(item, 'type', None)} "
                    f"lex={c.get('lexical_score')} vec={c.get('vector_score')} "
                    f"src={getattr(item, 'retrieval_source', None)} "
                    f"score={c.get('routing_score')} suppressed={c.get('suppression_reason_code')}"
                )
        # Derive envelope-based shape tags for downstream selection (not English-derived)
        _envelope_selection_tags: list[str] = []
        final_candidates, packaging_summary = _select_final_candidates(
            intent=intent,
            recall_mode=recall_mode,
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_filters=query_filters,
            query_shape_tags=_envelope_selection_tags,
            runtime_context=runtime_context,
            packaging_summary=packaging_summary,
            selected_lane=lane_result.selected_lane,
        )
        injection_blocks, injection_summary = _build_injectable_blocks(
            final_candidates,
            ranked_candidates=ranked_candidates,
            intent=intent,
            recall_mode=recall_mode,
            query_text=text,
            query_filters=query_filters,
            runtime_context=runtime_context,
            evidence_request=signal_envelope.evidence_request,
        )
        _annotate_excluded_candidates(
            ranked_candidates=ranked_candidates,
            final_candidates=final_candidates,
            requested_limit=requested_limit,
            routing_focus=routing_focus,
            packaging_summary=packaging_summary,
        )
        sharp_candidate_diagnostics = _build_sharp_candidate_diagnostics(
            ranked_candidates=ranked_candidates,
            final_candidates=final_candidates,
            injectable_blocks=injection_blocks,
            decision_reason=str(injection_summary["decision_reason"]),
            query_text=text,
            retrieved_result_ids={_routing_result_id(item) for item in retrieval_result.results},
            debug_candidate_loader=debug_candidate_loader if include_trace else None,
            candidate_injection_eligibility_fn=_candidate_is_injection_eligible,
            dedup_kept_map=dict(injection_summary.get("dedup_kept_map") or {}),
        )
        final_results = [candidate["item"] for candidate in final_candidates]

        routed_trace = None
        if include_trace and retrieval_result.trace is not None:
            routed_trace = QueryTrace(
                query_text=retrieval_result.trace.query_text,
                query_tokens=retrieval_result.trace.query_tokens,
                limit=requested_limit,
                filters=retrieval_result.trace.filters,
                stages=retrieval_result.trace.stages,
                visibility=retrieval_result.trace.visibility,
                requested_filters=retrieval_result.trace.requested_filters,
                filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                routing=_build_routing_trace(
                    intent=intent,
                    family_inference=family_inference,
                    preferred_layers=preferred_layers,
                    layer_summary=layer_summary,
                    routing_focus=routing_focus,
                    ranked_candidates=ranked_candidates,
                    final_candidates=final_candidates,
                    packaging_summary=packaging_summary,
                    runtime_context=runtime_context,
                    injection_summary=injection_summary,
                    sharp_candidate_diagnostics=sharp_candidate_diagnostics,
                    kind_prefilter_summary=kind_prefilter_summary,
                    anchor_prefilter_summary=anchor_prefilter_summary,
                    policy_ctx=policy_ctx,
                    lane_result=lane_result,
                    final_intent_used=final_intent_used,
                    signal_envelope=signal_envelope,
                    recall_mode=recall_mode,
                    relevance_floor={
                        "filtered_count": floor_result.filtered_count,
                        "filtered_score_ranges": floor_result.filtered_score_ranges,
                    } if floor_result.filtered_count > 0 else None,
                ),
            )

        return PackageQueryOutcome(
            results=final_results,
            trace=routed_trace,
            should_inject=bool(injection_summary["should_inject"]),
            decision_reason=str(injection_summary["decision_reason"]),
            injectable_blocks=injection_blocks,
            sharp_candidate_diagnostics=sharp_candidate_diagnostics,
            ranked_candidates=ranked_candidates,
        )

def _build_kind_prefilter_trace_entry(
    item: QueryResultItem,
    *,
    status: str,
    reason_code: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "result_id": _routing_result_id(item),
        "result_kind": item.result_kind,
        "memory_type": item.type,
        "candidate_envelope_kind": item.envelope.kind if item.envelope is not None else None,
        "status": status,
    }
    if item.envelope is not None:
        entry["candidate_subjects"] = _serialize_subject_anchors(item.envelope.subjects)
        entry["envelope_confidence"] = item.envelope.confidence
    if reason_code is not None:
        entry["reason_code"] = reason_code
        entry["reason"] = reason
    return entry


def _kind_prefilter_candidates(
    candidates: list[QueryResultItem],
    *,
    intent: str,
) -> tuple[list[QueryResultItem], dict[str, object], dict[str, dict[str, object]]]:
    allowed_kinds = ROUTING_FAMILY_ALLOWED_ENVELOPE_KINDS.get(intent)
    retained: list[QueryResultItem] = []
    fallback_candidates: list[QueryResultItem] = []
    excluded_candidates: list[dict[str, object]] = []
    candidate_states: dict[str, dict[str, object]] = {}
    fallback_reason = "Candidate has no write-time envelope and remains only as mixed-mode fallback."
    for item in candidates:
        if item.result_kind != "memory_hit":
            retained.append(item)
            continue
        result_id = _routing_result_id(item)
        if item.envelope is None:
            fallback_candidates.append(item)
            candidate_states[result_id] = {
                "kind_prefilter_status": "envelope_missing_fallback",
                "kind_prefilter_reason_code": "envelope_missing_fallback",
                "kind_prefilter_reason": fallback_reason,
            }
            continue
        if allowed_kinds is None or item.envelope.kind in allowed_kinds:
            candidate_states[result_id] = {"kind_prefilter_status": "allowed"}
            retained.append(item)
            continue
        excluded_candidates.append(
            _build_kind_prefilter_trace_entry(
                item,
                status="excluded",
                reason_code="kind_not_allowed",
                reason="Candidate envelope kind is not allowed for this query family.",
            )
        )
    ordered_candidates = [*retained, *fallback_candidates]
    summary: dict[str, object] = {
        "allowed_kinds": list(allowed_kinds) if allowed_kinds is not None else None,
        "input_candidate_count": len(candidates),
        "retained_candidate_count": len(ordered_candidates),
        "excluded_by_kind_count": len(excluded_candidates),
        "envelope_missing_fallback_count": len(fallback_candidates),
    }
    if excluded_candidates:
        summary["excluded_candidates"] = excluded_candidates[:5]
    if fallback_candidates:
        summary["fallback_candidates"] = [
            _build_kind_prefilter_trace_entry(
                item,
                status="envelope_missing_fallback",
                reason_code="envelope_missing_fallback",
                reason=fallback_reason,
            )
            for item in fallback_candidates[:5]
        ]
    return ordered_candidates, summary, candidate_states


def _anchor_prefilter_candidates(
    candidates: list[QueryResultItem],
    *,
    query_tokens: tuple[str, ...],
) -> tuple[list[QueryResultItem], dict[str, object], dict[str, dict[str, object]]]:
    memory_candidates = [item for item in candidates if item.result_kind == "memory_hit"]
    inference = _infer_selected_query_anchor(query_tokens, memory_candidates)
    selected_anchor = inference.get("selected_anchor")
    selected_anchor_kind = inference.get("selected_anchor_kind")
    status = str(inference.get("status") or "none")
    summary: dict[str, object] = {
        "query_anchor_status": status,
        "selected_query_anchor_kind": selected_anchor_kind,
        "selected_query_anchor": _serialize_subject_anchor(selected_anchor) if selected_anchor is not None else None,
        "input_candidate_count": len(memory_candidates),
        "aligned_candidate_count": 0,
        "insufficient_candidate_count": 0,
        "legacy_fallback_count": 0,
        "excluded_by_anchor_count": 0,
        "fallback_mode": "none",
    }
    if selected_anchor is None:
        return candidates, summary, {}

    aligned: list[QueryResultItem] = []
    insufficient: list[QueryResultItem] = []
    legacy: list[QueryResultItem] = []
    candidate_states: dict[str, dict[str, object]] = {}
    for item in memory_candidates:
        result_id = _routing_result_id(item)
        anchor_state = _classify_memory_candidate_anchor_state(item, selected_anchor)
        if anchor_state == "anchored_aligned":
            aligned.append(item)
            candidate_states[result_id] = {
                "anchor_prefilter_status": "aligned",
                "anchor_prefilter_reason_code": "anchor_aligned",
                "anchor_prefilter_reason": "Candidate matched the selected query anchor.",
            }
        elif anchor_state == "anchored_conflicting":
            insufficient.append(item)
            candidate_states[result_id] = {
                "anchor_prefilter_status": "insufficient_retained_demoted",
                "anchor_prefilter_reason_code": "anchor_conflict_demoted",
                "anchor_prefilter_reason": "Candidate conflicted with the selected query anchor and was demoted to the insufficient fallback tier.",
            }
        elif anchor_state == "anchored_insufficient":
            insufficient.append(item)
        else:
            legacy.append(item)
    summary["aligned_candidate_count"] = len(aligned)
    summary["insufficient_candidate_count"] = len(insufficient)
    summary["excluded_by_anchor_count"] = 0

    retained_memory_ids: set[int]
    legacy_retained: list[QueryResultItem] = []
    if aligned:
        secondary = [*insufficient, *legacy]
        retained_memory_ids = {id(item) for item in [*aligned, *secondary]}
        if secondary:
            summary["fallback_mode"] = "aligned_with_secondary"
            summary["secondary_tier_count"] = len(secondary)
            # Intentionally overwrites any earlier per-item status (including
            # insufficient_retained_demoted from Change 1) with secondary_tier
            # so the tier penalty applies uniformly across the secondary pool.
            for item in secondary:
                candidate_states[_routing_result_id(item)] = {
                    "anchor_prefilter_status": "secondary_tier",
                    "anchor_prefilter_reason_code": "anchor_secondary_tier",
                    "anchor_prefilter_reason": "Candidate entered the secondary tier alongside aligned candidates; ranked below aligned via tier penalty.",
                }
        else:
            summary["fallback_mode"] = "aligned_only"
    elif insufficient:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in [*insufficient, *legacy_retained]}
        summary["fallback_mode"] = "insufficient_then_legacy"
        for item in insufficient:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "insufficient_retained",
                "anchor_prefilter_reason_code": "anchor_insufficient",
                "anchor_prefilter_reason": "Candidate lacked the selected query-anchor kind and remained as anchored fallback.",
            }
    else:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in legacy_retained}
        summary["fallback_mode"] = "legacy_only"
    if legacy_retained:
        summary["legacy_fallback_count"] = len(legacy_retained)
        for item in legacy_retained:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "legacy_fallback_retained",
                "anchor_prefilter_reason_code": "anchor_missing_legacy_fallback",
                "anchor_prefilter_reason": "Candidate had no write-time anchors and remained only as legacy fallback.",
            }

    retained_candidates = [
        item
        for item in candidates
        if item.result_kind != "memory_hit" or id(item) in retained_memory_ids
    ]
    return retained_candidates, summary, candidate_states


