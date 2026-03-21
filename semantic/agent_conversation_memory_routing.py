from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Iterable, TypedDict

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
    _apply_structured_constraint_compatibility,
    _build_local_query_constraint_profile,
    _candidate_aligns_with_constraint_state,
    _candidate_has_self_conflicting_guidance,
    _preferred_constraint_text,
    _text_contains_operational_guidance,
)
from semantic.agent_conversation_memory_threads import (
    QUERY_ONLY_SUMMARY_MARKERS,
    SELECTED_WORK_ARTIFACT_KINDS,
    WORK_SIGNAL_PREFIX_TO_TYPE,
    UNRESOLVED_SUMMARY_MARKERS,
    WEAK_THREAD_SUMMARY_TEXT,
    _classify_work_signal_text as _thread_classify_work_signal_text,
    _extract_constraint_signal_text,
    _is_low_value_meta_text,
    _memory_hit_has_selected_work_artifacts,
    _parse_string_list,
)

ROUTING_POLICY_NAME = "agent_conversation_memory.intent_routing.v4"


@dataclass(frozen=True)
class PolicySelectedContext:
    query_policy_family: str
    allowed_query_intents: frozenset[str] | None = None
    resolver_invoked: bool = False
    resolver_action: str | None = None
    resolver_confidence: str | None = None
    resolver_reason_codes: tuple[str, ...] = ()
    option_a_family: str | None = None
    option_b_family: str | None = None
    deterministic_option: str | None = None
    ambiguity_pair_type: str | None = None


PASSTHROUGH_POLICY = PolicySelectedContext(query_policy_family="passthrough", allowed_query_intents=None)


@dataclass(frozen=True)
class LaneEligibility:
    lane: str
    state: str
    structural_signals: tuple[str, ...]
    shape_signals: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class LaneNarrowingResult:
    eligible_lanes: tuple[LaneEligibility, ...]
    selected_lane: str | None
    selection_mode: str
    lane_narrowing_used_intent: bool
    intent_effect: str
    abstain_reason: str | None
    mapped_intent: str | None
    mapped_policy_family: str | None


@dataclass(frozen=True)
class QuerySignalEnvelope:
    low_value: bool = False
    history_lookup: bool = False
    latest_status_request: bool = False
    resume_state: bool = False
    constraint_lookup: bool = False
    evidence_request: bool = False
    source: str = "structural"
    confidence: str = "low"
    legacy_english_fallback_used: bool = False
    semantic_classification_used: bool = False
    derivation_signals: tuple[str, ...] = ()


ROUTING_HIGHER_LEVEL_TYPES = {"pattern_memory", "continuity_memory", "task_checkpoint", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE}

ROUTING_LOWER_LEVEL_EXACT_TYPES = {"decision", "investigation_outcome"}

ROUTING_SUMMARY_TYPES = {"thread_summary", "discussion_summary"}

