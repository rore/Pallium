"""Tests for the constraint text quality gate.

Covers:
- _should_reject_constraint_text rejects known bad inputs (vague, anaphoric)
- _should_reject_constraint_text accepts known good inputs (specific, actionable)
- Integration: vague constraint_text produces no constraint_memory objects
- Integration: good constraint_text still produces constraint_memory objects
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from semantic.agent_conversation_memory_memory import _append_typed_constraint_memory_objects
from semantic.common import _should_reject_constraint_text, SemanticExtraction
from core.contracts import ProcessResult
from core.models import SourceItem
from tests.config_helpers import build_agent_conversation_client

CONTAINER = "chat:private-dm"
THREAD = "chat:thread-quality"


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    return build_agent_conversation_client(monkeypatch, sqlite_url)


# ---------------------------------------------------------------------------
# Unit tests: _should_reject_constraint_text rejects bad inputs
# ---------------------------------------------------------------------------


class TestRejectBadInputs:
    """Known bad inputs that should be rejected by the quality gate."""

    def test_rejects_too_short_text(self):
        """'on windows' is only 10 chars normalized — too short to be a constraint."""
        assert _should_reject_constraint_text("on windows") is True

    def test_rejects_anaphoric_its_not_allowed(self):
        """'its' not allowed' — only 'allowed' remains after stopwords, which is a generic verb."""
        assert _should_reject_constraint_text("its' not allowed") is True

    def test_rejects_anaphoric_never_do_that(self):
        """'never do that' — 'never' is a stopword, 'do' is generic, 'that' is anaphoric."""
        assert _should_reject_constraint_text("never do that") is True

    def test_rejects_vague_dont_want_to_do_it(self):
        """'i don't want to do it yet' — 'want' is generic, 'yet' is a stopword."""
        assert _should_reject_constraint_text("i don't want to do it yet") is True


# ---------------------------------------------------------------------------
# Unit tests: _should_reject_constraint_text accepts good inputs
# ---------------------------------------------------------------------------


class TestAcceptGoodInputs:
    """Known good inputs that must NOT be rejected."""

    def test_accepts_specific_name_constraint(self):
        assert _should_reject_constraint_text("do not use the name muxi in pallium documentation") is False

    def test_accepts_never_add_llm_calls(self):
        assert _should_reject_constraint_text("never add new llm calls to the extraction pipeline") is False

    def test_accepts_always_architect_review(self):
        assert _should_reject_constraint_text("always do an architect review before merging") is False

    def test_accepts_dont_add_llm_calls(self):
        assert _should_reject_constraint_text("don't add additional llm calls") is False

    def test_accepts_feedback_not_at_query_time(self):
        assert _should_reject_constraint_text("feedback is not intended to be used at query time") is False

    def test_accepts_percentage_baseline(self):
        assert _should_reject_constraint_text("5% overhead is the accepted baseline cost for Pallium") is False


# ---------------------------------------------------------------------------
# Integration: vague constraint produces no memory objects
# ---------------------------------------------------------------------------


def _make_source_item(source_id: str, content: str) -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        container_ref=CONTAINER,
        thread_ref=THREAD,
        visibility="private",
    )


def test_vague_constraint_produces_no_memory_objects():
    """Calling _append_typed_constraint_memory_objects with vague text returns empty result."""
    source_item = _make_source_item("vague-1", "on windows it doesn't work")
    extraction = SemanticExtraction(
        summary="some summary",
        constraint_text="on windows",
    )
    result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
    updated = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
    constraint_memories = [m for m in updated.memory_objects if m.type == "constraint_memory"]
    assert not constraint_memories, (
        f"Vague constraint text should not produce memory objects, but found: {constraint_memories}"
    )


def test_good_constraint_produces_memory_object():
    """Calling _append_typed_constraint_memory_objects with specific text creates a constraint_memory."""
    source_item = _make_source_item("good-1", "never add new llm calls to the extraction pipeline")
    extraction = SemanticExtraction(
        summary="some summary",
        constraint_text="never add new llm calls to the extraction pipeline",
    )
    result = ProcessResult(memory_objects=[], relations=[], index_entries=[])
    updated = _append_typed_constraint_memory_objects(result, source_item=source_item, extraction=extraction)
    constraint_memories = [m for m in updated.memory_objects if m.type == "constraint_memory"]
    assert len(constraint_memories) == 1, (
        f"Good constraint text should produce exactly one constraint_memory, "
        f"got {len(constraint_memories)}"
    )


# ---------------------------------------------------------------------------
# Integration: full pipeline test via HTTP client
# ---------------------------------------------------------------------------


def test_vague_constraint_rejected_via_full_pipeline(monkeypatch, test_db_url: str) -> None:
    """Vague constraint text ingested via HTTP should not produce constraint_memory."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "vague-pipeline-1",
            "content_type": "text/plain",
            "content": "its' not allowed to do that here",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER,
            "thread_ref": THREAD,
            "visibility": "private",
            "occurred_at": "2026-04-01T10:00:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        constraint_memories = [m for m in active_memories if m.type == "constraint_memory"]
        assert not constraint_memories, (
            f"Vague constraint text should not create constraint_memory via pipeline, "
            f"but found: {[m.payload for m in constraint_memories]}"
        )


def test_specific_constraint_accepted_via_full_pipeline(monkeypatch, test_db_url: str) -> None:
    """Specific constraint text ingested via HTTP should produce constraint_memory."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "specific-pipeline-1",
            "content_type": "text/plain",
            "content": "Important: do not use the name muxi in pallium documentation or any public code",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER,
            "thread_ref": THREAD,
            "visibility": "private",
            "occurred_at": "2026-04-01T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        constraint_memories = [m for m in active_memories if m.type == "constraint_memory"]
        assert constraint_memories, (
            f"Specific constraint text should create constraint_memory via pipeline, "
            f"but only found types: {[m.type for m in active_memories]}"
        )
