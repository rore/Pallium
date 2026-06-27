"""Tests for evals/injection_policy_2026_06/holdout.py pure compute layer.

See: docs/specs/2026-06-27-injection-policy-abstention.md
"""

from __future__ import annotations

import pytest

from evals.injection_policy_2026_06.analyze import InjectionRecord
from evals.injection_policy_2026_06.holdout import (
    InjectionEvent,
    MIN_HOLDOUT_KEPT,
    MIN_TRAIN_KEPT_RELEVANT,
    assemble_dispositions,
    assemble_recommended_policy,
    chronological_split,
    dedup_from_rows,
    derive_thresholds_with_min_kept,
    evaluate_on_holdout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    *,
    rating: str,
    memory_object_id: str,
    query_audit_log_id: str,
    memory_type: str = "decision",
    container_ref: str = "git:test",
    block_score: float | None = 22.0,
    routing_score: float | None = 10.0,
    created_at: str = "2026-06-27T00:00:00",
    feedback_id: str | None = None,
) -> dict:
    """Build a joined row shaped like load_joined_rows output."""
    import json as _json

    blocks = []
    if block_score is not None:
        blocks.append({
            "memory_object_id": memory_object_id,
            "memory_type": memory_type,
            "score": block_score,
            "retrieval_source": "vector",
        })
    candidates = []
    if routing_score is not None:
        candidates.append({
            "memory_object_id": memory_object_id,
            "memory_type": memory_type,
            "routing_score": routing_score,
            "lexical_score": None,
            "vector_score": None,
        })
    return {
        "feedback_id": feedback_id or f"fb-{memory_object_id}-{query_audit_log_id}-{rating}",
        "memory_object_id": memory_object_id,
        "rating": rating,
        "feedback_memory_type": memory_type,
        "feedback_container_ref": container_ref,
        "query_audit_log_id": query_audit_log_id,
        "feedback_created_at": created_at,
        "query_context": "",
        "audit_container_ref": container_ref,
        "injected_blocks_json": _json.dumps(blocks),
        "candidate_scores_json": _json.dumps(candidates) if candidates else None,
        "decision_reason": "carry_forward_available",
    }


def _event(
    *,
    rating: str,
    memory_type: str = "decision",
    block_score: float | None = 22.0,
    created_at: str = "2026-06-27T00:00:00",
    memory_object_id: str = "m",
    query_audit_log_id: str = "q",
) -> InjectionEvent:
    return InjectionEvent(
        rating=rating,
        memory_type=memory_type,
        container_ref="c",
        block_score=block_score,
        routing_score=10.0,
        event_created_at=created_at,
        memory_object_id=memory_object_id,
        query_audit_log_id=query_audit_log_id,
        n_underlying_ratings=1,
        tie_resolved=False,
    )


def _record(
    *,
    rating: str,
    memory_type: str = "decision",
    block_score: float | None = 22.0,
) -> InjectionRecord:
    return InjectionRecord(
        rating=rating,
        memory_type=memory_type,
        container_ref="c",
        block_score=block_score,
        retrieval_source=None,
        routing_score=10.0,
        lexical_score=None,
        vector_score=None,
    )


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_dedup_majority_rating_relevant_wins() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1"),
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1"),
        _row(rating="not_relevant", memory_object_id="m1", query_audit_log_id="q1"),
    ]
    events, dedup, _ = dedup_from_rows(rows)
    assert len(events) == 1
    assert events[0].rating == "relevant"
    assert events[0].n_underlying_ratings == 3
    assert events[0].tie_resolved is False
    assert dedup.n_collapsed_pairs == 1
    assert dedup.n_ties_to_not_relevant == 0


def test_dedup_tie_resolves_to_not_relevant() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1"),
        _row(rating="not_relevant", memory_object_id="m1", query_audit_log_id="q1"),
    ]
    events, dedup, _ = dedup_from_rows(rows)
    assert len(events) == 1
    assert events[0].rating == "not_relevant"  # tie -> conservative
    assert events[0].tie_resolved is True
    assert dedup.n_ties_to_not_relevant == 1


def test_dedup_single_rating_passes_through() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1"),
        _row(rating="not_relevant", memory_object_id="m2", query_audit_log_id="q2"),
    ]
    events, dedup, _ = dedup_from_rows(rows)
    assert len(events) == 2
    ratings = sorted(e.rating for e in events)
    assert ratings == ["not_relevant", "relevant"]
    assert dedup.n_collapsed_pairs == 0