ROUTING_PREFERRED_LAYERS = {
    "answer_continuity": ("continuity_memory", "investigation_outcome", "decision", "source_evidence", "task_checkpoint", "pattern_memory", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "broad_recall": ("pattern_memory", "investigation_outcome", "decision", "continuity_memory", "task_checkpoint", "source_evidence", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "work_resumption": ("task_checkpoint", "source_evidence", "investigation_outcome", "decision", "continuity_memory", "pattern_memory", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "precise_fact": ("decision", "investigation_outcome", "source_evidence", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory", CONSTRAINT_MEMORY_TYPE),
    "evidence_trace": ("source_evidence", "investigation_outcome", "decision", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory"),
    "investigative_conclusion": ("investigation_outcome", "decision", "source_evidence", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory", CONSTRAINT_MEMORY_TYPE),
}

ROUTING_FAMILY_ALLOWED_ENVELOPE_KINDS = {
    "answer_continuity": ("constraint", "summary", "finding"),
    "broad_recall": ("constraint", "summary", "finding"),
    "work_resumption": ("episode", "finding", "summary"),
    "precise_fact": ("finding",),
    "evidence_trace": None,
    "investigative_conclusion": ("constraint", "finding", "summary"),
}

ROUTING_LAYER_WEIGHTS = {
    "answer_continuity": {"continuity_memory": 400, CONSTRAINT_MEMORY_TYPE: 360, "investigation_outcome": 320, "decision": 300, "source_evidence": 200, "task_checkpoint": 140, "pattern_memory": 120, "thread_summary": 100, "discussion_summary": 70, "lower_level_memory": 260},
    "broad_recall": {CONSTRAINT_MEMORY_TYPE: 430, "pattern_memory": 400, "investigation_outcome": 330, "decision": 310, "continuity_memory": 180, "task_checkpoint": 150, "source_evidence": 120, "thread_summary": 130, "discussion_summary": 80, "lower_level_memory": 250},
    "work_resumption": {CONSTRAINT_MEMORY_TYPE: 490, "task_checkpoint": 470, "source_evidence": 390, "investigation_outcome": 300, "decision": 290, "continuity_memory": 180, "pattern_memory": 70, "thread_summary": 130, "discussion_summary": 70, "lower_level_memory": 250},
    "precise_fact": {"decision": 440, "investigation_outcome": 430, CONSTRAINT_MEMORY_TYPE: 260, "source_evidence": 320, "thread_summary": 110, "discussion_summary": 70, "continuity_memory": 140, "task_checkpoint": 110, "pattern_memory": 60, "lower_level_memory": 340},
    "evidence_trace": {"source_evidence": 460, "investigation_outcome": 380, "decision": 360, CONSTRAINT_MEMORY_TYPE: 110, "thread_summary": 120, "discussion_summary": 80, "continuity_memory": 120, "task_checkpoint": 90, "pattern_memory": 40, "lower_level_memory": 300},
    "investigative_conclusion": {"investigation_outcome": 480, "decision": 430, CONSTRAINT_MEMORY_TYPE: 220, "source_evidence": 360, "thread_summary": 220, "discussion_summary": 120, "continuity_memory": 110, "task_checkpoint": 100, "pattern_memory": 80, "lower_level_memory": 320},
}

ROUTING_META_QUERY_TOKENS = {
    "a",
    "about",
    "already",
    "an",
    "before",
    "did",
    "do",
    "exact",
    "have",
    "i",
    "need",
    "previously",
    "show",
    "source",
    "support",
    "supported",
    "the",
    "this",
    "trace",
    "we",
    "what",
    "which",
    "again",
    "can",
    "had",
    "have",
    "here",
    "in",
    "is",
    "lately",
    "latest",
    "me",
    "sir",
    "that",
    "there",
    "you",
}

ROUTING_WEAK_HIGHER_LEVEL_MATCH_PENALTY = {
    "answer_continuity": 0,
    "broad_recall": 260,
    "work_resumption": 200,
    "precise_fact": 120,
    "evidence_trace": 120,
    "investigative_conclusion": 90,
}

ROUTING_SAFE_FALLBACK_LAYERS = {
    "answer_continuity": ("lower_level_memory", "source_evidence"),
    "broad_recall": ("task_checkpoint", "thread_summary", "lower_level_memory", "source_evidence"),
    "work_resumption": ("source_evidence", "lower_level_memory"),
    "precise_fact": ("source_evidence",),
    "evidence_trace": ("lower_level_memory",),
    "investigative_conclusion": ("decision", "source_evidence", "thread_summary"),
}

ROUTING_SUPPORT_THRESHOLD = {"weak": 0, "supported": 60, "strong": 110}

# Policy layer constants
QUERY_POLICY_FAMILY_ALLOWED_INTENTS: dict[str, frozenset[str]] = {
    "noise": frozenset(),
    "recall_fact": frozenset({"answer_continuity", "broad_recall", "precise_fact", "evidence_trace", "investigative_conclusion"}),
    "latest_status": frozenset({"broad_recall", "work_resumption"}),
    "resume_work": frozenset({"work_resumption"}),
    "check_constraints": frozenset({"broad_recall", "work_resumption"}),
}
LATEST_STATUS_COLLAPSED_INTENTS = frozenset({"broad_recall"})
LATEST_STATUS_WORDING_TOKENS = {"latest", "lately"}
LATEST_STATUS_HISTORY_PHRASES = ("what is the latest", "what's the latest")
LATEST_STATUS_RESUME_PHRASES = ("what is the latest state", "what's the latest state")
POLICY_WORK_STATE_USEFULNESS_THRESHOLD = 24
POLICY_SUPPORT_THRESHOLD = ROUTING_SUPPORT_THRESHOLD["supported"]
AMBIGUITY_MARGIN_LATEST_VS_RESUME = 12
AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL = 10

# Lane narrowing constants
LANE_INTENT_MAPPING: dict[str, str] = {
    "constraint_policy": "broad_recall",
    "work_resumption": "work_resumption",
    "evidence_trace": "evidence_trace",
}

LANE_POLICY_FAMILY_MAPPING: dict[str, str] = {
    "constraint_policy": "check_constraints",
    "work_resumption": "resume_work",
    "evidence_trace": "recall_fact",
}

# Recall mode constants — modes only change weights and shaping, not selection path or gates
RECALL_MODE_WEIGHTS: dict[str, dict[str, int]] = {
    "default": ROUTING_LAYER_WEIGHTS["broad_recall"],
    "continuity_preference": ROUTING_LAYER_WEIGHTS["answer_continuity"],
    "sharp_fact_preference": ROUTING_LAYER_WEIGHTS["precise_fact"],
    "investigation_preference": ROUTING_LAYER_WEIGHTS["investigative_conclusion"],
}

RECALL_MODE_FRESHNESS_BONUS: dict[str, int] = {
    "default": 24,
    "continuity_preference": 0,  # skip freshness shaping
    "sharp_fact_preference": 24,
    "investigation_preference": 42,
}

RECALL_MODE_FRESH_THREAD_PREFERENCE: dict[str, bool] = {
    "default": True,
    "continuity_preference": True,
    "sharp_fact_preference": True,
    "investigation_preference": False,
}

ROUTING_TOPIC_LOW_SIGNAL_TOKENS = {
    "about", "already", "before", "carry", "constraint", "concluded", "did", "do", "earlier",
    "forward", "history", "latest", "lately", "old", "past", "prior", "previously", "remember",
    "remind", "repeat", "repeated", "resume", "state", "use", "using", "what", "which", "why",
}

ROUTING_FALLBACK_MARGIN = 35

ROUTING_FOCUS_BOOST = 120

ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY = 90


class RoutingOverrides(TypedDict, total=False):
    """Optional per-call overrides for routing constants.

    Used by the live harness shadow comparison path to test candidate tuning
    changes against captured scenarios before rollout. These knobs cover the
    main scoring levers; structural policy constants (ROUTING_PREFERRED_LAYERS,
    AMBIGUITY_MARGIN_*) are intentionally not overridable here.
    """

    layer_weights: dict[str, dict[str, int]]
    focus_boost: int
    fallback_margin: int
    support_threshold: dict[str, int]
    work_resumption_thin_checkpoint_penalty: int

ANSWER_CONTINUITY_CUES = (
    "already answered",
    "answered before",
    "have we already",
    "asked again",
    "asking again",
    "prior answer",
    "old answer",
    "not a new brainstorm",
    "carry forward",
)

BROAD_RECALL_CUES = (
    "what public conclusion",
    "what did we previously conclude",
    "what did we conclude before",
    "what did we conclude",
    "what did we learn",
    "why did we choose",
    "why do we use",
    "general lesson",
    "what lesson",
    "should we remember",
    "what should we remember",
    # Discussion/topic history vocabulary — must precede generic "what " startswith check at line ~911
    "what were we discussing",
    "what did we talk about",
    "what had we been discussing",
    "what was the topic",
    "what was our topic",
    "what have we been discussing",
    "what were we working on",
    "what had we been working on",
)

BROAD_RECALL_ABSTRACTION_CUES = (
    "general lesson",
    "what lesson",
    "should we remember",
    "what should we remember",
)

BROAD_RECALL_CONCLUSION_CUES = (
    "what public conclusion",
    "what did we previously conclude",
    "what did we conclude before",
    "what did we conclude",
)

PRECISE_FACT_CUES = (
    "what ordering",
    "which ordering",
    "what did we choose",
    "what decision",
    "exact choice",
    "exact value",
)

EVIDENCE_TRACE_CUES = (
    "exact finding",
    "what exact finding",
    "which exact prior evidence",
    "exact prior evidence",
    "what evidence",
    "show evidence",
    "quote the earlier",
    "quote the earlier note",
    "quote the note",
    "which source",
    "source evidence",
    "supported the",
    "supporting evidence",
    "trace",
    "which prior message",
    "prior message",
    "backed the",
)

INVESTIGATIVE_CONCLUSION_CUES = (
    "what had we concluded",
    "what did the investigation find",
    "what did investigation find",
    "which repo changed more and why",
    "which repo changed more",
    "what was the verdict",
    "what was our verdict",
    "what conclusion did we reach",
)

SHARP_DIAGNOSTIC_MEMORY_TYPES = {"task_checkpoint", "investigation_outcome", "decision"}

WORK_RESUMPTION_CUES = (
    "what blocker",
    "what progress",
    "what progress was preserved",
    "what state were we in",
    "what should i do next",
    "what should we do next",
    "what should we try next",
    "what finding should orient us",
    "queued again",
    "resume work",
)

WORK_RESUMPTION_NEXT_STEP_CUES = (
    "next step",
    "do next",
    "try next",
)

WORK_RESUMPTION_PROGRESS_CUES = (
    "what progress",
    "progress was preserved",
    "what state were we in",
)

WORK_RESUMPTION_BLOCKER_CUES = (
    "what blocker",
    "blocked",
    "failure",
    "failed",
)

WORK_RESUMPTION_SIGNAL_TYPES = ("task", "progress_update", "key_finding", "blocker", "next_step", "evidence", "freshness")

WORK_RESUMPTION_SHARP_CHECKPOINT_THRESHOLD = 44  # defined but not yet wired to a scoring gate; excluded from RoutingOverrides until a call site exists

WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY = 70

WORK_RESUMPTION_STALE_STATE_PENALTY = 55

WORK_RESUMPTION_STALE_SOURCE_PENALTY = 28

WORK_RESUMPTION_FRESH_STATE_BONUS = 18

WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS = 2700

WORK_RESUMPTION_SIGNAL_PRIORITY = ("blocker", "next_step", "progress_update")

ROUTING_QUERY_SHAPE_TOKENS = {
    "history_lookup": {"before", "earlier", "historical", "history", "past", "previously", "prior", "latest", "lately"},
    "big_picture": {"lesson", "pattern", "remember", "takeaway"},
    "analysis_request": {"concluded", "conclusion", "finding", "findings", "land", "outcome", "settled", "true", "verdict"},
    "carry_forward": {"again", "already", "carry", "forward", "old", "remind", "repeat", "repeated"},
    "constraint_recall": {"auth", "authenticate", "authentication", "avoid", "browser", "constraint", "jira", "login", "portal", "rely", "relying", "restriction", "sign", "slack"},
    "resume_state": {"blocked", "blocker", "continue", "continued", "continuing", "left", "next", "progress", "queued", "resume", "resumed", "state", "stuck", "unblock"},
    "evidence_request": {"backed", "evidence", "prove", "quote", "source", "support", "supported", "trace"},
    "precise_lookup": {"exact", "when", "which"},
}

ROUTING_QUERY_SHAPE_PHRASES = {
    "history_lookup": ("what do we know", "what is the latest", "what's the latest", "what had we concluded", "what had you concluded", "what constraint had i given", "remind me what we had latest", "remind me what we had latest about", "remind me what we had about", "what we had about", "what were we discussing", "what did we talk about", "what have we been discussing", "what had we been discussing", "what were we working on", "what had we been working on"),
    "big_picture": ("big picture", "general lesson", "larger lesson", "main takeaway", "should we remember", "what should we remember"),
    "analysis_request": ("where did we land", "what ended up being true", "what settled", "how did that shake out"),
    "constraint_recall": ("what constraint had i given", "what constraint did i give", "what had i told you not to use", "what did i tell you not to use", "anything i should avoid", "what should i not rely on", "what should i avoid", "anything to avoid"),
    "resume_state": ("pick this back up", "pick that back up", "where did we leave off", "where were we", "what is the latest state", "what's the latest state"),
    "evidence_request": ("what backs that up", "what points to", "what points back to", "where did that come from"),
}

ROUTING_FAMILY_INFERENCE_PRIORITY = (
    "work_resumption",
    "evidence_trace",
    "investigative_conclusion",
    "answer_continuity",
    "broad_recall",
    "precise_fact",
)

LOW_VALUE_GREETING_NOISE_PREFIXES = (
    "good morning",
    "good afternoon",
    "good evening",
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
)

LOW_VALUE_GREETING_NOISE_QUERIES = {
    "good morning",
    "good afternoon",
    "good evening",
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
}

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
            signal_classifier_config=None,  # Tier 2 wired in Phase 5
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
        # Step 4: Lane narrowing (consumes envelope via compatible shape tags)
        _envelope_shape_tags: list[str] = []
        if signal_envelope.constraint_lookup:
            _envelope_shape_tags.append("constraint_recall")
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
            recall_mode = _select_recall_mode(candidate_evidence)
            # Map envelope to policy family for trace compatibility
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
            # Use recall mode weights — wrap in intent key for _score_routed_candidate compatibility
            _mode_weights = RECALL_MODE_WEIGHTS.get(recall_mode, ROUTING_LAYER_WEIGHTS["broad_recall"])
            _layer_weights = {intent: _mode_weights for intent in ROUTING_LAYER_WEIGHTS}
            # Map recall mode to a compatible intent for downstream scoring/shaping
            # This keeps the existing scoring/shaping code working while we migrate
            _mode_intent_map = {
                "default": "broad_recall",
                "continuity_preference": "answer_continuity",
                "sharp_fact_preference": "precise_fact",
                "investigation_preference": "investigative_conclusion",
            }
            intent = _mode_intent_map.get(recall_mode, "broad_recall")
            policy_ctx = PolicySelectedContext(
                query_policy_family=envelope_policy,
                allowed_query_intents=frozenset({intent}),
            )
            final_intent_used = signal_envelope.legacy_english_fallback_used
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
        final_candidates, packaging_summary = _select_final_candidates(
            intent=intent,
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_filters=query_filters,
            query_shape_tags=list(family_inference["query_shape_tags"]),
            runtime_context=runtime_context,
            packaging_summary=packaging_summary,
            local_constraint_profile=_build_local_query_constraint_profile(text, runtime_context, ranked_candidates),
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

def _build_kind_prefilter_trace_entry(
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
    text_hint_family = _classify_query_intent_from_text(text)
    cue_matches = _matched_query_family_cues(text)
    query_shape_tags = _query_shape_tags(text, query_tokens)
    candidate_signals = _summarize_query_family_candidates(
        retrieved_candidates=retrieved_candidates,
        query_text=text,
        query_tokens=query_tokens,
        query_filters=query_filters,
    )
    family_scores: dict[str, dict[str, object]] = {}
    for family in ROUTING_FAMILY_INFERENCE_PRIORITY:
        cue_score = _query_family_cue_score(
            family,
            cue_matches=cue_matches,
            text_hint_family=text_hint_family,
        )
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
            "total": cue_score + query_shape_score + candidate_score,
            "cue_score": cue_score,
            "query_shape_score": query_shape_score,
            "candidate_score": candidate_score,
            "reasons": list(OrderedDict.fromkeys([*query_shape_reasons, *candidate_reasons])),
        }

    ranked_families = sorted(
        ROUTING_FAMILY_INFERENCE_PRIORITY,
        key=lambda family: (
            int(family_scores[family]["total"]),
            int(family_scores[family]["candidate_score"]),
            int(family_scores[family]["cue_score"]),
            -ROUTING_FAMILY_INFERENCE_PRIORITY.index(family),
        ),
        reverse=True,
    )
    selected_family = ranked_families[0] if ranked_families else text_hint_family
    if _preferred_constraint_text(text):
        selected_family = "broad_recall"
    elif text_hint_family == "broad_recall" and "history_lookup" in query_shape_tags and "evidence_request" not in query_shape_tags:
        selected_family = "broad_recall"
    elif selected_family == "evidence_trace" and text_hint_family != "evidence_trace" and "evidence_request" not in query_shape_tags:
        # evidence_trace must not win via candidate source-hit scores alone when the query text
        # contains no evidence-request signals. Fall back to the text-based classification.
        selected_family = text_hint_family
    runner_up_family = ranked_families[1] if len(ranked_families) > 1 else None
    return {
        "selected_family": selected_family,
        "text_hint_family": text_hint_family,
        "runner_up_family": runner_up_family,
        "query_shape_tags": query_shape_tags,
        "matched_cues": {family: matches for family, matches in cue_matches.items() if matches},
        "candidate_signals": candidate_signals,
        "family_scores": family_scores,
    }

def _classify_query_intent_from_text(text: str) -> str:
    lowered = text.lower()
    if _preferred_constraint_text(text):
        return "broad_recall"
    if "remind me" in lowered and ("latest" in lowered or "lately" in lowered or "what we had about" in lowered):
        return "broad_recall"
    if any(cue in lowered for cue in EVIDENCE_TRACE_CUES):
        return "evidence_trace"
    if any(cue in lowered for cue in WORK_RESUMPTION_CUES):
        return "work_resumption"
    if any(cue in lowered for cue in ANSWER_CONTINUITY_CUES):
        return "answer_continuity"
    if any(cue in lowered for cue in INVESTIGATIVE_CONCLUSION_CUES):
        return "investigative_conclusion"
    if any(phrase in lowered for phrase in ROUTING_QUERY_SHAPE_PHRASES["history_lookup"]):
        return "broad_recall"
    if any(cue in lowered for cue in BROAD_RECALL_CUES) or lowered.startswith("why "):
        return "broad_recall"
    if any(cue in lowered for cue in PRECISE_FACT_CUES) or lowered.startswith(("what ", "which ", "when ")):
        return "precise_fact"
    return "broad_recall"

def _matched_query_family_cues(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    history_matches = [phrase for phrase in ROUTING_QUERY_SHAPE_PHRASES["history_lookup"] if phrase in lowered][:3]
    matched = {
        "answer_continuity": [cue for cue in ANSWER_CONTINUITY_CUES if cue in lowered][:3],
        "broad_recall": list(OrderedDict.fromkeys([*[cue for cue in BROAD_RECALL_CUES if cue in lowered][:3], *history_matches])),
        "work_resumption": [cue for cue in WORK_RESUMPTION_CUES if cue in lowered][:3],
        "precise_fact": [cue for cue in PRECISE_FACT_CUES if cue in lowered][:3],
        "evidence_trace": [cue for cue in EVIDENCE_TRACE_CUES if cue in lowered][:3],
        "investigative_conclusion": [cue for cue in INVESTIGATIVE_CONCLUSION_CUES if cue in lowered][:3],
    }
    if lowered.startswith("why "):
        matched["broad_recall"] = list(OrderedDict.fromkeys([*matched["broad_recall"], "why*"]))
    if lowered.startswith(("what ", "which ", "when ")) and not history_matches:
        matched["precise_fact"] = list(OrderedDict.fromkeys([*matched["precise_fact"], "wh*"]))
    return matched

def _query_shape_tags(text: str, query_tokens: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    token_set = set(query_tokens)
    detected: set[str] = set()
    for tag, tokens in ROUTING_QUERY_SHAPE_TOKENS.items():
        if token_set.intersection(tokens):
            detected.add(tag)
    for tag, phrases in ROUTING_QUERY_SHAPE_PHRASES.items():
        if any(phrase in lowered for phrase in phrases):
            detected.add(tag)
    if "remind me" in lowered:
        detected.update({"history_lookup", "carry_forward"})
    if "remind me" in lowered and ("lately" in lowered or "latest" in lowered or "what we had about" in lowered):
        detected.update({"history_lookup", "carry_forward"})
    if _preferred_constraint_text(text):
        detected.add("constraint_recall")
    if lowered.startswith("why "):
        detected.add("big_picture")
    if lowered.startswith(("what ", "which ", "when ")):
        detected.add("precise_lookup")
    return [
        tag
        for tag in ("history_lookup", "big_picture", "analysis_request", "carry_forward", "constraint_recall", "resume_state", "evidence_request", "precise_lookup")
        if tag in detected
    ]

def _query_family_cue_score(
    family: str,
    *,
    cue_matches: dict[str, list[str]],
    text_hint_family: str,
) -> int:
    family_matches = cue_matches.get(family, [])
    score = 0
    if family_matches:
        score += 44 + (min(len(family_matches), 3) * 8)
    if family == text_hint_family:
        score += 16
    return score

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
        overlap_tokens = _routing_overlap_tokens(item, query_tokens)
        content_overlap_tokens = [token for token in overlap_tokens if token not in ROUTING_META_QUERY_TOKENS]
        support_score = _candidate_evidence_shape_score(
            item,
            layer=layer,
            content_overlap_tokens=content_overlap_tokens,
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
                    "content_overlap_count": len(content_overlap_tokens),
                    "content_overlap_tokens": list(content_overlap_tokens[:6]),
                    "strong_candidate": candidate_is_strong,
                }
            )
        if support_score >= int(stats["best_support"]):
            stats["best_support"] = support_score
            stats["best_work_usefulness"] = work_usefulness
            stats["best_content_overlap_count"] = len(content_overlap_tokens)
            stats["best_content_overlap_tokens"] = list(content_overlap_tokens[:6])
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

def _continuity_compatibility_adjustment(
    *,
    intent: str,
    layer: str,
    topic_overlap_tokens: list[str],
    same_thread: bool,
    same_container: bool,
) -> int:
    """Scoring adjustment for answer_continuity + continuity_memory when topic signal is absent.

    When a query carries no domain-token overlap with a continuity_memory candidate
    (topic_overlap_tokens is empty), thread and container affinity become the only
    available structural discriminators.  A candidate from the same thread is preferred;
    one from a different thread and container is mildly penalised so that an unrelated
    carry-forward does not silently win over a structurally compatible one.

    This is intentionally moderate: cross-thread carry-forward is a legitimate use case
    when both candidates have no affinity, so the adjustment must not act as a hard filter.
    """
    if intent != "answer_continuity" or layer != "continuity_memory" or topic_overlap_tokens:
        return 0
    if same_thread:
        return 60
    if same_container:
        return 10
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
    overlap_tokens = _routing_overlap_tokens(item, query_tokens)
    content_overlap_tokens = [token for token in overlap_tokens if token not in ROUTING_META_QUERY_TOKENS]
    query_topic_tokens = _query_topic_tokens(query_tokens)
    topic_overlap_tokens = [token for token in content_overlap_tokens if token in query_topic_tokens]
    same_thread = _candidate_matches_thread(item, query_filters)
    same_container = _candidate_matches_container(item, query_filters)
    evidence_shape_score = _candidate_evidence_shape_score(
        item,
        layer=layer,
        content_overlap_tokens=content_overlap_tokens,
        query_filters=query_filters,
    )
    _weights = layer_weights or ROUTING_LAYER_WEIGHTS
    base_routing_score = (
        _weights[intent][layer]
        + (retrieval_score * 10)
        + _specificity_bonus(item, intent, query_text=query_text)
        + evidence_shape_score
        + _routing_overlap_adjustment(layer, intent, content_overlap_tokens)
        + _topic_alignment_adjustment(layer=layer, query_topic_tokens=query_topic_tokens, topic_overlap_tokens=topic_overlap_tokens)
        + _continuity_compatibility_adjustment(
            intent=intent,
            layer=layer,
            topic_overlap_tokens=topic_overlap_tokens,
            same_thread=same_thread,
            same_container=same_container,
        )
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
        "content_overlap_tokens": content_overlap_tokens,
        "topic_overlap_tokens": topic_overlap_tokens,
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
    if _source_hit_is_greeting_or_noise_text(excerpt):
        return "greeting_source_noise", "Greeting or pleasantry chatter was excluded from recall packaging."
    if _source_hit_is_heartbeat_text(excerpt):
        return "heartbeat_source_noise", "Heartbeat-style source noise was excluded from recall packaging."
    if _source_hit_is_generic_capability_text(excerpt):
        return "generic_capability_source", "Generic capability chatter was excluded from recall packaging."
    if _source_hit_looks_like_recall_query(item, query_text):
        if _runtime_context_prefers_cross_thread_recall(runtime_context) and query_filters is not None and query_filters.thread_ref and item.thread_ref == query_filters.thread_ref:
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
    if payload.get("selected_work_artifacts") or payload.get("conclusions"):
        return None
    if _preferred_constraint_text(summary_text) or _summary_text_has_durable_state_cue(summary_text):
        return None
    if _summary_text_looks_query_only(summary_text, query_text):
        return "query_only_thread_summary", "A query-only summary was excluded from recall packaging."
    if _summary_text_looks_unresolved(summary_text):
        return "unresolved_thread_summary", "An unresolved summary without durable state was excluded from recall packaging."
    return None

def _summary_text_looks_query_only(summary_text: str, query_text: str) -> bool:
    lowered = summary_text.lower()
    if any(marker in lowered for marker in QUERY_ONLY_SUMMARY_MARKERS):
        return True
    overlap = len(set(_routing_query_tokens(summary_text)).intersection(set(_routing_query_tokens(query_text))))
    return overlap >= 4 and lowered.startswith("user asked")

def _summary_text_looks_unresolved(summary_text: str) -> bool:
    lowered = summary_text.lower().strip()
    if lowered in WEAK_THREAD_SUMMARY_TEXT or lowered.startswith("unresolved"):
        return True
    return any(marker in lowered for marker in UNRESOLVED_SUMMARY_MARKERS)

def _summary_text_has_durable_state_cue(summary_text: str) -> bool:
    lowered = summary_text.lower().strip()
    return any(
        marker in lowered
        for marker in (
            "constraint:",
            "blocked by",
            "blocker:",
            "next step:",
            "current state:",
            "decision:",
            "investigation outcome:",
            "resolved that",
            "concluded that",
        )
    )

def _source_hit_looks_like_recall_query(item: QueryResultItem, query_text: str) -> bool:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return False
    if not _source_hit_looks_like_request_or_question(item):
        return False
    if item.role not in {None, "user"} and (item.source_type or "") not in {"chat_message", "message"}:
        return False
    excerpt_tokens = tuple(_routing_query_tokens(excerpt))
    query_tokens = set(_routing_query_tokens(query_text))
    overlap = len(set(excerpt_tokens).intersection(query_tokens))
    excerpt_tags = set(_query_shape_tags(excerpt, excerpt_tokens))
    return overlap >= 3 and bool(excerpt_tags.intersection({"history_lookup", "carry_forward", "constraint_recall"}))

def _source_hit_looks_like_request_or_question(item: QueryResultItem) -> bool:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return False
    lowered = excerpt.lower()
    request_prefixes = (
        "can you", "could you", "would you", "will you", "please", "remind me", "what ", "which ", "why ", "how ",
        "when ", "where ", "who ", "do we", "did we", "are we", "is there", "should we", "so what"
    )
    if lowered.startswith(request_prefixes):
        return True
    if item.role == "assistant":
        return False
    if "?" in excerpt:
        return True
    if item.role == "user" and lowered.endswith(("right", "please")) and len(lowered.split()) <= 8:
        return True
    return False

def _assistant_source_is_answer_bearing_local_state(excerpt: str, query_text: str) -> bool:
    lowered_query = query_text.lower()
    if not any(marker in lowered_query for marker in ("paste", "repeat", "rewrite", "again", "exact", "exactly")):
        return False
    normalized_excerpt = str(excerpt or "").strip()
    if len(normalized_excerpt.split()) < 8:
        return False
    lowered_excerpt = normalized_excerpt.lower()
    if lowered_excerpt.startswith(("sure:", "here is", "here's", "try this", "rewrite:")):
        return True
    return '"' in normalized_excerpt or "'" in normalized_excerpt

def _source_hit_is_generic_capability_text(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("capabilities:") or "many talents" in lowered or ("i can" in lowered and "help" in lowered and "status" in lowered)

def _source_hit_is_heartbeat_text(text: str) -> bool:
    lowered = text.lower()
    return "heartbeat" in lowered or "still alive" in lowered or "still monitoring" in lowered or "healthcheck" in lowered

def _result_layer(item: QueryResultItem) -> str:
    if item.result_kind == "source_hit":
        return "source_evidence"
    if item.type == "pattern_memory":
        return "pattern_memory"
    if item.type == "continuity_memory":
        return "continuity_memory"
    if item.type == "task_checkpoint":
        return "task_checkpoint"
    if item.type == "thread_summary":
        return "thread_summary"
    if item.type == "discussion_summary":
        return "discussion_summary"
    if item.type == "investigation_outcome":
        return "investigation_outcome"
    if item.type == "decision":
        return "decision"
    return "lower_level_memory"

def _specificity_bonus(item: QueryResultItem, intent: str, *, query_text: str) -> int:
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
            if _query_contains_any(query_text, WORK_RESUMPTION_NEXT_STEP_CUES) and str(item.payload.get("next_step") or "").strip():
                bonus += 25
            if _query_contains_any(query_text, WORK_RESUMPTION_PROGRESS_CUES) and str(item.payload.get("current_state") or "").strip():
                bonus += 20
            if _query_contains_any(query_text, WORK_RESUMPTION_BLOCKER_CUES) and str(item.payload.get("blocker_state") or "").strip():
                bonus += 25
        elif intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
            bonus -= 35
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "answer_continuity":
        bonus += 25
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and intent == "broad_recall" and _query_contains_any(query_text, BROAD_RECALL_CONCLUSION_CUES):
        bonus += 85 if item.type == "decision" else 75
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "broad_recall" and _query_contains_any(query_text, BROAD_RECALL_CONCLUSION_CUES):
        bonus -= 45
    if item.result_kind == "memory_hit" and item.type == "pattern_memory" and intent == "broad_recall":
        bonus += 25
        if _query_contains_any(query_text, BROAD_RECALL_ABSTRACTION_CUES):
            bonus += 45
    if item.result_kind == "source_hit" and intent == "evidence_trace":
        bonus += 30 if item.artifact_kind == "assistant_output" else 10
    if item.result_kind == "source_hit" and intent == "work_resumption":
        bonus += 45 if (item.artifact_kind or "") in SELECTED_WORK_ARTIFACT_KINDS else 20
        if (item.artifact_kind or "") == "todo_snapshot" and _query_contains_any(query_text, WORK_RESUMPTION_NEXT_STEP_CUES):
            bonus += 25
    if item.result_kind == "source_hit" and intent == "investigative_conclusion":
        bonus += 6 if item.artifact_kind == "assistant_output" else 2
    return bonus

def _query_contains_any(text: str, cues: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in cues)

def _edit_distance_with_limit(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]

def _looks_like_low_value_greeting_variant(normalized: str) -> bool:
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    if normalized in LOW_VALUE_GREETING_NOISE_QUERIES:
        return True
    low_value_trailing_tokens = {"again", "sir", "team", "friend", "folks", "maam", "madam"}
    if tokens[0] == "good" and len(tokens) >= 2:
        if any(_edit_distance_with_limit(tokens[1], marker, 2) <= 2 for marker in ("morning", "afternoon", "evening")):
            return all(token in low_value_trailing_tokens for token in tokens[2:])
    for marker in ("hello", "hi", "hey", "thanks"):
        if _edit_distance_with_limit(tokens[0], marker, 1) <= 1:
            return all(token in low_value_trailing_tokens for token in tokens[1:])
    return False

def _source_hit_is_greeting_or_noise_text(text: str) -> bool:
    normalized = normalize_for_index(text)
    if not normalized:
        return False
    if _looks_like_low_value_greeting_variant(normalized):
        return True
    for prefix in LOW_VALUE_GREETING_NOISE_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        remainder = normalized[len(prefix):].strip()
        if not remainder:
            return True
        if _looks_like_low_value_greeting_variant(f"{prefix} {remainder}".strip()):
            return True
        if remainder.startswith(("i can help", "let me know", "when you are ready", "how can i help")):
            return True
    return False

def _query_is_low_value_greeting_or_noise(text: str) -> bool:
    normalized = normalize_for_index(text)
    if not normalized:
        return False
    if _looks_like_low_value_greeting_variant(normalized):
        return True
    return len(normalized.split()) <= 4 and _source_hit_is_greeting_or_noise_text(text)

def _routing_query_tokens(text: str) -> tuple[str, ...]:
    normalized = normalize_for_index(text)
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)

def _routing_overlap_adjustment(layer: str, intent: str, content_overlap_tokens: Iterable[str]) -> int:
    overlap_count = len(tuple(content_overlap_tokens))
    if layer not in ROUTING_HIGHER_LEVEL_TYPES:
        return 0
    if overlap_count == 0:
        return -ROUTING_WEAK_HIGHER_LEVEL_MATCH_PENALTY[intent]
    return 0

def _routing_overlap_tokens(item: QueryResultItem, query_tokens: tuple[str, ...]) -> list[str]:
    if not query_tokens:
        return []
    item_tokens = set(_routing_item_tokens(item))
    return sorted(token for token in set(query_tokens) if token in item_tokens)

def _routing_item_tokens(item: QueryResultItem) -> tuple[str, ...]:
    normalized = normalize_for_index(_routing_item_text(item))
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)

def _query_topic_tokens(query_tokens: tuple[str, ...]) -> set[str]:
    return {
        token
        for token in query_tokens
        if token not in ROUTING_META_QUERY_TOKENS and token not in ROUTING_TOPIC_LOW_SIGNAL_TOKENS
    }

def is_query_topic_signal_empty(query_tokens: Iterable[str]) -> bool:
    """Return True if none of the query tokens carry topic signal.

    A token carries topic signal when it is neither a generic meta-query word
    (ROUTING_META_QUERY_TOKENS) nor a structural low-signal routing word
    (ROUTING_TOPIC_LOW_SIGNAL_TOKENS).  Used by benchmark runners to classify
    whether a query was generic-topic-free, which matters for diagnosing
    answer_continuity contamination failures.
    """
    return not any(
        t for t in query_tokens
        if t not in ROUTING_META_QUERY_TOKENS and t not in ROUTING_TOPIC_LOW_SIGNAL_TOKENS
    )


def _topic_alignment_adjustment(*, layer: str, query_topic_tokens: set[str], topic_overlap_tokens: list[str]) -> int:
    if not query_topic_tokens:
        return 0
    if topic_overlap_tokens:
        return min(len(topic_overlap_tokens), 2) * 36
    if layer in {"task_checkpoint", "thread_summary", "discussion_summary", "continuity_memory", "pattern_memory"}:
        return -140
    if layer == "source_evidence":
        return -110
    return -90

def _routing_item_text(item: QueryResultItem) -> str:
    fragments: list[str] = []
    if item.excerpt:
        fragments.append(item.excerpt)
    if item.payload:
        if item.type == "decision":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("decision", "decision_evidence_text", "rationale")
            )
        elif item.type == "investigation_outcome":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("investigation_outcome", "investigation_evidence_text", "rationale")
            )
        elif item.type == CONSTRAINT_MEMORY_TYPE:
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "constraint_text", "action_class", "polarity")
            )
            for key in ("primary_scope_anchor", "target_anchor"):
                anchor = item.payload.get(key)
                if isinstance(anchor, dict):
                    fragments.append(str(anchor.get("value") or ""))
        elif item.type == "task_checkpoint":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "task", "current_state", "blocker_state", "next_step", "freshness_signal")
            )
            for field in ("key_findings", "evidence"):
                values = item.payload.get(field, [])
                if isinstance(values, list):
                    fragments.extend(str(value or "") for value in values)
            for work_artifact in item.payload.get("selected_work_artifacts", []):
                if isinstance(work_artifact, dict):
                    fragments.append(str(work_artifact.get("signal_type") or ""))
                    fragments.append(str(work_artifact.get("text") or ""))
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
        elif item.type in ROUTING_HIGHER_LEVEL_TYPES:
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "pattern_label", "continuity_question", "carry_forward_answer")
            )
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
        elif item.type == "thread_summary":
            fragments.append(str(item.payload.get("summary") or ""))
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
            for work_artifact in item.payload.get("selected_work_artifacts", []):
                if isinstance(work_artifact, dict):
                    fragments.append(str(work_artifact.get("signal_type") or ""))
                    fragments.append(str(work_artifact.get("text") or ""))
        else:
            fragments.append(json.dumps(item.payload, sort_keys=True))
    return " ".join(fragment for fragment in fragments if fragment)

