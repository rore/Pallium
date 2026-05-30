"""Round-trip test for MemoryEnvelopeScope.workstream_id (Phase 4A, design 014).

Confirms:
1. New envelope JSON with ``workstream_id`` round-trips cleanly.
2. Legacy envelope JSON without ``workstream_id`` decodes cleanly with
   ``workstream_id=None``.
"""
from __future__ import annotations

import json

from core.models import (
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemorySubjectAnchor,
)
from storage.sqlite_codec import SQLiteCodecMixin


_DERIVATION = MemoryEnvelopeDerivation(
    producer_kind="thread_aggregation",
    producer_schema_id="x:test/y",
    producer_schema_version="1.0",
)


def _envelope(workstream_id: str | None) -> MemoryEnvelope:
    return MemoryEnvelope(
        schema_id="core.memory_envelope",
        schema_version="v1",
        kind="finding",
        scope=MemoryEnvelopeScope(
            container_ref="c1", thread_ref="t1", workstream_id=workstream_id
        ),
        derivation=_DERIVATION,
        subjects=[MemorySubjectAnchor(kind="workstream", value="rekey design")],
        confidence="medium",
        source_content_length=42,
    )


def test_envelope_roundtrip_with_workstream_id():
    env_in = _envelope("ws:abc123def456")
    raw = SQLiteCodecMixin._dump_memory_envelope(env_in)
    env_out = SQLiteCodecMixin._load_memory_envelope(raw)
    assert env_out is not None
    assert env_out.scope.workstream_id == "ws:abc123def456"
    assert env_out.scope.container_ref == "c1"


def test_envelope_roundtrip_without_workstream_id():
    env_in = _envelope(None)
    raw = SQLiteCodecMixin._dump_memory_envelope(env_in)
    env_out = SQLiteCodecMixin._load_memory_envelope(raw)
    assert env_out is not None
    assert env_out.scope.workstream_id is None


def test_legacy_envelope_decodes_cleanly():
    """Legacy on-disk envelope JSON has no ``workstream_id`` field — must
    decode without error and produce ``workstream_id=None``."""
    legacy_payload = {
        "schema_id": "core.memory_envelope",
        "schema_version": "v1",
        "kind": "finding",
        "scope": {
            "container_ref": "c1",
            "thread_ref": "t1",
            "work_refs": ["proj-123"],
            # NOTE: no workstream_id key — must be tolerated
        },
        "derivation": {
            "producer_kind": "thread_aggregation",
            "producer_schema_id": "x:test/y",
            "producer_schema_version": "1.0",
            "prompt_variant": None,
            "model_role": None,
            "kind_basis": None,
        },
        "subjects": [],
        "confidence": "medium",
        "source_content_length": 0,
    }
    raw = json.dumps(legacy_payload)
    env = SQLiteCodecMixin._load_memory_envelope(raw)
    assert env is not None
    assert env.scope.workstream_id is None
    assert env.scope.work_refs == ("proj-123",)


def test_dump_includes_workstream_id_field():
    env = _envelope("ws:somewhere")
    raw = SQLiteCodecMixin._dump_memory_envelope(env)
    parsed = json.loads(raw)
    assert parsed["scope"]["workstream_id"] == "ws:somewhere"
