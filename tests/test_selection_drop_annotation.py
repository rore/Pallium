"""Unit tests for selection-layer drop annotation (Goal A).

Exercises `_collect_selection_drop_codes` + `_annotate_excluded_candidates`
behavior for each new `displaced_by_*` code, plus a precedence test
asserting suppression always wins over a selection-layer drop.

Pattern after `tests/test_r2b_subject_overlap_gate.py` — direct unit tests
against helpers, no DB or full plugin pipeline required.
"""
from __future__ import annotations

from core.models import QueryResultItem
from semantic import agent_conversation_memory_routing_selection as selection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(*, mtype: str, mid: str, payload: dict | None = None) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id=mid,
        type=mtype,
        payload=payload or {"decision": f"summary {mid}"},
    )


def _make_candidate(
    item: QueryResultItem,
    *,
    routing_rank: int = 1,
    routing_score: int = 100,
    layer: str | None = None,
    extras: dict | None = None,
) -> dict:
    cand = {
        "item": item,
        "layer": layer or item.type or "memory",
        "routing_rank": routing_rank,
        "routing_score": routing_score,
        "packaging_reasons": [],
    }
    if extras:
        cand.update(extras)
    return cand


def _annotate(
    *,
    ranked: list[dict],
    final: list[dict],
    injected_ids: set[str],
    injection_summary: dict | None = None,
    routing_focus: dict | None = None,
    packaging_summary: dict | None = None,
    requested_limit: int = 5,
) -> None:
    selection._annotate_excluded_candidates(
        ranked_candidates=ranked,
        final_candidates=final,
        requested_limit=requested_limit,
        routing_focus=routing_focus or {"applied": False, "primary_layer": None, "reason": ""},
        packaging_summary=packaging_summary,
        injection_summary=injection_summary or {},
        selected_injected_result_ids=injected_ids,
    )


# ---------------------------------------------------------------------------
# Per-code tests
# ---------------------------------------------------------------------------


def test_excluded_displaced_by_dedup() -> None:
    keep_item = _make_item(mtype="decision", mid="kept")
    drop_item = _make_item(mtype="decision", mid="dup")
    keep_cand = _make_candidate(keep_item, routing_rank=1)
    drop_cand = _make_candidate(drop_item, routing_rank=2)

    injection_summary = {
        "dedup_removed_result_ids": [drop_item.result_id],
        "dedup_kept_map": {drop_item.result_id: keep_item.result_id},
    }

    _annotate(
        ranked=[keep_cand, drop_cand],
        final=[keep_cand, drop_cand],
        injected_ids={keep_item.result_id},
        injection_summary=injection_summary,
    )

    assert keep_cand["excluded_reason_code"] is None
    assert drop_cand["excluded_reason_code"] == "displaced_by_dedup"


def test_excluded_displaced_by_fact_summary_cap() -> None:
    kept_item = _make_item(mtype="fact_summary", mid="fs-kept")
    drop_item = _make_item(mtype="fact_summary", mid="fs-drop")
    kept_cand = _make_candidate(kept_item, routing_rank=1)
    drop_cand = _make_candidate(
        drop_item, routing_rank=2,
        extras={"selection_drop_reason_code": "displaced_by_fact_summary_cap"},
    )

    _annotate(
        ranked=[kept_cand, drop_cand],
        final=[kept_cand, drop_cand],
        injected_ids={kept_item.result_id},
    )

    assert kept_cand["excluded_reason_code"] is None
    assert drop_cand["excluded_reason_code"] == "displaced_by_fact_summary_cap"


def test_excluded_displaced_by_expansion_ratio() -> None:
    kept_item = _make_item(mtype="decision", mid="strong")
    weak_item = _make_item(mtype="decision", mid="weak")
    kept_cand = _make_candidate(kept_item, routing_rank=1, routing_score=1000)
    weak_cand = _make_candidate(
        weak_item, routing_rank=2, routing_score=200,
        extras={"selection_drop_reason_code": "displaced_by_expansion_ratio"},
    )

    _annotate(
        ranked=[kept_cand, weak_cand],
        final=[kept_cand, weak_cand],
        injected_ids={kept_item.result_id},
    )

    assert weak_cand["excluded_reason_code"] == "displaced_by_expansion_ratio"


