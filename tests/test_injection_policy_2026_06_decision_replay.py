"""Tests for evals/injection_policy_2026_06/decision_replay.py.

Pure compute layer only; live-DB headline numbers belong in the
committed decision_replay_2026-06-27.json, not in tests.
"""

from __future__ import annotations

import json

import pytest

from evals.injection_policy_2026_06.decision_replay import (
    CandidateRecord,
    PHASE1_DERIVED_THRESHOLDS,
    ReplayVariant,
    SCORE_FIELD,
    SPEC_HEADLINE_THRESHOLDS,
    TOP_K_CAP,
    build_replay_report,
    parse_candidates,
    parse_injected_ids,
    rating_for,
    run_variant,
    simulate_variant_for_query,
    variant_precision,
)
from evals.retrieval_ablation.evaluate import FeedbackEntry


def _variant_spec() -> ReplayVariant:
    return ReplayVariant(
        name="spec_headline",
        thresholds=dict(SPEC_HEADLINE_THRESHOLDS),
        top_k_cap=TOP_K_CAP,
    )


def _candidate(
    *,
    mid: str,
    mtype: str,
    score: float | None,
    injected: bool = False,
) -> CandidateRecord:
    return CandidateRecord(
        memory_object_id=mid, memory_type=mtype, score=score, injected_in_prod=injected,
    )


# ---------------------------------------------------------------------------
# Score field constant
# ---------------------------------------------------------------------------


def test_score_field_locked_to_routing_score() -> None:
    """Phase 2a uses routing_score because historical rows lack result `score`."""
    assert SCORE_FIELD == "routing_score"


def test_proposed_policy_constants_match_spec() -> None:
    assert SPEC_HEADLINE_THRESHOLDS == {
        "constraint_memory": 20.0, "decision": 22.0, "task_checkpoint": 14.0,
    }
    # Phase 1 derived includes investigation_outcome (which the spec headline does not).
    assert PHASE1_DERIVED_THRESHOLDS == {
        "constraint_memory": 12.0, "decision": 19.0,
        "investigation_outcome": 23.0, "task_checkpoint": 13.0,
    }


# ---------------------------------------------------------------------------
# parse_candidates
# ---------------------------------------------------------------------------


def test_parse_candidates_extracts_routing_score() -> None:
    blob = json.dumps([
        {"memory_object_id": "m1", "memory_type": "decision", "routing_score": 22.5},
        {"memory_object_id": "m2", "memory_type": "constraint_memory", "routing_score": 15.0},
    ])
    recs, no_score = parse_candidates(blob, frozenset({"m1"}))
    assert len(recs) == 2
    assert no_score == 0
    rec1 = next(r for r in recs if r.memory_object_id == "m1")
    assert rec1.score == 22.5
    assert rec1.injected_in_prod is True
    rec2 = next(r for r in recs if r.memory_object_id == "m2")
    assert rec2.injected_in_prod is False


def test_parse_candidates_handles_none_score() -> None:
    blob = json.dumps([
        {"memory_object_id": "m1", "memory_type": "decision", "routing_score": None},
    ])
    recs, no_score = parse_candidates(blob, frozenset())
    assert recs == []
    assert no_score == 1


def test_parse_candidates_handles_missing_score_field() -> None:
    blob = json.dumps([
        {"memory_object_id": "m1", "memory_type": "decision"},
    ])
    recs, no_score = parse_candidates(blob, frozenset())
    assert recs == []
    assert no_score == 1


def test_parse_candidates_corrupt_json_returns_empty() -> None:
    recs, no_score = parse_candidates("not-json", frozenset())
    assert recs == []
    assert no_score == 0


def test_parse_candidates_empty_blob_returns_empty() -> None:
    recs, no_score = parse_candidates(None, frozenset())
    assert recs == []
    assert no_score == 0
    recs, no_score = parse_candidates("", frozenset())
    assert recs == []


def test_parse_injected_ids_extracts_ids() -> None:
    blob = json.dumps([
        {"memory_object_id": "m1"},
        {"memory_object_id": "m2"},
    ])
    ids = parse_injected_ids(blob)
    assert ids == frozenset({"m1", "m2"})


# ---------------------------------------------------------------------------
# simulate_variant_for_query — type allowlist, threshold, top-K
# ---------------------------------------------------------------------------