def test_dedup_carries_min_created_at_across_group() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             created_at="2026-06-27T05:00:00"),
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             created_at="2026-06-27T01:00:00"),  # earliest
        _row(rating="not_relevant", memory_object_id="m1", query_audit_log_id="q1",
             created_at="2026-06-27T03:00:00"),
    ]
    events, _, _ = dedup_from_rows(rows)
    assert len(events) == 1
    assert events[0].event_created_at == "2026-06-27T01:00:00"


def test_dedup_raises_on_inconsistent_memory_type_within_pair() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             memory_type="decision"),
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             memory_type="constraint_memory"),
    ]
    with pytest.raises(ValueError, match="Inconsistent memory_type"):
        dedup_from_rows(rows)


def test_dedup_raises_on_inconsistent_block_score_within_pair() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             block_score=22.0),
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1",
             block_score=18.0),
    ]
    with pytest.raises(ValueError, match="Inconsistent block_score"):
        dedup_from_rows(rows)


def test_dedup_drops_invalid_ratings() -> None:
    rows = [
        _row(rating="relevant", memory_object_id="m1", query_audit_log_id="q1"),
        _row(rating="unknown", memory_object_id="m2", query_audit_log_id="q2"),
    ]
    events, _, skips = dedup_from_rows(rows)
    assert len(events) == 1
    assert skips.other_rating == 1


# ---------------------------------------------------------------------------
# Chronological split
# ---------------------------------------------------------------------------


def test_chronological_split_deterministic_with_timestamp_ties() -> None:
    events = [
        _event(rating="relevant", memory_object_id="m2", query_audit_log_id="q",
               created_at="2026-06-27T00:00:00"),
        _event(rating="relevant", memory_object_id="m1", query_audit_log_id="q",
               created_at="2026-06-27T00:00:00"),
        _event(rating="not_relevant", memory_object_id="m3", query_audit_log_id="q",
               created_at="2026-06-27T01:00:00"),
        _event(rating="relevant", memory_object_id="m4", query_audit_log_id="q",
               created_at="2026-06-27T02:00:00"),
        _event(rating="relevant", memory_object_id="m5", query_audit_log_id="q",
               created_at="2026-06-27T03:00:00"),
    ]
    train1, hd1 = chronological_split(events, train_fraction=0.8)
    train2, hd2 = chronological_split(events, train_fraction=0.8)
    # Determinism
    assert [e.memory_object_id for e in train1] == [e.memory_object_id for e in train2]
    assert [e.memory_object_id for e in hd1] == [e.memory_object_id for e in hd2]
    # m1 sorts before m2 at the same timestamp (tie-break on memory_object_id)
    assert train1[0].memory_object_id == "m1"
    assert train1[1].memory_object_id == "m2"
    # 80% of 5 = 4 events in train
    assert len(train1) == 4
    assert len(hd1) == 1
    assert hd1[0].memory_object_id == "m5"


def test_chronological_split_n1_no_holdout() -> None:
    events = [_event(rating="relevant")]
    train, hd = chronological_split(events, train_fraction=0.8)
    assert len(train) == 0  # floor(0.8 * 1) = 0
    assert len(hd) == 1


def test_chronological_split_full_train_with_n5_full_fraction() -> None:
    events = [_event(rating="relevant", created_at=f"2026-06-27T0{i}:00:00",
                     memory_object_id=f"m{i}") for i in range(5)]
    train, hd = chronological_split(events, train_fraction=1.0)
    assert len(train) == 5
    assert len(hd) == 0


# ---------------------------------------------------------------------------
# Threshold derivation with min-N
# ---------------------------------------------------------------------------


def test_threshold_min_n_refuses_low_kept_relevant() -> None:
    """If best frontier point has kept_relevant < MIN_TRAIN_KEPT_RELEVANT,
    no threshold is recommended.
    """
    train = (
        [_record(rating="relevant", block_score=25.0) for _ in range(3)]
        + [_record(rating="not_relevant", block_score=10.0) for _ in range(20)]
    )
    out = derive_thresholds_with_min_kept(train, min_kept_relevant=5)
    decision_info = out["decision"]
    assert decision_info["best"] is None
    assert "kept_relevant=3" in decision_info["reason_no_threshold"]


