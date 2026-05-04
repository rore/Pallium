"""Tests for expand_available flag — codec round-trip, block builder, null-envelope fallback."""
from __future__ import annotations

import json

import pytest

from core.models import (
    EvidenceReference,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    QueryResultItem,
)
from semantic.agent_conversation_memory_routing_selection import (
    _build_injectable_block_from_candidate,
)
from storage.sqlite_codec import SQLiteCodecMixin


def _envelope(source_content_length: int) -> MemoryEnvelope:
    return MemoryEnvelope(
        schema_id="core.memory_envelope",
        schema_version="v1",
        kind="finding",
        scope=MemoryEnvelopeScope(container_ref="test:c"),
        derivation=MemoryEnvelopeDerivation(
            producer_kind="item_extraction",
            producer_schema_id="test",
            producer_schema_version="v1",
        ),
        source_content_length=source_content_length,
    )


def _item(mem_type: str, payload: dict, source_content_length: int) -> QueryResultItem:
    return QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-test",
        type=mem_type,
        payload=payload,
        score=100,
        evidence=[],
        envelope=_envelope(source_content_length),
    )


def _block(item: QueryResultItem) -> object:
    return _build_injectable_block_from_candidate({"item": item}, intent="recall")


# ---------------------------------------------------------------------------
# A. Codec round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("length", "expected"), [
    (0, 0),
    (999, 999),
    (1000, 1000),
    (1001, 1001),
    (5000, 5000),
])
def test_envelope_source_content_length_codec_roundtrip(length: int, expected: int) -> None:
    env = _envelope(length)
    serialized = SQLiteCodecMixin._dump_memory_envelope(env)
    assert serialized is not None
    loaded = SQLiteCodecMixin._load_memory_envelope(serialized)
    assert loaded is not None
    assert loaded.source_content_length == expected


def test_envelope_missing_source_content_length_defaults_to_zero() -> None:
    env = _envelope(500)
    serialized = SQLiteCodecMixin._dump_memory_envelope(env)
    assert serialized is not None
    payload = json.loads(serialized)
    del payload["source_content_length"]
    loaded = SQLiteCodecMixin._load_memory_envelope(json.dumps(payload))
    assert loaded is not None
    assert loaded.source_content_length == 0


def test_envelope_boolean_source_content_length_rejected() -> None:
    env = _envelope(0)
    serialized = SQLiteCodecMixin._dump_memory_envelope(env)
    assert serialized is not None
    payload = json.loads(serialized)
    payload["source_content_length"] = True
    loaded = SQLiteCodecMixin._load_memory_envelope(json.dumps(payload))
    assert loaded is not None
    assert loaded.source_content_length == 0


# ---------------------------------------------------------------------------
# B. Block builder — payload-presence per type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("mem_type", "payload", "expected"), [
    # decision: expand when evidence text present
    ("decision", {"decision": "x", "decision_evidence_text": "verbatim quote"}, True),
    ("decision", {"decision": "x"}, False),
    ("decision", {"decision": "x", "decision_evidence_text": ""}, False),
    # investigation_outcome: expand when evidence text present
    ("investigation_outcome", {"investigation_outcome": "x", "investigation_evidence_text": "verbatim"}, True),
    ("investigation_outcome", {"investigation_outcome": "x"}, False),
    # task_checkpoint: expand when key_findings or work_artifacts present
    ("task_checkpoint", {"summary": "x", "key_findings": ["f1", "f2"]}, True),
    ("task_checkpoint", {"summary": "x", "selected_work_artifacts": [{"text": "a"}]}, True),
    ("task_checkpoint", {"summary": "x"}, False),
    ("task_checkpoint", {"summary": "x", "key_findings": []}, False),
    # thread_summary: expand when conclusions or work_artifacts present
    ("thread_summary", {"summary": "x", "conclusions": [{"type": "t", "text": "c"}]}, True),
    ("thread_summary", {"summary": "x", "selected_work_artifacts": [{"text": "a"}]}, True),
    ("thread_summary", {"summary": "x"}, False),
    # pattern_memory: expand when >1 conclusion
    ("pattern_memory", {"summary": "x", "conclusions": [{"text": "a"}, {"text": "b"}]}, True),
    ("pattern_memory", {"summary": "x", "conclusions": [{"text": "only one"}]}, False),
    ("pattern_memory", {"summary": "x"}, False),
    # constraint_memory: expand when evidence_context present
    ("constraint_memory", {"constraint_text": "x", "evidence_context": "full ctx"}, True),
    ("constraint_memory", {"constraint_text": "x"}, False),
    # types with no expand
    ("fact_summary", {"summary": "x"}, False),
    ("interest", {"interest_text": "x"}, False),
    ("atomic_fact", {"statement": "x"}, False),
])
def test_expand_available_per_type(mem_type: str, payload: dict, expected: bool) -> None:
    item = _item(mem_type, payload, source_content_length=500)
    block = _block(item)
    assert block.expand_available is expected, f"type={mem_type}, payload={payload}"


# ---------------------------------------------------------------------------
# D. source_evidence block — never flagged
# ---------------------------------------------------------------------------

def test_source_evidence_block_never_gets_flag() -> None:
    item = QueryResultItem(
        result_kind="source_hit",
        score=1,
        evidence=[],
        excerpt="short",
    )
    block = _build_injectable_block_from_candidate({"item": item}, intent="recall")
    assert block.expand_available is False


# ---------------------------------------------------------------------------
# E. Null envelope — no flag
# ---------------------------------------------------------------------------

def test_no_flag_when_envelope_is_none() -> None:
    item = QueryResultItem(
        result_kind="memory_hit",
        memory_object_id="mo-x",
        type="investigation_outcome",
        payload={"investigation_outcome": "x", "rationale": "r"},
        score=100,
        evidence=[],
        envelope=None,
    )
    block = _block(item)
    assert block.expand_available is False