def _routing_reason(
    intent: str,
    layer: str,
    content_overlap_tokens: list[str],
    support_grade: str,
    routing_focus: dict[str, object],
    packaging_reasons: list[str],
) -> str:
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if not content_overlap_tokens and layer in ROUTING_HIGHER_LEVEL_TYPES else ""
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

def _routing_result_id(item: QueryResultItem) -> str:
    return str(item.result_id)

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

# ---------------------------------------------------------------------------
# Policy layer: evidence building, classification, option construction
# ---------------------------------------------------------------------------

def _build_policy_evidence(
    candidates: list[QueryResultItem],
) -> dict[str, object]:
    task_checkpoint_best_work_usefulness = 0
    source_evidence_best_work_usefulness = 0
    strong_task_checkpoint_survives = False
    structured_best_support = 0
    cross_thread_continuity_survives = False
    constraint_best_support = 0
    constraint_best_kind = ""
    constraint_memory_only_support = 0
    structured_layers = {"thread_summary", "discussion_summary", "continuity_memory"}

    for item in candidates:
        layer = _result_layer(item)
        support = _policy_candidate_support_estimate(item, layer)
        if layer == "task_checkpoint":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            task_checkpoint_best_work_usefulness = max(task_checkpoint_best_work_usefulness, usefulness)
            if support >= POLICY_SUPPORT_THRESHOLD:
                strong_task_checkpoint_survives = True
        elif layer == "source_evidence":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            source_evidence_best_work_usefulness = max(source_evidence_best_work_usefulness, usefulness)
        if layer in structured_layers:
            structured_best_support = max(structured_best_support, support)
        if layer == "continuity_memory" and item.thread_ref is None:
            if support >= POLICY_SUPPORT_THRESHOLD:
                cross_thread_continuity_survives = True
        if item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
            if support > constraint_best_support:
                constraint_best_support = support
                constraint_best_kind = CONSTRAINT_MEMORY_TYPE
            constraint_memory_only_support = max(constraint_memory_only_support, support)
        elif item.result_kind == "memory_hit" and item.type in {"task_checkpoint", "thread_summary"}:
            # Structured types can carry constraint signals
            payload = item.payload or {}
            if payload.get("constraint_text") or payload.get("blocker_state"):
                if support > constraint_best_support:
                    constraint_best_support = support
                    constraint_best_kind = item.type

    return {
        "task_checkpoint_best_work_usefulness": task_checkpoint_best_work_usefulness,
        "source_evidence_best_work_usefulness": source_evidence_best_work_usefulness,
        "strong_task_checkpoint_survives": strong_task_checkpoint_survives,
        "structured_best_support": structured_best_support,
        "cross_thread_continuity_survives": cross_thread_continuity_survives,
        "constraint_best_support": constraint_best_support,
        "constraint_best_kind": constraint_best_kind,
        "constraint_memory_only_support": constraint_memory_only_support,
    }


