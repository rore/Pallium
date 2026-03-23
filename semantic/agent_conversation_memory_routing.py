from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone

from core.contracts import PackageQueryOutcome
from core.models import InjectableBlock, QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_anchors import (
    _classify_memory_candidate_anchor_state,
    _infer_selected_query_anchor,
    _serialize_subject_anchor,
    _serialize_subject_anchors,
)
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_TYPE,
)
from semantic.agent_conversation_memory_threads import (
    SELECTED_WORK_ARTIFACT_KINDS,
    _is_low_value_meta_text,
    _memory_hit_has_selected_work_artifacts,
    _parse_string_list,
)

# Re-export everything from the constants module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_constants import (  # noqa: F401
    PolicySelectedContext,
    LaneEligibility,
    LaneNarrowingResult,
    QuerySignalEnvelope,
    RoutingOverrides,
    ROUTING_POLICY_NAME,
    PASSTHROUGH_POLICY,
    ROUTING_HIGHER_LEVEL_TYPES,
    ROUTING_LOWER_LEVEL_EXACT_TYPES,
    ROUTING_SUMMARY_TYPES,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_FAMILY_ALLOWED_ENVELOPE_KINDS,
    ROUTING_LAYER_WEIGHTS,
    HIGHER_LEVEL_RETRIEVAL_FLOOR,
    ROUTING_SAFE_FALLBACK_LAYERS,
    ROUTING_SUPPORT_THRESHOLD,
    QUERY_POLICY_FAMILY_ALLOWED_INTENTS,
    LATEST_STATUS_COLLAPSED_INTENTS,
    POLICY_WORK_STATE_USEFULNESS_THRESHOLD,
    POLICY_SUPPORT_THRESHOLD,
    AMBIGUITY_MARGIN_LATEST_VS_RESUME,
    AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL,
    LANE_INTENT_MAPPING,
    LANE_POLICY_FAMILY_MAPPING,
    RECALL_MODE_WEIGHTS,
    RECALL_MODE_FRESHNESS_BONUS,
    RECALL_MODE_FRESH_THREAD_PREFERENCE,
    ROUTING_FALLBACK_MARGIN,
    ROUTING_FOCUS_BOOST,
    ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY,
    SHARP_DIAGNOSTIC_MEMORY_TYPES,
    WORK_RESUMPTION_SIGNAL_TYPES,
    WORK_RESUMPTION_SHARP_CHECKPOINT_THRESHOLD,
    WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY,
    WORK_RESUMPTION_STALE_STATE_PENALTY,
    WORK_RESUMPTION_STALE_SOURCE_PENALTY,
    WORK_RESUMPTION_FRESH_STATE_BONUS,
    WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS,
    WORK_RESUMPTION_SIGNAL_PRIORITY,
    ROUTING_FAMILY_INFERENCE_PRIORITY,
    _routing_result_id,
    _result_layer,
    _routing_query_tokens,
    _routing_support_grade,
    _candidate_matches_thread,
    _candidate_matches_container,
    _candidate_thread_refs,
    _candidate_container_refs,
    _candidate_freshness_timestamp,
    _normalize_timestamp,
    _parse_iso_timestamp,
    is_query_topic_signal_empty,
)

# Re-export everything from the trace module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_trace import (  # noqa: F401
    _build_routing_trace,
    _build_routing_trace_entry,
    _build_lane_narrowing_trace,
    _build_signal_envelope_trace,
    _build_kind_prefilter_trace_entry,
    _build_anchor_prefilter_trace_entry,
    _build_sharp_candidate_diagnostics,
    _routing_reason,
    _routing_strategy_name,
    _routing_fallback_suffix,
    _routing_packaging_suffix,
    _query_family_label,
)

# Re-export everything from the signals module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_signals import (  # noqa: F401
    _derive_query_signal_envelope,
    _check_evidence_trace_override,
    _policy_family_from_signal_envelope,
    _select_recall_mode,
    _build_policy_evidence,
    _policy_candidate_support_estimate,
    _work_state_evidence_gate_passes,
    _candidate_layer_dominance,
    _compute_typed_candidate_evidence,
    _work_resumption_signal_types,
    _work_resumption_usefulness_score,
    _classify_work_signal_text,
    _is_thin_task_checkpoint_payload,
)