def test_threshold_min_n_accepts_sufficient_kept() -> None:
    """If best frontier point has kept_relevant >= MIN_TRAIN_KEPT_RELEVANT,
    threshold is returned.
    """
    train = (
        [_record(rating="relevant", block_score=25.0) for _ in range(7)]
        + [_record(rating="not_relevant", block_score=10.0) for _ in range(10)]
    )
    out = derive_thresholds_with_min_kept(train, min_kept_relevant=5)
    decision_info = out["decision"]
    assert decision_info["best"] is not None
    assert decision_info["best"]["kept_relevant"] >= 5


def test_threshold_min_n_default_constant_matches_spec() -> None:
    assert MIN_TRAIN_KEPT_RELEVANT == 5


# ---------------------------------------------------------------------------
# Holdout evaluation
# ---------------------------------------------------------------------------


def test_evaluate_on_holdout_basic() -> None:
    # train derives threshold=22 for decision (7 rel >=22, 10 bad <22)
    train = (
        [_record(rating="relevant", block_score=25.0) for _ in range(7)]
        + [_record(rating="not_relevant", block_score=10.0) for _ in range(10)]
    )
    thresholds = derive_thresholds_with_min_kept(train, min_kept_relevant=5)
    assert thresholds["decision"]["best"]["threshold"] == 25.0  # the only score in rel set

    # holdout: 4 rel >= 25 (kept), 1 rel = 20 (dropped), 2 bad = 25 (kept), 5 bad = 10 (dropped)
    holdout = (
        [_record(rating="relevant", block_score=25.0) for _ in range(4)]
        + [_record(rating="relevant", block_score=20.0) for _ in range(1)]
        + [_record(rating="not_relevant", block_score=25.0) for _ in range(2)]
        + [_record(rating="not_relevant", block_score=10.0) for _ in range(5)]
    )
    result = evaluate_on_holdout(holdout, thresholds)["decision"]
    assert result["applied_threshold"] == 25.0
    assert result["kept_relevant"] == 4
    assert result["kept_bad"] == 2
    assert result["kept_total"] == 6
    assert result["precision"] == pytest.approx(4 / 6)
    assert result["recall"] == pytest.approx(4 / 5)  # 4 kept of 5 relevant in holdout


def test_evaluate_on_holdout_no_threshold_skips_type() -> None:
    holdout = [_record(rating="relevant", block_score=25.0)]
    thresholds = {"decision": {"best": None, "n_relevant_train": 0, "n_total_train": 0,
                                "target_precision": 0.7, "min_kept_relevant_required": 5,
                                "reason_no_threshold": "x"}}
    result = evaluate_on_holdout(holdout, thresholds)["decision"]
    assert result["applied_threshold"] is None
    assert result["kept_total"] == 0
    assert result["precision"] is None


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------


def test_disposition_proactive_when_pass_bar_met() -> None:
    thresholds = {"decision": {"best": {"threshold": 22.0, "kept_relevant": 10,
                                        "kept_bad": 2, "precision": 0.83, "recall": 0.5},
                                "n_relevant_train": 30, "n_total_train": 60,
                                "target_precision": 0.7, "min_kept_relevant_required": 5,
                                "reason_no_threshold": None}}
    holdout = {"decision": {"applied_threshold": 22.0, "kept_total": 15,
                             "kept_relevant": 12, "kept_bad": 3,
                             "precision": 0.8, "recall": 0.4,
                             "n_holdout": 30, "n_relevant_holdout": 15}}
    counts = {"decision": 90}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["decision"]["disposition"] == "proactive"


def test_disposition_demote_when_holdout_precision_below_target() -> None:
    thresholds = {"decision": {"best": {"threshold": 22.0, "kept_relevant": 10,
                                        "kept_bad": 2, "precision": 0.83, "recall": 0.5},
                                "n_relevant_train": 30, "n_total_train": 60,
                                "target_precision": 0.7, "min_kept_relevant_required": 5,
                                "reason_no_threshold": None}}
    holdout = {"decision": {"applied_threshold": 22.0, "kept_total": 15,
                             "kept_relevant": 9, "kept_bad": 6,
                             "precision": 0.60, "recall": 0.3,
                             "n_holdout": 30, "n_relevant_holdout": 30}}
    counts = {"decision": 90}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["decision"]["disposition"] == "demote_to_on_demand"


def test_disposition_demote_when_holdout_kept_under_min() -> None:
    thresholds = {"decision": {"best": {"threshold": 22.0, "kept_relevant": 10,
                                        "kept_bad": 2, "precision": 0.83, "recall": 0.5},
                                "n_relevant_train": 30, "n_total_train": 60,
                                "target_precision": 0.7, "min_kept_relevant_required": 5,
                                "reason_no_threshold": None}}
    holdout = {"decision": {"applied_threshold": 22.0, "kept_total": MIN_HOLDOUT_KEPT - 1,
                             "kept_relevant": 7, "kept_bad": 2,
                             "precision": 0.78, "recall": 0.3,
                             "n_holdout": 30, "n_relevant_holdout": 30}}
    counts = {"decision": 90}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["decision"]["disposition"] == "demote_to_on_demand"


