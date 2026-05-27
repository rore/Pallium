"""Unit tests for the R2b post-routing subject-overlap gate.

Tests the gate primitives (`_subject_tokens_for_item`, `_r2b_should_keep`,
`_apply_r2b_gate`) directly. Flips the module-level `_R2B_GATE_ENABLED` flag
via `monkeypatch.setattr` since it is read once at module import.
"""
from __future__ import annotations

import pytest

from core.models import InjectableBlock, QueryResultItem
from semantic import agent_conversation_memory_routing_selection as selection


def _make_item(*, mtype: str, payload: dict) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id=f"mo-{mtype}-{abs(hash(repr(payload))) % 10000}",
        type=mtype,
        payload=payload,
    )


def _make_candidate(item: QueryResultItem) -> dict:
    return {"item": item, "layer": item.type or "memory"}


def _make_block(item: QueryResultItem) -> InjectableBlock:
    return InjectableBlock(
        result_id=item.result_id or "rid",
        block_type="memory",
        title="t",
        text="t",
        evidence=[],
        memory_type=item.type,
        memory_object_id=item.memory_object_id,
    )


# ---- _subject_tokens_for_item -----------------------------------------------


def test_subject_tokens_uses_payload_subject():
    item = _make_item(mtype="decision", payload={"decision": "deploy service approved"})
    tokens = selection._subject_tokens_for_item(item)
    assert tokens == {"deploy", "service", "approved"}


def test_subject_tokens_falls_back_to_payload_when_no_subject():
    item = _make_item(mtype="unknown_type", payload={"random_field": "alpha beta gamma"})
    tokens = selection._subject_tokens_for_item(item)
    assert tokens == {"alpha", "beta", "gamma"}


def test_subject_tokens_empty_when_no_payload():
    item = _make_item(mtype="decision", payload={})
    assert selection._subject_tokens_for_item(item) == set()


# ---- _r2b_should_keep -------------------------------------------------------


def test_r2b_keeps_when_query_tokens_empty():
    item = _make_item(mtype="decision", payload={"decision": "x"})
    assert selection._r2b_should_keep(item, set()) is True


def test_r2b_keeps_when_subject_tokens_empty():
    item = _make_item(mtype="decision", payload={})
    assert selection._r2b_should_keep(item, {"deploy", "service"}) is True


def test_r2b_keeps_with_two_token_overlap():
    item = _make_item(mtype="decision", payload={"decision": "deploy service approved"})
    assert selection._r2b_should_keep(item, {"deploy", "service", "config"}) is True


def test_r2b_drops_with_one_token_overlap():
    item = _make_item(mtype="decision", payload={"decision": "tenant lookup refactor"})
    assert selection._r2b_should_keep(item, {"deploy", "tenant"}) is False


def test_r2b_drops_with_zero_overlap():
    item = _make_item(mtype="decision", payload={"decision": "alpha beta"})
    assert selection._r2b_should_keep(item, {"gamma", "delta"}) is False


# ---- _apply_r2b_gate --------------------------------------------------------


def test_gate_keeps_block_with_two_token_subject_overlap():
    item = _make_item(mtype="decision", payload={"decision": "deploy service approved"})
    cand = _make_candidate(item)
    blk = _make_block(item)
    kept_cands, kept_blocks, dropped = selection._apply_r2b_gate(
        [cand], [blk], "deploy service config"
    )
    assert kept_cands == [cand]
    assert kept_blocks == [blk]
    assert dropped == 0
    assert "post_routing_drop_reason" not in cand


def test_gate_drops_block_with_one_token_subject_overlap():
    item = _make_item(mtype="decision", payload={"decision": "tenant lookup refactor"})
    cand = _make_candidate(item)
    blk = _make_block(item)
    kept_cands, kept_blocks, dropped = selection._apply_r2b_gate(
        [cand], [blk], "deploy tenant config"
    )
    assert kept_cands == []
    assert kept_blocks == []
    assert dropped == 1
    assert cand["post_routing_drop_reason"] == "r2b_subject_overlap_insufficient"


def test_gate_uses_payload_derived_subject_when_db_column_null():
    """Parity with replay rule: production gate uses payload-derived subject.

    The legacy `subject` field on memory_objects is NULL in production. The
    gate must derive subject from payload (per memory type) and produce the
    same outcome as the replay harness's memory_text fallback rule.
    """
    item = _make_item(
        mtype="investigation_outcome",
        payload={"investigation_outcome": "alpha beta finding root cause"},
    )
    cand = _make_candidate(item)
    blk = _make_block(item)

    keep_cands, keep_blocks, dropped = selection._apply_r2b_gate(
        [cand], [blk], "alpha beta query"
    )
    assert dropped == 0
    assert keep_cands == [cand]

    cand2 = _make_candidate(item)
    blk2 = _make_block(item)
    _, _, dropped2 = selection._apply_r2b_gate([cand2], [blk2], "delta gamma query")
    assert dropped2 == 1
    assert cand2["post_routing_drop_reason"] == "r2b_subject_overlap_insufficient"


def test_gate_keeps_when_subject_empty_falls_back_to_payload_values():
    """Body fallback: empty subject keys -> payload value tokens used."""
    item = _make_item(
        mtype="unknown_type",
        payload={"freeform_blob": "deploy service config rollout"},
    )
    cand = _make_candidate(item)
    blk = _make_block(item)
    _, kept_blocks, dropped = selection._apply_r2b_gate(
        [cand], [blk], "deploy service request"
    )
    assert dropped == 0
    assert kept_blocks == [blk]


def test_gate_keeps_when_both_subject_and_payload_empty():
    """Cannot judge -> keep."""
    item = _make_item(mtype="decision", payload={})
    cand = _make_candidate(item)
    blk = _make_block(item)
    _, kept_blocks, dropped = selection._apply_r2b_gate(
        [cand], [blk], "deploy service config"
    )
    assert dropped == 0
    assert kept_blocks == [blk]


def test_gate_partitions_mixed_batch():
    keep_item = _make_item(mtype="decision", payload={"decision": "deploy service approved"})
    drop_item = _make_item(mtype="decision", payload={"decision": "unrelated tenant work"})
    keep_cand = _make_candidate(keep_item)
    drop_cand = _make_candidate(drop_item)
    keep_blk = _make_block(keep_item)
    drop_blk = _make_block(drop_item)
    kept_cands, kept_blocks, dropped = selection._apply_r2b_gate(
        [keep_cand, drop_cand], [keep_blk, drop_blk], "deploy service config"
    )
    assert kept_cands == [keep_cand]
    assert kept_blocks == [keep_blk]
    assert dropped == 1
    assert "post_routing_drop_reason" not in keep_cand
    assert drop_cand["post_routing_drop_reason"] == "r2b_subject_overlap_insufficient"


# ---- Module-flag wiring -----------------------------------------------------


def test_gate_flag_default_off():
    """Production default: gate is off unless env var explicitly enables it."""
    import os
    flag_env = os.environ.get("PALLIUM_R2B_SUBJECT_OVERLAP_GATE", "")
    if flag_env != "1":
        assert selection._R2B_GATE_ENABLED is False


def test_gate_constants_have_expected_values():
    assert selection._R2B_MIN_OVERLAP == 2
    assert selection._R2B_DROP_REASON == "r2b_subject_overlap_insufficient"
