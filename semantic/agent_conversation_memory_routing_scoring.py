from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from core.models import QueryFilters, QueryResultItem, QueryRuntimeContext
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_threads import (
    SELECTED_WORK_ARTIFACT_KINDS,
    _is_low_value_meta_text,
    _memory_hit_has_selected_work_artifacts,
    _parse_string_list,
)
from semantic.agent_conversation_memory_routing_constants import (
    ANCHOR_SECONDARY_TIER_PENALTY,
    HIGHER_LEVEL_RETRIEVAL_FLOOR,
    LEXICAL_NORM_SCALE,
    QUALITY_WEIGHT,
    ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY,
    ROUTING_FALLBACK_MARGIN,
    ROUTING_FAMILY_INFERENCE_PRIORITY,
    ROUTING_FOCUS_BOOST,
    ROUTING_HIGHER_LEVEL_TYPES,
    ROUTING_LAYER_WEIGHTS,
    ROUTING_LOWER_LEVEL_EXACT_TYPES,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_SAFE_FALLBACK_LAYERS,
    ROUTING_SUMMARY_TYPES,
    ROUTING_SUPPORT_THRESHOLD,
    STRUCTURED_LAYERS,
    POLICY_WORK_STATE_USEFULNESS_THRESHOLD,
    _candidate_freshness_timestamp,
    _candidate_matches_container,
    _candidate_matches_thread,
    _result_layer,
    _routing_query_tokens,
    _routing_result_id,
    _routing_support_grade,
)
from semantic.agent_conversation_memory_routing_trace import (
    _routing_strategy_name,
)
from semantic.agent_conversation_memory_routing_signals import (
    _work_resumption_signal_types,
    _work_resumption_usefulness_score,
)
from semantic.agent_conversation_memory_anchors import (
    _serialize_subject_anchors,
)


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------

def _compute_quality_score(lexical_score: int, vector_score: int) -> float:
    """Normalized quality from raw retrieval scores. Returns 0.0-1.0.

    Uses fixed normalization (LEXICAL_NORM_SCALE=6, not result-set-dependent).
    """
    lex_norm = min(lexical_score / LEXICAL_NORM_SCALE, 1.0)
    vec_norm = vector_score / 1000.0
    return max(lex_norm, vec_norm)


# ---------------------------------------------------------------------------
# Intent inference
# ---------------------------------------------------------------------------

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
    selected_family = ranked_families[0] if ranked_families else "recall"
    runner_up_family = ranked_families[1] if len(ranked_families) > 1 else None
    return {
        "selected_family": selected_family,
        "text_hint_family": "recall",
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
        "recall": {"carry_forward": 12, "history_lookup": 22, "big_picture": 52, "constraint_recall": 28},
        "structured_recall": {"analysis_request": 30, "history_lookup": 10, "precise_lookup": 18},
        "work_resumption": {"resume_state": 34, "carry_forward": 8},
        "evidence_trace": {"evidence_request": 44},
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
    if runtime_context is not None and family == "recall" and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}:
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

    if family == "recall":
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
            reasons.append("evidence_request_outweighs_recall")
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


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

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
    quality_score = _compute_quality_score(
        int(item.lexical_score or 0),
        int(item.vector_score or 0),
    )
    base_routing_score = (
        _weights[intent][layer]
        + int(quality_score * QUALITY_WEIGHT)
        + _specificity_bonus(item, intent)
        + evidence_shape_score
        + _higher_level_retrieval_floor_adjustment(layer, retrieval_score, quality_score=quality_score)
        + _locality_adjustment(intent=intent, layer=layer, same_thread=same_thread, same_container=same_container)
    )
    support_grade = _routing_support_grade(evidence_shape_score, support_threshold=support_threshold)
    # Compute work resumption signals unconditionally (was previously in _apply_work_resumption_packaging)
    _signal_types = _work_resumption_signal_types(item)
    _usefulness, _ = _work_resumption_usefulness_score(item, _signal_types)
    # Compute freshness_timestamp ISO string unconditionally
    _freshness_ts_value = _candidate_freshness_timestamp(item)
    _freshness_ts = _freshness_ts_value.isoformat() if isinstance(_freshness_ts_value, datetime) else None
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
        "topic_overlap_tokens": [],
        "evidence_count": len(item.evidence),
        "same_thread": same_thread,
        "same_container": same_container,
        "freshness_timestamp_value": _freshness_ts_value,
        "freshness_timestamp": _freshness_ts,
        "packaging_adjustment": 0,
        "packaging_reasons": [],
        "anchor_tier_penalty": 0,
        "work_signal_types": _signal_types,
        "work_usefulness_score": _usefulness,
        "lexical_score": item.lexical_score,
        "vector_score": item.vector_score,
        "quality_score": quality_score,
    }


