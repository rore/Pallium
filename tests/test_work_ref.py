"""Unit tests for work_ref extraction, normalisation, merge, and storage round-trip."""
from __future__ import annotations

import json

import pytest

from core.models import MemoryEnvelopeScope
from semantic.llm_agent_memory import (
    _normalize_work_ref,
    _normalize_work_refs,
)
from semantic.agent_conversation_memory_memory import (
    WORK_REFS_METADATA_KEY,
    _merge_work_refs,
    _work_refs_from_metadata,
)
from storage.sqlite_codec import SQLiteCodecMixin


class TestNormalizeWorkRef:
    def test_basic_casefold(self):
        assert _normalize_work_ref("PROJ-123") == "proj-123"

    def test_lowercase_passthrough(self):
        assert _normalize_work_ref("proj-123") == "proj-123"

    def test_space_to_hyphen(self):
        assert _normalize_work_ref("PROJ 123") == "proj-123"

    def test_underscore_to_hyphen(self):
        assert _normalize_work_ref("proj_123") == "proj-123"

    def test_mixed_separators(self):
        assert _normalize_work_ref("Proj - 123") == "proj-123"

    def test_multiple_spaces(self):
        assert _normalize_work_ref("PROJ   123") == "proj-123"

    def test_leading_trailing_whitespace(self):
        assert _normalize_work_ref("  PROJ-123  ") == "proj-123"

    def test_slash_preserved(self):
        assert _normalize_work_ref("org/repo#456") == "org/repo#456"

    def test_empty_string(self):
        assert _normalize_work_ref("") is None

    def test_whitespace_only(self):
        assert _normalize_work_ref("   ") is None

    def test_too_long(self):
        assert _normalize_work_ref("A" * 129) is None

    def test_max_length(self):
        result = _normalize_work_ref("A" * 128)
        assert result is not None
        assert len(result) == 128

    def test_separator_only(self):
        assert _normalize_work_ref("---") is None

    def test_leading_trailing_separator_stripped(self):
        assert _normalize_work_ref("-PROJ-123-") == "proj-123"


class TestNormalizeWorkRefs:
    def test_basic_list(self):
        assert _normalize_work_refs(["PROJ-123", "SYNC-42"]) == ("proj-123", "sync-42")

    def test_dedup(self):
        assert _normalize_work_refs(["PROJ-123", "proj-123"]) == ("proj-123",)

    def test_dedup_with_separator_variants(self):
        assert _normalize_work_refs(["PROJ-123", "PROJ 123", "proj_123"]) == ("proj-123",)

    def test_none_input(self):
        assert _normalize_work_refs(None) == ()

    def test_non_list_input(self):
        assert _normalize_work_refs("PROJ-123") == ()

    def test_non_string_items_skipped(self):
        assert _normalize_work_refs(["PROJ-123", 42, None, "SYNC-42"]) == ("proj-123", "sync-42")

    def test_empty_list(self):
        assert _normalize_work_refs([]) == ()

    def test_empty_strings_skipped(self):
        assert _normalize_work_refs(["", "  ", "PROJ-123"]) == ("proj-123",)


class TestMergeWorkRefs:
    def test_merge_two_groups(self):
        assert _merge_work_refs(("a",), ("b",)) == ("a", "b")

    def test_merge_dedup(self):
        assert _merge_work_refs(("a", "b"), ("b", "c")) == ("a", "b", "c")

    def test_merge_preserves_order(self):
        assert _merge_work_refs(("b", "a"), ("c",)) == ("b", "a", "c")

    def test_merge_empty(self):
        assert _merge_work_refs((), ()) == ()

    def test_merge_one_empty(self):
        assert _merge_work_refs(("a",), ()) == ("a",)


class TestWorkRefsFromMetadata:
    def test_reads_from_metadata(self):
        metadata = {WORK_REFS_METADATA_KEY: ["PROJ-123", "SYNC-42"]}
        assert _work_refs_from_metadata(metadata) == ("proj-123", "sync-42")

    def test_none_metadata(self):
        assert _work_refs_from_metadata(None) == ()

    def test_missing_key(self):
        assert _work_refs_from_metadata({"other": "value"}) == ()

    def test_non_list_value(self):
        assert _work_refs_from_metadata({WORK_REFS_METADATA_KEY: "PROJ-123"}) == ()

    def test_normalises_values(self):
        metadata = {WORK_REFS_METADATA_KEY: ["PROJ 123"]}
        assert _work_refs_from_metadata(metadata) == ("proj-123",)


class TestEnvelopeScopeRoundTrip:
    """Verify work_refs survive serialisation through envelope_json."""

    def test_scope_with_work_refs(self):
        scope = MemoryEnvelopeScope(
            container_ref="c1",
            thread_ref="t1",
            work_refs=("proj-123", "sync-42"),
        )
        assert scope.work_refs == ("proj-123", "sync-42")

    def test_scope_default_empty(self):
        scope = MemoryEnvelopeScope(container_ref="c1")
        assert scope.work_refs == ()

    def test_envelope_json_round_trip(self):
        """Full envelope round-trip: build → serialize → deserialize → check work_refs."""
        from core.models import (
            MemoryEnvelope,
            MemoryEnvelopeDerivation,
            MemorySubjectAnchor,
        )

        envelope = MemoryEnvelope(
            schema_id="core.memory_envelope",
            schema_version="v1",
            kind="finding",
            scope=MemoryEnvelopeScope(
                container_ref="c1",
                thread_ref="t1",
                work_refs=("proj-123", "sync-42"),
            ),
            derivation=MemoryEnvelopeDerivation(
                producer_kind="item_extraction",
                producer_schema_id="typed_memory_extraction",
                producer_schema_version="v7",
            ),
            subjects=[MemorySubjectAnchor(kind="workstream", value="auth redesign")],
            confidence="high",
        )

        # Serialize
        serialized = SQLiteCodecMixin._dump_memory_envelope(envelope)
        assert serialized is not None

        # Verify JSON contains work_refs
        raw = json.loads(serialized)
        assert raw["scope"]["work_refs"] == ["proj-123", "sync-42"]

        # Deserialize
        loaded = SQLiteCodecMixin._load_memory_envelope(serialized)
        assert loaded is not None
        assert loaded.scope.work_refs == ("proj-123", "sync-42")
        assert loaded.scope.container_ref == "c1"
        assert loaded.scope.thread_ref == "t1"
        assert loaded.kind == "finding"
        assert len(loaded.subjects) == 1

    def test_envelope_without_work_refs_backward_compat(self):
        """Existing envelopes without work_refs field deserialize with empty tuple."""
        raw_json = json.dumps({
            "schema_id": "core.memory_envelope",
            "schema_version": "v1",
            "kind": "finding",
            "scope": {"container_ref": "c1", "thread_ref": "t1"},
            "derivation": {
                "producer_kind": "item_extraction",
                "producer_schema_id": "test",
                "producer_schema_version": "v1",
            },
            "subjects": [],
            "confidence": "high",
        })
        loaded = SQLiteCodecMixin._load_memory_envelope(raw_json)
        assert loaded is not None
        assert loaded.scope.work_refs == ()