def _policy_candidate_support_estimate(item: QueryResultItem, layer: str) -> int:
    """Lightweight support estimate for policy-level gates without query token overlap."""
    score = min(len(item.evidence), 3) * 8
    if item.result_kind == "source_hit":
        score += 18
        return score
    payload = item.payload or {}
    if layer == "task_checkpoint":
        explicit_fields = sum(1 for f in ("task", "current_state", "blocker_state", "next_step", "key_findings", "evidence") if payload.get(f))
        score += 18 + min(explicit_fields, 5) * 8
        if payload.get("blocker_state") and payload.get("next_step"):
            score += 10
    elif layer in {"decision", "investigation_outcome"}:
        score += 34
        if payload.get("decision_evidence_text") or payload.get("investigation_evidence_text"):
            score += 10
    elif layer == "continuity_memory":
        score += 18
        if payload.get("carry_forward_answer"):
            score += 18
    elif layer in {"thread_summary", "discussion_summary"}:
        score += 8
    elif item.result_kind == "memory_hit" and item.type == CONSTRAINT_MEMORY_TYPE:
        score += 24
        payload = item.payload or {}
        if payload.get("constraint_text"):
            score += 18
        if payload.get("primary_scope_anchor") and payload.get("target_anchor"):
            score += 12
    return score


def _has_latest_status_wording(text: str) -> bool:
    """Detect queries specifically asking about current status/state, not general recall with 'latest'."""
    lowered = text.lower()
    if any(phrase in lowered for phrase in LATEST_STATUS_RESUME_PHRASES):
        return True
    if any(phrase in lowered for phrase in LATEST_STATUS_HISTORY_PHRASES):
        # "what is the latest" / "what's the latest" are status queries only when NOT followed
        # by broad recall patterns like "about" or when standing alone
        for phrase in LATEST_STATUS_HISTORY_PHRASES:
            idx = lowered.find(phrase)
            if idx < 0:
                continue
            after = lowered[idx + len(phrase):].strip()
            # "what's the latest state" is a resume phrase (already handled above)
            # "what's the latest on X" or "what's the latest?" = status query
            # "what do we know the latest about X" = broad recall, not status
            if not after or after.startswith("on ") or after.startswith("?") or after.startswith("with "):
                return True
    return False