_ANCHOR_SECONDARY_STATUSES = frozenset({
    "insufficient_retained",
    "legacy_fallback_retained",
    "insufficient_retained_demoted",
    "secondary_tier",
})

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

    The same-container bonus (+20) is gated on recall intent to
    avoid boosting cross-topic carry-forward when the query isn't a repeated
    question.
    """
    if layer != "continuity_memory":
        return 0
    if same_thread:
        return 60
    if same_container and intent == "recall":
        return 20
    if same_container:
        return 0
    return -60

def _specificity_bonus(item: QueryResultItem, intent: str) -> int:
    bonus = 0
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if intent == "structured_recall":
            bonus += 48 if item.type == "investigation_outcome" else 40
        elif intent in {"structured_recall", "evidence_trace"}:
            bonus += 25 if item.type == "decision" else 23
        else:
            bonus += 10
    if item.result_kind == "memory_hit" and item.type in ROUTING_SUMMARY_TYPES and intent in {"structured_recall", "evidence_trace"}:
        bonus -= 20
    if item.result_kind == "memory_hit" and item.type == "thread_summary" and intent == "work_resumption":
        if _memory_hit_has_selected_work_artifacts(item):
            bonus += 18
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        if intent == "work_resumption":
            bonus += 28
        elif intent in {"structured_recall", "evidence_trace"}:
            bonus -= 18
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "recall":
        bonus += 13
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and intent == "recall":
        bonus += 43 if item.type == "decision" else 38
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "recall":
        bonus -= 23
    if item.result_kind == "memory_hit" and item.type == "pattern_memory" and intent == "recall":
        bonus += 13
    if item.result_kind == "source_hit" and intent == "evidence_trace":
        bonus += 15 if item.artifact_kind == "assistant_output" else 5
    if item.result_kind == "source_hit" and intent == "work_resumption":
        bonus += 23 if (item.artifact_kind or "") in SELECTED_WORK_ARTIFACT_KINDS else 10
    if item.result_kind == "source_hit" and intent == "structured_recall":
        bonus += 3 if item.artifact_kind == "assistant_output" else 1
    return bonus


def _higher_level_retrieval_floor_adjustment(layer: str, retrieval_score: int, quality_score: float = 0.0) -> int:
    """Penalise higher-level memory whose retrieval quality falls below the floor.

    Uses quality_score (normalized 0-1 from raw lexical/vector scores) rather
    than RRF retrieval_score, because RRF scores are compressed into a narrow
    8-19 range where a fixed floor of 40 would penalize every candidate.
    quality_score >= 0.5 means at least moderate lexical or vector match.
    """
    if layer not in ROUTING_HIGHER_LEVEL_TYPES:
        return 0
    if quality_score < 0.5:
        return -160
    return 0

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


# ---------------------------------------------------------------------------
# Scoring components (cross-candidate, applied after annotations)
# ---------------------------------------------------------------------------

# Freshness shaping: carry forward from _apply_same_kind_freshness_shaping
FRESHNESS_BONUS_BY_INTENT: dict[str, int] = {
    "recall": 24,
    "structured_recall": 42,
    "work_resumption": 18,
    "evidence_trace": 0,
}
FRESHNESS_DECAY_PER_RANK = 12
FRESHNESS_MAX_PENALTY = 30

def _freshness_component(freshness_rank: int | None, intent: str) -> int:
    """Bonus for freshest candidate in type, penalty for stale ones.

    Replaces _apply_same_kind_freshness_shaping.
    """
    bonus = FRESHNESS_BONUS_BY_INTENT.get(intent, 0)
    if bonus == 0 or freshness_rank is None:
        return 0
    if freshness_rank == 1:
        return bonus
    if freshness_rank == 2:
        return 0
    return -min(FRESHNESS_DECAY_PER_RANK * (freshness_rank - 2), FRESHNESS_MAX_PENALTY)


# Work resumption staleness: carry forward from _apply_work_resumption_packaging
WORK_RESUMPTION_STALE_PENALTY = 55
WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY_V2 = 50

def _usefulness_adjustment(candidate: dict, intent: str) -> int:
    """Work resumption usefulness + staleness adjustment.

    Replaces the freshness/thin-checkpoint parts of _apply_work_resumption_packaging.
    The base usefulness score is already computed in _score_routed_candidate.
    """
    if intent != "work_resumption":
        return 0
    adjustment = 0
    layer = str(candidate.get("layer", ""))
    # Stale checkpoint penalty
    if layer == "task_checkpoint" and candidate.get("work_resumption_stale"):
        adjustment -= WORK_RESUMPTION_STALE_PENALTY
    # Thin checkpoint penalty (few work signals)
    if layer == "task_checkpoint":
        usefulness = int(candidate.get("work_usefulness_score", 0))
        if usefulness < POLICY_WORK_STATE_USEFULNESS_THRESHOLD:
            adjustment -= WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY_V2
    # Stale source evidence penalty (smaller)
    if layer == "source_evidence" and candidate.get("work_resumption_stale"):
        adjustment -= 28  # WORK_RESUMPTION_STALE_SOURCE_PENALTY
    return adjustment


# Fresh session preference: carry forward from _apply_fresh_thread_structured_recall_preference
FRESH_SESSION_SOURCE_PENALTY = -80  # was -120, reduced because quality score now differentiates better
FRESH_SESSION_STRUCTURED_BONUS = 26

def _fresh_session_component(
    runtime_context, layer: str, structured_dominates: bool,
) -> int:
    """Prefer structured memory over source hits in fresh sessions.

    Replaces _apply_fresh_thread_structured_recall_preference.
    Fires when turn_kind is new_thread/new_session AND
    session_has_sufficient_local_context is False AND
    structured candidates dominate source hits.
    """
    if runtime_context is None:
        return 0
    turn_kind = getattr(runtime_context, "turn_kind", None)
    if turn_kind not in ("new_thread", "new_session"):
        return 0
    if getattr(runtime_context, "session_has_sufficient_local_context", False):
        return 0
    if not structured_dominates:
        return 0
    if layer == "source_evidence":
        return FRESH_SESSION_SOURCE_PENALTY
    if layer in STRUCTURED_LAYERS:
        return FRESH_SESSION_STRUCTURED_BONUS
    return 0


def _runtime_context_prefers_cross_thread_recall(runtime_context: QueryRuntimeContext | None) -> bool:
    return bool(
        runtime_context is not None
        and runtime_context.turn_kind in {"new_thread", "new_session"}
        and runtime_context.session_has_sufficient_local_context is False
    )


# ---------------------------------------------------------------------------
# Source / summary suppression helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Routing focus / layer summarisation
# ---------------------------------------------------------------------------

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
        if intent == "recall":
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
            intent in {"recall", "work_resumption"}
            and primary_grade == "weak"
            and fallback_grade == "strong"
            and fallback_support >= primary_support + _margin
        ):
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "weak_higher_level_support"
            reason = "Higher-level memory was retrieved, but its candidate support was materially weaker than a strongly supported safer layer."
        elif intent not in {"recall", "work_resumption"} and primary_grade == "weak" and fallback_grade in {"supported", "strong"}:
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
