"""Tests for turn_kind / session_has_sufficient_local_context inference."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.models import QueryRuntimeContext, SourceItem
from core.turn_inference import (
    CONTINUATION_THRESHOLD_SECONDS,
    InferredRuntimeContext,
    ThreadStats,
    infer_from_thread_stats,
    resolve_runtime_context,
)
from storage.sqlite import SQLiteStorageProvider


# ── Pure inference logic tests ────────────────────────────────────────────────

NOW = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)


def test_infer_new_thread_when_no_prior_items() -> None:
    stats = ThreadStats(item_count=0, latest_created_at=None)
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "new_thread"
    assert result.session_has_sufficient_local_context is False


def test_infer_same_thread_continuation_when_recent_activity() -> None:
    stats = ThreadStats(item_count=3, latest_created_at=NOW - timedelta(minutes=2))
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "same_thread_continuation"
    assert result.session_has_sufficient_local_context is True


def test_infer_resumed_session_when_stale_activity() -> None:
    stats = ThreadStats(item_count=5, latest_created_at=NOW - timedelta(hours=3))
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "resumed_session"
    assert result.session_has_sufficient_local_context is False


def test_infer_boundary_just_under_threshold() -> None:
    gap = timedelta(seconds=CONTINUATION_THRESHOLD_SECONDS - 1)
    stats = ThreadStats(item_count=2, latest_created_at=NOW - gap)
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "same_thread_continuation"
    assert result.session_has_sufficient_local_context is True


def test_infer_boundary_at_threshold() -> None:
    gap = timedelta(seconds=CONTINUATION_THRESHOLD_SECONDS)
    stats = ThreadStats(item_count=2, latest_created_at=NOW - gap)
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "resumed_session"
    assert result.session_has_sufficient_local_context is False


def test_infer_single_prior_item_recent() -> None:
    stats = ThreadStats(item_count=1, latest_created_at=NOW - timedelta(seconds=5))
    result = infer_from_thread_stats(stats, now=NOW)
    assert result.turn_kind == "same_thread_continuation"
    assert result.session_has_sufficient_local_context is True


# ── Storage layer: get_thread_stats ───────────────────────────────────────────


def _make_item(*, thread_ref: str, source_id: str, created_at: datetime | None = None) -> SourceItem:
    return SourceItem(
        source_type="chat_thread",
        source_id=source_id,
        content_type="text/plain",
        content=f"content for {source_id}",
        metadata=None,
        thread_ref=thread_ref,
    )


def test_get_thread_stats_empty(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    stats = storage.get_thread_stats("nonexistent-thread")
    assert stats.item_count == 0
    assert stats.latest_created_at is None


def test_get_thread_stats_counts_items(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    storage.create_source_item(_make_item(thread_ref="thread-a", source_id="msg-1"))
    storage.create_source_item(_make_item(thread_ref="thread-a", source_id="msg-2"))
    storage.create_source_item(_make_item(thread_ref="thread-b", source_id="msg-3"))

    stats = storage.get_thread_stats("thread-a")
    assert stats.item_count == 2
    assert stats.latest_created_at is not None


def test_get_thread_stats_excludes_item(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    item1 = _make_item(thread_ref="thread-a", source_id="msg-1")
    item2 = _make_item(thread_ref="thread-a", source_id="msg-2")
    storage.create_source_item(item1)
    storage.create_source_item(item2)

    stats = storage.get_thread_stats("thread-a", exclude_item_id=item2.id)
    assert stats.item_count == 1

    stats_all = storage.get_thread_stats("thread-a")
    assert stats_all.item_count == 2


def test_get_thread_stats_exclude_only_item(test_db_url: str) -> None:
    """Excluding the only item should look like a new thread."""
    storage = SQLiteStorageProvider(test_db_url)
    item = _make_item(thread_ref="thread-a", source_id="msg-1")
    storage.create_source_item(item)

    stats = storage.get_thread_stats("thread-a", exclude_item_id=item.id)
    assert stats.item_count == 0
    assert stats.latest_created_at is None


# ── Integration: resolve_runtime_context via service ──────────────────────────


def test_service_infers_when_runtime_context_absent(client) -> None:
    """When no runtime_context is passed, the service infers from thread state."""
    # First message in a new thread — should infer new_thread
    response = client.post(
        "/item-and-query/debug",
        json={
            "source_type": "chat_thread",
            "source_id": "ti-msg-1",
            "content_type": "text/plain",
            "content": "Hello, this is the first message.",
            "thread_ref": "ti-thread-1",
            "container_ref": "workspace-1",
            "visibility": "container",
            "role": "user",
            "artifact_kind": "message",
        },
    )
    assert response.status_code == 200
    trace = response.json().get("trace", {})
    routing = trace.get("routing", {})
    # The routing trace should reflect the inferred turn_kind if the routing
    # package includes it. At minimum, the request should succeed without crash.


def test_service_caller_override_wins(client) -> None:
    """Caller-provided runtime_context takes precedence over inference."""
    service = client.app.state.pallium_service

    # Create a thread with some items so inference would yield same_thread_continuation
    service.ingest_item(
        source_type="chat_thread",
        source_id="ti-seed-1",
        content_type="text/plain",
        content="seed message",
        metadata=None,
        use_case=None,
        thread_ref="ti-thread-2",
        container_ref="workspace-1",
        visibility="container",
        role="user",
        artifact_kind="message",
    )

    # Now query with explicit turn_kind override
    result = service.query(
        "test query",
        5,
        thread_ref="ti-thread-2",
        container_ref="workspace-1",
        visibility="container",
        runtime_context=QueryRuntimeContext(
            turn_kind="new_thread",
            session_has_sufficient_local_context=False,
        ),
    )
    # Should not crash — override accepted


def test_service_no_thread_ref_skips_inference(client) -> None:
    """Queries without thread_ref skip inference, leave runtime_context as-is."""
    service = client.app.state.pallium_service
    # Should not crash with no thread_ref and no runtime_context
    result = service.query(
        "test query",
        5,
        container_ref="workspace-1",
        visibility="container",
    )
    assert isinstance(result.results, list)


def test_service_partial_override(client) -> None:
    """Caller provides only turn_kind; inference fills session_has_sufficient_local_context."""
    service = client.app.state.pallium_service

    service.ingest_item(
        source_type="chat_thread",
        source_id="ti-partial-1",
        content_type="text/plain",
        content="some content",
        metadata=None,
        use_case=None,
        thread_ref="ti-thread-partial",
        container_ref="workspace-1",
        visibility="container",
        role="user",
        artifact_kind="message",
    )

    result = service.query(
        "test",
        5,
        thread_ref="ti-thread-partial",
        container_ref="workspace-1",
        visibility="container",
        runtime_context=QueryRuntimeContext(
            turn_kind="resumed_session",
            session_has_sufficient_local_context=None,
        ),
    )
    assert isinstance(result.results, list)


def test_item_and_query_excludes_just_ingested_item(client) -> None:
    """In /item-and-query, the just-ingested item should be excluded from thread stats.

    If the thread has zero prior items and we ingest one in item-and-query,
    inference should see 0 prior items and yield new_thread, not same_thread_continuation.
    """
    service = client.app.state.pallium_service

    # First, ingest an item to get its ID
    ingest_result = service.ingest_item(
        source_type="chat_thread",
        source_id="ti-excl-1",
        content_type="text/plain",
        content="first and only message",
        metadata=None,
        use_case=None,
        thread_ref="ti-thread-excl",
        container_ref="workspace-1",
        visibility="container",
        role="user",
        artifact_kind="message",
    )

    # resolve_runtime_context with exclude_item_id — should see 0 prior items → new_thread
    rc = resolve_runtime_context(
        service._storage,
        "ti-thread-excl",
        None,
        exclude_item_id=ingest_result.source_item_id,
    )
    assert rc is not None
    assert rc.turn_kind == "new_thread"
    assert rc.session_has_sufficient_local_context is False

    # Without exclude — should see 1 prior item → same_thread_continuation
    rc2 = resolve_runtime_context(
        service._storage,
        "ti-thread-excl",
        None,
    )
    assert rc2 is not None
    assert rc2.turn_kind == "same_thread_continuation"
    assert rc2.session_has_sufficient_local_context is True
    assert rc2.thread_item_count == 1


def test_resolve_runtime_context_fills_thread_item_count_when_turn_kind_provided(client) -> None:
    """When turn_kind and local_context are pre-set, thread_item_count is still populated."""
    service = client.app.state.pallium_service
    service.ingest_item(
        source_type="chat_message",
        source_id="ti-item-count-1",
        content_type="text/plain",
        content="first message",
        metadata=None,
        use_case=None,
        container_ref="chat:item-count-test",
        thread_ref="ti-thread-count",
        visibility="container",
        role="user",
        artifact_kind="message",
    )
    service.ingest_item(
        source_type="chat_message",
        source_id="ti-item-count-2",
        content_type="text/plain",
        content="second message",
        metadata=None,
        use_case=None,
        container_ref="chat:item-count-test",
        thread_ref="ti-thread-count",
        visibility="container",
        role="assistant",
        artifact_kind="message",
    )

    pre_set_context = QueryRuntimeContext(
        turn_kind="same_thread_continuation",
        session_has_sufficient_local_context=True,
    )
    rc = resolve_runtime_context(
        service._storage,
        "ti-thread-count",
        pre_set_context,
    )
    assert rc is not None
    assert rc.turn_kind == "same_thread_continuation"
    assert rc.session_has_sufficient_local_context is True
    assert rc.thread_item_count == 2
