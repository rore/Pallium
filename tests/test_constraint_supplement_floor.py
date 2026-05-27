"""Tests for B-extended: constraint supplement gating.

Covers:
- candidate_injection_eligible blocks lex=None vec=X candidates from supplement.
- routing_rank > _CONSTRAINT_SUPPLEMENT_RANK_FLOOR blocks the candidate.
- Already-selected candidates are skipped.
- High-rank, well-scored constraints still pass.
- HIGH_VALUE_MEMORY_TYPES now includes constraint_memory.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.models import QueryResultItem
from semantic.agent_conversation_memory_routing_constants import _routing_result_id
from semantic.agent_conversation_memory_routing_injection import (
    HIGH_VALUE_MEMORY_TYPES,
)
from semantic.agent_conversation_memory_routing_selection import (
    _CONSTRAINT_SUPPLEMENT_RANK_FLOOR,
    _find_constraint_supplements,
)


def _constraint_item(moid: str = "c1") -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id=moid,
        type="constraint_memory",
        payload={"constraint_text": f"constraint {moid}"},
        score=100,
        evidence=[],
        freshness_at=datetime.now(timezone.utc),
    )


def _candidate(
    *,
    moid: str = "c1",
    rank: int | None = 1,
    lexical_score: float | None = 20.0,
    vector_score: int | None = 850,
    suppression: str | None = None,
) -> dict:
    return {
        "item": _constraint_item(moid),
        "routing_rank": rank,
        "routing_score": 300,
        "retrieval_score": 0.5,
        "lexical_score": lexical_score,
        "vector_score": vector_score,
        "suppression_reason_code": suppression,
    }


def test_constraint_memory_in_high_value_set() -> None:
    assert "constraint_memory" in HIGH_VALUE_MEMORY_TYPES


def test_well_scored_top_rank_constraint_passes() -> None:
    cand = _candidate(rank=1, lexical_score=20.0, vector_score=850)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert len(out) == 1


def test_eligibility_blocks_lex_none_vec_only_constraint() -> None:
    # raw_lex=None fails the primary BM25 floor in candidate_injection_eligible.
    # This is the 8f08b05b-pattern bypass that B closes.
    cand = _candidate(rank=1, lexical_score=None, vector_score=900)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_eligibility_blocks_low_bm25_constraint() -> None:
    # raw_lex=8 < min_raw_lexical_bm25 (12.0) is rejected.
    cand = _candidate(rank=1, lexical_score=8.0, vector_score=None)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_rank_floor_blocks_candidate_beyond_top_n() -> None:
    cand = _candidate(rank=_CONSTRAINT_SUPPLEMENT_RANK_FLOOR + 1, lexical_score=20.0, vector_score=850)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_rank_floor_passes_candidate_at_boundary() -> None:
    cand = _candidate(rank=_CONSTRAINT_SUPPLEMENT_RANK_FLOOR, lexical_score=20.0, vector_score=850)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert len(out) == 1


def test_missing_routing_rank_is_blocked() -> None:
    cand = _candidate(rank=None, lexical_score=20.0, vector_score=850)
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_already_selected_excluded_before_rank_check() -> None:
    cand = _candidate(moid="c1", rank=2, lexical_score=20.0, vector_score=850)
    selected_id = _routing_result_id(cand["item"])
    assert selected_id, "result_id must be non-empty for the already_selected branch to be testable"
    out = _find_constraint_supplements(
        [cand], already_selected_ids={selected_id}
    )
    assert out == []


def test_suppressed_candidate_excluded() -> None:
    cand = _candidate(rank=1, lexical_score=20.0, vector_score=850, suppression="some-reason")
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_freshness_old_constraint_excluded() -> None:
    item = _constraint_item("c-old")
    object.__setattr__(item, "freshness_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    cand = {
        "item": item,
        "routing_rank": 1,
        "routing_score": 300,
        "retrieval_score": 0.5,
        "lexical_score": 20.0,
        "vector_score": 850,
        "suppression_reason_code": None,
    }
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []


def test_max_count_caps_returned_supplements() -> None:
    candidates = [
        _candidate(moid=f"c{i}", rank=i, lexical_score=20.0, vector_score=850)
        for i in range(1, 5)
    ]
    out = _find_constraint_supplements(candidates, already_selected_ids=set(), max_count=1)
    assert len(out) == 1


def test_freshness_ordered_most_recent_first() -> None:
    now = datetime.now(timezone.utc)
    older = _constraint_item("older")
    object.__setattr__(older, "freshness_at", now - timedelta(days=12))
    newer = _constraint_item("newer")
    object.__setattr__(newer, "freshness_at", now - timedelta(days=5))
    cands = [
        {
            "item": older, "routing_rank": 1, "routing_score": 300,
            "retrieval_score": 0.5, "lexical_score": 20.0, "vector_score": 850,
            "suppression_reason_code": None,
        },
        {
            "item": newer, "routing_rank": 2, "routing_score": 290,
            "retrieval_score": 0.5, "lexical_score": 20.0, "vector_score": 850,
            "suppression_reason_code": None,
        },
    ]
    out = _find_constraint_supplements(cands, already_selected_ids=set(), max_count=2)
    assert [c["item"].memory_object_id for c in out] == ["newer", "older"]


def test_non_constraint_candidates_ignored() -> None:
    item = QueryResultItem(
        result_kind="memory_hit", memory_object_id="d1", type="decision",
        payload={}, score=100, evidence=[],
        freshness_at=datetime.now(timezone.utc),
    )
    cand = {
        "item": item, "routing_rank": 1, "routing_score": 300,
        "retrieval_score": 0.5, "lexical_score": 20.0, "vector_score": 850,
        "suppression_reason_code": None,
    }
    out = _find_constraint_supplements([cand], already_selected_ids=set())
    assert out == []