# Re-export everything from the policy module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_policy import (  # noqa: F401
    _determine_eligible_lanes,
    _classify_query_policy_family,
    _build_ambiguity_options,
    _build_latest_vs_resume_pair,
    _maybe_invoke_resolver,
    _apply_policy_intent_restriction,
    _invoke_resolver_for_ambiguity,
    _build_resolver_candidate_cards,
)

# Re-export everything from the scoring module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_scoring import (  # noqa: F401
    _infer_query_intent,
    _query_family_query_shape_score,
    _summarize_query_family_candidates,
    _query_family_candidate_score,
    _query_family_layer_metric,
    _query_family_top_layer,
    _candidate_has_rationale,
    _candidate_has_explicit_evidence,
    _score_routed_candidate,
    _locality_adjustment,
    _specificity_bonus,
    _higher_level_retrieval_floor_adjustment,
    _candidate_evidence_shape_score,
    _apply_same_kind_freshness_shaping,
    _runtime_context_prefers_cross_thread_recall,
    _apply_fresh_thread_structured_recall_preference,
    _source_hit_matches_current_query_text,
    _apply_current_query_source_suppression,
    _apply_recall_source_noise_suppression,
    _is_current_query_echo,
    _source_noise_suppression_reason,
    _apply_recall_structured_summary_suppression,
    _structured_summary_suppression_reason,
    _summary_low_value_reason,
    _apply_work_resumption_packaging,
    _candidate_matches_requested_locality,
    _work_resumption_freshness_adjustment,
    _summarize_routing_layers,
    _select_routing_focus,
    _routing_focus_adjustment,
)

# Re-export everything from the selection module so existing importers work unchanged.
from semantic.agent_conversation_memory_routing_selection import (  # noqa: F401
    _select_final_candidates,
    _select_compatible_recall_candidates,
    _candidate_locality_compatible_for_packaging,
    _build_injectable_blocks,
    _build_injectable_block_from_candidate,
    _task_checkpoint_injection_text,
    _join_unique_text_parts,
    _evaluate_same_thread_local_context,
    _candidate_could_supply_external_carry_forward,
    _candidate_qualifies_as_same_thread_local_state,
    _candidate_is_injection_eligible,
    _candidate_is_low_value,
    _source_candidate_is_primary_injection_eligible,
    _source_candidate_is_companion_injection_eligible,
    _source_candidate_has_quote_grade_support,
    _source_excerpt_disclaims_exact_evidence,
    _query_requests_quote_grade_source,
    _annotate_excluded_candidates,
)

