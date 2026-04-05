from __future__ import annotations

import pytest

from semantic.agent_conversation_memory_routing_selection import (
    _select_compatible_recall_candidates,
    MIN_SOURCE_HIT_SLOTS,
)
from core.models import QueryResultItem


def _make_candidate(result_kind: str, score: int, layer: str = "atomic_fact") -> dict:
    """Helper to build a routing candidate dict for testing."""
    if result_kind == "memory_hit":
        item = QueryResultItem(
            result_kind="memory_hit",
            result_id=f"mem-{score}-{id(object())}",
            memory_object_id=f"mo-{score}",
            type="atomic_fact",
            payload={"statement": f"fact {score}"},
            score=score,
            evidence=[],
        )
    else:
        item = QueryResultItem(
            result_kind="source_hit",
            result_id=f"src-{score}-{id(object())}",
            source_item_id=f"si-{score}",
            source_type="chat",
            source_id=f"s-{score}",
            excerpt=f"source content {score}",
            score=score,
            evidence=[],
        )
    return {
        "item": item,
        "layer": layer,
        "retrieval_score": score,
        "routing_score": score,
    }


def test_recall_reserves_source_hit_slots():
    """When both memory_hits and source_hits exist, source_hits get reserved slots."""
    candidates = (
        [_make_candidate("memory_hit", 100 - i) for i in range(8)]
        + [_make_candidate("source_hit", 80 - i, layer="source_evidence") for i in range(4)]
    )
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=10,
        query_shape_tags=[],
        packaging_summary={},
    )
    source_count = sum(1 for c in selected if c["item"].result_kind == "source_hit")
    assert source_count >= MIN_SOURCE_HIT_SLOTS


def test_recall_source_reservation_respects_score_floor():
    """Source hits below 50% of primary score should not be included despite reservation."""
    candidates = (
        [_make_candidate("memory_hit", 100)]
        + [_make_candidate("source_hit", 10, layer="source_evidence")]
    )
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=10,
        query_shape_tags=[],
        packaging_summary={},
    )
    source_count = sum(1 for c in selected if c["item"].result_kind == "source_hit")
    assert source_count == 0


def test_recall_no_source_hits_fills_with_structured():
    """When no source hits exist, all slots go to structured."""
    candidates = [_make_candidate("memory_hit", 100 - i) for i in range(8)]
    selected, _ = _select_compatible_recall_candidates(
        ranked_candidates=candidates,
        requested_limit=5,
        query_shape_tags=[],
        packaging_summary={},
    )
    assert len(selected) == 5
    assert all(c["item"].result_kind == "memory_hit" for c in selected)
