"""Unit tests for work_ref extraction, normalisation, merge, and storage round-trip."""
from __future__ import annotations

import json

import pytest

from core.models import MemoryEnvelopeScope
from core.service import _sanitize_work_ref_metadata
from semantic.llm_agent_memory import (
    _normalize_extraction,
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


class TestIngestWorkRefSanitization:
    def test_sanitizes_key_only_and_preserves_other_metadata(self):
        metadata = {
            "pallium_work_refs": ["PROJ 1", "ghp_abcdefghijklmnopqrstuvwxyz1234567890"],
            "other": {"keep": "value"},
        }
        result = _sanitize_work_ref_metadata(metadata)
        assert result == {"pallium_work_refs": ["proj-1"], "other": {"keep": "value"}}
        assert metadata["other"] == {"keep": "value"}

    def test_invalid_work_ref_key_is_removed_without_touching_note_metadata(self):
        metadata = {"pallium_work_refs": "PROJ-1", "content_hint": "verbatim"}
        assert _sanitize_work_ref_metadata(metadata) == {"content_hint": "verbatim"}


class TestSourceIdFilter:
    """Verify that _normalize_extraction filters work_refs matching the source_id."""

    def test_source_id_filtered_from_work_refs(self):
        extraction = _normalize_extraction(
            {"summary": "Test", "work_refs": ["investigation-003", "PROJ-123"]},
            source_id="investigation-003",
        )
        assert extraction.work_refs == ("proj-123",)

    def test_source_id_not_filtered_when_different(self):
        extraction = _normalize_extraction(
            {"summary": "Test", "work_refs": ["PROJ-123"]},
            source_id="investigation-003",
        )
        assert extraction.work_refs == ("proj-123",)

    def test_no_source_id_no_filtering(self):
        extraction = _normalize_extraction(
            {"summary": "Test", "work_refs": ["investigation-003"]},
        )
        assert extraction.work_refs == ("investigation-003",)

    def test_source_id_case_insensitive_match(self):
        extraction = _normalize_extraction(
            {"summary": "Test", "work_refs": ["INVESTIGATION-003"]},
            source_id="investigation-003",
        )
        assert extraction.work_refs == ()


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

    def test_metadata_precedes_extracted_and_caps_at_five(self):
        assert _merge_work_refs(("meta-1", "meta-2"), tuple(f"x-{i}" for i in range(5))) == (
            "meta-1", "meta-2", "x-0", "x-1", "x-2"
        )


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


# ---------------------------------------------------------------------------
# Pipeline integration: extraction → envelope → metadata
# ---------------------------------------------------------------------------

from providers.llm.base import LLMCallMetadata, LLMJsonResponse
from semantic.llm_agent_memory import LLMAgentMemoryPlugin
from semantic.agent_conversation_memory_memory import (
    _apply_direct_memory_envelopes,
)
from semantic.common import SemanticExtraction
from core.models import SourceItem


class _StubLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        return LLMJsonResponse(
            raw_text="{}",
            metadata=LLMCallMetadata(provider_name="stub", provider_kind="stub", model="stub"),
            parsed_json={
                "summary": "Decision about LIB-241 schema change",
                "candidate_type": "decision",
                "decision_text": "use event-time ordering for LIB-241",
                "decision_evidence_text": "Decision: use event-time ordering for LIB-241 to avoid duplicate holds during concurrent sync operations across all background worker instances.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "interest_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
                "subject_hints": [],
                "work_refs": ["LIB-241"],
            },
        )


class TestExtractionToEnvelopePipeline:
    """Integration test: LLM extraction with work_refs → memory envelope → metadata."""

    def test_work_refs_flow_through_extraction_to_envelope(self):
        plugin = LLMAgentMemoryPlugin(provider=_StubLLMProvider())
        source_item = SourceItem(
            source_type="assistant_artifact",
            source_id="test-decision-001",
            content_type="text/plain",
            content="Decision: use event-time ordering for LIB-241 to avoid duplicate holds during concurrent sync operations across all background worker instances.",
            artifact_kind="assistant_output",
            role="user",
            container_ref="chat:library-help",
            thread_ref="chat:library-help:thread-001",
        )

        result = plugin.process_item(source_item)

        # Apply envelopes (same as production pipeline)
        extraction = SemanticExtraction(
            summary="Decision about LIB-241",
            candidate_type="decision",
            work_refs=("lib-241",),
        )
        enveloped = _apply_direct_memory_envelopes(result, source_item=source_item, extraction=extraction)

        # Memory object should have work_refs in envelope scope
        assert len(enveloped.memory_objects) > 0
        mem = enveloped.memory_objects[0]
        assert mem.envelope is not None
        assert mem.envelope.scope.work_refs == ("lib-241",)

        # Source item metadata should have work_refs persisted
        metadata_updates = enveloped.source_item_metadata_updates.get(source_item.id, {})
        assert WORK_REFS_METADATA_KEY in metadata_updates
        assert "lib-241" in metadata_updates[WORK_REFS_METADATA_KEY]

    def test_runtime_hints_merge_with_extraction(self):
        plugin = LLMAgentMemoryPlugin(provider=_StubLLMProvider())
        source_item = SourceItem(
            source_type="assistant_artifact",
            source_id="test-decision-002",
            content_type="text/plain",
            content="Decision: use event-time ordering for LIB-241 to avoid duplicate holds during concurrent sync operations across all background worker instances.",
            artifact_kind="assistant_output",
            role="user",
            container_ref="chat:library-help",
            thread_ref="chat:library-help:thread-001",
            metadata={WORK_REFS_METADATA_KEY: ["SYNC-42"]},  # runtime hint
        )

        result = plugin.process_item(source_item)

        extraction = SemanticExtraction(
            summary="Decision about LIB-241",
            candidate_type="decision",
            work_refs=("lib-241",),  # LLM extracted
        )
        enveloped = _apply_direct_memory_envelopes(result, source_item=source_item, extraction=extraction)

        # Should have both LLM-extracted and runtime hint refs
        mem = enveloped.memory_objects[0]
        assert "lib-241" in mem.envelope.scope.work_refs
        assert "sync-42" in mem.envelope.scope.work_refs

    def test_empty_work_refs_no_metadata_entry(self):
        """When no work_refs extracted, no metadata key should be added."""

        class _EmptyWorkRefsProvider:
            def generate_json(self, **kwargs) -> LLMJsonResponse:
                return LLMJsonResponse(
                    raw_text="{}",
                    metadata=LLMCallMetadata(provider_name="stub", provider_kind="stub", model="stub"),
                    parsed_json={
                        "summary": "General discussion",
                        "candidate_type": None,
                        "is_low_value_meta": False,
                        "work_refs": [],
                    },
                )

        plugin = LLMAgentMemoryPlugin(provider=_EmptyWorkRefsProvider())
        source_item = SourceItem(
            source_type="chat_message",
            source_id="test-msg-001",
            content_type="text/plain",
            content="The admin toggle wiring is ready.",
            artifact_kind="message",
            role="user",
        )

        result = plugin.process_item(source_item)
        extraction = SemanticExtraction(summary="General discussion", work_refs=())
        enveloped = _apply_direct_memory_envelopes(result, source_item=source_item, extraction=extraction)

        metadata_updates = enveloped.source_item_metadata_updates.get(source_item.id, {})
        assert WORK_REFS_METADATA_KEY not in metadata_updates


# ---------------------------------------------------------------------------
# Slice 2: Routing integration tests
# ---------------------------------------------------------------------------

from core.models import (
    EvidenceReference,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    QueryFilters,
    QueryResultItem,
)
from semantic.agent_conversation_memory_routing_constants import (
    _candidate_work_refs,
    _candidate_matches_work_ref,
)
from semantic.agent_conversation_memory_routing import (
    _detect_query_work_refs,
)


def _make_query_result_item(
    *,
    work_refs: tuple[str, ...] = (),
    thread_ref: str | None = None,
    container_ref: str | None = None,
    result_kind: str = "memory_hit",
    memory_type: str = "decision",
) -> QueryResultItem:
    """Create a minimal QueryResultItem for routing tests."""
    envelope = MemoryEnvelope(
        schema_id="core.memory_envelope",
        schema_version="v1",
        kind="finding",
        scope=MemoryEnvelopeScope(
            container_ref=container_ref,
            thread_ref=thread_ref,
            work_refs=work_refs,
        ),
        derivation=MemoryEnvelopeDerivation(
            producer_kind="item_extraction",
            producer_schema_id="test",
            producer_schema_version="v1",
        ),
    )
    return QueryResultItem(
        result_kind=result_kind,
        score=100,
        evidence=[],
        result_id="test-id",
        memory_object_id="test-mem-id",
        type=memory_type,
        payload={},
        envelope=envelope,
        container_ref=container_ref,
        thread_ref=thread_ref,
    )


class TestCandidateWorkRefs:
    def test_extracts_from_envelope(self):
        item = _make_query_result_item(work_refs=("proj-123", "sync-42"))
        assert _candidate_work_refs(item) == ("proj-123", "sync-42")

    def test_empty_when_no_envelope(self):
        item = QueryResultItem(
            result_kind="memory_hit",
            score=100,
            evidence=[],
            result_id="test",
            type="decision",
            payload={},
            envelope=None,
        )
        assert _candidate_work_refs(item) == ()

    def test_empty_when_no_work_refs(self):
        item = _make_query_result_item(work_refs=())
        assert _candidate_work_refs(item) == ()


class TestCandidateMatchesWorkRef:
    def test_matches_when_shared(self):
        item = _make_query_result_item(work_refs=("proj-123",))
        filters = QueryFilters(work_refs=("proj-123",))
        assert _candidate_matches_work_ref(item, filters) is True

    def test_no_match_when_different(self):
        item = _make_query_result_item(work_refs=("proj-123",))
        filters = QueryFilters(work_refs=("sync-42",))
        assert _candidate_matches_work_ref(item, filters) is False

    def test_no_match_when_filters_empty(self):
        item = _make_query_result_item(work_refs=("proj-123",))
        filters = QueryFilters()
        assert _candidate_matches_work_ref(item, filters) is False

    def test_no_match_when_no_filters(self):
        item = _make_query_result_item(work_refs=("proj-123",))
        assert _candidate_matches_work_ref(item, None) is False

    def test_partial_overlap_matches(self):
        item = _make_query_result_item(work_refs=("proj-123", "sync-42"))
        filters = QueryFilters(work_refs=("sync-42", "other-99"))
        assert _candidate_matches_work_ref(item, filters) is True


class TestDetectQueryWorkRefs:
    def test_detects_from_query_text(self):
        item = _make_query_result_item(work_refs=("lib-241",))
        result = _detect_query_work_refs(
            "What state were we in on ticket LIB-241?",
            [item],
            None,
        )
        assert result is not None
        assert "lib-241" in result.work_refs

    def test_preserves_existing_work_refs(self):
        item = _make_query_result_item(work_refs=("lib-241",))
        filters = QueryFilters(work_refs=("already-set",))
        result = _detect_query_work_refs(
            "What about LIB-241?",
            [item],
            filters,
        )
        assert result is not None
        assert result.work_refs == ("already-set",)

    def test_no_detection_when_no_candidates(self):
        result = _detect_query_work_refs("What about LIB-241?", [], None)
        assert result is None

    def test_no_detection_when_ref_not_in_query(self):
        item = _make_query_result_item(work_refs=("lib-241",))
        result = _detect_query_work_refs(
            "What is the status of the catalog sync?",
            [item],
            None,
        )
        assert result is None

    def test_detection_case_insensitive(self):
        item = _make_query_result_item(work_refs=("proj-123",))
        result = _detect_query_work_refs(
            "Continue work on PROJ 123",
            [item],
            None,
        )
        assert result is not None
        assert "proj-123" in result.work_refs