def _work_state_evidence_gate_passes(policy_evidence: dict[str, object]) -> bool:
    if bool(policy_evidence["strong_task_checkpoint_survives"]):
        return True
    if int(policy_evidence["task_checkpoint_best_work_usefulness"]) >= POLICY_WORK_STATE_USEFULNESS_THRESHOLD:
        return True
    if int(policy_evidence["source_evidence_best_work_usefulness"]) >= POLICY_WORK_STATE_USEFULNESS_THRESHOLD:
        return True
    return False


# ---------------------------------------------------------------------------
# Signal envelope: derivation, classification, recall mode selection
# ---------------------------------------------------------------------------

def _candidate_layer_dominance(
    candidates: list[QueryResultItem],
) -> dict[str, dict[str, object]]:
    """Per-layer: count, best_support_score. Language-agnostic — no query text."""
    layers: dict[str, dict[str, object]] = {}
    for item in candidates:
        layer = _result_layer(item)
        support = _policy_candidate_support_estimate(item, layer)
        if layer not in layers:
            layers[layer] = {"count": 0, "best_support_score": 0}
        layers[layer]["count"] = int(layers[layer]["count"]) + 1
        layers[layer]["best_support_score"] = max(int(layers[layer]["best_support_score"]), support)
    return layers


def _compute_typed_candidate_evidence(
    candidates: list[QueryResultItem],
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    """Language-agnostic candidate summary — no query text or tokens."""
    layer_dom = _candidate_layer_dominance(candidates)
    memory_layers = {
        layer: info for layer, info in layer_dom.items()
        if layer != "source_evidence"
    }
    dominant_memory_layer = max(
        memory_layers,
        key=lambda layer: int(memory_layers[layer]["best_support_score"]),
    ) if memory_layers else None

    checkpoint_best_usefulness = 0
    strong_checkpoint_present = False
    for item in candidates:
        if _result_layer(item) == "task_checkpoint":
            signal_types = _work_resumption_signal_types(item)
            usefulness, _ = _work_resumption_usefulness_score(item, signal_types)
            checkpoint_best_usefulness = max(checkpoint_best_usefulness, usefulness)
            support = _policy_candidate_support_estimate(item, "task_checkpoint")
            if support >= POLICY_SUPPORT_THRESHOLD:
                strong_checkpoint_present = True

    thread_ref = query_filters.thread_ref if query_filters else None
    same_thread_hit_count = sum(
        1 for item in candidates
        if thread_ref and item.thread_ref == thread_ref
    ) if thread_ref else 0

    source_hit_count = sum(1 for item in candidates if item.result_kind == "source_hit")
    total = len(candidates) or 1

    return {
        "per_layer_support": layer_dom,
        "dominant_memory_layer": dominant_memory_layer,
        "checkpoint_best_usefulness": checkpoint_best_usefulness,
        "strong_checkpoint_present": strong_checkpoint_present,
        "source_hit_count": source_hit_count,
        "source_hit_ratio": source_hit_count / total,
        "same_thread_hit_count": same_thread_hit_count,
        "continuity_memory_present": any(item.type == "continuity_memory" for item in candidates if item.result_kind == "memory_hit"),
        "cross_thread_continuity": any(
            item.type == "continuity_memory" and item.thread_ref is None
            for item in candidates if item.result_kind == "memory_hit"
        ),
        "constraint_memory_present": any(
            item.type == CONSTRAINT_MEMORY_TYPE
            for item in candidates if item.result_kind == "memory_hit"
        ),
    }


def _select_recall_mode(candidate_evidence: dict[str, object]) -> str:
    """Select recall-mode preference from candidate evidence. Weight/shaping only.

    Conservative: only switch from default when the dominant layer type is
    unambiguously the sole substantial signal. Mixed candidate sets always
    get default mode, which is safe broad-recall behavior.
    """
    dominant = candidate_evidence.get("dominant_memory_layer")
    per_layer = candidate_evidence.get("per_layer_support", {})

    def _layer_support(layer: str) -> int:
        info = per_layer.get(layer, {})
        return int(info.get("best_support_score", 0)) if isinstance(info, dict) else 0

    def _has_competing_layers(target_layers: set[str]) -> bool:
        """True if any memory layer outside target_layers has meaningful support."""
        for layer, info in per_layer.items():
            if layer in target_layers or layer == "source_evidence":
                continue
            if isinstance(info, dict) and int(info.get("best_support_score", 0)) >= POLICY_SUPPORT_THRESHOLD:
                return True
        return False

    # investigation_preference: dominant investigation_outcome, no competing recall layers
    if (
        dominant == "investigation_outcome"
        and _layer_support("investigation_outcome") >= POLICY_SUPPORT_THRESHOLD
        and not _has_competing_layers({"investigation_outcome", "decision"})
    ):
        return "investigation_preference"

    # sharp_fact_preference: dominant decision/investigation, no competing recall layers
    if dominant in {"decision", "investigation_outcome"}:
        combined = _layer_support("decision") + _layer_support("investigation_outcome")
        if combined >= POLICY_SUPPORT_THRESHOLD and not _has_competing_layers({"decision", "investigation_outcome"}):
            return "sharp_fact_preference"

    # continuity_preference: dominant continuity_memory + same-thread, no competing layers
    if (
        dominant == "continuity_memory"
        and int(candidate_evidence.get("same_thread_hit_count", 0)) > 0
        and not _has_competing_layers({"continuity_memory"})
    ):
        return "continuity_preference"

    return "default"


def _derive_query_signal_envelope(
    *,
    text: str,
    query_tokens: tuple[str, ...],
    policy_evidence: dict[str, object],
    candidate_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
    runtime_context: QueryRuntimeContext | None,
    signal_classifier_config: dict[str, object] | None,
) -> QuerySignalEnvelope:
    """Three-tier signal derivation: structural → semantic → legacy English."""
    normalized = normalize_for_index(text)

    # Tier 1: structural/typed derivation
    signals: dict[str, bool] = {
        "low_value": False,
        "history_lookup": False,
        "latest_status_request": False,
        "resume_state": False,
        "constraint_lookup": False,
        "evidence_request": False,
    }
    derivation: list[str] = []

    # low_value: only truly empty queries
    if not normalized or not normalized.strip():
        signals["low_value"] = True
        derivation.append("empty_query")

    if not signals["low_value"]:
        dominant = str(candidate_evidence.get("dominant_memory_layer") or "")
        per_layer = candidate_evidence.get("per_layer_support", {})

        # constraint_lookup
        constraint_only_support = int(policy_evidence.get("constraint_memory_only_support", 0))
        if constraint_only_support >= POLICY_SUPPORT_THRESHOLD:
            signals["constraint_lookup"] = True
            derivation.append("constraint_memory_with_support")
        elif dominant == CONSTRAINT_MEMORY_TYPE:
            signals["constraint_lookup"] = True
            derivation.append("constraint_dominant_layer")

        # resume_state: requires resumed_session context + candidate-side evidence
        is_resumed = runtime_context is not None and runtime_context.turn_kind == "resumed_session"
        work_gate = _work_state_evidence_gate_passes(policy_evidence)
        if is_resumed and work_gate:
            signals["resume_state"] = True
            derivation.append("resumed_session_with_evidence")

        # evidence_request: NOT derivable from Tier 1 structural signals

        # history_lookup
        history_layers = {"pattern_memory", "continuity_memory"}
        sharp_layers = {"decision", "investigation_outcome"}
        if dominant in history_layers:
            signals["history_lookup"] = True
            derivation.append(f"dominant_{dominant}")
        elif dominant in sharp_layers:
            layer_info = per_layer.get(dominant, {})
            if isinstance(layer_info, dict) and int(layer_info.get("best_support_score", 0)) >= POLICY_SUPPORT_THRESHOLD:
                signals["history_lookup"] = True
                derivation.append(f"strong_{dominant}")

        # latest_status_request: requires dominant fresh state memory
        if not any(signals[s] for s in ("constraint_lookup", "resume_state", "history_lookup")):
            from datetime import timezone as _tz
            _now = datetime.now(_tz.utc)
            for item in anchor_prefiltered_candidates:
                if item.result_kind != "memory_hit":
                    continue
                if item.type not in {"task_checkpoint", "thread_summary"}:
                    continue
                payload = item.payload or {}
                has_state = bool(payload.get("current_state") or payload.get("freshness_signal"))
                if not has_state:
                    continue
                if item.freshness_at and (_now - item.freshness_at).total_seconds() < 86400:
                    layer = _result_layer(item)
                    if layer == dominant:
                        signals["latest_status_request"] = True
                        derivation.append("dominant_fresh_state_memory")
                        break

    # Tier 1 confidence
    active_signals = [s for s, v in signals.items() if v and s != "low_value"]
    if signals["low_value"] or len(active_signals) == 1:
        tier1_confidence = "high"
    elif len(active_signals) > 1:
        tier1_confidence = "medium"
    else:
        tier1_confidence = "low"

    # Tier 2: bounded evidence classifier — runs when source hits exist and
    # no higher-priority hard route (work_resumption, constraint) has won
    has_source_hits = any(item.result_kind == "source_hit" for item in anchor_prefiltered_candidates)
    if has_source_hits and not signals["constraint_lookup"] and not signals["resume_state"]:
        evidence_classified = _maybe_classify_evidence_request(
            text=text,
            candidate_evidence=candidate_evidence,
            runtime_context=runtime_context,
            signal_classifier_config=signal_classifier_config,
        )
        if evidence_classified:
            signals["evidence_request"] = True
            derivation.append("semantic_evidence_request")
            return QuerySignalEnvelope(
                **signals,
                source="semantic",
                confidence="medium",
                legacy_english_fallback_used=False,
                semantic_classification_used=True,
                derivation_signals=tuple(derivation),
            )

    if tier1_confidence in ("high", "medium"):
        return QuerySignalEnvelope(
            **signals,
            source="structural",
            confidence=tier1_confidence,
            legacy_english_fallback_used=False,
            semantic_classification_used=False,
            derivation_signals=tuple(derivation),
        )

    # Tier 3: legacy English fallback
    return _legacy_english_query_signals(text, query_tokens)


def _maybe_classify_evidence_request(
    *,
    text: str,
    candidate_evidence: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
    signal_classifier_config: dict[str, object] | None,
) -> bool:
    """Tier 2 evidence-request classifier. Returns True if evidence request detected."""
    # Stub — will be implemented in Phase 5
    return False


def _legacy_english_query_signals(
    text: str,
    query_tokens: tuple[str, ...],
) -> QuerySignalEnvelope:
    """Tier 3: wrap all existing English logic behind one entry point."""
    signals: dict[str, bool] = {
        "low_value": False,
        "history_lookup": False,
        "latest_status_request": False,
        "resume_state": False,
        "constraint_lookup": False,
        "evidence_request": False,
    }
    derivation: list[str] = []

    if _query_is_low_value_greeting_or_noise(text):
        signals["low_value"] = True
        derivation.append("english_greeting_or_noise")

    if not signals["low_value"]:
        if _has_latest_status_wording(text):
            signals["latest_status_request"] = True
            derivation.append("english_latest_status_wording")

        shape_tags = _query_shape_tags(text, query_tokens)
        if "resume_state" in shape_tags:
            signals["resume_state"] = True
            derivation.append("english_resume_state_tag")
        if "constraint_recall" in shape_tags or _preferred_constraint_text(text):
            signals["constraint_lookup"] = True
            derivation.append("english_constraint_text_or_tag")
        if "evidence_request" in shape_tags:
            signals["evidence_request"] = True
            derivation.append("english_evidence_request_tag")
        if "history_lookup" in shape_tags:
            signals["history_lookup"] = True
            derivation.append("english_history_lookup_tag")

    return QuerySignalEnvelope(
        **signals,
        source="legacy_english_fallback",
        confidence="medium",
        legacy_english_fallback_used=True,
        semantic_classification_used=False,
        derivation_signals=tuple(derivation),
    )


def _build_signal_envelope_trace(envelope: QuerySignalEnvelope) -> dict[str, object]:
    return {
        "low_value": envelope.low_value,
        "history_lookup": envelope.history_lookup,
        "latest_status_request": envelope.latest_status_request,
        "resume_state": envelope.resume_state,
        "constraint_lookup": envelope.constraint_lookup,
        "evidence_request": envelope.evidence_request,
        "source": envelope.source,
        "confidence": envelope.confidence,
        "legacy_english_fallback_used": envelope.legacy_english_fallback_used,
        "semantic_classification_used": envelope.semantic_classification_used,
        "derivation_signals": list(envelope.derivation_signals),
    }


def _policy_family_from_signal_envelope(envelope: QuerySignalEnvelope) -> str:
    """Map signal envelope to coarse route / policy family."""
    if envelope.low_value:
        return "noise"
    if envelope.constraint_lookup:
        return "check_constraints"
    if envelope.resume_state:
        return "resume_work"
    if envelope.evidence_request:
        return "recall_fact"  # evidence_trace handled at lane level
    if envelope.latest_status_request:
        return "latest_status"
    return "recall_fact"


def _determine_eligible_lanes(
    *,
    text: str,
    query_shape_tags: list[str],
    policy_evidence: dict[str, object],
    anchor_prefiltered_candidates: list[QueryResultItem],
    family_inference: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
) -> LaneNarrowingResult:
    lanes: list[LaneEligibility] = []

    # --- constraint_policy ---
    constraint_structural: list[str] = []
    constraint_shape: list[str] = []
    if _preferred_constraint_text(text):
        constraint_structural.append("constraint_text_detected")
    if int(policy_evidence.get("constraint_memory_only_support", 0)) >= POLICY_SUPPORT_THRESHOLD:
        constraint_structural.append("constraint_memory_with_support")
    if "constraint_recall" in query_shape_tags:
        constraint_shape.append("constraint_recall_tag")

    if constraint_structural:
        constraint_state = "strongly_eligible"
        constraint_reason = "Structural constraint signal: " + ", ".join(constraint_structural)
    elif constraint_shape:
        constraint_state = "plausible"
        constraint_reason = "Query-shape hint only: " + ", ".join(constraint_shape)
    else:
        constraint_state = "excluded"
        constraint_reason = "No constraint signals"
    lanes.append(LaneEligibility(
        lane="constraint_policy", state=constraint_state,
        structural_signals=tuple(constraint_structural), shape_signals=tuple(constraint_shape),
        reason=constraint_reason,
    ))

    # --- work_resumption ---
    work_structural: list[str] = []
    work_shape: list[str] = []
    is_resumed_session = runtime_context is not None and runtime_context.turn_kind == "resumed_session"
    has_resume_state_tag = "resume_state" in query_shape_tags
    work_evidence_gate = _work_state_evidence_gate_passes(policy_evidence)
    if is_resumed_session:
        work_structural.append("resumed_session")
    if has_resume_state_tag:
        work_shape.append("resume_state_tag")
    if int(policy_evidence.get("task_checkpoint_best_work_usefulness", 0)) > 0:
        work_structural.append("checkpoint_usefulness_present")
    # Strong eligibility requires both a query-side signal AND candidate-side evidence.
    # resumed_session alone is only plausible — users ask broad recall questions in
    # resumed sessions. Evidence gate alone is also insufficient (see constraint test).
    if is_resumed_session and work_evidence_gate:
        work_structural.append("resumed_session_with_evidence")
        work_state = "strongly_eligible"
        work_reason = "Structural work signal: resumed session with checkpoint evidence"
    elif work_evidence_gate and has_resume_state_tag:
        work_structural.append("work_state_evidence_gate")
        work_state = "strongly_eligible"
        work_reason = "Structural work signal: evidence gate + resume_state tag"
    elif work_shape or work_structural:
        work_state = "plausible"
        all_hints = work_shape + [s for s in work_structural if s not in ("resumed_session_with_evidence", "work_state_evidence_gate")]
        work_reason = ("Structural and shape hints: " if work_structural else "Query-shape hint only: ") + ", ".join(all_hints)
    else:
        work_state = "excluded"
        work_reason = "No work resumption signals"
    lanes.append(LaneEligibility(
        lane="work_resumption", state=work_state,
        structural_signals=tuple(work_structural), shape_signals=tuple(work_shape),
        reason=work_reason,
    ))

    # --- evidence_trace ---
    evidence_structural: list[str] = []
    evidence_shape: list[str] = []
    has_source_hits = any(item.result_kind == "source_hit" for item in anchor_prefiltered_candidates)
    if "evidence_request" in query_shape_tags and has_source_hits:
        evidence_structural.append("evidence_request_with_source_hits")
    if has_source_hits and not evidence_structural:
        evidence_shape.append("source_hits_present")

    if evidence_structural:
        evidence_state = "strongly_eligible"
        evidence_reason = "Structural evidence signal: " + ", ".join(evidence_structural)
    elif evidence_shape:
        evidence_state = "plausible"
        evidence_reason = "Source hits present but no explicit evidence request"
    else:
        evidence_state = "excluded"
        evidence_reason = "No source evidence signals"
    lanes.append(LaneEligibility(
        lane="evidence_trace", state=evidence_state,
        structural_signals=tuple(evidence_structural), shape_signals=tuple(evidence_shape),
        reason=evidence_reason,
    ))

    # --- residual_recall ---
    strongly_eligible_lanes = [le for le in lanes if le.state == "strongly_eligible"]
    if strongly_eligible_lanes:
        residual_state = "excluded"
        residual_reason = "Excluded: other lane(s) strongly eligible"
    else:
        residual_state = "plausible"
        residual_reason = "No lane strongly eligible; fallthrough to existing pipeline"
    lanes.append(LaneEligibility(
        lane="residual_recall", state=residual_state,
        structural_signals=(), shape_signals=(), reason=residual_reason,
    ))

    # --- Decision logic ---
    strongly_count = len(strongly_eligible_lanes)

    if strongly_count == 1:
        winner = strongly_eligible_lanes[0]
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=winner.lane,
            selection_mode="single_lane_bypass",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason=None,
            mapped_intent=LANE_INTENT_MAPPING.get(winner.lane),
            mapped_policy_family=LANE_POLICY_FAMILY_MAPPING.get(winner.lane),
        )

    if strongly_count > 1:
        constraint_is_strong = any(le.lane == "constraint_policy" and le.state == "strongly_eligible" for le in lanes)
        if constraint_is_strong:
            return LaneNarrowingResult(
                eligible_lanes=tuple(lanes),
                selected_lane="constraint_policy",
                selection_mode="single_lane_bypass",
                lane_narrowing_used_intent=False,
                intent_effect="suppressed",
                abstain_reason=None,
                mapped_intent=LANE_INTENT_MAPPING["constraint_policy"],
                mapped_policy_family=LANE_POLICY_FAMILY_MAPPING["constraint_policy"],
            )
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=None,
            selection_mode="abstain",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason="lane_ambiguity",
            mapped_intent=None,
            mapped_policy_family=None,
        )

    plausible_lanes = [le for le in lanes if le.state == "plausible"]
    if plausible_lanes:
        return LaneNarrowingResult(
            eligible_lanes=tuple(lanes),
            selected_lane=None,
            selection_mode="residual_fallthrough",
            lane_narrowing_used_intent=False,
            intent_effect="none",
            abstain_reason=None,
            mapped_intent=None,
            mapped_policy_family=None,
        )

    return LaneNarrowingResult(
        eligible_lanes=tuple(lanes),
        selected_lane=None,
        selection_mode="abstain",
        lane_narrowing_used_intent=False,
        intent_effect="none",
        abstain_reason="no_lane_eligible",
        mapped_intent=None,
        mapped_policy_family=None,
    )