def test_disposition_investigation_outcome_always_on_demand() -> None:
    thresholds = {"investigation_outcome": {"best": None,
                                             "n_relevant_train": 50, "n_total_train": 100,
                                             "target_precision": 0.7,
                                             "min_kept_relevant_required": 5,
                                             "reason_no_threshold": "unreachable"}}
    holdout = {"investigation_outcome": {"applied_threshold": None,
                                          "kept_total": 0,
                                          "kept_relevant": 0, "kept_bad": 0,
                                          "precision": None, "recall": None,
                                          "n_holdout": 40, "n_relevant_holdout": 20}}
    counts = {"investigation_outcome": 200}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["investigation_outcome"]["disposition"] == "demote_to_on_demand"


def test_disposition_task_checkpoint_always_reference_only() -> None:
    thresholds = {"task_checkpoint": {"best": {"threshold": 14, "kept_relevant": 30,
                                                "kept_bad": 10, "precision": 0.75,
                                                "recall": 0.4},
                                       "n_relevant_train": 100, "n_total_train": 200,
                                       "target_precision": 0.7,
                                       "min_kept_relevant_required": 5,
                                       "reason_no_threshold": None}}
    holdout = {"task_checkpoint": {"applied_threshold": 14, "kept_total": 50,
                                    "kept_relevant": 40, "kept_bad": 10,
                                    "precision": 0.80, "recall": 0.5,
                                    "n_holdout": 100, "n_relevant_holdout": 80}}
    counts = {"task_checkpoint": 300}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    # Even with great numbers, task_checkpoint stays reference-only — Phase 4
    # event triggers are its real gate.
    assert dispositions["task_checkpoint"]["disposition"] == "reference_only"


def test_disposition_fact_summary_always_suspended() -> None:
    thresholds = {"fact_summary": {"best": None, "n_relevant_train": 2,
                                    "n_total_train": 5, "target_precision": 0.7,
                                    "min_kept_relevant_required": 5,
                                    "reason_no_threshold": "kept_relevant=2 < 5"}}
    holdout = {"fact_summary": {"applied_threshold": None, "kept_total": 0,
                                 "kept_relevant": 0, "kept_bad": 0,
                                 "precision": None, "recall": None,
                                 "n_holdout": 2, "n_relevant_holdout": 1}}
    counts = {"fact_summary": 10}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["fact_summary"]["disposition"] == "suspend_insufficient_data"


def test_disposition_insufficient_for_reporting() -> None:
    thresholds = {"task_trace": {"best": None, "n_relevant_train": 0,
                                  "n_total_train": 2, "target_precision": 0.7,
                                  "min_kept_relevant_required": 5,
                                  "reason_no_threshold": "n_total < min"}}
    holdout = {}
    counts = {"task_trace": 2}
    dispositions = assemble_dispositions(thresholds, holdout, counts)
    assert dispositions["task_trace"]["disposition"] is None
    assert dispositions["task_trace"]["insufficient_for_reporting"] is True


def test_recommended_policy_only_includes_proactive() -> None:
    thresholds = {
        "decision": {"best": {"threshold": 22.0, "kept_relevant": 10, "kept_bad": 2,
                              "precision": 0.83, "recall": 0.5},
                     "n_relevant_train": 30, "n_total_train": 60,
                     "target_precision": 0.7, "min_kept_relevant_required": 5,
                     "reason_no_threshold": None},
        "task_checkpoint": {"best": {"threshold": 14.0, "kept_relevant": 30, "kept_bad": 10,
                                      "precision": 0.75, "recall": 0.4},
                             "n_relevant_train": 100, "n_total_train": 200,
                             "target_precision": 0.7, "min_kept_relevant_required": 5,
                             "reason_no_threshold": None},
    }
    dispositions = {
        "decision": {"disposition": "proactive"},
        "task_checkpoint": {"disposition": "reference_only"},
    }
    policy = assemble_recommended_policy(thresholds, dispositions)
    assert "decision" in policy
    assert "task_checkpoint" not in policy
    assert policy["decision"] == {"mode": "proactive", "min_score": 22.0}
