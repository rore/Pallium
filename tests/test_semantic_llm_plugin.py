from __future__ import annotations

import pytest

from core.models import SourceItem
from providers.llm.base import LLMJsonResponse, LLMProviderError
from semantic.llm_agent_memory import LLMAgentMemoryPlugin, build_analysis_request


class StubLLMProvider:
    def __init__(self, *, response: LLMJsonResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.last_system_prompt: str | None = None

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.last_system_prompt = system_prompt
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_llm_plugin_promotes_decision_memory_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Decision discussion","candidate_type":"decision","decision_text":"use event timestamp watermarking","decision_evidence_text":"Decision: use event timestamp watermarking","investigation_text":null,"investigation_evidence_text":null,"rationale_text":"to avoid skipped records"}',
                parsed_json={
                    "summary": "Decision discussion",
                    "candidate_type": "decision",
                    "decision_text": "use event timestamp watermarking",
                    "decision_evidence_text": "Decision: use event timestamp watermarking",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
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
    assert result.memory_objects[0].payload["decision_evidence_text"] == "Decision: use event timestamp watermarking"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_id"] == "typed_memory_extraction"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_version"] == "v3"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_variant"] == "strict_decision_v2_source_aware"


def test_llm_plugin_promotes_investigation_outcome_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Investigation summary","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"ingestion-time progress tracking skipped records during lag","investigation_evidence_text":"Investigation found that ingestion-time progress tracking skipped records during lag","rationale_text":"because EventHub lag delayed ingestion"}',
                parsed_json={
                    "summary": "Investigation summary",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "ingestion-time progress tracking skipped records during lag",
                    "investigation_evidence_text": "Investigation found that ingestion-time progress tracking skipped records during lag",
                    "rationale_text": "because EventHub lag delayed ingestion",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-123",
        content_type="text/plain",
        content="Investigation found that ingestion-time progress tracking skipped records during lag.",
        artifact_kind="tool_use_summary",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 2
    assert result.memory_objects[0].type == "investigation_outcome"
    assert result.memory_objects[0].payload["investigation_outcome"] == "ingestion-time progress tracking skipped records during lag"
    assert result.memory_objects[0].payload["investigation_evidence_text"] == "Investigation found that ingestion-time progress tracking skipped records during lag"


def test_llm_plugin_uses_discussion_summary_when_typed_output_lacks_evidence_text() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"We discussed watermarking","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"ingestion-time progress tracking skipped records","investigation_evidence_text":null,"rationale_text":null}',
                parsed_json={
                    "summary": "We discussed watermarking",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "ingestion-time progress tracking skipped records",
                    "investigation_evidence_text": None,
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
    plugin = LLMAgentMemoryPlugin(provider=StubLLMProvider(error=LLMProviderError("malformed output")))
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-456",
        content_type="text/plain",
        content="Decision: use event timestamp watermarking for exports to avoid skipped records.",
    )

    with pytest.raises(LLMProviderError):
        plugin.process_item(source_item)


def test_build_analysis_request_uses_requested_prompt_variant() -> None:
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-789",
        content_type="text/plain",
        content="We need to decide whether export watermarking should use ingestion time or event time.",
        artifact_kind="message",
        role="user",
    )

    request = build_analysis_request(source_item, prompt_variant="strict_decision_v1")

    assert request.prompt_variant == "strict_decision_v1"
    assert request.prompt_schema_id == "typed_memory_extraction"
    assert request.prompt_schema_version == "v3"
    assert 'investigation_outcome' in request.schema_description
    assert 'Artifact kind: message' in request.user_prompt


def test_llm_plugin_with_prompt_variant_uses_variant_prompt() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"Summary","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null}',
            parsed_json={
                "summary": "Summary",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider, prompt_variant="strict_decision_v2_source_aware")
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-999",
        content_type="text/plain",
        content="Investigation found that ingestion-time progress tracking skipped records during lag.",
        artifact_kind="tool_use_summary",
    )

    plugin.process_item(source_item)

    assert provider.last_system_prompt is not None
    assert 'investigation_outcome' in provider.last_system_prompt
    assert 'Do not convert findings into decisions.' in provider.last_system_prompt
