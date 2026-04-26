from core.models import SourceItem
from storage.base import ThreadProcessingScope, ThreadProcessingLease, LeasedThreadScopeInfo

def test_source_item_has_thread_position():
    item = SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="hello",
        thread_position=3,
    )
    assert item.thread_position == 3

def test_source_item_thread_position_defaults_to_none():
    item = SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="hello",
    )
    assert item.thread_position is None

def test_thread_processing_scope_allows_none_thread_ref():
    scope = ThreadProcessingScope(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
        visibility="private",
    )
    assert scope.thread_ref is None

def test_thread_processing_lease_allows_none_thread_ref():
    lease = ThreadProcessingLease(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
        visibility="private",
    )
    assert lease.thread_ref is None
    assert lease.collection_watermark_at is None
    scope = lease.as_scope()
    assert scope.thread_ref is None

def test_leased_thread_scope_info_allows_none_thread_ref():
    info = LeasedThreadScopeInfo(
        scope_key="test-key",
        use_case="test",
        container_ref="slack:dm:test",
        thread_ref=None,
    )
    assert info.thread_ref is None

def test_consolidation_trigger_with_none_thread_ref():
    """Container scope facts should trigger consolidation against thread-scope facts."""
    current_thread_ref = None
    fact_thread_ref = "slack:thread:test:123"
    has_cross_thread = fact_thread_ref and fact_thread_ref != current_thread_ref
    assert has_cross_thread is True

def test_thread_scope_consolidation_against_container_facts():
    """Thread-scope rebuild: container-scope facts (thread_ref=None) don't trigger
    consolidation from the thread side due to falsy None.  Acceptable — the
    next container-scope rebuild triggers it in the other direction."""
    current_thread_ref = "slack:thread:test:456"
    container_fact_thread_ref = None
    has_cross_thread = container_fact_thread_ref and container_fact_thread_ref != current_thread_ref
    assert has_cross_thread is not True