def test_simulate_drops_types_not_in_allowlist() -> None:
    variant = ReplayVariant(name="v", thresholds={"decision": 22.0})
    cands = [
        _candidate(mid="m1", mtype="decision", score=23),
        _candidate(mid="m2", mtype="thread_summary", score=99),  # not in allowlist
    ]
    kept = simulate_variant_for_query(cands, variant)
    assert [c.memory_object_id for c in kept] == ["m1"]


def test_simulate_drops_below_threshold() -> None:
    variant = ReplayVariant(name="v", thresholds={"decision": 22.0})
    cands = [
        _candidate(mid="m1", mtype="decision", score=21.99),
        _candidate(mid="m2", mtype="decision", score=22.00),
        _candidate(mid="m3", mtype="decision", score=22.01),
    ]
    kept = simulate_variant_for_query(cands, variant)
    kept_ids = {c.memory_object_id for c in kept}
    assert kept_ids == {"m2", "m3"}  # boundary >= keeps 22.00


def test_simulate_drops_none_score() -> None:
    variant = ReplayVariant(name="v", thresholds={"decision": 22.0})
    cands = [_candidate(mid="m1", mtype="decision", score=None)]
    kept = simulate_variant_for_query(cands, variant)
    assert kept == []


def test_simulate_topk_cap_applied() -> None:
    variant = ReplayVariant(name="v", thresholds={"decision": 0.0}, top_k_cap=3)
    cands = [
        _candidate(mid=f"m{i}", mtype="decision", score=float(10 - i))
        for i in range(6)
    ]
    kept = simulate_variant_for_query(cands, variant)
    assert len(kept) == 3
    # Highest scores survive
    assert {c.memory_object_id for c in kept} == {"m0", "m1", "m2"}


def test_simulate_deterministic_tie_break_by_memory_id() -> None:
    variant = ReplayVariant(name="v", thresholds={"decision": 0.0}, top_k_cap=2)
    cands = [
        _candidate(mid="m_b", mtype="decision", score=10.0),
        _candidate(mid="m_a", mtype="decision", score=10.0),  # same score
        _candidate(mid="m_c", mtype="decision", score=5.0),
    ]
    kept = simulate_variant_for_query(cands, variant)
    # Top-2: both score-10 candidates. m_a sorts before m_b (ASC tie-break).
    assert [c.memory_object_id for c in kept] == ["m_a", "m_b"]


# ---------------------------------------------------------------------------
# rating_for / variant evaluation
# ---------------------------------------------------------------------------


def test_rating_for_uses_majority() -> None:
    index = {
        ("m1", "q1"): [
            FeedbackEntry("m1", "relevant", "", "decision"),
            FeedbackEntry("m1", "relevant", "", "decision"),
            FeedbackEntry("m1", "not_relevant", "", "decision"),
        ],
    }
    assert rating_for("m1", "q1", index) == "relevant"


def test_rating_for_returns_none_when_no_feedback() -> None:
    assert rating_for("m1", "q1", {}) is None


def test_run_variant_counts_rated_kept() -> None:
    audit_rows = [
        {
            "query_audit_log_id": "q1",
            "audit_created_at": "2026-06-27T00:00:00",
            "audit_container_ref": "c",
            "candidate_scores_json": json.dumps([
                {"memory_object_id": "m_rel", "memory_type": "decision",
                 "routing_score": 22.5},
                {"memory_object_id": "m_bad", "memory_type": "decision",
                 "routing_score": 22.5},
                {"memory_object_id": "m_below", "memory_type": "decision",
                 "routing_score": 10.0},
            ]),
            "injected_blocks_json": json.dumps([
                {"memory_object_id": "m_rel"},
            ]),
        },
    ]
    feedback_index = {
        ("m_rel", "q1"): [FeedbackEntry("m_rel", "relevant", "", "decision")],
        ("m_bad", "q1"): [FeedbackEntry("m_bad", "not_relevant", "", "decision")],
    }
    variant = _variant_spec()
    totals, diag = run_variant(audit_rows, feedback_index, variant)
    assert totals.queries_evaluated == 1
    assert totals.candidates_total == 3
    assert totals.candidates_passed == 2
    assert totals.candidates_kept_after_topk == 2
    assert totals.rated_relevant == 1
    assert totals.rated_not_relevant == 1
    assert totals.rated_unknown == 0
    # m_bad was kept by sim but not injected in prod → substitution
    assert totals.substituted_in == 1
    assert any(d["substituted_memory_object_id"] == "m_bad" for d in diag)


