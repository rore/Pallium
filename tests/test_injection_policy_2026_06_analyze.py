"""Tests for evals/injection_policy_2026_06/analyze.py pure compute layer.

Live-DB behaviour is not asserted here; the headline numbers from the
production database belong in the committed snapshot JSON, not in tests.
This file only exercises edge cases of the pure functions:
- NULL injected_blocks_json (filtered out at the SQL layer; we still
  verify behaviour if the row sneaks through with `[]`),
- missing block `score` field,
- ratings outside the {relevant, not_relevant} enum,
- duplicate ratings on the same memory/audit pair,
- routing-score sanity check column.

See: docs/specs/2026-06-27-injection-policy-abstention.md
"""

from __future__ import annotations

import json

import pytest

from evals.injection_policy_2026_06.analyze import (
    PROPOSED_POLICY,
    InjectionRecord,
    apply_proposed_policy,
    build_report,
    compute_container_rates,
    compute_pr_frontier,
    compute_type_distributions,
    derive_target_thresholds,
    extract_records,
)


def _row(
    *,
    feedback_id: str,
    memory_object_id: str,
    rating: str,
    memory_type: str = "decision",
    container_ref: str = "git:test",
    block_score: float | None = 20.0,
    routing_score: float | None = 12.0,
    block_present: bool = True,
    extra_blocks: list[dict] | None = None,
    extra_candidates: list[dict] | None = None,
) -> dict:
    """Build a joined row matching the shape produced by load_joined_rows."""
    blocks: list[dict] = []
    if block_present:
        block: dict = {
            "memory_object_id": memory_object_id,
            "memory_type": memory_type,
            "retrieval_source": "vector",
        }
        if block_score is not None:
            block["score"] = block_score
        blocks.append(block)
    if extra_blocks:
        blocks.extend(extra_blocks)

    candidates: list[dict] = []
    if routing_score is not None:
        candidates.append({
            "memory_object_id": memory_object_id,
            "memory_type": memory_type,
            "routing_score": routing_score,
            "lexical_score": 4.0,
            "vector_score": 0.8,
        })
    if extra_candidates:
        candidates.extend(extra_candidates)

    return {
        "feedback_id": feedback_id,
        "memory_object_id": memory_object_id,
        "rating": rating,
        "feedback_memory_type": memory_type,
        "feedback_container_ref": container_ref,
        "query_audit_log_id": "audit-1",
        "feedback_created_at": "2026-06-27T00:00:00",
        "query_context": "test query",
        "audit_container_ref": container_ref,
        "injected_blocks_json": json.dumps(blocks),
        "candidate_scores_json": json.dumps(candidates) if candidates else None,
        "decision_reason": "carry_forward_available",
    }


def test_extract_records_basic_happy_path() -> None:
    rows = [
        _row(feedback_id="f1", memory_object_id="m1", rating="relevant", block_score=22),
        _row(feedback_id="f2", memory_object_id="m2", rating="not_relevant", block_score=10),
    ]
    records, skips = extract_records(rows)
    assert len(records) == 2
    assert skips.no_block_match == 0
    assert skips.no_block_score == 0
    assert skips.other_rating == 0
    assert {r.rating for r in records} == {"relevant", "not_relevant"}
    assert all(r.block_score is not None for r in records)


def test_extract_records_drops_other_ratings() -> None:
    rows = [
        _row(feedback_id="f1", memory_object_id="m1", rating="relevant"),
        _row(feedback_id="f2", memory_object_id="m2", rating="unsure"),  # not in enum
        _row(feedback_id="f3", memory_object_id="m3", rating=""),  # empty
    ]
    records, skips = extract_records(rows)
    assert len(records) == 1
    assert skips.other_rating == 2


def test_extract_records_counts_missing_block_score() -> None:
    rows = [
        _row(
            feedback_id="f1",
            memory_object_id="m1",
            rating="relevant",
            block_score=None,  # block present but score field missing
        ),
    ]
    records, skips = extract_records(rows)
    # Record is kept (for routing-score sanity check) but block_score is None
    # and the missing-score skip counter increments.
    assert len(records) == 1
    assert records[0].block_score is None
    assert skips.no_block_score == 1


