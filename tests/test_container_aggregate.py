from capabilities.thread_aggregation import ThreadAggregate, build_thread_aggregate
from core.models import SourceItem

def _make_item(source_id: str, content: str, *, thread_ref: str | None = None, container_ref: str = "container-a") -> SourceItem:
    return SourceItem(
        source_type="chat_message",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        role="user",
        artifact_kind="message",
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

def test_build_aggregate_with_mixed_thread_refs():
    items = [
        _make_item("msg-1", "first message", thread_ref="thread-a"),
        _make_item("msg-2", "second message", thread_ref="thread-b"),
        _make_item("msg-3", "third message", thread_ref=None),
    ]
    aggregate = build_thread_aggregate(items, container_scope=True)
    assert aggregate.thread_ref is None
    assert aggregate.container_ref == "container-a"
    assert len(aggregate.source_items) == 3
    assert "first message" in aggregate.aggregate_text
    assert "third message" in aggregate.aggregate_text

def test_build_aggregate_normal_thread_unchanged():
    items = [
        _make_item("msg-1", "first", thread_ref="thread-a"),
        _make_item("msg-2", "second", thread_ref="thread-a"),
    ]
    aggregate = build_thread_aggregate(items)
    assert aggregate.thread_ref == "thread-a"