def test_excluded_displaced_by_hard_ceiling() -> None:
    items = [_make_item(mtype="decision", mid=f"d{i}") for i in range(6)]
    cands = [_make_candidate(it, routing_rank=i + 1) for i, it in enumerate(items)]
    # First five injected; the sixth is hard-ceiling tagged at the source.
    cands[5]["selection_drop_reason_code"] = "displaced_by_hard_ceiling"
    injected_ids = {it.result_id for it in items[:5]}

    _annotate(
        ranked=cands,
        final=cands,
        injected_ids=injected_ids,
    )

    assert cands[5]["excluded_reason_code"] == "displaced_by_hard_ceiling"


def test_excluded_displaced_by_companion_fill() -> None:
    kept_item = _make_item(mtype="task_checkpoint", mid="ck")
    drop_item = _make_item(mtype="source_evidence", mid="cf")
    kept_cand = _make_candidate(kept_item)
    drop_cand = _make_candidate(
        drop_item,
        routing_rank=6,
        extras={"selection_drop_reason_code": "displaced_by_companion_fill"},
    )

    _annotate(
        ranked=[kept_cand, drop_cand],
        final=[kept_cand, drop_cand],
        injected_ids={kept_item.result_id},
    )

    assert drop_cand["excluded_reason_code"] == "displaced_by_companion_fill"


def test_excluded_displaced_by_constraint_supplement() -> None:
    kept_item = _make_item(mtype="decision", mid="d-keep")
    cs_item = _make_item(mtype="constraint_memory", mid="c-drop", payload={"constraint": "x"})
    kept_cand = _make_candidate(kept_item)
    cs_cand = _make_candidate(
        cs_item,
        routing_rank=3,
        extras={"selection_drop_reason_code": "displaced_by_constraint_supplement"},
    )

    _annotate(
        ranked=[kept_cand, cs_cand],
        final=[kept_cand, cs_cand],
        injected_ids={kept_item.result_id},
    )

    assert cs_cand["excluded_reason_code"] == "displaced_by_constraint_supplement"


def test_excluded_displaced_by_locality_compatibility() -> None:
    primary = _make_item(mtype="task_checkpoint", mid="ck-primary")
    other = _make_item(mtype="source_evidence", mid="se-other")
    primary_cand = _make_candidate(primary)
    other_cand = _make_candidate(
        other,
        routing_rank=2,
        extras={"selection_drop_reason_code": "displaced_by_locality_compatibility"},
    )

    _annotate(
        ranked=[primary_cand, other_cand],
        final=[primary_cand],  # locality-blocked candidate didn't make selection
        injected_ids={primary.result_id},
    )

    assert other_cand["excluded_reason_code"] == "displaced_by_locality_compatibility"


def test_excluded_displaced_by_cross_thread_checkpoint_suppression() -> None:
    kept_item = _make_item(mtype="task_checkpoint", mid="ck-local")
    drop_item = _make_item(mtype="task_checkpoint", mid="ck-cross")
    kept_cand = _make_candidate(kept_item, extras={"same_thread": True})
    drop_cand = _make_candidate(
        drop_item,
        routing_rank=2,
        extras={
            "same_thread": False,
            "selection_drop_reason_code": "displaced_by_cross_thread_checkpoint_suppression",
        },
    )

    _annotate(
        ranked=[kept_cand, drop_cand],
        final=[kept_cand, drop_cand],
        injected_ids={kept_item.result_id},
    )

    assert drop_cand["excluded_reason_code"] == "displaced_by_cross_thread_checkpoint_suppression"