def test_run_variant_records_prod_dropped() -> None:
    """If prod injected m_x but our sim doesn't keep it, it's a prod-drop event."""
    audit_rows = [
        {
            "query_audit_log_id": "q1",
            "audit_created_at": "2026-06-27T00:00:00",
            "audit_container_ref": "c",
            "candidate_scores_json": json.dumps([
                {"memory_object_id": "m_x", "memory_type": "decision",
                 "routing_score": 10.0},  # below 22.0 threshold
            ]),
            "injected_blocks_json": json.dumps([
                {"memory_object_id": "m_x"},
            ]),
        },
    ]
    variant = _variant_spec()
    totals, _ = run_variant(audit_rows, {}, variant)
    assert totals.candidates_kept_after_topk == 0
    assert totals.prod_dropped_by_sim == 1


def test_run_variant_zero_when_no_candidates() -> None:
    audit_rows = [{
        "query_audit_log_id": "q1",
        "audit_created_at": "2026-06-27T00:00:00",
        "audit_container_ref": "c",
        "candidate_scores_json": "[]",
        "injected_blocks_json": "[]",
    }]
    variant = _variant_spec()
    totals, _ = run_variant(audit_rows, {}, variant)
    assert totals.queries_evaluated == 0
    assert totals.candidates_total == 0


def test_variant_precision_handles_unrated_kept_set() -> None:
    from evals.injection_policy_2026_06.decision_replay import VariantTotals
    t = VariantTotals(rated_relevant=0, rated_not_relevant=0)
    assert variant_precision(t) is None
    t = VariantTotals(rated_relevant=3, rated_not_relevant=1)
    assert variant_precision(t) == 0.75


# ---------------------------------------------------------------------------
# Variant comparison — sanity check that spec_headline vs phase1_derived disagree
# ---------------------------------------------------------------------------


def test_variants_disagree_on_borderline_score() -> None:
    """A decision-type candidate at score 20.0 fails spec_headline (>=22)
    but passes phase1_derived (>=19).
    """
    audit_rows = [{
        "query_audit_log_id": "q1",
        "audit_created_at": "2026-06-27T00:00:00",
        "audit_container_ref": "c",
        "candidate_scores_json": json.dumps([
            {"memory_object_id": "m1", "memory_type": "decision",
             "routing_score": 20.0},
        ]),
        "injected_blocks_json": "[]",
    }]
    v_spec = ReplayVariant(name="spec_headline", thresholds=dict(SPEC_HEADLINE_THRESHOLDS))
    v_p1 = ReplayVariant(name="phase1_derived", thresholds=dict(PHASE1_DERIVED_THRESHOLDS))
    spec_totals, _ = run_variant(audit_rows, {}, v_spec)
    p1_totals, _ = run_variant(audit_rows, {}, v_p1)
    assert spec_totals.candidates_kept_after_topk == 0
    assert p1_totals.candidates_kept_after_topk == 1


# ---------------------------------------------------------------------------
# build_replay_report — smoke
# ---------------------------------------------------------------------------


def test_build_replay_report_smoke() -> None:
    audit_rows = [{
        "query_audit_log_id": "q1",
        "audit_created_at": "2026-06-27T00:00:00",
        "audit_container_ref": "c",
        "candidate_scores_json": json.dumps([
            {"memory_object_id": "m1", "memory_type": "decision",
             "routing_score": 22.5},
        ]),
        "injected_blocks_json": "[]",
    }]
    variants = [
        ReplayVariant(name="spec_headline", thresholds=dict(SPEC_HEADLINE_THRESHOLDS)),
        ReplayVariant(name="phase1_derived", thresholds=dict(PHASE1_DERIVED_THRESHOLDS)),
    ]
    report = build_replay_report(audit_rows, {}, variants)
    assert report["phase"].startswith("2a")
    assert report["score_field_used"] == SCORE_FIELD
    assert "score_field_caveat" in report
    assert "framing" in report
    assert set(report["variants"].keys()) == {"spec_headline", "phase1_derived"}
    assert report["variants"]["spec_headline"]["totals"]["queries_evaluated"] == 1