def test_extract_records_no_block_no_candidate_skips() -> None:
    rows = [
        _row(
            feedback_id="f1",
            memory_object_id="m1",
            rating="relevant",
            block_present=False,
            routing_score=None,
        ),
    ]
    records, skips = extract_records(rows)
    assert records == []
    assert skips.no_block_match == 1


def test_extract_records_handles_corrupt_json() -> None:
    rows = [
        {
            "feedback_id": "f1",
            "memory_object_id": "m1",
            "rating": "relevant",
            "feedback_memory_type": "decision",
            "feedback_container_ref": "c",
            "query_audit_log_id": "audit-1",
            "feedback_created_at": "2026-06-27T00:00:00",
            "query_context": "q",
            "audit_container_ref": "c",
            "injected_blocks_json": "not-json",  # parse failure
            "candidate_scores_json": "{bad",
            "decision_reason": "x",
        }
    ]
    records, skips = extract_records(rows)
    assert records == []
    assert skips.no_block_match == 1


def test_duplicate_ratings_treated_as_separate_events() -> None:
    """Spec contract: duplicates on (memory_object_id, query_audit_log_id) are
    rated independently — each is a distinct feedback event. We intentionally
    do NOT collapse with majority_rating at this stage; the analyze.py output
    reports per-rating counts. (majority_rating is reserved for later phases
    that need a single rating per memory.)
    """
    rows = [
        _row(feedback_id="f1", memory_object_id="m1", rating="relevant", block_score=20),
        _row(feedback_id="f2", memory_object_id="m1", rating="not_relevant", block_score=20),
    ]
    records, skips = extract_records(rows)
    assert len(records) == 2
    ratings = sorted(r.rating for r in records)
    assert ratings == ["not_relevant", "relevant"]


def test_compute_container_rates() -> None:
    records = [
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=20, retrieval_source="vector",
                        routing_score=10, lexical_score=4, vector_score=0.8),
        InjectionRecord(rating="not_relevant", memory_type="decision",
                        container_ref="A", block_score=15, retrieval_source="vector",
                        routing_score=10, lexical_score=4, vector_score=0.8),
        InjectionRecord(rating="not_relevant", memory_type="decision",
                        container_ref="B", block_score=15, retrieval_source="vector",
                        routing_score=10, lexical_score=4, vector_score=0.8),
    ]
    rates = compute_container_rates(records)
    assert rates["A"]["total"] == 2
    assert rates["A"]["precision"] == 0.5
    assert rates["B"]["bad_rate"] == 1.0


def test_compute_type_distributions_skips_none_scores() -> None:
    records = [
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=20, retrieval_source=None,
                        routing_score=10, lexical_score=None, vector_score=None),
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=None, retrieval_source=None,
                        routing_score=10, lexical_score=None, vector_score=None),
        InjectionRecord(rating="not_relevant", memory_type="decision",
                        container_ref="A", block_score=10, retrieval_source=None,
                        routing_score=10, lexical_score=None, vector_score=None),
    ]
    dist = compute_type_distributions(records, "block_score")
    assert dist["decision"]["relevant"]["n"] == 1  # the None is dropped
    assert dist["decision"]["not_relevant"]["n"] == 1
    assert dist["decision"]["coverage"]["total"] == 2


def test_compute_pr_frontier_monotonic_threshold() -> None:
    records = [
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=25, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=22, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="not_relevant", memory_type="decision",
                        container_ref="A", block_score=10, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
    ]
    frontier = compute_pr_frontier(records, "block_score")["decision"]
    assert frontier["n_relevant"] == 2
    assert frontier["n_total"] == 3
    # At threshold=10 we keep all three (precision 2/3). At threshold=22 we
    # keep only the two relevant (precision 1.0, recall 1.0).
    by_thr = {round(p["threshold"], 1): p for p in frontier["frontier"]}
    assert by_thr[10.0]["precision"] == pytest.approx(2 / 3)
    assert by_thr[22.0]["precision"] == 1.0
    assert by_thr[22.0]["recall"] == 1.0


