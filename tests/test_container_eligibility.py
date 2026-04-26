from core.models import SourceItem

def _make_item(*, thread_ref=None, container_ref="container-a", role="user", artifact_kind="message"):
    return SourceItem(
        source_type="chat_message",
        source_id="test-1",
        content_type="text/plain",
        content="test content",
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        visibility="private",
        processing_status="completed",
    )

def test_fact_extraction_eligible_without_thread_ref():
    from semantic.conversational_knowledge import _is_eligible_for_fact_extraction
    item = _make_item(thread_ref=None, container_ref="container-a")
    assert _is_eligible_for_fact_extraction(item) is True

def test_fact_extraction_still_requires_container_ref():
    from semantic.conversational_knowledge import _is_eligible_for_fact_extraction
    item = _make_item(thread_ref=None, container_ref=None)
    assert _is_eligible_for_fact_extraction(item) is False

def test_agent_memory_plugin_eligible_without_thread_ref():
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    plugin = AgentConversationMemoryPlugin.__new__(AgentConversationMemoryPlugin)
    item = _make_item(thread_ref=None, container_ref="container-a")
    assert plugin.supports_thread_aggregation(item) is True

def test_agent_memory_plugin_still_requires_container_ref():
    from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
    plugin = AgentConversationMemoryPlugin.__new__(AgentConversationMemoryPlugin)
    item = _make_item(thread_ref=None, container_ref=None)
    assert plugin.supports_thread_aggregation(item) is False
