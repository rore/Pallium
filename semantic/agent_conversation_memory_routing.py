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


def _infer_query_intent(
    *,
    text: str,
    query_tokens: tuple[str, ...],
    retrieved_candidates: list[QueryResultItem],
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> dict[str, object]:
    query_shape_tags: list[str] = []
    candidate_signals = _summarize_query_family_candidates(
        retrieved_candidates=retrieved_candidates,
        query_text=text,
        query_tokens=query_tokens,
        query_filters=query_filters,
    )
    family_scores: dict[str, dict[str, object]] = {}
    for family in ROUTING_FAMILY_INFERENCE_PRIORITY:
        query_shape_score, query_shape_reasons = _query_family_query_shape_score(
            family,
            query_shape_tags=query_shape_tags,
            runtime_context=runtime_context,
        )
        candidate_score, candidate_reasons = _query_family_candidate_score(
            family,
            candidate_signals=candidate_signals,
            query_shape_tags=query_shape_tags,
            runtime_context=runtime_context,
        )
        family_scores[family] = {
            "total": query_shape_score + candidate_score,
            "cue_score": 0,
            "query_shape_score": query_shape_score,
            "candidate_score": candidate_score,
            "reasons": list(OrderedDict.fromkeys([*query_shape_reasons, *candidate_reasons])),
        }

    ranked_families = sorted(
        ROUTING_FAMILY_INFERENCE_PRIORITY,
        key=lambda family: (
            int(family_scores[family]["total"]),
            int(family_scores[family]["candidate_score"]),
            -ROUTING_FAMILY_INFERENCE_PRIORITY.index(family),
        ),
        reverse=True,
    )
    selected_family = ranked_families[0] if ranked_families else "broad_recall"
    runner_up_family = ranked_families[1] if len(ranked_families) > 1 else None
    return {
        "selected_family": selected_family,
        "text_hint_family": "broad_recall",
        "runner_up_family": runner_up_family,
        "query_shape_tags": query_shape_tags,
        "matched_cues": {},
        "candidate_signals": candidate_signals,
        "family_scores": family_scores,
    }

def _query_family_query_shape_score(
    family: str,
    *,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    weights = {
        "answer_continuity": {"carry_forward": 28, "history_lookup": 8, "constraint_recall": 18},
        "broad_recall": {"history_lookup": 22, "big_picture": 52, "constraint_recall": 28, "carry_forward": 12},
        "work_resumption": {"resume_state": 34, "carry_forward": 8},
        "precise_fact": {"precise_lookup": 18},
        "evidence_trace": {"evidence_request": 44},
        "investigative_conclusion": {"analysis_request": 30, "history_lookup": 10},
    }
    score = 0
    reasons: list[str] = []
    for tag, bonus in weights.get(family, {}).items():
        if tag in query_shape_tags:
            score += bonus
            reasons.append(f"{tag}_query_shape")
    if runtime_context is not None and family == "work_resumption" and runtime_context.turn_kind == "resumed_session":
        score += 12
        reasons.append("resumed_session_runtime")
    if runtime_context is not None and family == "answer_continuity" and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}:
        score += 10
        reasons.append("same_thread_runtime")
    return score, reasons

def _summarize_query_family_candidates(
    *,
    retrieved_candidates: list[QueryResultItem],
    query_text: str,
    query_tokens: tuple[str, ...],
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    layer_support: dict[str, dict[str, object]] = {}
    continuity_candidates: list[dict[str, object]] = []
    for item in retrieved_candidates:
        layer = _result_layer(item)
        support_score = _candidate_evidence_shape_score(
            item,
            layer=layer,
            query_filters=query_filters,
        )
        same_thread = _candidate_matches_thread(item, query_filters)
        same_container = _candidate_matches_container(item, query_filters)
        work_signal_types = _work_resumption_signal_types(item)
        work_usefulness, work_reasons = _work_resumption_usefulness_score(item, work_signal_types)
        if _source_hit_matches_current_query_text(item, query_text=query_text, query_filters=query_filters):
            continue
        has_rationale = _candidate_has_rationale(item)
        has_explicit_evidence = _candidate_has_explicit_evidence(item)
        stats = layer_support.setdefault(
            layer,
            {
                "count": 0,
                "best_support": 0,
                "same_thread_hits": 0,
                "same_container_hits": 0,
                "evidence_hits": 0,
                "rationale_hits": 0,
                "best_work_usefulness": 0,
                "best_content_overlap_count": 0,
                "best_content_overlap_tokens": [],
                "best_result_id": None,
                "strong_candidate": False,
                "sharp_candidate": False,
                "dominant_work_signals": [],
            },
        )
        stats["count"] = int(stats["count"]) + 1
        stats["same_thread_hits"] = int(stats["same_thread_hits"]) + int(same_thread)
        stats["same_container_hits"] = int(stats["same_container_hits"]) + int(same_container)
        stats["evidence_hits"] = int(stats["evidence_hits"]) + int(has_explicit_evidence or bool(item.evidence))
        stats["rationale_hits"] = int(stats["rationale_hits"]) + int(has_rationale)
        candidate_is_strong = _routing_support_grade(support_score) in {"supported", "strong"}
        if layer == "continuity_memory":
            continuity_candidates.append(
                {
                    "result_id": _routing_result_id(item),
                    "support": support_score,
                    "same_thread": same_thread,
                    "content_overlap_count": 0,
                    "content_overlap_tokens": [],
                    "strong_candidate": candidate_is_strong,
                }
            )
        if support_score >= int(stats["best_support"]):
            stats["best_support"] = support_score
            stats["best_work_usefulness"] = work_usefulness
            stats["best_content_overlap_count"] = 0
            stats["best_content_overlap_tokens"] = []
            stats["best_result_id"] = _routing_result_id(item)
            stats["strong_candidate"] = candidate_is_strong
            stats["sharp_candidate"] = bool(
                ("sharp_checkpoint" in work_reasons)
                or (layer in ROUTING_LOWER_LEVEL_EXACT_TYPES and (has_rationale or has_explicit_evidence))
            )
            stats["dominant_work_signals"] = list(work_signal_types[:3])

    bounded_layer_support: dict[str, dict[str, object]] = {}
    for layer, stats in layer_support.items():
        entry = {
            "count": int(stats["count"]),
            "best_support": int(stats["best_support"]),
            "same_thread_hits": int(stats["same_thread_hits"]),
            "same_container_hits": int(stats["same_container_hits"]),
            "evidence_hits": int(stats["evidence_hits"]),
            "rationale_hits": int(stats["rationale_hits"]),
            "best_work_usefulness": int(stats["best_work_usefulness"]),
            "best_content_overlap_count": int(stats["best_content_overlap_count"]),
            "strong_candidate": bool(stats["strong_candidate"]),
            "sharp_candidate": bool(stats["sharp_candidate"]),
        }
        if stats["best_result_id"]:
            entry["best_result_id"] = stats["best_result_id"]
        if stats["best_content_overlap_tokens"]:
            entry["best_content_overlap_tokens"] = list(stats["best_content_overlap_tokens"])
        if stats["dominant_work_signals"]:
            entry["dominant_work_signals"] = list(stats["dominant_work_signals"])
        bounded_layer_support[layer] = entry

    sharp_lower_level_topic_tokens = list(
        OrderedDict.fromkeys(
            token
            for layer in ("investigation_outcome", "decision", "lower_level_memory")
            for token in list((bounded_layer_support.get(layer) or {}).get("best_content_overlap_tokens") or [])
            if isinstance(token, str)
        )
    )
    relevant_continuity_candidates: list[dict[str, object]] = []
    for candidate in continuity_candidates:
        overlap_tokens = [
            token
            for token in list(candidate.get("content_overlap_tokens") or [])
            if isinstance(token, str)
        ]
        alignment_tokens = [token for token in overlap_tokens if token in sharp_lower_level_topic_tokens][:4]
        if (
            bool(candidate.get("strong_candidate"))
            and not bool(candidate.get("same_thread"))
            and int(candidate.get("content_overlap_count") or 0) >= 2
            and len(alignment_tokens) >= 2
        ):
            relevant_continuity_candidates.append(
                {
                    "result_id": candidate.get("result_id"),
                    "support": int(candidate.get("support") or 0),
                    "content_overlap_count": int(candidate.get("content_overlap_count") or 0),
                    "content_overlap_tokens": overlap_tokens,
                    "alignment_tokens": alignment_tokens,
                }
            )
    relevant_continuity_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("support") or 0),
            int(candidate.get("content_overlap_count") or 0),
        ),
        reverse=True,
    )
    best_relevant_cross_thread_continuity = relevant_continuity_candidates[0] if relevant_continuity_candidates else None
    continuity_topic_alignment_tokens = list((best_relevant_cross_thread_continuity or {}).get("alignment_tokens") or [])
    relevant_cross_thread_continuity_in_scope = best_relevant_cross_thread_continuity is not None

    top_layers = [
        {"layer": layer, **stats}
        for layer, stats in sorted(
            bounded_layer_support.items(),
            key=lambda item: (int(item[1].get("best_support", 0)), int(item[1].get("count", 0))),
            reverse=True,
        )[:4]
    ]
    return {
        "layer_support": bounded_layer_support,
        "top_layers": top_layers,
        "sharp_lower_level_in_scope": any(
            bool((bounded_layer_support.get(layer) or {}).get("strong_candidate"))
            for layer in ("investigation_outcome", "decision", "lower_level_memory")
        ),
        "strong_task_checkpoint_in_scope": bool(
            (bounded_layer_support.get("task_checkpoint") or {}).get("strong_candidate")
            or (bounded_layer_support.get("task_checkpoint") or {}).get("sharp_candidate")
        ),
        "strong_source_evidence_in_scope": bool((bounded_layer_support.get("source_evidence") or {}).get("strong_candidate")),
        "relevant_cross_thread_continuity_in_scope": relevant_cross_thread_continuity_in_scope,
        "continuity_topic_alignment_tokens": continuity_topic_alignment_tokens,
        "relevant_cross_thread_continuity": best_relevant_cross_thread_continuity,
    }

