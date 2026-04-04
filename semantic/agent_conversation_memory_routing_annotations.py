"""Pre-computation annotations for multi-candidate scoring.

These run once over all candidates BEFORE per-candidate scoring.
They add annotation fields to candidate dicts that the scoring formula reads.
"""
from __future__ import annotations

from datetime import datetime

from semantic.agent_conversation_memory_routing_constants import (
    ROUTING_SUPPORT_THRESHOLD,
    WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS,
)

STRUCTURED_LAYERS = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "pattern_memory", "continuity_memory", "interest", "constraint_memory",
    "thread_summary", "discussion_summary",
})


def _ts_value(c: dict) -> float:
    """Extract timestamp as float from candidate dict."""
    v = c.get("freshness_timestamp_value")
    if isinstance(v, datetime):
        return v.timestamp()
    return float(v or 0)


def annotate_freshness_ranks(scored_candidates: list[dict]) -> None:
    """Assign freshness_rank_in_type (1=freshest) to each candidate.

    Groups by layer, sorts by timestamp descending, assigns rank starting at 1.
    """
    by_type: dict[str, list[dict]] = {}
    for c in scored_candidates:
        by_type.setdefault(c.get("layer", ""), []).append(c)
    for type_candidates in by_type.values():
        sorted_by_time = sorted(type_candidates, key=_ts_value, reverse=True)
        for rank, c in enumerate(sorted_by_time, start=1):
            c["freshness_rank_in_type"] = rank


def compute_structured_support_ratio(scored_candidates: list[dict]) -> dict:
    """Compute whether structured candidates dominate source hits.

    Returns {"structured_dominates": bool, "structured_supported_count": int,
             "source_count": int}.
    Used by _fresh_session_component to decide whether to prefer structured
    memory over source hits in fresh sessions.
    """
    structured_supported = 0
    source_count = 0
    supported_threshold = ROUTING_SUPPORT_THRESHOLD["supported"]
    for c in scored_candidates:
        layer = c.get("layer", "")
        if layer in STRUCTURED_LAYERS:
            if (c.get("support_score", 0) or 0) >= supported_threshold:
                structured_supported += 1
        elif layer == "source_evidence":
            source_count += 1
    return {
        "structured_dominates": structured_supported > 0 and structured_supported >= source_count,
        "structured_supported_count": structured_supported,
        "source_count": source_count,
    }


def annotate_work_resumption_context(
    scored_candidates: list[dict],
    *,
    query_filters=None,
) -> None:
    """Annotate checkpoint candidates with staleness relative to the freshest.

    Sets 'work_resumption_stale' (bool) on each task_checkpoint candidate.
    A checkpoint is stale if it's older than FRESHNESS_MARGIN_SECONDS relative
    to the freshest checkpoint in the same locality.
    """
    checkpoints = [c for c in scored_candidates if c.get("layer") == "task_checkpoint"]
    if not checkpoints:
        return
    # Prefer checkpoints in same container for reference timestamp
    local_checkpoints = [c for c in checkpoints if c.get("same_container", False)]
    if not local_checkpoints:
        local_checkpoints = checkpoints
    reference_ts = max(_ts_value(c) for c in local_checkpoints)
    margin = WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS
    for c in checkpoints:
        c["work_resumption_stale"] = (reference_ts - _ts_value(c)) > margin
