"""Unit tests for the routing trace `loss_stage` map for the new Goal A
`displaced_by_*` codes. Without these mappings the trace would silently
bucket every new code under `loss_stage = "injection_cap"` /
`"final_injection_cap"`, inverting the debuggability gain the audit
consumer relies on.
"""
from __future__ import annotations

import pytest

from core.models import InjectableBlock, QueryResultItem
from semantic import agent_conversation_memory_routing_trace as trace_mod


def _make_item(*, mtype: str, mid: str) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id=mid,
        type=mtype,
        payload={"decision": f"summary {mid}"},
    )


def _make_candidate(item: QueryResultItem, *, code: str) -> dict:
    return {
        "item": item,
        "layer": item.type or "memory",
        "routing_rank": 5,
        "routing_score": 100,
        "lexical_rank": None,
        "excluded_reason_code": code,
        "excluded_reason": "test reason",
    }


def _diagnostic_for(code: str) -> dict:
    item = _make_item(mtype="decision", mid=f"d-{code}")
    cand = _make_candidate(item, code=code)
    diagnostics = trace_mod._build_sharp_candidate_diagnostics(
        ranked_candidates=[cand],
        final_candidates=[],  # candidate is excluded
        injectable_blocks=[],  # nothing injected
        decision_reason="carry_forward_available",
        query_text="probe",
    )
    by_id = {d["result_id"]: d for d in diagnostics}
    return by_id[item.result_id]


# ---- packaging-bucket codes -------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "displaced_by_adjacent_evidence_packaging",
        "displaced_by_dedup",
        "displaced_by_fact_summary_cap",
        "displaced_by_locality_compatibility",
        "displaced_by_companion_fill",
        "displaced_by_constraint_supplement",
        "displaced_by_r2b_subject_overlap",
        "displaced_by_cross_thread_checkpoint_suppression",
    ],
)
def test_routing_trace_loss_stage_map_for_new_codes_packaging(code: str) -> None:
    diag = _diagnostic_for(code)
    assert diag["loss_stage"] == "packaging"
    assert diag["loss_reason_code"] == code


# ---- injection_cap-bucket codes ---------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "displaced_by_hard_ceiling",
        "displaced_by_expansion_ratio",
        "displaced_by_per_candidate_eligibility",
    ],
)
def test_routing_trace_loss_stage_map_for_new_codes_injection_cap(code: str) -> None:
    diag = _diagnostic_for(code)
    assert diag["loss_stage"] == "injection_cap"
    assert diag["loss_reason_code"] == code


def test_routing_trace_loss_stage_unknown_code_falls_through() -> None:
    """An excluded_reason_code that is not in either map falls back to
    `loss_stage = "routing"` (the default for non-final candidates)
    rather than being silently miscategorized."""
    diag = _diagnostic_for("lower_routing_score_than_selected_limit")
    # lower_routing_score_than_selected_limit is the legacy fallback code
    # — it should not be in either Goal A map.
    assert diag["loss_stage"] == "routing"
    assert diag["loss_reason_code"] == "lower_routing_score_than_selected_limit"