def route_query_results(
    *,
    text: str,
    requested_limit: int,
    retrieval_result,
    query_filters: QueryFilters | None = None,
    runtime_context: QueryRuntimeContext | None = None,
    include_trace: bool = False,
    debug_candidate_loader=None,
    resolver_config: dict[str, object] | None = None,
    routing_overrides: RoutingOverrides | None = None,
) -> PackageQueryOutcome:
        _ov = routing_overrides or {}
        _layer_weights: dict[str, dict[str, int]] = _ov.get("layer_weights") or ROUTING_LAYER_WEIGHTS
        _focus_boost: int = _ov.get("focus_boost", ROUTING_FOCUS_BOOST)  # type: ignore[assignment]
        _fallback_margin: int = _ov.get("fallback_margin", ROUTING_FALLBACK_MARGIN)  # type: ignore[assignment]
        _support_threshold: dict[str, int] = _ov.get("support_threshold") or ROUTING_SUPPORT_THRESHOLD
        _thin_checkpoint_penalty: int = _ov.get("work_resumption_thin_checkpoint_penalty", WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY)  # type: ignore[assignment]
        query_tokens = _routing_query_tokens(text)
        # Step 1: Family-independent anchor prefilter
        anchor_prefiltered_candidates, anchor_prefilter_summary, anchor_prefilter_states = _anchor_prefilter_candidates(
            retrieval_result.results,
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
        # Step 3b: Orthogonal evidence_trace override (post-envelope, post-noise)
        signal_envelope = _check_evidence_trace_override(
            envelope=signal_envelope,
            source_ratio=float(candidate_evidence.get("source_hit_ratio", 0)),
            query_text=text,
            candidates=anchor_prefiltered_candidates,
            runtime_context=runtime_context,
            resolver_config=resolver_config,
            resolver_fn=_invoke_resolver_for_ambiguity,
        )
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
                _mode_weights = RECALL_MODE_WEIGHTS.get(recall_mode, ROUTING_LAYER_WEIGHTS["broad_recall"])
                _layer_weights = {intent_name: _mode_weights for intent_name in ROUTING_LAYER_WEIGHTS}
                # Map recall mode to compatible intent for downstream scoring/shaping.
                # Note: this means modes influence some downstream gates (envelope filtering,
                # injection eligibility) through the mapped intent. This is a known trade-off
                # until downstream code is refactored to branch on mode directly.
                # The mode selector is conservative (only fires for dominant single-type
                # candidate sets), so the risk of wrong gate activation is bounded.
                _mode_intent_map = {
                    "default": "broad_recall",
                    "continuity_preference": "answer_continuity",
                    "sharp_fact_preference": "broad_recall",
                    "investigation_preference": "broad_recall",
                }
                intent = _mode_intent_map.get(recall_mode, "broad_recall")
                policy_ctx = PolicySelectedContext(
                    query_policy_family=envelope_policy,
                    allowed_query_intents=frozenset({intent}),
                )
                final_intent_used = False
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
                query_text=text,
                query_tokens=query_tokens,
                lexical_rank=index,
                query_filters=query_filters,
                layer_weights=_layer_weights,
                support_threshold=_support_threshold,
            )
            for index, item in enumerate(kind_filtered_candidates, start=1)
        ]
        for candidate in scored_candidates:
            result_id = _routing_result_id(candidate["item"])
            candidate.update(kind_prefilter_states.get(result_id, {}))
            candidate.update(anchor_prefilter_states.get(result_id, {}))
        if scored_candidates:
            _apply_current_query_source_suppression(
                scored_candidates,
                query_text=text,
                query_filters=query_filters,
            )
            _apply_same_kind_freshness_shaping(scored_candidates, intent=intent)
            _apply_fresh_thread_structured_recall_preference(
                scored_candidates,
                intent=intent,
                candidate_signals=family_inference["candidate_signals"],
                runtime_context=runtime_context,
            )
            _apply_recall_source_noise_suppression(
                scored_candidates,
                intent=intent,
                query_text=text,
                query_filters=query_filters,
                runtime_context=runtime_context,
            )
            _apply_recall_structured_summary_suppression(
                scored_candidates,
                intent=intent,
                query_text=text,
                query_filters=query_filters,
                runtime_context=runtime_context,
            )
        packaging_summary = None
        if intent == "work_resumption" and scored_candidates:
            packaging_summary = _apply_work_resumption_packaging(
                scored_candidates,
                query_filters=query_filters,
                thin_checkpoint_penalty=_thin_checkpoint_penalty,
            )
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
                content_overlap_tokens=list(candidate["content_overlap_tokens"]),
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
        # Derive envelope-based shape tags for downstream selection (not English-derived)
        _envelope_selection_tags: list[str] = []
        final_candidates, packaging_summary = _select_final_candidates(
            intent=intent,
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
            query_text=text,
            query_filters=query_filters,
            runtime_context=runtime_context,
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
            debug_candidate_loader=debug_candidate_loader if include_trace else None,
            candidate_injection_eligibility_fn=_candidate_is_injection_eligible,
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
                ),
            )

        return PackageQueryOutcome(
            results=final_results,
            trace=routed_trace,
            should_inject=bool(injection_summary["should_inject"]),
            decision_reason=str(injection_summary["decision_reason"]),
            injectable_blocks=injection_blocks,
            sharp_candidate_diagnostics=sharp_candidate_diagnostics,
        )

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
    conflicting: list[QueryResultItem] = []
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
            conflicting.append(item)
        elif anchor_state == "anchored_insufficient":
            insufficient.append(item)
        else:
            legacy.append(item)
    summary["aligned_candidate_count"] = len(aligned)
    summary["insufficient_candidate_count"] = len(insufficient)
    summary["excluded_by_anchor_count"] = len(conflicting)
    if conflicting:
        summary["excluded_candidates"] = [
            _build_anchor_prefilter_trace_entry(
                item,
                status="conflicting_excluded",
                reason_code="anchor_conflict",
                reason="Candidate conflicted with the selected query anchor.",
            )
            for item in conflicting[:5]
        ]

    retained_memory_ids: set[int]
    legacy_retained: list[QueryResultItem] = []
    if aligned:
        retained_memory_ids = {id(item) for item in aligned}
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