def test_excluded_displaced_by_per_candidate_eligibility() -> None:
    kept_item = _make_item(mtype="decision", mid="d-kept")
    weak_item = _make_item(mtype="decision", mid="d-weak")
    kept_cand = _make_candidate(kept_item)
    weak_cand = _make_candidate(
        weak_item,
        routing_rank=2,
        extras={"selection_drop_reason_code": "displaced_by_per_candidate_eligibility"},
    )

    _annotate(
        ranked=[kept_cand, weak_cand],
        final=[kept_cand, weak_cand],
        injected_ids={kept_item.result_id},
    )

    assert weak_cand["excluded_reason_code"] == "displaced_by_per_candidate_eligibility"


def test_excluded_displaced_by_r2b_subject_overlap() -> None:
    """R2b mirror: candidate carries BOTH `post_routing_drop_reason` and the
    new `excluded_reason_code = displaced_by_r2b_subject_overlap`. Asserts
    the architect-required dual-field population.
    """
    kept_item = _make_item(mtype="decision", mid="d-on-topic")
    r2b_item = _make_item(mtype="decision", mid="d-off-topic")
    kept_cand = _make_candidate(kept_item)
    r2b_cand = _make_candidate(
        r2b_item,
        routing_rank=2,
        extras={"post_routing_drop_reason": selection._R2B_DROP_REASON},
    )

    _annotate(
        ranked=[kept_cand, r2b_cand],
        final=[kept_cand, r2b_cand],
        injected_ids={kept_item.result_id},
    )

    # BOTH fields populated — consumer parity guarantee.
    assert r2b_cand["excluded_reason_code"] == "displaced_by_r2b_subject_overlap"
    assert r2b_cand["post_routing_drop_reason"] == selection._R2B_DROP_REASON


# ---------------------------------------------------------------------------
# Precedence test (architect F8)
# ---------------------------------------------------------------------------


def test_excluded_code_precedence_suppression_wins() -> None:
    """A candidate that hits BOTH a suppression mirror AND a new selection
    drop site must be annotated with the suppression code. This protects the
    pre-existing audit-aggregator semantics: suppression > injection-stage
    drop > packaging > focus > lower-routing-score.
    """
    kept_item = _make_item(mtype="decision", mid="d-kept")
    conflicted_item = _make_item(mtype="decision", mid="d-confused")
    kept_cand = _make_candidate(kept_item)
    conflicted_cand = _make_candidate(
        conflicted_item,
        routing_rank=2,
        extras={
            # Suppression set upstream …
            "suppression_reason_code": "current_query_source_echo",
            "suppression_reason": "Candidate echoes the current query source.",
            # … AND a downstream selection-layer marker (e.g. dedup match).
            "selection_drop_reason_code": "displaced_by_dedup",
        },
    )

    _annotate(
        ranked=[kept_cand, conflicted_cand],
        final=[kept_cand, conflicted_cand],
        injected_ids={kept_item.result_id},
        injection_summary={
            "dedup_removed_result_ids": [conflicted_item.result_id],
            "dedup_kept_map": {conflicted_item.result_id: kept_item.result_id},
        },
    )

    # Suppression wins — preserves existing branch order in
    # `_annotate_excluded_candidates`.
    assert conflicted_cand["excluded_reason_code"] == "current_query_source_echo"
    assert conflicted_cand["excluded_reason"] == "Candidate echoes the current query source."


def test_excluded_existing_codes_unchanged() -> None:
    """Keep parity with the pre-existing branches in
    `_annotate_excluded_candidates`: lower-routing-score and
    fallback_layer_deprioritized still fire when no new code applies.
    """
    kept_item = _make_item(mtype="decision", mid="d-kept")
    overflow_item = _make_item(mtype="decision", mid="d-overflow")
    kept_cand = _make_candidate(kept_item, routing_rank=1)
    overflow_cand = _make_candidate(overflow_item, routing_rank=8)

    _annotate(
        ranked=[kept_cand, overflow_cand],
        final=[kept_cand],
        injected_ids={kept_item.result_id},
        requested_limit=5,
    )

    # No selection drop tag, no suppression → fallback to existing
    # lower-routing-score code.
    assert overflow_cand["excluded_reason_code"] == "lower_routing_score_than_selected_limit"