def _classify_query_policy_family(
    text: str,
    *,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
    initial_intent: str | None = None,
) -> str:
    if _query_is_low_value_greeting_or_noise(text):
        return "noise"
    if _has_latest_status_wording(text):
        return "latest_status"
    if "resume_state" in query_shape_tags:
        return "resume_work"
    if runtime_context is not None and runtime_context.turn_kind == "resumed_session" and initial_intent == "work_resumption":
        return "resume_work"
    if _preferred_constraint_text(text) or "constraint_recall" in query_shape_tags:
        return "check_constraints"
    return "recall_fact"


def _build_ambiguity_options(
    policy_family: str,
    *,
    text: str,
    policy_evidence: dict[str, object],
    family_inference: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
    query_shape_tags: list[str],
) -> tuple[PolicySelectedContext, list[dict[str, object]]]:
    if policy_family == "noise":
        return PolicySelectedContext(
            query_policy_family="noise",
            allowed_query_intents=frozenset(),
        ), []

    if policy_family == "latest_status":
        if _work_state_evidence_gate_passes(policy_evidence):
            return _build_latest_vs_resume_pair(
                policy_evidence=policy_evidence,
                runtime_context=runtime_context,
                query_shape_tags=query_shape_tags,
            )
        return PolicySelectedContext(
            query_policy_family="latest_status",
            allowed_query_intents=LATEST_STATUS_COLLAPSED_INTENTS,
        ), []

    if policy_family == "resume_work":
        return PolicySelectedContext(
            query_policy_family="resume_work",
            allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["resume_work"],
        ), []

    if policy_family == "check_constraints":
        family_scores = family_inference.get("family_scores", {})
        recall_fact_intents = QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"]
        if isinstance(family_scores, dict):
            max_recall_score = max(
                (int((family_scores.get(f) or {}).get("total", 0) if isinstance(family_scores.get(f), dict) else 0) for f in recall_fact_intents),
                default=0,
            )
        else:
            max_recall_score = 0
        has_constraint_support = bool(_preferred_constraint_text(text)) or "constraint_recall" in query_shape_tags
        if has_constraint_support and max_recall_score > 0:
            return _build_constraints_vs_recall_pair(
                text=text,
                policy_evidence=policy_evidence,
                family_inference=family_inference,
                query_shape_tags=query_shape_tags,
            )
        return PolicySelectedContext(
            query_policy_family="check_constraints",
            allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["check_constraints"],
        ), []

    # recall_fact — default
    return PolicySelectedContext(
        query_policy_family="recall_fact",
        allowed_query_intents=QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"],
    ), []