def _candidate_has_rationale(item: QueryResultItem) -> bool:
    if item.result_kind != "memory_hit" or not item.payload:
        return False
    return bool(str(item.payload.get("rationale") or "").strip())

def _candidate_has_explicit_evidence(item: QueryResultItem) -> bool:
    if item.result_kind == "source_hit":
        return bool(item.evidence)
    payload = item.payload or {}
    if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
        return True
    if _parse_string_list(payload.get("evidence")):
        return True
    conclusions = payload.get("conclusions", [])
    return isinstance(conclusions, list) and any(isinstance(entry, dict) and str(entry.get("text") or "").strip() for entry in conclusions)

def _query_family_layer_metric(candidate_signals: dict[str, object], layer: str, metric: str) -> int:
    layer_support = candidate_signals.get("layer_support", {})
    if not isinstance(layer_support, dict):
        return 0
    stats = layer_support.get(layer, {})
    if not isinstance(stats, dict):
        return 0
    value = stats.get(metric)
    if isinstance(value, bool):
        return int(value)
    return int(value) if isinstance(value, int) else 0

def _query_family_top_layer(candidate_signals: dict[str, object]) -> str:
    top_layers = candidate_signals.get("top_layers", [])
    if not isinstance(top_layers, list) or not top_layers:
        return "none"
    top_layer = top_layers[0]
    if not isinstance(top_layer, dict):
        return "none"
    return str(top_layer.get("layer") or "none")

