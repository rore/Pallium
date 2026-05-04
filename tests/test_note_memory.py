import pytest
from api.schemas import ArtifactKind
from typing import get_args
from core.models import SourceItem


def _make_source_item(
    content: str,
    *,
    artifact_kind: str = "note",
    container_ref: str = "git:test/repo",
    actor_ref: str = "user:test",
    visibility: str = "private",
    role: str = "user",
    source_id: str = "test-source-1",
    thread_ref: str = "test-thread-1",
) -> SourceItem:
    return SourceItem(
        source_type="agent_artifact",
        source_id=source_id,
        content_type="text/plain",
        content=content,
        artifact_kind=artifact_kind,
        role=role,
        container_ref=container_ref,
        actor_ref=actor_ref,
        thread_ref=thread_ref,
        visibility=visibility,
    )


def test_note_is_valid_artifact_kind():
    valid_kinds = get_args(ArtifactKind)
    assert "note" in valid_kinds


from unittest.mock import MagicMock
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin


def test_plugin_process_item_note_uses_dedicated_prompt():
    """Note artifact_kind triggers the dedicated note prompt, not standard extraction."""
    mock_provider = MagicMock()
    # Mock LLM response — the exact structure depends on eval-chosen variant.
    # At minimum, the prompt returns {"title": ...}. Other fields are variant-dependent.
    mock_provider.generate_json.return_value = MagicMock(
        parsed_json={"title": "BM25 floor gate threshold info"},
        metadata={},
    )
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    source_item = _make_source_item(
        "Remember: the BM25 floor gate threshold is 12, precision went from 18% to 52.7%"
    )

    result = plugin.process_item(source_item)

    # LLM SHOULD be called — but with the note extraction prompt, not the standard one
    mock_provider.generate_json.assert_called_once()
    call_kwargs = mock_provider.generate_json.call_args
    system_prompt = call_kwargs[1].get("system_prompt") or call_kwargs[0][0]
    assert "title" in system_prompt.lower()
    assert "candidate_type" not in system_prompt  # NOT the standard extraction prompt

    # Should produce a note memory object with original content preserved
    assert len(result.memory_objects) == 1
    assert result.memory_objects[0].type == "note"
    assert "BM25 floor gate" in result.memory_objects[0].payload["content"]
    assert result.memory_objects[0].payload["title"] == "BM25 floor gate threshold info"


from core.type_registry import TypeRegistry


def test_note_type_registered_in_routing():
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    registry = TypeRegistry()
    plugin.register_routing_types(registry)

    assert "note" in registry
    reg = registry.get("note")
    assert reg is not None
    assert reg.high_value is True
    assert reg.block_title == "Note"
    assert reg.block_text_field == "content"


from semantic.agent_conversation_memory_routing_constants import (
    STRUCTURED_LAYERS,
    ROUTING_LAYER_WEIGHTS,
    ROUTING_PREFERRED_LAYERS,
    ROUTING_SAFE_FALLBACK_LAYERS,
)


def test_note_in_structured_layers():
    assert "note" in STRUCTURED_LAYERS


def test_note_in_routing_layer_weights():
    for intent in ("recall", "structured_recall", "work_resumption", "evidence_trace"):
        assert "note" in ROUTING_LAYER_WEIGHTS[intent], f"note missing from {intent} weights"


def test_note_in_routing_preferred_layers():
    for intent in ("recall", "structured_recall", "work_resumption", "evidence_trace"):
        assert "note" in ROUTING_PREFERRED_LAYERS[intent], f"note missing from {intent} preferred layers"


from core.models import QueryResultItem
from semantic.agent_conversation_memory_routing_selection import _build_raw_injectable_block


def test_note_injectable_block_short_content():
    """Short notes render full content, no source expansion needed."""
    item = QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id="test-note-id",
        type="note",
        payload={"content": "Full note content here", "title": "My Note Title"},
    )
    candidate = {"item": item, "layer": "note", "final_score": 100}
    block = _build_raw_injectable_block(candidate, intent="recall")

    assert block.title == "Note: My Note Title"
    assert block.text == "Full note content here"
    assert block.memory_object_id == "test-note-id"
    assert block.source_expanded_available is False  # short note — full content already shown


def test_note_injectable_block_big_content_truncated():
    """Big notes show title + snippet + source pointer instead of full content."""
    long_content = "A" * 1000  # well above threshold
    item = QueryResultItem(
        result_kind="memory_hit",
        score=100.0,
        evidence=[],
        memory_object_id="test-note-id",
        type="note",
        payload={"content": long_content, "title": "Long Procedure"},
    )
    candidate = {"item": item, "layer": "note", "final_score": 100}
    block = _build_raw_injectable_block(candidate, intent="recall")

    assert block.title == "Note: Long Procedure"
    # Should NOT contain the full 1000 chars
    assert len(block.text) < 700
    # Should contain a truncated snippet
    assert "AAA" in block.text
    # Should signal that full content is available via get_evidence
    assert block.source_expanded_available is True


def test_note_in_durable_retention_types():
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    policy = plugin.memory_retention_policy
    assert "note" in policy.durable_types


def test_note_excluded_from_consolidation():
    """Notes are standalone — they must not participate in thread consolidation."""
    mock_provider = MagicMock()
    plugin = AgentConversationMemoryPlugin(
        provider=mock_provider,
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    from core.models import MemoryObject
    note_mo = MemoryObject(
        type="note",
        schema_id="agent_conversation_memory.note",
        schema_version="1",
        payload={"content": "test", "title": "test"},
        container_ref="git:test/repo",
        visibility="private",
    )
    assert plugin.supports_consolidation(note_mo) is False
