from __future__ import annotations

import pytest

from core.models import SourceItem
from providers.llm.base import LLMJsonResponse, LLMProviderError
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


class StubLLMProvider:
    def __init__(self, *, response: LLMJsonResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_llm_plugin_promotes_decision_memory_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Decision discussion","candidate_type":"decision","decision_text":"use event timestamp watermarking","rationale_text":"to avoid skipped records"}',
                parsed_json={
                    "summary": "Decision discussion",
                    "candidate_type": "decision",
                    "decision_text": "use event timestamp watermarking",
                    "rationale_text": "to avoid skipped records",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-123",
        content_type="text/plain",
        content="Decision: use event timestamp watermarking for exports to avoid skipped records.",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 2
    assert result.memory_objects[0].type == "decision"
    assert result.memory_objects[0].schema_id == "llm.decision"
    assert result.memory_objects[0].payload["decision"] == "use event timestamp watermarking"


def test_llm_plugin_falls_back_to_discussion_summary_for_non_decision_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"We discussed watermarking","candidate_type":null,"decision_text":null,"rationale_text":null}',
                parsed_json={
                    "summary": "We discussed watermarking",
                    "candidate_type": None,
                    "decision_text": None,
                    "rationale_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-123",
        content_type="text/plain",
        content="We discussed watermarking options today.",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 1
    assert result.memory_objects[0].type == "discussion_summary"
    assert result.memory_objects[0].schema_id == "llm.discussion_summary"


def test_llm_plugin_raises_on_invalid_output() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            error=LLMProviderError("malformed output")
        )
    )
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-456",
        content_type="text/plain",
        content="Decision: use event timestamp watermarking for exports to avoid skipped records.",
    )

    with pytest.raises(LLMProviderError):
        plugin.process_item(source_item)