def _build_latest_vs_resume_pair(
    *,
    policy_evidence: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
    query_shape_tags: list[str],
) -> tuple[PolicySelectedContext, list[dict[str, object]]]:
    resume_work_score = 0
    if runtime_context is not None and runtime_context.turn_kind == "resumed_session":
        resume_work_score += 12
    if "resume_state" in query_shape_tags:
        resume_work_score += 18
    resume_work_score += min(int(policy_evidence["task_checkpoint_best_work_usefulness"]), 40)
    resume_work_score += min(int(policy_evidence["source_evidence_best_work_usefulness"]), 16)

    latest_status_score = 0
    latest_status_score += 18  # latest_status wording is always present when this pair is eligible
    if "history_lookup" in query_shape_tags:
        latest_status_score += 14
    if bool(policy_evidence["cross_thread_continuity_survives"]):
        latest_status_score += 12
    latest_status_score += min(int(policy_evidence["structured_best_support"]), 24)

    # Determine option A
    if resume_work_score > latest_status_score:
        option_a_family = "resume_work"
    elif resume_work_score == latest_status_score:
        option_a_family = "resume_work" if (runtime_context is not None and runtime_context.turn_kind == "resumed_session") else "latest_status"
    else:
        option_a_family = "latest_status"
    option_b_family = "latest_status" if option_a_family == "resume_work" else "resume_work"

    options = [
        {
            "option_id": "A",
            "query_policy_family": option_a_family,
            "allowed_query_intents": list({"work_resumption"} if option_a_family == "resume_work" else {"broad_recall"}),
            "score": resume_work_score if option_a_family == "resume_work" else latest_status_score,
        },
        {
            "option_id": "B",
            "query_policy_family": option_b_family,
            "allowed_query_intents": list({"work_resumption"} if option_b_family == "resume_work" else {"broad_recall"}),
            "score": resume_work_score if option_b_family == "resume_work" else latest_status_score,
        },
    ]

    # Phase 3: always use option A (deterministic). Phase 4 will add resolver here.
    selected_family = option_a_family
    allowed_intents = frozenset({"work_resumption"}) if selected_family == "resume_work" else frozenset({"broad_recall"})

    return PolicySelectedContext(
        query_policy_family=selected_family,
        allowed_query_intents=allowed_intents,
        option_a_family=option_a_family,
        option_b_family=option_b_family,
        deterministic_option="A",
        ambiguity_pair_type="latest_status_vs_resume_work",
    ), options


def _build_constraints_vs_recall_pair(
    *,
    text: str,
    policy_evidence: dict[str, object],
    family_inference: dict[str, object],
    query_shape_tags: list[str],
) -> tuple[PolicySelectedContext, list[dict[str, object]]]:
    check_constraints_score = 0
    if _preferred_constraint_text(text):
        check_constraints_score += 24
    if "constraint_recall" in query_shape_tags:
        check_constraints_score += 18
    # Constraint support from post-anchor-prefilter policy evidence
    constraint_best_support = int(policy_evidence.get("constraint_best_support", 0))
    if constraint_best_support >= POLICY_SUPPORT_THRESHOLD:
        check_constraints_score += 20
        constraint_best_kind = str(policy_evidence.get("constraint_best_kind", ""))
        if constraint_best_kind in {"task_checkpoint", "thread_summary"}:
            check_constraints_score += 12

    family_scores = family_inference.get("family_scores")
    recall_fact_intents = QUERY_POLICY_FAMILY_ALLOWED_INTENTS["recall_fact"]
    if isinstance(family_scores, dict):
        recall_fact_score = max(
            (int((family_scores.get(f) or {}).get("total", 0) if isinstance(family_scores.get(f), dict) else 0) for f in recall_fact_intents),
            default=0,
        )
    else:
        recall_fact_score = 0

    if check_constraints_score >= recall_fact_score:
        option_a_family = "check_constraints"
    else:
        option_a_family = "recall_fact"
    option_b_family = "recall_fact" if option_a_family == "check_constraints" else "check_constraints"

    options = [
        {
            "option_id": "A",
            "query_policy_family": option_a_family,
            "allowed_query_intents": list(QUERY_POLICY_FAMILY_ALLOWED_INTENTS[option_a_family]),
            "score": check_constraints_score if option_a_family == "check_constraints" else recall_fact_score,
        },
        {
            "option_id": "B",
            "query_policy_family": option_b_family,
            "allowed_query_intents": list(QUERY_POLICY_FAMILY_ALLOWED_INTENTS[option_b_family]),
            "score": check_constraints_score if option_b_family == "check_constraints" else recall_fact_score,
        },
    ]

    # Phase 3: always use option A
    selected_family = option_a_family
    allowed_intents = QUERY_POLICY_FAMILY_ALLOWED_INTENTS[selected_family]

    return PolicySelectedContext(
        query_policy_family=selected_family,
        allowed_query_intents=allowed_intents,
        option_a_family=option_a_family,
        option_b_family=option_b_family,
        deterministic_option="A",
        ambiguity_pair_type="check_constraints_vs_recall_fact",
    ), options


def _maybe_invoke_resolver(
    *,
    policy_ctx: PolicySelectedContext,
    policy_options: list[dict[str, object]],
    anchor_prefiltered_candidates: list[QueryResultItem],
    query_text: str,
    runtime_context: QueryRuntimeContext | None,
    resolver_config: dict[str, object] | None,
) -> PolicySelectedContext:
    if resolver_config is None:
        return policy_ctx
    if not resolver_config.get("resolver_enabled", True):
        return policy_ctx
    if policy_ctx.ambiguity_pair_type is None:
        return policy_ctx
    if len(policy_options) != 2:
        return policy_ctx

    # Check score delta against ambiguity margin
    score_a = int(policy_options[0].get("score", 0))
    score_b = int(policy_options[1].get("score", 0))
    delta = abs(score_a - score_b)
    margin = AMBIGUITY_MARGIN_LATEST_VS_RESUME if policy_ctx.ambiguity_pair_type == "latest_status_vs_resume_work" else AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL
    if delta > margin:
        return policy_ctx

    from semantic.agent_conversation_memory_resolver import (
        build_resolver_packet,
        resolve_query_ambiguity,
    )

    provider = resolver_config.get("provider")
    if provider is None:
        return policy_ctx

    packet = build_resolver_packet(
        query_text=query_text,
        turn_kind=runtime_context.turn_kind if runtime_context else None,
        ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
        option_a=policy_options[0],
        option_b=policy_options[1],
        candidates=[
            {
                "result_id": getattr(item, "memory_object_id", None) or getattr(item, "source_item_id", None) or "",
                "layer": _result_layer(item),
                "memory_type": item.type if item.result_kind == "memory_hit" else "source_hit",
                "support_score": _policy_candidate_support_estimate(item, _result_layer(item)),
                "summary": str((item.payload or {}).get("summary", item.excerpt or ""))[:200],
            }
            for item in anchor_prefiltered_candidates[:10]
        ],
    )

    timeout_ms = int(resolver_config.get("resolver_timeout_ms", 800))
    prompt_variant = str(resolver_config.get("prompt_variant", "qar_v1_compact_contract"))

    result = resolve_query_ambiguity(
        provider=provider,
        model=None,
        prompt_variant=prompt_variant,
        resolver_packet=packet,
        timeout_ms=timeout_ms,
    )

    # Apply resolver result
    if result.is_valid_selection and result.selected_option_id in {"A", "B"}:
        selected_idx = 0 if result.selected_option_id == "A" else 1
        selected_option = policy_options[selected_idx]
        selected_family = str(selected_option.get("query_policy_family", policy_ctx.query_policy_family))
        allowed = QUERY_POLICY_FAMILY_ALLOWED_INTENTS.get(selected_family)
        if allowed is None:
            allowed = policy_ctx.allowed_query_intents
        return PolicySelectedContext(
            query_policy_family=selected_family,
            allowed_query_intents=allowed,
            resolver_invoked=True,
            resolver_action=result.action,
            resolver_confidence=result.confidence,
            resolver_reason_codes=result.reason_codes,
            option_a_family=policy_ctx.option_a_family,
            option_b_family=policy_ctx.option_b_family,
            deterministic_option=policy_ctx.deterministic_option,
            ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
        )

    # Fallback: keep deterministic option A
    return PolicySelectedContext(
        query_policy_family=policy_ctx.query_policy_family,
        allowed_query_intents=policy_ctx.allowed_query_intents,
        resolver_invoked=True,
        resolver_action="FALLBACK",
        resolver_confidence=result.confidence,
        resolver_reason_codes=result.reason_codes,
        option_a_family=policy_ctx.option_a_family,
        option_b_family=policy_ctx.option_b_family,
        deterministic_option=policy_ctx.deterministic_option,
        ambiguity_pair_type=policy_ctx.ambiguity_pair_type,
    )