def test_derive_target_thresholds_picks_lowest_meeting_target() -> None:
    # Three relevant (scores 20,21,22), two bad (scores 10, 23). At
    # threshold=20 precision is 3/(3+1)=0.75 with full recall — that's
    # the best (highest-recall) point that meets the 70% bar.
    records = [
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=s, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None)
        for s in (20.0, 21.0, 22.0)
    ] + [
        InjectionRecord(rating="not_relevant", memory_type="decision",
                        container_ref="A", block_score=s, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None)
        for s in (10.0, 23.0)
    ]
    frontier = compute_pr_frontier(records, "block_score")
    targets = derive_target_thresholds(frontier, precision_target=0.70)
    best = targets["decision"]["best"]
    assert best is not None
    assert best["threshold"] == 20.0
    assert best["precision"] >= 0.70
    assert best["recall"] == 1.0


def test_derive_target_thresholds_unreachable() -> None:
    # Every threshold has precision <70%.
    records = [
        InjectionRecord(rating="relevant", memory_type="x",
                        container_ref="A", block_score=10, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="not_relevant", memory_type="x",
                        container_ref="A", block_score=10, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="not_relevant", memory_type="x",
                        container_ref="A", block_score=12, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
    ]
    frontier = compute_pr_frontier(records, "block_score")
    targets = derive_target_thresholds(frontier)
    assert targets["x"]["best"] is None


def test_apply_proposed_policy_block_vs_routing_field_diverge() -> None:
    """If the policy is applied against the wrong field (routing_score
    instead of block_score) precision must materially regress. This is the
    spec's load-bearing sanity check.
    """
    # Build a small population where block_score perfectly separates
    # (rel >= 22, bad <= 16) but routing_score is constant and uninformative.
    records = []
    for s in (22.0, 23.0, 24.0):
        records.append(InjectionRecord(
            rating="relevant", memory_type="decision", container_ref="A",
            block_score=s, retrieval_source=None,
            routing_score=22.0, lexical_score=None, vector_score=None,
        ))
    for s in (10.0, 14.0, 16.0):
        records.append(InjectionRecord(
            rating="not_relevant", memory_type="decision", container_ref="A",
            block_score=s, retrieval_source=None,
            routing_score=22.0, lexical_score=None, vector_score=None,
        ))
    policy = {"decision": 22.0}
    block_result = apply_proposed_policy(records, policy, "block_score")
    routing_result = apply_proposed_policy(records, policy, "routing_score")
    assert block_result["new_precision"] == 1.0
    assert routing_result["new_precision"] == 0.5  # constant routing_score keeps everything


def test_apply_proposed_policy_excludes_types_not_in_policy() -> None:
    records = [
        InjectionRecord(rating="relevant", memory_type="decision",
                        container_ref="A", block_score=23, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="relevant", memory_type="investigation_outcome",
                        container_ref="A", block_score=24, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
        InjectionRecord(rating="not_relevant", memory_type="investigation_outcome",
                        container_ref="A", block_score=23, retrieval_source=None,
                        routing_score=None, lexical_score=None, vector_score=None),
    ]
    result = apply_proposed_policy(records, {"decision": 22.0}, "block_score")
    # investigation_outcome is excluded entirely — only the decision row is kept.
    assert result["kept_total"] == 1
    assert result["kept_relevant"] == 1
    assert result["kept_bad"] == 0


def test_build_report_smoke() -> None:
    """End-to-end smoke test: the report has all expected top-level sections."""
    rows = [
        _row(feedback_id="f1", memory_object_id="m1", rating="relevant",
             memory_type="decision", block_score=22),
        _row(feedback_id="f2", memory_object_id="m2", rating="not_relevant",
             memory_type="decision", block_score=10),
    ]
    records, skips = extract_records(rows)
    report = build_report(records, skips)
    assert "by_container" in report
    assert "block_score" in report
    assert "routing_score_sanity_check" in report
    assert report["records"]["n_records"] == 2
    assert report["block_score"]["proposed_policy"]["score_field"] == "block_score"
    assert (
        report["routing_score_sanity_check"]["same_thresholds_on_routing_score"][
            "score_field"
        ]
        == "routing_score"
    )


def test_proposed_policy_constant_documented() -> None:
    """Lock the policy values that are referenced by the spec headline."""
    assert PROPOSED_POLICY == {
        "constraint_memory": 20.0,
        "decision": 22.0,
        "task_checkpoint": 14.0,
    }
