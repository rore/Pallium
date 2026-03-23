from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, TypedDict

from core.models import QueryFilters, QueryResultItem
from semantic.common import normalize_for_index
from semantic.agent_conversation_memory_constraints import (
    CONSTRAINT_MEMORY_TYPE,
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

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
    evidence_request: bool = False
    source: str = "structural"
    confidence: str = "low"
    semantic_classification_used: bool = False
    derivation_signals: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTING_POLICY_NAME = "agent_conversation_memory.intent_routing.v4"

PASSTHROUGH_POLICY = PolicySelectedContext(query_policy_family="passthrough", allowed_query_intents=None)

ROUTING_HIGHER_LEVEL_TYPES = {"pattern_memory", "continuity_memory", "task_checkpoint", "interest", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE}

ROUTING_LOWER_LEVEL_EXACT_TYPES = {"decision", "investigation_outcome"}

ROUTING_SUMMARY_TYPES = {"thread_summary", "discussion_summary"}

ROUTING_PREFERRED_LAYERS = {
    "answer_continuity": ("continuity_memory", "investigation_outcome", "decision", "source_evidence", "task_checkpoint", "pattern_memory", "interest", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "broad_recall": ("pattern_memory", "investigation_outcome", "decision", "continuity_memory", "task_checkpoint", "source_evidence", "interest", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "work_resumption": ("task_checkpoint", "source_evidence", "investigation_outcome", "decision", "continuity_memory", "pattern_memory", "interest", "thread_summary", "discussion_summary", CONSTRAINT_MEMORY_TYPE),
    "precise_fact": ("decision", "investigation_outcome", "source_evidence", "interest", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory", CONSTRAINT_MEMORY_TYPE),
    "evidence_trace": ("source_evidence", "investigation_outcome", "decision", "interest", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory"),
    "investigative_conclusion": ("investigation_outcome", "decision", "source_evidence", "interest", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory", CONSTRAINT_MEMORY_TYPE),
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
    "answer_continuity": {"continuity_memory": 400, CONSTRAINT_MEMORY_TYPE: 360, "investigation_outcome": 320, "decision": 300, "source_evidence": 200, "task_checkpoint": 140, "pattern_memory": 120, "interest": 100, "thread_summary": 100, "discussion_summary": 70, "lower_level_memory": 260},
    "broad_recall": {CONSTRAINT_MEMORY_TYPE: 430, "pattern_memory": 400, "investigation_outcome": 330, "decision": 310, "continuity_memory": 180, "task_checkpoint": 150, "source_evidence": 120, "interest": 110, "thread_summary": 130, "discussion_summary": 80, "lower_level_memory": 250},
    "work_resumption": {CONSTRAINT_MEMORY_TYPE: 490, "task_checkpoint": 470, "source_evidence": 390, "investigation_outcome": 300, "decision": 290, "continuity_memory": 180, "pattern_memory": 70, "interest": 100, "thread_summary": 130, "discussion_summary": 70, "lower_level_memory": 250},
    "precise_fact": {"decision": 440, "investigation_outcome": 430, CONSTRAINT_MEMORY_TYPE: 260, "source_evidence": 320, "interest": 90, "thread_summary": 110, "discussion_summary": 70, "continuity_memory": 140, "task_checkpoint": 110, "pattern_memory": 60, "lower_level_memory": 340},
    "evidence_trace": {"source_evidence": 460, "investigation_outcome": 380, "decision": 360, CONSTRAINT_MEMORY_TYPE: 110, "interest": 85, "thread_summary": 120, "discussion_summary": 80, "continuity_memory": 120, "task_checkpoint": 90, "pattern_memory": 40, "lower_level_memory": 300},
    "investigative_conclusion": {"investigation_outcome": 480, "decision": 430, CONSTRAINT_MEMORY_TYPE: 220, "source_evidence": 360, "interest": 110, "thread_summary": 220, "discussion_summary": 120, "continuity_memory": 110, "task_checkpoint": 100, "pattern_memory": 80, "lower_level_memory": 320},
}


HIGHER_LEVEL_RETRIEVAL_FLOOR = 40

INJECTION_RETRIEVAL_RELEVANCE_FLOOR = 2

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
}
LATEST_STATUS_COLLAPSED_INTENTS = frozenset({"broad_recall"})
POLICY_WORK_STATE_USEFULNESS_THRESHOLD = 24
POLICY_SUPPORT_THRESHOLD = ROUTING_SUPPORT_THRESHOLD["supported"]
AMBIGUITY_MARGIN_LATEST_VS_RESUME = 12
AMBIGUITY_MARGIN_CONSTRAINTS_VS_RECALL = 10

# Lane narrowing constants
LANE_INTENT_MAPPING: dict[str, str] = {
    "work_resumption": "work_resumption",
    "evidence_trace": "evidence_trace",
}

LANE_POLICY_FAMILY_MAPPING: dict[str, str] = {
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


ROUTING_FALLBACK_MARGIN = 35

ROUTING_FOCUS_BOOST = 120

ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY = 90


SHARP_DIAGNOSTIC_MEMORY_TYPES = {"task_checkpoint", "investigation_outcome", "decision"}

WORK_RESUMPTION_SIGNAL_TYPES = ("task", "progress_update", "key_finding", "blocker", "next_step", "evidence", "freshness")

WORK_RESUMPTION_SHARP_CHECKPOINT_THRESHOLD = 44  # defined but not yet wired to a scoring gate; excluded from RoutingOverrides until a call site exists

WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY = 70

WORK_RESUMPTION_STALE_STATE_PENALTY = 55

WORK_RESUMPTION_STALE_SOURCE_PENALTY = 28

WORK_RESUMPTION_FRESH_STATE_BONUS = 18

WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS = 2700

WORK_RESUMPTION_SIGNAL_PRIORITY = ("blocker", "next_step", "progress_update")

ROUTING_FAMILY_INFERENCE_PRIORITY = (
    "work_resumption",
    "evidence_trace",
    "investigative_conclusion",
    "answer_continuity",
    "broad_recall",
    "precise_fact",
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _routing_result_id(item: QueryResultItem) -> str:
    return str(item.result_id)

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
    if item.type == "interest":
        return "interest"
    if item.type == "discussion_summary":
        return "discussion_summary"
    if item.type == "investigation_outcome":
        return "investigation_outcome"
    if item.type == "decision":
        return "decision"
    return "lower_level_memory"

def _routing_query_tokens(text: str) -> tuple[str, ...]:
    normalized = normalize_for_index(text)
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)

def _routing_support_grade(support_score: int, *, support_threshold: dict[str, int] | None = None) -> str:
    _threshold = support_threshold or ROUTING_SUPPORT_THRESHOLD
    if support_score >= _threshold["strong"]:
        return "strong"
    if support_score >= _threshold["supported"]:
        return "supported"
    return "weak"

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

def is_query_topic_signal_empty(query_tokens: Iterable[str]) -> bool:
    """Return True — topic signal classification removed (cue-free control plane)."""
    return True
