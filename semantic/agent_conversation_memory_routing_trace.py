from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from core.models import InjectableBlock, QueryResultItem, QueryRuntimeContext
from semantic.agent_conversation_memory_anchors import (
    _serialize_subject_anchors,
)
from semantic.agent_conversation_memory_routing_constants import (
    LaneNarrowingResult,
    PolicySelectedContext,
    QuerySignalEnvelope,
    PASSTHROUGH_POLICY,
    ROUTING_HIGHER_LEVEL_TYPES,
    ROUTING_POLICY_NAME,
    SHARP_DIAGNOSTIC_MEMORY_TYPES,
    _routing_result_id,
)


def _build_anchor_prefilter_trace_entry(
    item: QueryResultItem,
    *,
    status: str,
    reason_code: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    entry = {
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


def _query_family_label(intent: str, *, runtime_context: QueryRuntimeContext | None, injection_summary: dict[str, object] | None = None) -> str:
    turn_kind = runtime_context.turn_kind if runtime_context is not None else None
    session_has_sufficient_local_context = (
        runtime_context.session_has_sufficient_local_context if runtime_context is not None else None
    )
    if turn_kind in {"same_thread", "same_thread_continuation"} and session_has_sufficient_local_context is True:
        decision_reason = str((injection_summary or {}).get("decision_reason") or "")
        should_inject = bool((injection_summary or {}).get("should_inject"))
        if decision_reason == "same_thread_context_sufficient" or not should_inject and decision_reason in {"same_thread_context_sufficient", "no_relevant_memory", "only_low_value_candidates"}:
            return "same_thread_no_value_continuation"
    if intent == "answer_continuity":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
    if intent == "work_resumption":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
    if intent == "broad_recall":
        return "broad_recurring_recall"
    return intent


def _routing_reason(
    intent: str,
    layer: str,
    support_grade: str,
    routing_focus: dict[str, object],
    packaging_reasons: list[str],
) -> str:
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if layer in ROUTING_HIGHER_LEVEL_TYPES else ""
    fallback_suffix = _routing_fallback_suffix(
        layer=layer,
        selected_layer=str(routing_focus["selected_layer"]),
        primary_layer=str(routing_focus["primary_layer"]),
        applied=bool(routing_focus["applied"]),
        reason_code=str(routing_focus["reason_code"]),
        support_grade=support_grade,
    )
    packaging_suffix = _routing_packaging_suffix(packaging_reasons)
    if intent == "investigative_conclusion":
        if layer == "investigation_outcome":
            return "Investigative wording favors prior resolved findings before broader summaries." + fallback_suffix + packaging_suffix
        if layer == "decision":
            return "A prior decision remains sharp context, but explicit investigation findings outrank it here." + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Source evidence stays close behind carried conclusions for investigative questions." + fallback_suffix + packaging_suffix
        if layer == "thread_summary":
            return "Thread summaries stay available, but investigative queries prefer sharper findings and decisions first." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Discussion summaries are last-resort context for investigative questions." + weak_match_suffix + fallback_suffix + packaging_suffix
    if intent == "answer_continuity":
        if layer == "continuity_memory":
            return "Repeated-answer wording favors compact carry-forward memory." + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are narrower than repeated-answer carry-forward memory." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "pattern_memory":
            return "Broad pattern memory is demoted because the query is asking whether the answer was already given." + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Exact lower-level memory remains a fallback behind continuity carry-forward." + fallback_suffix + packaging_suffix
        return "Source evidence remains available, but routing prefers compact carry-forward first." + fallback_suffix + packaging_suffix
    if intent == "broad_recall":
        if layer == "pattern_memory":
            return "Broad recall wording favors higher-level pattern memory." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory is narrower than the broad prior-conclusion question." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are narrower than the broad prior-conclusion question." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Lower-level memory stays relevant, but broader recall prefers a consolidated pattern when present." + fallback_suffix + packaging_suffix
        return "Source evidence remains available, but compact prior-conclusion memory is preferred." + fallback_suffix + packaging_suffix
    if intent == "work_resumption":
        if layer == "task_checkpoint":
            return "Resume-oriented wording favors compact task checkpoints that preserve task state, blockers, and next steps." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Resume-oriented wording favors exact prior work artifacts and source evidence." + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Lower-level memory can orient resumed work, but routing keeps sharper prior work evidence ahead of summaries." + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory can help resumed work, but exact blocker and next-step evidence is preferred first." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Pattern or summary memory is too broad for resume-oriented state carry-forward." + weak_match_suffix + fallback_suffix + packaging_suffix
    if intent == "precise_fact":
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Precise factual wording favors exact lower-level memory over higher-level summaries." + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Source evidence stays near the top for precise factual lookup." + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are demoted because they compress state instead of preserving exact factual detail." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory is demoted because it can blur exact factual lookup." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Higher-level summary memory is demoted because it can blur exact factual lookup." + weak_match_suffix + fallback_suffix + packaging_suffix
    if layer == "source_evidence":
        return "Evidence-trace wording favors raw supporting source evidence." + fallback_suffix + packaging_suffix
    if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
        return "Lower-level memory stays close behind source evidence for evidence-trace questions." + fallback_suffix + packaging_suffix
    if layer == "task_checkpoint":
        return "Task checkpoints are demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix
    if layer == "continuity_memory":
        return "Continuity memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix
    return "Pattern or summary memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix

def _routing_strategy_name(item: QueryResultItem) -> str | None:
    if item.result_kind != "memory_hit" or not item.payload:
        return None
    provenance = item.payload.get("consolidation_provenance", {})
    if not isinstance(provenance, dict):
        return None
    strategy_name = provenance.get("strategy_name")
    return str(strategy_name) if isinstance(strategy_name, str) and strategy_name else None


def _build_signal_envelope_trace(envelope: QuerySignalEnvelope) -> dict[str, object]:
    return {
        "low_value": envelope.low_value,
        "history_lookup": envelope.history_lookup,
        "latest_status_request": envelope.latest_status_request,
        "resume_state": envelope.resume_state,
        "evidence_request": envelope.evidence_request,
        "source": envelope.source,
        "confidence": envelope.confidence,
        "semantic_classification_used": envelope.semantic_classification_used,
        "derivation_signals": list(envelope.derivation_signals),
    }


def _build_lane_narrowing_trace(
    lane_result: LaneNarrowingResult,
    *,
    final_intent_used: bool,
) -> dict[str, object]:
    eligible = [le for le in lane_result.eligible_lanes if le.state != "excluded"]
    excluded = [le for le in lane_result.eligible_lanes if le.state == "excluded"]
    trace: dict[str, object] = {
        "eligible_lanes": [le.lane for le in eligible],
        "excluded_lanes": [le.lane for le in excluded],
        "lane_exclusion_reasons": {le.lane: le.reason for le in excluded},
        "lane_details": [
            {"lane": le.lane, "state": le.state,
             "structural_signals": list(le.structural_signals),
             "shape_signals": list(le.shape_signals),
             "reason": le.reason}
            for le in lane_result.eligible_lanes
        ],
        "selected_lane": lane_result.selected_lane,
        "selection_mode": lane_result.selection_mode,
        "lane_narrowing_used_intent": lane_result.lane_narrowing_used_intent,
        "final_intent_used": final_intent_used,
        "intent_effect": lane_result.intent_effect,
        "abstain_reason": lane_result.abstain_reason,
    }
    return trace


def _build_routing_trace(
    *,
    intent: str,
    family_inference: dict[str, object],
    preferred_layers: tuple[str, ...],
    layer_summary: dict[str, dict[str, object]],
    routing_focus: dict[str, object],
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    packaging_summary: dict[str, object] | None,
    runtime_context: QueryRuntimeContext | None,
    injection_summary: dict[str, object],
    sharp_candidate_diagnostics: list[dict[str, object]],
    kind_prefilter_summary: dict[str, object],
    anchor_prefilter_summary: dict[str, object],
    policy_ctx: PolicySelectedContext = PASSTHROUGH_POLICY,
    lane_result: LaneNarrowingResult | None = None,
    final_intent_used: bool = True,
    signal_envelope: QuerySignalEnvelope | None = None,
    recall_mode: str = "default",
    relevance_floor: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_results = [_build_routing_trace_entry(candidate) for candidate in final_candidates]
    demoted_higher_level_hits = [
        _build_routing_trace_entry(candidate)
        for candidate in ranked_candidates
        if candidate["layer"] in ROUTING_HIGHER_LEVEL_TYPES
        and int(candidate["routing_rank"]) > int(candidate["lexical_rank"])
    ][:4]
    excluded_high_scoring_candidates = [
        _build_routing_trace_entry(candidate)
        for candidate in ranked_candidates
        if candidate.get("excluded_reason_code")
    ][:5]
    returned_result_kinds: dict[str, int] = {}
    for candidate in final_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        returned_result_kinds[item.result_kind] = returned_result_kinds.get(item.result_kind, 0) + 1
    trace = {
        "policy_name": ROUTING_POLICY_NAME,
        "query_intent": intent,
        "query_family": _query_family_label(intent, runtime_context=runtime_context, injection_summary=injection_summary),
        "family_inference": family_inference,
        "preferred_layers": list(preferred_layers),
        "selected_layer": routing_focus["selected_layer"],
        "candidate_count_entering_routing": len(ranked_candidates),
        "returned_result_kinds": returned_result_kinds,
        "fallback": {
            "applied": routing_focus["applied"],
            "from_layer": routing_focus["primary_layer"],
            "to_layer": routing_focus["selected_layer"],
            "reason_code": routing_focus["reason_code"],
            "reason": routing_focus["reason"],
        },
        "candidate_summary": layer_summary,
        "kind_prefilter": kind_prefilter_summary,
        "anchor_prefilter": anchor_prefilter_summary,
        "relevance_floor": relevance_floor,
        "selected_results": selected_results,
        "excluded_high_scoring_candidates": excluded_high_scoring_candidates,
        "demoted_higher_level_hits": demoted_higher_level_hits,
        "injection_decision": injection_summary,
        "sharp_candidate_diagnostics": sharp_candidate_diagnostics,
        "query_policy_family": policy_ctx.query_policy_family,
    }
    if lane_result is not None:
        trace["lane_narrowing"] = _build_lane_narrowing_trace(lane_result, final_intent_used=final_intent_used)
    if signal_envelope is not None:
        trace["query_signal_envelope"] = _build_signal_envelope_trace(signal_envelope)
    trace["recall_mode"] = recall_mode
    if packaging_summary:
        trace["packaging"] = packaging_summary
    if policy_ctx.resolver_invoked:
        trace["policy_resolver"] = {
            "resolver_invoked": True,
            "resolver_action": policy_ctx.resolver_action,
            "resolver_confidence": policy_ctx.resolver_confidence,
            "resolver_reason_codes": list(policy_ctx.resolver_reason_codes),
            "option_a_family": policy_ctx.option_a_family,
            "option_b_family": policy_ctx.option_b_family,
            "deterministic_option": policy_ctx.deterministic_option,
            "ambiguity_pair_type": policy_ctx.ambiguity_pair_type,
        }
    return trace

def _build_routing_trace_entry(candidate: dict[str, object]) -> dict[str, object]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    entry = {
        "result_id": _routing_result_id(item),
        "result_kind": item.result_kind,
        "result_origin": "memory" if item.result_kind == "memory_hit" else "source",
        "memory_type": item.type,
        "layer": candidate["layer"],
        "lexical_rank": candidate["lexical_rank"],
        "routing_rank": candidate["routing_rank"],
        "retrieval_score": candidate["retrieval_score"],
        "routing_score": candidate["routing_score"],
        "support_score": candidate["support_score"],
        "support_grade": candidate["support_grade"],
        "reason": candidate["reason"],
        "candidate_envelope_kind": candidate.get("envelope_kind"),
        "envelope_confidence": candidate.get("envelope_confidence"),
    }
    envelope_subjects = list(candidate.get("envelope_subjects") or [])
    if envelope_subjects:
        entry["candidate_subjects"] = envelope_subjects
    if candidate.get("kind_prefilter_status"):
        entry["kind_prefilter_status"] = candidate["kind_prefilter_status"]
    if candidate.get("kind_prefilter_reason_code"):
        entry["kind_prefilter_reason_code"] = candidate["kind_prefilter_reason_code"]
        entry["kind_prefilter_reason"] = candidate.get("kind_prefilter_reason")
    if candidate.get("anchor_prefilter_status"):
        entry["anchor_prefilter_status"] = candidate["anchor_prefilter_status"]
    if "anchor_tier_penalty" in candidate:
        entry["anchor_tier_penalty"] = candidate["anchor_tier_penalty"]
    if candidate.get("anchor_prefilter_reason_code"):
        entry["anchor_prefilter_reason_code"] = candidate["anchor_prefilter_reason_code"]
        entry["anchor_prefilter_reason"] = candidate.get("anchor_prefilter_reason")
    if candidate["evidence_count"]:
        entry["evidence_count"] = candidate["evidence_count"]
    if candidate["same_thread"]:
        entry["same_thread"] = True
    if candidate["same_container"]:
        entry["same_container"] = True
    if candidate["freshness_timestamp"]:
        entry["freshness_timestamp"] = candidate["freshness_timestamp"]
    if candidate["packaging_adjustment"]:
        entry["packaging_adjustment"] = candidate["packaging_adjustment"]
    if candidate["work_usefulness_score"]:
        entry["work_usefulness_score"] = candidate["work_usefulness_score"]
    if candidate["work_signal_types"]:
        entry["work_signal_types"] = list(candidate["work_signal_types"])
    if candidate["packaging_reasons"]:
        entry["packaging_reasons"] = list(candidate["packaging_reasons"])
    if candidate.get("constraint_compatibility"):
        entry["constraint_compatibility"] = candidate["constraint_compatibility"]
    if candidate.get("constraint_governing_rule"):
        entry["constraint_governing_rule"] = candidate["constraint_governing_rule"]
    if candidate.get("excluded_reason_code"):
        entry["excluded_reason_code"] = candidate["excluded_reason_code"]
        entry["excluded_reason"] = candidate.get("excluded_reason")
    if candidate.get("quality_score") is not None:
        entry["quality_score"] = candidate["quality_score"]
    if candidate.get("freshness_rank_in_type") is not None:
        entry["freshness_rank_in_type"] = candidate["freshness_rank_in_type"]
    entry["suppressed"] = candidate.get("suppressed", False)
    strategy_name = candidate["strategy_name"]
    if strategy_name is not None:
        entry["strategy_name"] = strategy_name
    return entry


def _build_sharp_candidate_diagnostics(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    injectable_blocks: list[InjectableBlock],
    decision_reason: str,
    query_text: str,
    retrieved_result_ids: set[str] | None = None,
    debug_candidate_loader=None,
    candidate_injection_eligibility_fn: Callable[..., bool] | None = None,
) -> list[dict[str, object]]:
    selected_injection_ids = {block.result_id for block in injectable_blocks}
    final_result_ids = {_routing_result_id(candidate["item"]) for candidate in final_candidates}
    diagnostics: dict[str, dict[str, object]] = {}

    for candidate in ranked_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.type not in SHARP_DIAGNOSTIC_MEMORY_TYPES:
            continue
        result_id = _routing_result_id(item)
        loss_stage = "selected" if result_id in selected_injection_ids else "routing"
        loss_reason_code = None
        loss_reason = None
        if result_id not in final_result_ids:
            if candidate.get("excluded_reason_code") == "displaced_by_adjacent_evidence_packaging":
                loss_stage = "packaging"
            loss_reason_code = candidate.get("excluded_reason_code")
            loss_reason = candidate.get("excluded_reason")
        elif result_id not in selected_injection_ids:
            if decision_reason == "same_thread_context_sufficient":
                loss_stage = "packaging"
                loss_reason_code = "same_thread_context_sufficient"
                loss_reason = "Current same-thread session already had sufficient local context, so Pallium suppressed injection."
            elif decision_reason in {"only_low_value_candidates", "no_relevant_memory", "same_thread_context_sufficient", "injection_policy_unavailable"}:
                loss_stage = "packaging"
                loss_reason_code = decision_reason
                loss_reason = "Candidate survived routing but was excluded from final injection packaging."
            else:
                loss_stage = "injection_cap"
                loss_reason_code = "final_injection_cap"
                loss_reason = "Candidate remained eligible but was dropped by the final injection cap."
        injection_eligible = True
        if candidate_injection_eligibility_fn is not None:
            injection_eligible = candidate_injection_eligibility_fn(
                candidate,
                intent="structured_recall",
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=False,
            )
        diagnostics[result_id] = {
            "result_id": result_id,
            "candidate_kind": item.type,
            "result_kind": item.result_kind,
            "score": candidate["routing_score"],
            "injection_eligible": injection_eligible,
            "selected_for_injection": result_id in selected_injection_ids,
            "loss_stage": loss_stage,
            "loss_reason_code": loss_reason_code,
            "loss_reason": loss_reason,
            "retrieved": True,
            "lexical_rank": candidate.get("lexical_rank"),
            "routing_rank": candidate.get("routing_rank"),
        }

    if callable(debug_candidate_loader):
        for item in debug_candidate_loader(memory_types=list(SHARP_DIAGNOSTIC_MEMORY_TYPES)):
            if item.type not in SHARP_DIAGNOSTIC_MEMORY_TYPES:
                continue
            result_id = str(item.result_id)
            dropped_by_prefilter = retrieved_result_ids is not None and result_id in retrieved_result_ids
            diagnostics.setdefault(
                result_id,
                {
                    "result_id": result_id,
                    "candidate_kind": item.type,
                    "result_kind": item.result_kind,
                    "score": 0,
                    "injection_eligible": True,
                    "selected_for_injection": False,
                    "loss_stage": "routing" if dropped_by_prefilter else "retrieval",
                    "loss_reason_code": "dropped_by_routing_prefilter" if dropped_by_prefilter else "not_retrieved",
                    "loss_reason": (
                        "Sharp candidate was retrieved but excluded by a routing prefilter (kind or anchor)."
                        if dropped_by_prefilter
                        else "Sharp candidate was in scope but not returned by retrieval (lexical + vector)."
                    ),
                    "retrieved": dropped_by_prefilter,
                    "lexical_rank": None,
                    "routing_rank": None,
                },
            )
    return list(diagnostics.values())


def _routing_fallback_suffix(
    *,
    layer: str,
    selected_layer: str,
    primary_layer: str,
    applied: bool,
    reason_code: str,
    support_grade: str,
) -> str:
    if not applied:
        return ""
    if layer == selected_layer:
        return f" Candidate-aware fallback selected this layer because `{reason_code}`."
    if layer == primary_layer and layer in ROUTING_HIGHER_LEVEL_TYPES and layer != selected_layer:
        return " Candidate-aware fallback demoted this higher-level layer because retrieved support was weaker than safer evidence."
    if support_grade == "weak":
        return " Candidate-aware fallback kept weakly supported alternatives behind the selected layer."
    return ""

def _routing_packaging_suffix(packaging_reasons: list[str]) -> str:
    suffixes: list[str] = []
    if "sharp_checkpoint" in packaging_reasons:
        suffixes.append(" It preserved blocker, next-step, evidence, and freshness state more explicitly than weaker checkpoint packaging.")
    if "thin_checkpoint" in packaging_reasons:
        suffixes.append(" Thin checkpoint packaging weakened it against sharper resumed-work state.")
    if "stale_against_fresher_state" in packaging_reasons:
        suffixes.append(" Fresher explicit state outranked older carried-forward state.")
    if "fresh_explicit_state" in packaging_reasons:
        suffixes.append(" Fresh explicit state strengthened this candidate.")
    if "explicit_freshness_signal" in packaging_reasons and "fresh_explicit_state" not in packaging_reasons:
        suffixes.append(" Explicit freshness state improved its resumed-work usefulness.")
    return "".join(OrderedDict.fromkeys(suffixes))