def _apply_policy_intent_restriction(
    family_inference: dict[str, object],
    policy_ctx: PolicySelectedContext,
) -> str:
    selected = str(family_inference["selected_family"])
    allowed = policy_ctx.allowed_query_intents
    if allowed is None:
        return selected
    if selected in allowed:
        return selected
    # Override to the highest-scoring allowed intent
    family_scores = family_inference.get("family_scores")
    best_intent = None
    best_score = -1
    for intent in allowed:
        if isinstance(family_scores, dict):
            score_data = family_scores.get(intent)
            score = int(score_data.get("total", 0)) if isinstance(score_data, dict) else 0
        else:
            score = 0
        if score > best_score:
            best_score = score
            best_intent = intent
    return best_intent if best_intent else (next(iter(allowed)) if allowed else selected)


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
    strongly_eligible_count = sum(1 for le in lane_result.eligible_lanes if le.state == "strongly_eligible")
    constraint_is_strong = any(
        le.lane == "constraint_policy" and le.state == "strongly_eligible"
        for le in lane_result.eligible_lanes
    )
    if constraint_is_strong and strongly_eligible_count > 1:
        trace["constraint_safety_override"] = True
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
    content_overlap_tokens = list(candidate["content_overlap_tokens"])
    if content_overlap_tokens:
        entry["content_overlap_terms"] = content_overlap_tokens
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
    strategy_name = candidate["strategy_name"]
    if strategy_name is not None:
        entry["strategy_name"] = strategy_name
    return entry

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
    if _query_is_low_value_greeting_or_noise(query_text):
        return [], {
            "should_inject": False,
            "decision_reason": "low_value_query",
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
        if _source_hit_is_greeting_or_noise_text(excerpt):
            return False, "greeting_or_noise_same_thread_source"
        if _source_hit_looks_like_recall_query(item, query_text):
            return False, "query_like_same_thread_source"
        if item.role == "assistant" and _assistant_source_is_answer_bearing_local_state(excerpt, query_text):
            return True, ""
        if work_usefulness >= 18:
            return True, ""
        if support_grade in {"supported", "strong"} and _text_contains_operational_guidance(excerpt):
            if item.role == "assistant" or _preferred_constraint_text(excerpt):
                return True, ""
        if support_grade in {"supported", "strong"} and len(overlap_tokens) >= 2 and not _source_hit_looks_like_request_or_question(item):
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
        if _preferred_constraint_text(summary_text) or _summary_text_has_durable_state_cue(summary_text):
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
    if item.type in {"decision", "investigation_outcome", "task_checkpoint", "continuity_memory", "pattern_memory", "thread_summary", CONSTRAINT_MEMORY_TYPE}:
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
        return _is_low_value_meta_text(str(item.excerpt or ""))
    if item.type in {"discussion_summary", "thread_summary"}:
        payload = item.payload or {}
        return _is_low_value_meta_text(str(payload.get("summary") or ""))
    return False

def _task_checkpoint_injection_text(payload: dict[str, object]) -> str:
    constraint = _preferred_constraint_text(
        str(payload.get("summary") or ""),
        str(payload.get("current_state") or ""),
        str(payload.get("blocker_state") or ""),
        *[str(value or "") for value in _parse_string_list(payload.get("key_findings"))],
        *[str(value or "") for value in _parse_string_list(payload.get("evidence"))],
    )
    summary = str(payload.get("summary") or "").strip()
    current_state = str(payload.get("current_state") or "").strip()
    blocker = str(payload.get("blocker_state") or "").strip()
    next_step = str(payload.get("next_step") or "").strip()
    parts: list[str] = []
    if constraint:
        parts.append(f"Constraint: {constraint}")
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
    if item.type in {"thread_summary", "discussion_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        constraint = _preferred_constraint_text(summary_text)
        if constraint:
            # Strip any leading "Constraint:" label from summary_text to avoid
            # producing "Constraint: X Constraint: X" when the summary itself
            # already begins with that label.
            clean_summary = re.sub(r"(?i)^constraint\s*:\s*", "", summary_text).strip()
            text_parts = [f"Constraint: {constraint}"]
            if clean_summary and normalize_for_index(clean_summary) != normalize_for_index(constraint):
                text_parts.append(clean_summary)
            block_text = _join_unique_text_parts(text_parts)
        else:
            block_text = summary_text
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary" if item.type == "thread_summary" else "Discussion Summary",
            text=block_text,
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

def _build_sharp_candidate_diagnostics(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    injectable_blocks: list[InjectableBlock],
    decision_reason: str,
    query_text: str,
    debug_candidate_loader=None,
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
        diagnostics[result_id] = {
            "result_id": result_id,
            "candidate_kind": item.type,
            "result_kind": item.result_kind,
            "score": candidate["routing_score"],
            "injection_eligible": _candidate_is_injection_eligible(
                candidate,
                intent="investigative_conclusion",
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=False,
            ),
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
            diagnostics.setdefault(
                result_id,
                {
                    "result_id": result_id,
                    "candidate_kind": item.type,
                    "result_kind": item.result_kind,
                    "score": 0,
                    "injection_eligible": True,
                    "selected_for_injection": False,
                    "loss_stage": "retrieval",
                    "loss_reason_code": "not_retrieved",
                    "loss_reason": "Sharp candidate was in scope but not retrieved lexically.",
                    "retrieved": False,
                    "lexical_rank": None,
                    "routing_rank": None,
                },
            )
    return list(diagnostics.values())

def _candidate_evidence_shape_score(
    item: QueryResultItem,
    *,
    layer: str,
    content_overlap_tokens: list[str],
    query_filters: QueryFilters | None,
) -> int:
    score = len(content_overlap_tokens) * 24
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
        score += 34
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

def _work_resumption_signal_types(item: QueryResultItem) -> tuple[str, ...]:
    signal_types: set[str] = set()
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "").strip()
        signal_type = _classify_work_signal_text(item.artifact_kind, excerpt)
        if signal_type:
            signal_types.add(signal_type)
        if excerpt:
            signal_types.add("evidence")
        return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)

    payload = item.payload or {}
    if item.type == "task_checkpoint":
        if str(payload.get("task") or "").strip():
            signal_types.add("task")
        if str(payload.get("current_state") or "").strip():
            signal_types.add("progress_update")
        if _parse_string_list(payload.get("key_findings")):
            signal_types.add("key_finding")
        if str(payload.get("blocker_state") or "").strip():
            signal_types.add("blocker")
        if str(payload.get("next_step") or "").strip():
            signal_types.add("next_step")
        if _parse_string_list(payload.get("evidence")):
            signal_types.add("evidence")
        if str(payload.get("freshness_signal") or "").strip():
            signal_types.add("freshness")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        signal_types.add("key_finding")
        if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
            signal_types.add("evidence")
    elif item.type in ROUTING_SUMMARY_TYPES:
        if str(payload.get("summary") or "").strip():
            signal_types.add("key_finding")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type == "continuity_memory":
        if str(payload.get("carry_forward_answer") or "").strip():
            signal_types.add("key_finding")
    elif item.type == "pattern_memory" and str(payload.get("summary") or "").strip():
        signal_types.add("key_finding")
    return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)

def _classify_work_signal_text(artifact_kind: str | None, text: str) -> str:
    return _thread_classify_work_signal_text(artifact_kind, text)

def _work_resumption_usefulness_score(item: QueryResultItem, signal_types: tuple[str, ...], *, thin_checkpoint_penalty: int | None = None) -> tuple[int, list[str]]:
    signal_set = set(signal_types)
    reasons: list[str] = []
    score = 0
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        payload = item.payload or {}
        if "task" in signal_set:
            score += 6
        if "progress_update" in signal_set:
            score += 8
        if "key_finding" in signal_set:
            score += 6
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "evidence" in signal_set:
            score += 10
        if "freshness" in signal_set:
            score += 8
        selected_work_artifacts = payload.get("selected_work_artifacts", [])
        artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
        score += min(artifact_count, 3) * 2
        if {"blocker", "next_step", "evidence", "freshness"}.issubset(signal_set) and signal_set.intersection({"progress_update", "key_finding"}):
            score += 10
            reasons.append("sharp_checkpoint")
        if _is_thin_task_checkpoint_payload(payload):
            score -= (thin_checkpoint_penalty if thin_checkpoint_penalty is not None else WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY)
            reasons.append("thin_checkpoint")
        return score, reasons

    if item.result_kind == "source_hit":
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "progress_update" in signal_set:
            score += 8
        if "evidence" in signal_set:
            score += 4
        return score, reasons

    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if "key_finding" in signal_set:
            score += 10
        if "evidence" in signal_set:
            score += 6
        return score, reasons

    if item.type in ROUTING_SUMMARY_TYPES and signal_set.intersection({"blocker", "next_step", "progress_update"}):
        score += 8
    return score, reasons

def _is_thin_task_checkpoint_payload(payload: dict[str, object]) -> bool:
    explicit_core_fields = sum(
        1
        for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
        if str(payload.get(key) or "").strip()
    )
    has_findings = bool(_parse_string_list(payload.get("key_findings")))
    has_evidence = bool(_parse_string_list(payload.get("evidence")))
    has_operational_state = bool(str(payload.get("blocker_state") or "").strip() or str(payload.get("next_step") or "").strip())
    return explicit_core_fields < 3 or not has_operational_state or (not has_findings and not has_evidence)

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
    local_constraint_profile: dict[str, object] | None,
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
            local_constraint_profile=local_constraint_profile,
            selected_lane=selected_lane,
        )
    if intent != "work_resumption":
        return ranked_candidates[:requested_limit], summary or None

    ranked_candidates, summary, _constraint_anchor, constraint_state = _apply_structured_constraint_compatibility(
        ranked_candidates=ranked_candidates,
        packaging_summary=summary,
        local_constraint_profile=local_constraint_profile,
    )
    if not ranked_candidates:
        if constraint_state is not None or summary.get("incompatible_structured_candidates"):
            summary["mode"] = "compatible_work_resumption"
        return [], summary or None
    if summary.get("incompatible_structured_candidates") and not any(candidate["layer"] == "task_checkpoint" for candidate in ranked_candidates):
        summary["mode"] = "compatible_work_resumption"
        return [], summary or None
    top_candidate = ranked_candidates[0]
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
    elif constraint_state is not None or summary.get("incompatible_structured_candidates"):
        summary["mode"] = "compatible_work_resumption"
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
    local_constraint_profile: dict[str, object] | None,
    selected_lane: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    compatible_candidates, packaging_summary, constraint_anchor, constraint_state = _apply_structured_constraint_compatibility(
        ranked_candidates=ranked_candidates,
        packaging_summary=packaging_summary,
        local_constraint_profile=local_constraint_profile,
    )
    if not compatible_candidates:
        if constraint_state is not None or packaging_summary.get("incompatible_structured_candidates"):
            packaging_summary["mode"] = "compatible_structured_recall"
        return [], packaging_summary or None

    explicit_constraint_focus = "constraint_recall" in query_shape_tags or selected_lane == "constraint_policy"
    if explicit_constraint_focus and constraint_anchor is not None and constraint_anchor in compatible_candidates:
        primary_candidate = constraint_anchor
    else:
        primary_candidate = compatible_candidates[0]

    selected_candidates = [primary_candidate]
    used_result_ids = {_routing_result_id(primary_candidate["item"])}
    primary_topic_tokens = set(primary_candidate.get("topic_overlap_tokens") or [])
    strict_primary_topic_filter = bool(primary_topic_tokens)
    primary_aligns_with_active_constraint = _candidate_aligns_with_constraint_state(primary_candidate, constraint_state)
    if constraint_anchor is not None and constraint_anchor in compatible_candidates:
        anchor_result_id = _routing_result_id(constraint_anchor["item"])
        anchor_topic_tokens = set(constraint_anchor.get("topic_overlap_tokens") or [])
        if (
            anchor_result_id not in used_result_ids
            and len(selected_candidates) < requested_limit
            and (
                explicit_constraint_focus
                or not strict_primary_topic_filter
                or primary_topic_tokens.intersection(anchor_topic_tokens)
            )
        ):
            selected_candidates.append(constraint_anchor)
            used_result_ids.add(anchor_result_id)

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
            candidate_topic_tokens = set(candidate.get("topic_overlap_tokens") or [])
            if strict_primary_topic_filter and not primary_topic_tokens.intersection(candidate_topic_tokens):
                if not (
                    primary_aligns_with_active_constraint
                    and _candidate_aligns_with_constraint_state(candidate, constraint_state)
                ):
                    continue
            if (
                primary_topic_tokens
                and not candidate_topic_tokens.intersection(primary_topic_tokens)
                and str(candidate.get("layer")) in {"continuity_memory", "pattern_memory", "thread_summary", "discussion_summary"}
            ):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
        if len(selected_candidates) >= requested_limit:
            break

    if packaging_summary.get("incompatible_structured_candidates"):
        packaging_summary["mode"] = "compatible_structured_recall"
    elif constraint_state is not None:
        packaging_summary["mode"] = "compatible_structured_recall"
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

def _candidate_freshness_timestamp(item: QueryResultItem) -> datetime | None:
    timestamps: list[datetime] = []
    if item.freshness_at is not None:
        timestamps.append(_normalize_timestamp(item.freshness_at))
    if item.occurred_at is not None:
        timestamps.append(_normalize_timestamp(item.occurred_at))
    if item.payload:
        payload_timestamp = _parse_iso_timestamp(item.payload.get("latest_occurred_at"))
        if payload_timestamp is not None:
            timestamps.append(payload_timestamp)
    for evidence in item.evidence:
        if evidence.occurred_at is not None:
            timestamps.append(_normalize_timestamp(evidence.occurred_at))
    if not timestamps:
        return None
    return max(timestamps)

def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _parse_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_timestamp(parsed)

def _routing_support_grade(support_score: int, *, support_threshold: dict[str, int] | None = None) -> str:
    _threshold = support_threshold or ROUTING_SUPPORT_THRESHOLD
    if support_score >= _threshold["strong"]:
        return "strong"
    if support_score >= _threshold["supported"]:
        return "supported"
    return "weak"

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

def _candidate_matches_thread(item: QueryResultItem, query_filters: QueryFilters | None) -> bool:
    if query_filters is None or not query_filters.thread_ref:
        return False
    candidate_thread_refs = {thread_ref for thread_ref in _candidate_thread_refs(item) if thread_ref}
    return query_filters.thread_ref in candidate_thread_refs

def _candidate_matches_container(item: QueryResultItem, query_filters: QueryFilters | None) -> bool:
    if query_filters is None or not query_filters.container_ref:
        return False
    candidate_container_refs = {container_ref for container_ref in _candidate_container_refs(item) if container_ref}
    return query_filters.container_ref in candidate_container_refs

def _candidate_thread_refs(item: QueryResultItem) -> tuple[str, ...]:
    refs: list[str] = []
    if item.thread_ref:
        refs.append(item.thread_ref)
    refs.extend(evidence.thread_ref for evidence in item.evidence if evidence.thread_ref)
    return tuple(dict.fromkeys(refs))

def _candidate_container_refs(item: QueryResultItem) -> tuple[str, ...]:
    refs: list[str] = []
    if item.container_ref:
        refs.append(item.container_ref)
    refs.extend(evidence.container_ref for evidence in item.evidence if evidence.container_ref)
    return tuple(dict.fromkeys(refs))