def _query_family_candidate_score(
    family: str,
    *,
    candidate_signals: dict[str, object],
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    pattern_support = _query_family_layer_metric(candidate_signals, "pattern_memory", "best_support")
    pattern_count = _query_family_layer_metric(candidate_signals, "pattern_memory", "count")
    continuity_support = _query_family_layer_metric(candidate_signals, "continuity_memory", "best_support")
    continuity_same_thread_hits = _query_family_layer_metric(candidate_signals, "continuity_memory", "same_thread_hits")
    checkpoint_support = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_support")
    thread_summary_support = _query_family_layer_metric(candidate_signals, "thread_summary", "best_support")
    discussion_summary_support = _query_family_layer_metric(candidate_signals, "discussion_summary", "best_support")
    checkpoint_same_thread_hits = _query_family_layer_metric(candidate_signals, "task_checkpoint", "same_thread_hits")
    checkpoint_work_usefulness = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_work_usefulness")
    source_support = _query_family_layer_metric(candidate_signals, "source_evidence", "best_support")
    source_same_thread_hits = _query_family_layer_metric(candidate_signals, "source_evidence", "same_thread_hits")
    source_evidence_hits = _query_family_layer_metric(candidate_signals, "source_evidence", "evidence_hits")
    source_work_usefulness = _query_family_layer_metric(candidate_signals, "source_evidence", "best_work_usefulness")
    decision_support = _query_family_layer_metric(candidate_signals, "decision", "best_support")
    investigation_support = _query_family_layer_metric(candidate_signals, "investigation_outcome", "best_support")
    lower_level_support = _query_family_layer_metric(candidate_signals, "lower_level_memory", "best_support")
    sharp_lower_level_support = max(decision_support, investigation_support, lower_level_support)
    sharp_lower_level_rationale_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "rationale_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    sharp_lower_level_evidence_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "evidence_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    sharp_lower_level_same_thread_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "same_thread_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    top_layer = _query_family_top_layer(candidate_signals)
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    structured_recall_support = max(
        pattern_support,
        continuity_support,
        checkpoint_support,
        thread_summary_support,
        discussion_summary_support,
        sharp_lower_level_support,
    )
    fresh_thread_cross_thread_recall = _runtime_context_prefers_cross_thread_recall(runtime_context)
    history_recall_with_relevant_carry_forward = (
        "history_lookup" in query_shape_tags
        and bool(candidate_signals.get("relevant_cross_thread_continuity_in_scope"))
        and sharp_lower_level_support >= supported_floor
    )
    constraint_recall = "constraint_recall" in query_shape_tags
    structured_summary_support = max(checkpoint_support, thread_summary_support, discussion_summary_support)
    score = 0
    reasons: list[str] = []

    if family == "answer_continuity":
        if continuity_support:
            score += (continuity_support // 2) + (continuity_same_thread_hits * 14)
            reasons.append("continuity_memory_support")
        if fresh_thread_cross_thread_recall and structured_recall_support >= supported_floor:
            score += min(structured_recall_support // 2, 52)
            reasons.append("fresh_thread_structured_memory_support")
        if fresh_thread_cross_thread_recall and constraint_recall and structured_summary_support >= supported_floor:
            score += min(structured_summary_support // 3, 28)
            reasons.append("constraint_carry_forward_support")
        if top_layer == "continuity_memory":
            score += 10
            reasons.append("continuity_memory_won_candidate_competition")
        if continuity_support < supported_floor and structured_recall_support < supported_floor:
            score -= 12
            reasons.append("weak_continuity_support")
        if "evidence_request" in query_shape_tags and source_support >= supported_floor:
            score -= 54
            reasons.append("evidence_request_outweighs_continuity")
        return score, reasons

    if family == "broad_recall":
        if pattern_support:
            score += pattern_support + (min(pattern_count, 2) * 10)
            reasons.append("pattern_memory_support")
        if history_recall_with_relevant_carry_forward:
            score += min(continuity_support // 3, 70) + 36
            reasons.append("cross_thread_carry_forward_support")
        if sharp_lower_level_support:
            score += min(sharp_lower_level_support, 44)
            reasons.append("sharp_lower_level_available")
        if fresh_thread_cross_thread_recall and structured_recall_support >= supported_floor:
            score += min(structured_recall_support // 2, 56)
            reasons.append("fresh_thread_structured_memory_support")
        if structured_summary_support >= supported_floor:
            score += min(structured_summary_support // 3, 36)
            reasons.append("structured_summary_support")
        if checkpoint_support >= supported_floor and {"history_lookup", "carry_forward"}.issubset(set(query_shape_tags)):
            score += min(checkpoint_support // 2, 72)
            reasons.append("checkpoint_carry_forward_support")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and structured_recall_support >= supported_floor:
            score += 28
            reasons.append("fresh_thread_history_recall")
        if top_layer == "pattern_memory":
            score += 12
            reasons.append("pattern_memory_won_candidate_competition")
        if history_recall_with_relevant_carry_forward and top_layer == "continuity_memory":
            score += 18
            reasons.append("carry_forward_memory_won_candidate_competition")
        if pattern_support and pattern_support >= sharp_lower_level_support:
            score += 10
            reasons.append("pattern_memory_beats_sharp_lower_level")
        if pattern_support < supported_floor and sharp_lower_level_support > pattern_support and "analysis_request" in query_shape_tags:
            score -= 18
            reasons.append("sharp_lower_level_outweighs_weak_pattern_memory")
        if "evidence_request" in query_shape_tags and source_support >= supported_floor:
            score -= 84
            reasons.append("evidence_request_outweighs_broad_recall")
        return score, reasons

    if family == "work_resumption":
        if checkpoint_support:
            score += (checkpoint_support // 2) + checkpoint_work_usefulness + (checkpoint_same_thread_hits * 16)
            reasons.append("task_checkpoint_support")
        if source_work_usefulness:
            score += min(source_support // 2, 42) + source_work_usefulness + (source_same_thread_hits * 8)
            reasons.append("work_state_source_support")
        if fresh_thread_cross_thread_recall and checkpoint_support >= supported_floor:
            score += min(checkpoint_support // 3, 42)
            reasons.append("fresh_thread_checkpoint_support")
        if bool(candidate_signals.get("strong_task_checkpoint_in_scope")):
            score += 16
            reasons.append("sharp_task_checkpoint_in_scope")
        if top_layer in {"task_checkpoint", "source_evidence"}:
            score += 8
            reasons.append("work_state_won_candidate_competition")
        if runtime_context is not None and runtime_context.turn_kind == "resumed_session":
            score += 6
            reasons.append("resumed_session_candidate_tiebreak")
        if "resume_state" not in query_shape_tags and (runtime_context is None or runtime_context.turn_kind != "resumed_session"):
            score -= 180
            reasons.append("missing_resume_query_shape")
        if checkpoint_support < supported_floor and source_work_usefulness < 18:
            score -= 20
            reasons.append("weak_resumption_state_support")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and "resume_state" not in query_shape_tags:
            score -= 56
            reasons.append("history_lookup_outweighs_resume_state")
        return score, reasons

    if family == "precise_fact":
        if sharp_lower_level_support:
            score += (sharp_lower_level_support // 2) + (sharp_lower_level_same_thread_hits * 8)
            reasons.append("sharp_lower_level_support")
        if source_support:
            score += min(source_support, 36)
            reasons.append("source_evidence_fallback")
        if top_layer in {"decision", "investigation_outcome", "lower_level_memory"}:
            score += 8
            reasons.append("sharp_lower_level_won_candidate_competition")
        if sharp_lower_level_support < supported_floor:
            score -= 12
            reasons.append("weak_precise_fact_support")
        if "big_picture" in query_shape_tags:
            score -= 48
            reasons.append("pattern_memory_points_to_broad_recall")
        if history_recall_with_relevant_carry_forward:
            score -= 74
            reasons.append("carry_forward_history_outweighs_precise_lookup")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and structured_recall_support >= supported_floor:
            score -= 56
            reasons.append("history_lookup_outweighs_precise_lookup")
        return score, reasons

    if family == "evidence_trace":
        if source_support:
            score += (source_support // 2) + (source_evidence_hits * 10)
            reasons.append("source_evidence_support")
        if bool(candidate_signals.get("strong_source_evidence_in_scope")):
            score += 14
            reasons.append("sharp_source_evidence_in_scope")
        if sharp_lower_level_evidence_hits:
            score += sharp_lower_level_evidence_hits * 8
            reasons.append("lower_level_evidence_available")
        if top_layer == "source_evidence":
            score += 12
            reasons.append("source_evidence_won_candidate_competition")
        if source_support < supported_floor:
            score -= 16
            reasons.append("weak_source_evidence_support")
        if checkpoint_support > source_support + 20 and "resume_state" in query_shape_tags:
            score -= 18
            reasons.append("checkpoint_state_outweighs_weak_source_evidence")
        if fresh_thread_cross_thread_recall and structured_recall_support >= max(source_support, supported_floor) and "evidence_request" not in query_shape_tags:
            score -= 72
            reasons.append("structured_recall_outweighs_source_evidence")
        if {"history_lookup", "carry_forward"}.issubset(set(query_shape_tags)) and checkpoint_support >= supported_floor and "evidence_request" not in query_shape_tags:
            score -= 84
            reasons.append("checkpoint_carry_forward_outweighs_evidence_trace")
        if ("history_lookup" in query_shape_tags or constraint_recall) and structured_summary_support >= supported_floor and "evidence_request" not in query_shape_tags:
            score -= 54
            reasons.append("history_lookup_outweighs_evidence_trace")
        return score, reasons

    if sharp_lower_level_support:
        score += (sharp_lower_level_support // 2) + (sharp_lower_level_rationale_hits * 12) + (sharp_lower_level_evidence_hits * 8) + (sharp_lower_level_same_thread_hits * 10)
        reasons.append("sharp_lower_level_support")
    if bool(candidate_signals.get("sharp_lower_level_in_scope")):
        score += 14
        reasons.append("sharp_lower_level_in_scope")
    if source_support:
        score += min(source_support // 2, 32)
        reasons.append("supporting_source_evidence_available")
    if top_layer in {"investigation_outcome", "decision", "lower_level_memory"}:
        score += 10
        reasons.append("sharp_lower_level_won_candidate_competition")
    if sharp_lower_level_support < supported_floor:
        score -= 16
        reasons.append("weak_investigative_support")
    if pattern_support >= sharp_lower_level_support and "big_picture" in query_shape_tags:
        score -= 18
        reasons.append("pattern_memory_outweighs_sharp_conclusion")
    return score, reasons

def _locality_adjustment(
    *,
    intent: str,
    layer: str,
    same_thread: bool,
    same_container: bool,
) -> int:
    """Structural locality bonus for continuity_memory candidates.

    Replaces the former topic-overlap-gated continuity compatibility
    adjustment.  Uses only structural thread/container affinity, no tokens.

    The same-container bonus (+20) is gated on answer_continuity intent to
    avoid boosting cross-topic carry-forward when the query isn't a repeated
    question.
    """
    if layer != "continuity_memory":
        return 0
    if same_thread:
        return 60
    if same_container and intent == "answer_continuity":
        return 20
    if same_container:
        return 0
    return -60


def _score_routed_candidate(
    item: QueryResultItem,
    intent: str,
    *,
    query_text: str,
    query_tokens: tuple[str, ...],
    lexical_rank: int,
    query_filters: QueryFilters | None,
    layer_weights: dict[str, dict[str, int]] | None = None,
    support_threshold: dict[str, int] | None = None,
) -> dict[str, object]:
    layer = _result_layer(item)
    retrieval_score = int(item.score)
    same_thread = _candidate_matches_thread(item, query_filters)
    same_container = _candidate_matches_container(item, query_filters)
    evidence_shape_score = _candidate_evidence_shape_score(
        item,
        layer=layer,
        query_filters=query_filters,
    )
    _weights = layer_weights or ROUTING_LAYER_WEIGHTS
    base_routing_score = (
        _weights[intent][layer]
        + (retrieval_score * 10)
        + _specificity_bonus(item, intent)
        + evidence_shape_score
        + _higher_level_retrieval_floor_adjustment(layer, retrieval_score)
        + _locality_adjustment(intent=intent, layer=layer, same_thread=same_thread, same_container=same_container)
    )
    support_grade = _routing_support_grade(evidence_shape_score, support_threshold=support_threshold)
    return {
        "item": item,
        "layer": layer,
        "lexical_rank": lexical_rank,
        "retrieval_score": retrieval_score,
        "base_routing_score": base_routing_score,
        "routing_score": base_routing_score,
        "support_score": evidence_shape_score,
        "support_grade": support_grade,
        "envelope_kind": item.envelope.kind if item.envelope is not None else None,
        "envelope_subjects": _serialize_subject_anchors(item.envelope.subjects) if item.envelope is not None else [],
        "envelope_confidence": item.envelope.confidence if item.envelope is not None else None,
        "reason": "",
        "strategy_name": _routing_strategy_name(item),
        "content_overlap_tokens": [],
        "topic_overlap_tokens": [],
        "evidence_count": len(item.evidence),
        "same_thread": same_thread,
        "same_container": same_container,
        "freshness_timestamp_value": _candidate_freshness_timestamp(item),
        "freshness_timestamp": None,
        "packaging_adjustment": 0,
        "packaging_reasons": [],
        "work_signal_types": (),
        "work_usefulness_score": 0,
    }

def _apply_same_kind_freshness_shaping(scored_candidates: list[dict[str, object]], *, intent: str) -> None:
    if intent not in {"investigative_conclusion", "precise_fact", "broad_recall"}:
        return
    for memory_type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        typed_candidates = [candidate for candidate in scored_candidates if getattr(candidate["item"], "type", None) == memory_type]
        if len(typed_candidates) < 2:
            continue
        typed_candidates.sort(
            key=lambda candidate: (
                candidate.get("freshness_timestamp_value") is not None,
                candidate.get("freshness_timestamp_value") or datetime.min.replace(tzinfo=timezone.utc),
                bool(candidate.get("same_thread")),
                int(candidate.get("retrieval_score", 0)),
            ),
            reverse=True,
        )
        freshest = typed_candidates[0].get("freshness_timestamp_value")
        for index, candidate in enumerate(typed_candidates):
            freshness_delta = 0
            if index == 0:
                freshness_delta += 42 if intent == "investigative_conclusion" else 24
                if candidate.get("same_thread"):
                    freshness_delta += 16
            else:
                freshness_delta -= min(index * 12, 30)
                if freshest is not None and candidate.get("freshness_timestamp_value") is not None:
                    candidate_time = candidate.get("freshness_timestamp_value")
                    if isinstance(candidate_time, datetime) and freshest > candidate_time:
                        freshness_delta -= 10
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) + freshness_delta
            candidate["support_score"] = max(0, int(candidate["support_score"]) + max(freshness_delta // 2, 0))
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            if freshness_delta > 0:
                candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_same_kind_conclusion"]))
            elif freshness_delta < 0:
                candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "older_same_kind_conclusion"]))

def _runtime_context_prefers_cross_thread_recall(runtime_context: QueryRuntimeContext | None) -> bool:
    return bool(
        runtime_context is not None
        and runtime_context.turn_kind in {"new_thread", "new_session"}
        and runtime_context.session_has_sufficient_local_context is False
    )

def _apply_fresh_thread_structured_recall_preference(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    candidate_signals: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity", "work_resumption", "precise_fact"}:
        return
    if not _runtime_context_prefers_cross_thread_recall(runtime_context):
        return

    structured_support = max(
        _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_support"),
        _query_family_layer_metric(candidate_signals, "thread_summary", "best_support"),
        _query_family_layer_metric(candidate_signals, "discussion_summary", "best_support"),
        _query_family_layer_metric(candidate_signals, "continuity_memory", "best_support"),
        _query_family_layer_metric(candidate_signals, "pattern_memory", "best_support"),
        _query_family_layer_metric(candidate_signals, "decision", "best_support"),
        _query_family_layer_metric(candidate_signals, "investigation_outcome", "best_support"),
        _query_family_layer_metric(candidate_signals, "lower_level_memory", "best_support"),
    )
    if structured_support < ROUTING_SUPPORT_THRESHOLD["supported"]:
        return

    structured_layers = {
        "task_checkpoint",
        "thread_summary",
        "discussion_summary",
        "continuity_memory",
        "pattern_memory",
        "decision",
        "investigation_outcome",
        "lower_level_memory",
    }
    for candidate in scored_candidates:
        layer = str(candidate["layer"])
        if layer == "source_evidence":
            penalty = 120 if int(candidate["support_score"]) <= structured_support + 20 else 80
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
            candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 18))
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            candidate["packaging_reasons"] = list(
                OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_thread_structured_memory_preferred"])
            )
        elif layer in structured_layers and str(candidate["support_grade"]) in {"supported", "strong"}:
            bonus = 26 if layer in {"task_checkpoint", "decision", "investigation_outcome"} else 18
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) + bonus
            candidate["support_score"] = int(candidate["support_score"]) + max(bonus // 2, 8)
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            candidate["packaging_reasons"] = list(
                OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_thread_structured_memory_preferred"] )
            )

def _source_hit_matches_current_query_text(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
) -> bool:
    if item.result_kind != "source_hit":
        return False
    excerpt = normalize_for_index(str(item.excerpt or ""))
    normalized_query = normalize_for_index(query_text)
    if not excerpt or not normalized_query or excerpt != normalized_query:
        return False
    if item.role not in {None, "user"} and (item.source_type or "") not in {"chat_message", "message"}:
        return False
    if query_filters is not None and query_filters.thread_ref and not _candidate_matches_thread(item, query_filters):
        return False
    return True


def _apply_current_query_source_suppression(
    scored_candidates: list[dict[str, object]],
    *,
    query_text: str,
    query_filters: QueryFilters | None,
) -> None:
    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if not _source_hit_matches_current_query_text(item, query_text=query_text, query_filters=query_filters):
            continue
        penalty = 260
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
        candidate["support_score"] = 0
        candidate["support_grade"] = _routing_support_grade(0)
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "current_query_source_echo"]))
        candidate["suppression_reason_code"] = "current_query_source_echo"
        candidate["suppression_reason"] = "The active user query was excluded from recall evidence so routing does not self-echo the current turn."


def _apply_recall_source_noise_suppression(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity"}:
        return
    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "source_hit":
            continue
        if candidate.get("suppression_reason_code") == "current_query_source_echo":
            continue
        suppression = _source_noise_suppression_reason(
            item,
            query_text=query_text,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        if suppression is None:
            continue
        reason_code, reason_text = suppression
        penalty = 220 if reason_code in {"current_thread_recall_query", "duplicate_recall_query_source"} else 180
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
        candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 24))
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
        candidate["suppression_reason_code"] = reason_code
        candidate["suppression_reason"] = reason_text

def _is_current_query_echo(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
) -> bool:
    """Return True when a source hit is the user's own query echoed back from the same thread."""
    if item.result_kind != "source_hit":
        return False
    if item.role not in {None, "user"}:
        return False
    thread_ref = query_filters.thread_ref if query_filters else None
    if not thread_ref or item.thread_ref != thread_ref:
        return False
    return normalize_for_index(item.excerpt or "") == normalize_for_index(query_text)

def _source_noise_suppression_reason(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[str, str] | None:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return None
    if _is_low_value_meta_text(excerpt):
        return "low_value_meta_source", "Low-value orchestration source is not useful carry-forward for recall packaging."
    if _is_current_query_echo(item, query_text=query_text, query_filters=query_filters):
        if _runtime_context_prefers_cross_thread_recall(runtime_context):
            return "current_thread_recall_query", "The current fresh-thread query was excluded from cross-thread recall packaging."
        return "duplicate_recall_query_source", "A duplicate unresolved recall question was excluded from recall packaging."
    return None

def _apply_recall_structured_summary_suppression(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity"}:
        return
    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "memory_hit" or item.type not in ROUTING_SUMMARY_TYPES:
            continue
        suppression = _structured_summary_suppression_reason(
            item,
            query_text=query_text,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        if suppression is None:
            continue
        reason_code, reason_text = suppression
        penalty = 180
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
        candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 24))
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
        candidate["suppression_reason_code"] = reason_code
        candidate["suppression_reason"] = reason_text

def _structured_summary_suppression_reason(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[str, str] | None:
    if item.type != "thread_summary":
        return None
    payload = item.payload or {}
    summary_text = str(payload.get("summary") or "").strip()
    rejection = _summary_low_value_reason(
        item.type,
        payload,
        summary_text=summary_text,
        query_text=query_text,
    )
    if rejection is None:
        return None
    if _runtime_context_prefers_cross_thread_recall(runtime_context) and query_filters is not None and query_filters.thread_ref and item.thread_ref == query_filters.thread_ref:
        if rejection[0] == "query_only_thread_summary":
            return "current_thread_empty_summary", "A current-thread query-only summary was excluded from recall packaging."
        return "current_thread_unresolved_summary", "A current-thread unresolved summary was excluded from recall packaging."
    return rejection

def _summary_low_value_reason(
    memory_type: str,
    payload: dict[str, object],
    *,
    summary_text: str,
    query_text: str,
) -> tuple[str, str] | None:
    if memory_type not in ROUTING_SUMMARY_TYPES or not summary_text:
        return None
    content_quality = payload.get("content_quality")
    if content_quality == "query_only":
        return "query_only_thread_summary", "A query-only summary was excluded from recall packaging."
    if content_quality == "unresolved":
        return "unresolved_thread_summary", "An unresolved summary without durable state was excluded from recall packaging."
    if content_quality == "weak":
        return "weak_thread_summary", "A weak summary was excluded from recall packaging."
    return None

def _specificity_bonus(item: QueryResultItem, intent: str) -> int:
    bonus = 0
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if intent == "investigative_conclusion":
            bonus += 95 if item.type == "investigation_outcome" else 80
        elif intent in {"precise_fact", "evidence_trace"}:
            bonus += 50 if item.type == "decision" else 45
        else:
            bonus += 20
    if item.result_kind == "memory_hit" and item.type in ROUTING_SUMMARY_TYPES and intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
        bonus -= 40
    if item.result_kind == "memory_hit" and item.type == "thread_summary" and intent == "work_resumption":
        if _memory_hit_has_selected_work_artifacts(item):
            bonus += 35
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        if intent == "work_resumption":
            bonus += 55
        elif intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
            bonus -= 35
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "answer_continuity":
        bonus += 25
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and intent == "broad_recall":
        bonus += 85 if item.type == "decision" else 75
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "broad_recall":
        bonus -= 45
    if item.result_kind == "memory_hit" and item.type == "pattern_memory" and intent == "broad_recall":
        bonus += 25
    if item.result_kind == "source_hit" and intent == "evidence_trace":
        bonus += 30 if item.artifact_kind == "assistant_output" else 10
    if item.result_kind == "source_hit" and intent == "work_resumption":
        bonus += 45 if (item.artifact_kind or "") in SELECTED_WORK_ARTIFACT_KINDS else 20
    if item.result_kind == "source_hit" and intent == "investigative_conclusion":
        bonus += 6 if item.artifact_kind == "assistant_output" else 2
    return bonus


def _higher_level_retrieval_floor_adjustment(layer: str, retrieval_score: int) -> int:
    """Penalise higher-level memory whose retrieval score falls below the floor.

    Replaces the former token-overlap binary check.  The penalty magnitude
    (-260) matches the prior broad_recall overlap penalty so ranking behaviour
    is comparable.
    """
    if layer not in ROUTING_HIGHER_LEVEL_TYPES:
        return 0
    if retrieval_score < HIGHER_LEVEL_RETRIEVAL_FLOOR:
        return -260
    return 0






def _annotate_excluded_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    requested_limit: int,
    routing_focus: dict[str, object],
    packaging_summary: dict[str, object] | None,
) -> None:
    selected_result_ids = {_routing_result_id(candidate["item"]) for candidate in final_candidates}
    packaging_mode = str((packaging_summary or {}).get("mode") or "")
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if result_id in selected_result_ids:
            candidate["excluded_reason_code"] = None
            candidate["excluded_reason"] = None
            continue
        if candidate.get("suppression_reason_code"):
            candidate["excluded_reason_code"] = candidate.get("suppression_reason_code")
            candidate["excluded_reason"] = candidate.get("suppression_reason")
        elif (
            packaging_mode == "task_checkpoint_plus_adjacent_evidence"
            and int(candidate.get("routing_rank", 0)) <= requested_limit
        ):
            candidate["excluded_reason_code"] = "displaced_by_adjacent_evidence_packaging"
            candidate["excluded_reason"] = "Checkpoint packaging preferred adjacent source evidence for resumed-work coverage."
        elif bool(routing_focus.get("applied")) and str(candidate.get("layer")) == str(routing_focus.get("primary_layer")):
            candidate["excluded_reason_code"] = "fallback_layer_deprioritized"
            candidate["excluded_reason"] = str(routing_focus.get("reason"))
        else:
            candidate["excluded_reason_code"] = "lower_routing_score_than_selected_limit"
            candidate["excluded_reason"] = "Candidate remained below the final routed cutoff."


def _build_injectable_blocks(
    final_candidates: list[dict[str, object]],
    *,
    ranked_candidates: list[dict[str, object]],
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    same_thread_context = _evaluate_same_thread_local_context(
        ranked_candidates,
        intent=intent,
        query_text=query_text,
        query_filters=query_filters,
        runtime_context=runtime_context,
    )
    if same_thread_context["suppress_injection"]:
        return [], {
            "should_inject": False,
            "decision_reason": "same_thread_context_sufficient",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }
    if not final_candidates:
        return [], {
            "should_inject": False,
            "decision_reason": "no_relevant_memory",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    primary_non_discussion_eligible = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=False,
        )
    ]
    primary_eligible_candidates = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=not primary_non_discussion_eligible,
            allow_source_companion=False,
        )
    ]
    if not primary_eligible_candidates:
        decision_reason = "only_low_value_candidates" if any(_candidate_is_low_value(candidate) for candidate in final_candidates) else "no_relevant_memory"
        return [], {
            "should_inject": False,
            "decision_reason": decision_reason,
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    selected_candidates = list(primary_eligible_candidates[:3])
    if intent == "work_resumption" and len(selected_candidates) < 3:
        used_result_ids = {_routing_result_id(candidate["item"]) for candidate in selected_candidates}
        companion_candidates = [
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=True,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in used_result_ids
        ]
        for candidate in companion_candidates:
            if len(selected_candidates) >= 3:
                break
            selected_candidates.append(candidate)
            used_result_ids.add(_routing_result_id(candidate["item"]))

    blocks = [_build_injectable_block_from_candidate(candidate, intent=intent) for candidate in selected_candidates]
    returned_ids = [block.result_id for block in blocks]
    eligible_candidates = list(primary_eligible_candidates)
    if intent == "work_resumption":
        eligible_candidates.extend(
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=True,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in {_routing_result_id(item["item"]) for item in eligible_candidates}
        )
    eligible_ids = [_routing_result_id(candidate["item"]) for candidate in eligible_candidates]
    dropped_ids = [result_id for result_id in eligible_ids if result_id not in returned_ids]
    return blocks, {
        "should_inject": bool(blocks),
        "decision_reason": "carry_forward_available" if blocks else "no_relevant_memory",
        "returned_block_ids": returned_ids,
        "eligible_result_ids": eligible_ids,
        "dropped_by_cap_result_ids": dropped_ids,
        "cap": 3,
        "same_thread_context_evaluation": same_thread_context,
    }

def _evaluate_same_thread_local_context(
    ranked_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> dict[str, object]:
    if not (
        runtime_context is not None
        and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}
        and runtime_context.session_has_sufficient_local_context is True
    ):
        return {"evaluated": False, "suppress_injection": False}
    if query_filters is None or not query_filters.thread_ref:
        return {
            "evaluated": True,
            "suppress_injection": True,
            "reason_code": "runtime_same_thread_context_only",
            "qualifying_result_ids": [],
            "external_carry_forward_result_ids": [],
            "rejected_candidates": [],
        }

    qualifying_result_ids: list[str] = []
    external_carry_forward_result_ids: list[str] = []
    rejected_candidates: list[dict[str, str]] = []
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if bool(candidate.get("same_thread")):
            qualifies, reason_code = _candidate_qualifies_as_same_thread_local_state(
                candidate,
                intent=intent,
                query_text=query_text,
                query_filters=query_filters,
            )
            if qualifies:
                qualifying_result_ids.append(result_id)
                continue
            rejected_candidates.append({"result_id": result_id, "reason_code": reason_code})
            continue
        if _candidate_could_supply_external_carry_forward(candidate, intent=intent, query_text=query_text):
            external_carry_forward_result_ids.append(result_id)

    if qualifying_result_ids:
        reason_code = "relevant_same_thread_local_state"
        suppress_injection = True
    elif not external_carry_forward_result_ids:
        reason_code = "no_external_carry_forward_available"
        suppress_injection = True
    else:
        reason_code = "insufficient_same_thread_local_state"
        suppress_injection = False

    return {
        "evaluated": True,
        "suppress_injection": suppress_injection,
        "reason_code": reason_code,
        "qualifying_result_ids": qualifying_result_ids,
        "external_carry_forward_result_ids": external_carry_forward_result_ids[:6],
        "rejected_candidates": rejected_candidates[:6],
    }

def _candidate_could_supply_external_carry_forward(candidate: dict[str, object], *, intent: str, query_text: str) -> bool:
    if _candidate_is_low_value(candidate):
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text=query_text,
            allow_discussion_fallback=False,
            allow_source_companion=False,
        )
    return _candidate_is_injection_eligible(
        candidate,
        intent=intent,
        query_text=query_text,
        allow_discussion_fallback=True,
        allow_source_companion=False,
    )

def _candidate_qualifies_as_same_thread_local_state(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
) -> tuple[bool, str]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    suppression_reason = str(candidate.get("suppression_reason_code") or "")
    if suppression_reason:
        return False, suppression_reason
    if _candidate_is_low_value(candidate):
        return False, "low_value_same_thread_context"

    support_grade = str(candidate.get("support_grade") or "weak")
    support_score = int(candidate.get("support_score") or 0)
    work_usefulness = int(candidate.get("work_usefulness_score") or 0)
    overlap_tokens = list(candidate.get("content_overlap_tokens") or [])

    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        if normalize_for_index(excerpt) == normalize_for_index(query_text):
            return False, "current_query_same_thread_source"
        if _is_current_query_echo(item, query_text=query_text, query_filters=query_filters):
            return False, "query_like_same_thread_source"
        if work_usefulness >= 18:
            return True, ""
        if support_grade in {"supported", "strong"} and len(overlap_tokens) >= 2:
            if item.role == "assistant" or intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
                return True, ""
        return False, "weak_same_thread_source"

    if item.type in {"task_checkpoint", "decision", "investigation_outcome", CONSTRAINT_MEMORY_TYPE}:
        if support_grade in {"supported", "strong"}:
            return True, ""
        return False, "weak_same_thread_structured_state"

    if item.type in {"thread_summary", "discussion_summary"}:
        payload = item.payload or {}
        summary_text = str(payload.get("summary") or "").strip()
        summary_rejection = _summary_low_value_reason(
            item.type,
            payload,
            summary_text=summary_text,
            query_text=query_text,
        )
        if summary_rejection is not None:
            return False, summary_rejection[0]
        if payload.get("selected_work_artifacts") or payload.get("conclusions"):
            return True, ""
        if payload.get("content_quality") == "substantive":
            return True, ""
        if support_grade in {"supported", "strong"} and (support_score >= ROUTING_SUPPORT_THRESHOLD["supported"] or len(overlap_tokens) >= 2):
            return True, ""
        return False, "weak_same_thread_summary"

    return False, "non_local_state_candidate"

def _candidate_is_injection_eligible(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
    allow_discussion_fallback: bool,
    allow_source_companion: bool,
) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if _candidate_is_low_value(candidate):
        return False
    if candidate.get("suppression_reason_code"):
        return False
    if item.result_kind == "source_hit":
        if normalize_for_index(str(item.excerpt or "")) == normalize_for_index(query_text):
            return False
        if _source_candidate_is_primary_injection_eligible(candidate, intent, query_text=query_text):
            return True
        return allow_source_companion and _source_candidate_is_companion_injection_eligible(intent)
    if item.type in {"decision", "investigation_outcome", "task_checkpoint", "continuity_memory", "pattern_memory", "interest", "thread_summary", CONSTRAINT_MEMORY_TYPE}:
        return True
    if item.type == "discussion_summary":
        return allow_discussion_fallback
    return False

def _query_requests_quote_grade_source(query_text: str) -> bool:
    lowered = query_text.lower()
    if any(
        cue in lowered
        for cue in (
            "exact line",
            "exact log line",
            "proof line",
            "smoking gun",
            "exact wording",
            "exact text",
            "quote the",
            "quote that",
        )
    ):
        return True
    if ("which line" in lowered or "what line" in lowered) and any(
        cue in lowered for cue in ("prove", "proved", "proof", "backed", "support", "supported", "log")
    ):
        return True
    return False

def _source_candidate_has_quote_grade_support(candidate: dict[str, object], *, query_text: str) -> bool:
    if not _query_requests_quote_grade_source(query_text):
        return False
    overlap_tokens = {str(token) for token in candidate.get("content_overlap_tokens") or []}
    proof_overlap = overlap_tokens.intersection({"exact", "line", "log", "proof", "quote"})
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    excerpt = str(item.excerpt or "")
    excerpt_lower = excerpt.lower()
    if any(hedge in excerpt_lower for hedge in ("probably", "maybe", "somewhere", "did not keep", "don't have", "not sure")):
        return False
    proof_like_excerpt = any(
        cue in excerpt_lower
        for cue in ("investigation found", "exact log line", "smoking gun", "showed", "proved", "backed")
    )
    quoted_evidence = (excerpt.count("'") >= 2 or excerpt.count('"') >= 2) and bool(proof_overlap)
    support_grade = str(candidate.get("support_grade") or "weak")
    return (support_grade in {"supported", "strong"} and proof_like_excerpt) or quoted_evidence


def _source_excerpt_disclaims_exact_evidence(excerpt: str) -> bool:
    """Return True when the source explicitly states that exact evidence was not retained.

    This is an interim guardrail for evidence_trace suppression.  It catches
    sources that directly disclaim having the evidence ("did not keep the exact
    line", "not preserved", etc.) rather than sources that simply lack strong
    proof.  Keep this list narrow — "probably" alone is NOT sufficient.
    """
    lowered = excerpt.lower()
    return any(phrase in lowered for phrase in (
        "did not keep",
        "didn't keep",
        "don't have the exact",
        "do not have the exact",
        "didn't have the exact",
        "couldn't find the exact",
        "could not find the exact",
        "can't find the exact",
        "cannot find the exact",
        "no exact record",
        "not preserved",
        "wasn't preserved",
        "was not preserved",
    ))


def _source_candidate_is_primary_injection_eligible(candidate: dict[str, object], intent: str, *, query_text: str) -> bool:
    if intent == "evidence_trace":
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        excerpt = str(item.excerpt or "")
        if _source_excerpt_disclaims_exact_evidence(excerpt):
            return False
        return True
    if intent == "investigative_conclusion":
        return True
    return intent == "precise_fact" and _source_candidate_has_quote_grade_support(candidate, query_text=query_text)

def _source_candidate_is_companion_injection_eligible(intent: str) -> bool:
    return intent == "work_resumption"

def _candidate_is_low_value(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        return _is_low_value_meta_text(excerpt)
    if item.type in {"discussion_summary", "thread_summary"}:
        payload = item.payload or {}
        return _is_low_value_meta_text(str(payload.get("summary") or ""))
    return False

def _task_checkpoint_injection_text(payload: dict[str, object]) -> str:
    summary = str(payload.get("summary") or "").strip()
    current_state = str(payload.get("current_state") or "").strip()
    blocker = str(payload.get("blocker_state") or "").strip()
    next_step = str(payload.get("next_step") or "").strip()
    parts: list[str] = []
    # When an active blocker is present, lead with it so the blocking issue is
    # immediately visible — it is the most actionable signal for resumption.
    if blocker:
        parts.append(f"Blocker: {blocker}")
    if current_state and normalize_for_index(current_state) not in normalize_for_index(blocker):
        parts.append(f"Current state: {current_state}")
    elif not blocker and summary:
        parts.append(summary)
    if next_step:
        parts.append(f"Next step: {next_step}")
    # Always include summary when it carries task identity not already present.
    # This matters for blocker-only checkpoints where current_state is absent:
    # without summary the injected text is just "Blocker: ..." with no task context.
    if summary and not current_state:
        parts.append(summary)
    return _join_unique_text_parts(parts)


def _build_injectable_block_from_candidate(candidate: dict[str, object], *, intent: str) -> InjectableBlock:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="source_evidence",
            title="Supporting Evidence",
            text=str(item.excerpt or "").strip(),
            memory_type=None,
            evidence=item.evidence,
        )

    payload = item.payload or {}
    if item.type == "decision":
        text = str(payload.get("decision") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Decision: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Decision",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "investigation_outcome":
        text = str(payload.get("investigation_outcome") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Investigation outcome: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Investigation",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "task_checkpoint":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Task Checkpoint",
            text=_task_checkpoint_injection_text(payload),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == CONSTRAINT_MEMORY_TYPE:
        constraint_text = str(payload.get("constraint_text") or payload.get("summary") or "").strip()
        summary_text = str(payload.get("summary") or "").strip()
        constraint_line = f"Constraint: {constraint_text}" if constraint_text else ""
        summary_line = ""
        if summary_text and normalize_for_index(summary_text) != normalize_for_index(constraint_line):
            summary_line = summary_text
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Active Constraint",
            text=_join_unique_text_parts([constraint_line, summary_line]),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "continuity_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Carry Forward",
            text=str(payload.get("carry_forward_answer") or payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "pattern_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Pattern Memory",
            text=str(payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "interest":
        interest_text = str(payload.get("interest_text") or payload.get("summary") or "").strip()
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Interest",
            text=interest_text,
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type in {"thread_summary", "discussion_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary" if item.type == "thread_summary" else "Discussion Summary",
            text=summary_text,
            evidence=item.evidence,
            memory_type=item.type,
        )
    return InjectableBlock(
        result_id=str(item.result_id),
        block_type="memory",
        title=item.type or "Memory",
        text=str(payload.get("summary") or "").strip(),
        evidence=item.evidence,
        memory_type=item.type,
    )

def _join_unique_text_parts(parts: list[str]) -> str:
    ordered_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = str(part or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered_parts.append(normalized)
    return " ".join(ordered_parts)

def _candidate_evidence_shape_score(
    item: QueryResultItem,
    *,
    layer: str,
    query_filters: QueryFilters | None,
) -> int:
    score = 0
    evidence_count = len(item.evidence)
    score += min(evidence_count, 3) * 8
    if _candidate_matches_thread(item, query_filters):
        score += 12
    elif _candidate_matches_container(item, query_filters):
        score += 6

    if item.result_kind == "source_hit":
        artifact_kind = (item.artifact_kind or "").lower()
        if artifact_kind in SELECTED_WORK_ARTIFACT_KINDS:
            score += 34
        elif artifact_kind == "assistant_output":
            score += 28
        else:
            score += 18
        return score

    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        score += 42
        payload = item.payload or {}
        if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
            score += 10
        return score

    payload = item.payload or {}
    if item.type == "task_checkpoint":
        explicit_fields = sum(
            1
            for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
            if str(payload.get(key) or "").strip()
        )
        selected_work_artifacts = payload.get("selected_work_artifacts", [])
        artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
        key_findings = _parse_string_list(payload.get("key_findings"))
        evidence_lines = _parse_string_list(payload.get("evidence"))
        score += 18 + min(explicit_fields, 5) * 8 + min(artifact_count, 4) * 6
        score += min(len(key_findings), 3) * 4 + min(len(evidence_lines), 3) * 5
        if str(payload.get("blocker_state") or "").strip() and str(payload.get("next_step") or "").strip():
            score += 10
        freshness_text = str(payload.get("freshness_signal") or "").lower()
        if freshness_text and any(marker in freshness_text for marker in ("latest", "current", "stale")):
            score += 6
        if not evidence_lines and not key_findings:
            score -= 12
        return score

    if item.type == "continuity_memory":
        score += 18
        if str(payload.get("carry_forward_answer") or "").strip():
            score += 18
    elif item.type == "pattern_memory":
        score += 14
        if str(payload.get("pattern_label") or "").strip() and str(payload.get("pattern_label") or "").strip() != "generic_pattern":
            score += 10
    elif item.type in ROUTING_SUMMARY_TYPES:
        score += 8

    conclusions = payload.get("conclusions", [])
    if isinstance(conclusions, list):
        score += min(len([entry for entry in conclusions if isinstance(entry, dict) and entry.get("text")]), 3) * 8
    return score

def _apply_work_resumption_packaging(
    scored_candidates: list[dict[str, object]],
    *,
    query_filters: QueryFilters | None,
    thin_checkpoint_penalty: int | None = None,
) -> dict[str, object]:
    relevant_candidates = [
        candidate
        for candidate in scored_candidates
        if _candidate_matches_requested_locality(candidate, query_filters)
    ]
    freshest_timestamp = max(
        (
            timestamp
            for timestamp in (
                candidate.get("freshness_timestamp_value")
                for candidate in relevant_candidates
            )
            if isinstance(timestamp, datetime)
        ),
        default=None,
    )

    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        signal_types = _work_resumption_signal_types(item)
        candidate["work_signal_types"] = signal_types
        usefulness_score, usefulness_reasons = _work_resumption_usefulness_score(item, signal_types, thin_checkpoint_penalty=thin_checkpoint_penalty)
        freshness_adjustment, freshness_reasons = _work_resumption_freshness_adjustment(candidate, freshest_timestamp)
        packaging_adjustment = usefulness_score + freshness_adjustment
        candidate["work_usefulness_score"] = usefulness_score
        candidate["packaging_adjustment"] = packaging_adjustment
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*usefulness_reasons, *freshness_reasons]))
        timestamp = candidate.get("freshness_timestamp_value")
        candidate["freshness_timestamp"] = timestamp.isoformat() if isinstance(timestamp, datetime) else None
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) + packaging_adjustment
        support_adjustment = (usefulness_score // 2) + freshness_adjustment
        candidate["support_score"] = max(0, int(candidate["support_score"]) + support_adjustment)
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))

    return {
        "mode": "work_resumption_ranking",
        "freshest_state_timestamp": freshest_timestamp.isoformat() if isinstance(freshest_timestamp, datetime) else None,
    }

def _candidate_matches_requested_locality(candidate: dict[str, object], query_filters: QueryFilters | None) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if query_filters is not None and query_filters.thread_ref:
        return query_filters.thread_ref in _candidate_thread_refs(item)
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in _candidate_container_refs(item)
    return True

def _work_resumption_freshness_adjustment(
    candidate: dict[str, object],
    freshest_timestamp: datetime | None,
) -> tuple[int, list[str]]:
    timestamp = candidate.get("freshness_timestamp_value")
    signal_types = set(candidate.get("work_signal_types") or ())
    if not isinstance(timestamp, datetime):
        return 0, []
    if freshest_timestamp is None:
        if candidate["layer"] == "task_checkpoint" and "freshness" in signal_types:
            return 8, ["explicit_freshness_signal"]
        return 0, []

    delta_seconds = (freshest_timestamp - timestamp).total_seconds()
    if delta_seconds >= WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS:
        if candidate["layer"] == "task_checkpoint":
            return -WORK_RESUMPTION_STALE_STATE_PENALTY, ["stale_against_fresher_state"]
        if candidate["layer"] == "source_evidence":
            return -WORK_RESUMPTION_STALE_SOURCE_PENALTY, ["stale_against_fresher_state"]
        return -(WORK_RESUMPTION_STALE_SOURCE_PENALTY // 2), ["stale_against_fresher_state"]
    if delta_seconds <= 0 and signal_types.intersection({"blocker", "next_step", "progress_update"}):
        return WORK_RESUMPTION_FRESH_STATE_BONUS, ["fresh_explicit_state"]
    if candidate["layer"] == "task_checkpoint" and "freshness" in signal_types:
        return 8, ["explicit_freshness_signal"]
    return 0, []

def _select_final_candidates(
    *,
    intent: str,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_filters: QueryFilters | None,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
    packaging_summary: dict[str, object] | None,
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    summary = dict(packaging_summary or {})
    if not ranked_candidates:
        return ranked_candidates[:requested_limit], summary or None
    if intent in {"broad_recall", "answer_continuity"}:
        return _select_compatible_recall_candidates(
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_shape_tags=query_shape_tags,
            packaging_summary=summary,
            selected_lane=selected_lane,
        )
    if intent != "work_resumption":
        return ranked_candidates[:requested_limit], summary or None

    # Filter out suppressed candidates
    unsuppressed = [c for c in ranked_candidates if not c.get("suppression_reason_code")]
    if not unsuppressed:
        return [], summary or None
    top_candidate = unsuppressed[0]
    summary["top_result_layer"] = top_candidate["layer"]
    if top_candidate["layer"] != "task_checkpoint" or requested_limit <= 1:
        demoted_checkpoint = next((candidate for candidate in ranked_candidates if candidate["layer"] == "task_checkpoint"), None)
        if demoted_checkpoint is not None and demoted_checkpoint is not top_candidate:
            summary["demoted_task_checkpoint"] = {
                "result_id": _routing_result_id(demoted_checkpoint["item"]),
                "packaging_reasons": list(demoted_checkpoint["packaging_reasons"]),
            }
        return ranked_candidates[:requested_limit], summary

    selected_candidates = [top_candidate]
    used_result_ids = {_routing_result_id(top_candidate["item"])}
    adjacent_evidence: list[dict[str, str]] = []
    for signal_type in WORK_RESUMPTION_SIGNAL_PRIORITY:
        if len(selected_candidates) >= requested_limit:
            break
        for candidate in ranked_candidates[1:]:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if candidate["layer"] != "source_evidence":
                continue
            if signal_type not in candidate["work_signal_types"]:
                continue
            if not _candidate_locality_compatible_for_packaging(top_candidate["item"], candidate["item"], query_filters):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
            adjacent_evidence.append({"signal_type": signal_type, "result_id": candidate_result_id})
            break

    if adjacent_evidence:
        summary["mode"] = "task_checkpoint_plus_adjacent_evidence"
        summary["adjacent_evidence"] = adjacent_evidence
    else:
        summary["mode"] = "task_checkpoint_only"

    # Fill any remaining slots with the next-best non-suppressed candidates.
    # The signal-based source_evidence pass may not exhaust the requested limit
    # (e.g. when few source_evidence items carry a matching signal type).  Lower-
    # level memory (decision, investigation_outcome) is useful supporting context
    # and should fill those slots rather than leaving them empty.
    # Apply the same locality guard as the adjacent-evidence pass above so that
    # only same-thread / same-container derived memory is included.
    if len(selected_candidates) < requested_limit:
        CHECKPOINT_FILL_ALLOWED_LAYERS = {"decision", "investigation_outcome", "lower_level_memory"}
        for candidate in ranked_candidates[1:]:
            if len(selected_candidates) >= requested_limit:
                break
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if candidate.get("suppression_reason_code"):
                continue
            if candidate["layer"] not in CHECKPOINT_FILL_ALLOWED_LAYERS:
                continue
            if not _candidate_locality_compatible_for_packaging(top_candidate["item"], candidate["item"], query_filters):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)

    return selected_candidates, summary

def _select_compatible_recall_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_shape_tags: list[str],
    packaging_summary: dict[str, object],
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    # Filter out suppressed candidates
    compatible_candidates = [c for c in ranked_candidates if not c.get("suppression_reason_code")]
    if not compatible_candidates:
        return [], packaging_summary or None

    primary_candidate = compatible_candidates[0]

    selected_candidates = [primary_candidate]
    used_result_ids = {_routing_result_id(primary_candidate["item"])}
    primary_retrieval_score = int(primary_candidate.get("retrieval_score") or 0)
    retrieval_score_floor = primary_retrieval_score * 0.5

    remaining_candidates = [
        candidate
        for candidate in compatible_candidates
        if _routing_result_id(candidate["item"]) not in used_result_ids
    ]
    structured_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) == "memory_hit"
    ]
    source_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) != "memory_hit"
    ]
    for candidate_group in (structured_remaining, source_remaining):
        for candidate in candidate_group:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if len(selected_candidates) >= requested_limit:
                break
            candidate_retrieval_score = int(candidate.get("retrieval_score") or 0)
            if primary_retrieval_score > 0 and candidate_retrieval_score < retrieval_score_floor:
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
        if len(selected_candidates) >= requested_limit:
            break

    return selected_candidates, packaging_summary or None

def _candidate_locality_compatible_for_packaging(
    primary_item: QueryResultItem,
    candidate_item: QueryResultItem,
    query_filters: QueryFilters | None,
) -> bool:
    primary_thread_refs = set(_candidate_thread_refs(primary_item))
    candidate_thread_refs = set(_candidate_thread_refs(candidate_item))
    if query_filters is not None and query_filters.thread_ref:
        return query_filters.thread_ref in primary_thread_refs and query_filters.thread_ref in candidate_thread_refs
    if primary_thread_refs and candidate_thread_refs and primary_thread_refs.intersection(candidate_thread_refs):
        return True

    primary_container_refs = set(_candidate_container_refs(primary_item))
    candidate_container_refs = set(_candidate_container_refs(candidate_item))
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in primary_container_refs and query_filters.container_ref in candidate_container_refs
    if primary_container_refs and candidate_container_refs:
        return bool(primary_container_refs.intersection(candidate_container_refs))
    return True


def _summarize_routing_layers(scored_candidates: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    all_layers = {
        "pattern_memory",
        "continuity_memory",
        "task_checkpoint",
        "lower_level_memory",
        "source_evidence",
        "decision",
        "investigation_outcome",
        "thread_summary",
        "discussion_summary",
    }
    lower_level_layers = {"lower_level_memory", "decision", "investigation_outcome"}
    for layer in sorted(all_layers):
        if layer == "lower_level_memory":
            layer_candidates = [candidate for candidate in scored_candidates if str(candidate["layer"]) in lower_level_layers]
        else:
            layer_candidates = [candidate for candidate in scored_candidates if candidate["layer"] == layer]
        if not layer_candidates:
            summary[layer] = {
                "candidate_count": 0,
                "supported_candidate_count": 0,
                "strong_candidate_count": 0,
            }
            continue
        best_candidate = max(
            layer_candidates,
            key=lambda candidate: (int(candidate["support_score"]), int(candidate["retrieval_score"])),
        )
        summary[layer] = {
            "candidate_count": len(layer_candidates),
            "supported_candidate_count": sum(
                1 for candidate in layer_candidates if str(candidate["support_grade"]) in {"supported", "strong"}
            ),
            "strong_candidate_count": sum(1 for candidate in layer_candidates if candidate["support_grade"] == "strong"),
            "best_support_score": best_candidate["support_score"],
            "best_support_grade": best_candidate["support_grade"],
            "best_retrieval_score": best_candidate["retrieval_score"],
            "best_lexical_rank": best_candidate["lexical_rank"],
        }
    return summary

def _select_routing_focus(
    *,
    intent: str,
    preferred_layers: tuple[str, ...],
    layer_summary: dict[str, dict[str, object]],
    fallback_margin: int | None = None,
) -> dict[str, object]:
    _margin = fallback_margin if fallback_margin is not None else ROUTING_FALLBACK_MARGIN
    primary_layer = preferred_layers[0]
    primary_summary = layer_summary.get(primary_layer, {})
    selected_layer = primary_layer
    applied = False
    reason_code = "preferred_layer_supported"
    reason = "Preferred layer had enough candidate support to stay selected."

    fallback_candidates = [
        (layer, layer_summary.get(layer, {}))
        for layer in ROUTING_SAFE_FALLBACK_LAYERS[intent]
        if int(layer_summary.get(layer, {}).get("candidate_count", 0)) > 0
    ]
    best_fallback_layer = None
    best_fallback_summary = None
    if fallback_candidates:
        if intent == "broad_recall":
            structured_fallback = [
                (layer, summary)
                for layer, summary in fallback_candidates
                if layer in {"task_checkpoint", "thread_summary", "discussion_summary", "lower_level_memory"}
                and str(summary.get("best_support_grade", "weak")) in {"supported", "strong"}
            ]
            supported_lower_level = next(
                (
                    (layer, summary)
                    for layer, summary in fallback_candidates
                    if layer == "lower_level_memory"
                    and str(summary.get("best_support_grade", "weak")) in {"supported", "strong"}
                ),
                None,
            )
            if structured_fallback:
                best_fallback_layer, best_fallback_summary = max(
                    structured_fallback,
                    key=lambda item: (
                        int(item[1].get("best_support_score", 0)),
                        int(item[1].get("best_retrieval_score", 0)),
                    ),
                )
            elif supported_lower_level is not None:
                best_fallback_layer, best_fallback_summary = supported_lower_level
            else:
                best_fallback_layer, best_fallback_summary = max(
                    fallback_candidates,
                    key=lambda item: (
                        int(item[1].get("best_support_score", 0)),
                        int(item[1].get("best_retrieval_score", 0)),
                    ),
                )
        else:
            best_fallback_layer, best_fallback_summary = max(
                fallback_candidates,
                key=lambda item: (
                    int(item[1].get("best_support_score", 0)),
                    int(item[1].get("best_retrieval_score", 0)),
                ),
            )
    primary_count = int(primary_summary.get("candidate_count", 0))
    primary_support = int(primary_summary.get("best_support_score", 0))
    primary_grade = str(primary_summary.get("best_support_grade", "weak"))

    if primary_count == 0 and best_fallback_layer is not None and best_fallback_summary is not None:
        selected_layer = best_fallback_layer
        applied = True
        reason_code = "preferred_layer_missing"
        reason = f"No {primary_layer} candidate was retrieved, so routing fell back to the sharpest safer layer."
    elif primary_layer in ROUTING_HIGHER_LEVEL_TYPES and best_fallback_layer is not None and best_fallback_summary is not None:
        fallback_support = int(best_fallback_summary.get("best_support_score", 0))
        fallback_grade = str(best_fallback_summary.get("best_support_grade", "weak"))
        if (
            intent in {"answer_continuity", "work_resumption"}
            and primary_grade == "weak"
            and fallback_grade == "strong"
            and fallback_support >= primary_support + _margin
        ):
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "weak_higher_level_support"
            reason = "Higher-level memory was retrieved, but its candidate support was materially weaker than a strongly supported safer layer."
        elif intent not in {"answer_continuity", "work_resumption"} and primary_grade == "weak" and fallback_grade in {"supported", "strong"}:
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "weak_higher_level_support"
            reason = "Higher-level memory was retrieved, but its candidate support was weak, so routing chose a safer layer."
        elif (
            intent == "work_resumption"
            and primary_layer == "task_checkpoint"
            and best_fallback_layer == "source_evidence"
            and primary_grade in {"supported", "strong"}
        ):
            reason_code = "supported_checkpoint_preserved"
            reason = "Supported task-checkpoint packaging stayed selected because resumed-work carry-forward needs explicit blocker and next-step state."
        elif fallback_support >= primary_support + _margin:
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "safer_layer_stronger"
            reason = "A safer layer had materially stronger candidate support than the higher-level preference."
    elif (
        primary_layer in {"source_evidence", "lower_level_memory"}
        and intent != "evidence_trace"
        and best_fallback_layer is not None
        and best_fallback_summary is not None
        and primary_grade == "weak"
        and str(best_fallback_summary.get("best_support_grade", "weak")) in {"supported", "strong"}
    ):
        selected_layer = best_fallback_layer
        applied = True
        reason_code = "primary_support_weak"
        reason = "The preferred sharp layer was weakly supported, so routing used the next safer retrieved layer."

    return {
        "applied": applied,
        "primary_layer": primary_layer,
        "selected_layer": selected_layer,
        "reason_code": reason_code,
        "reason": reason,
    }

def _routing_focus_adjustment(
    *,
    layer: str,
    selected_layer: str,
    primary_layer: str,
    fallback_applied: bool,
    focus_boost: int | None = None,
) -> int:
    _boost = focus_boost if focus_boost is not None else ROUTING_FOCUS_BOOST
    adjustment = _boost if layer == selected_layer else 0
    if fallback_applied and primary_layer in ROUTING_HIGHER_LEVEL_TYPES and layer == primary_layer and layer != selected_layer:
        adjustment -= ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY
    return adjustment


