from __future__ import annotations

import pytest

from core.models import SourceItem
from providers.llm.base import LLMJsonResponse, LLMProviderError
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY
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
                raw_text='{"summary":"Decision discussion","candidate_type":"decision","decision_text":"use item item event time reservation ordering","decision_evidence_text":"Decision: use item item event time reservation ordering","investigation_text":null,"investigation_evidence_text":null,"rationale_text":"to avoid missed hold updates","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "Decision discussion",
                    "candidate_type": "decision",
                    "decision_text": "use item item event time reservation ordering",
                    "decision_evidence_text": "Decision: use item item event time reservation ordering",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
                    "rationale_text": "to avoid missed hold updates",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-123",
        content_type="text/plain",
        content="Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 2
    assert result.memory_objects[0].type == "decision"
    assert result.memory_objects[0].schema_id == "llm.decision"
    assert result.memory_objects[0].payload["decision"] == "use item item event time reservation ordering"
    assert result.memory_objects[0].payload["decision_evidence_text"] == "Decision: use item item event time reservation ordering"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_id"] == "typed_memory_extraction"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_schema_version"] == "v5"
    assert result.memory_objects[0].payload["semantic_provenance"]["prompt_variant"] == "strict_typed_memory_v4_evidence_guarded"


def test_llm_plugin_promotes_investigation_outcome_from_explicit_verdict_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Comparative verdict","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"transaction-transformer had the most significant recent ledger changes","investigation_evidence_text":"Here\'s the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin.","rationale_text":"because it touched more tickets, files, and transaction flows","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":"transaction-transformer had the most significant recent ledger changes because it touched more tickets, files, and transaction flows than ledger-query"}',
                parsed_json={
                    "summary": "Comparative verdict",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "transaction-transformer had the most significant recent ledger changes",
                    "investigation_evidence_text": "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin.",
                    "rationale_text": "because it touched more tickets, files, and transaction flows",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": "transaction-transformer had the most significant recent ledger changes because it touched more tickets, files, and transaction flows than ledger-query",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="investigation-verdict-123",
        content_type="text/plain",
        content="Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin. It touched more tickets, files, and transaction flows than ledger-query.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 2
    assert result.memory_objects[0].type == "investigation_outcome"
    assert result.memory_objects[0].payload["investigation_outcome"] == "transaction-transformer had the most significant recent ledger changes"
    assert result.memory_objects[0].payload["investigation_evidence_text"] == "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin."
    assert result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]["key_finding_text"].startswith("transaction-transformer")


def test_llm_plugin_returns_internal_signals_and_metadata_patch_from_single_call() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"Local-only operating plan","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":"No browser auth, no Jira or Slack auth; use the local repos only and ask the user directly for anything behind those services.","next_step_text":"Compare ledger-query vs transaction-transformer locally and explain which repo changed more.","blocker_text":"Browser and SSO-backed services are unavailable in this environment.","progress_text":"The latest ledger changes were already summarized across the local repos.","key_finding_text":"transaction-transformer expanded transaction coverage while ledger-query focused on export and ADX plumbing"}',
            parsed_json={
                "summary": "Local-only operating plan",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": "No browser auth, no Jira or Slack auth; use the local repos only and ask the user directly for anything behind those services.",
                "next_step_text": "Compare ledger-query vs transaction-transformer locally and explain which repo changed more.",
                "blocker_text": "Browser and SSO-backed services are unavailable in this environment.",
                "progress_text": "The latest ledger changes were already summarized across the local repos.",
                "key_finding_text": "transaction-transformer expanded transaction coverage while ledger-query focused on export and ADX plumbing",
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider)
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="signal-rich-1",
        content_type="text/plain",
        content="No browser auth, no Jira or Slack auth. Use the local repos only. I already summarized the latest ledger changes; next I should compare ledger-query vs transaction-transformer locally and explain which repo changed more.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    trace = plugin.analyze_item(source_item)

    assert trace.process_result.memory_objects[0].type == "discussion_summary"
    summary_annotation = trace.process_result.annotations[0]
    semantic_signals = summary_annotation.payload["semantic_signals"]
    assert semantic_signals["constraint_text"].startswith("No browser auth")
    assert semantic_signals["next_step_text"].startswith("Compare ledger-query")
    assert semantic_signals["blocker_text"].startswith("Browser and SSO")
    assert semantic_signals["progress_text"].startswith("The latest ledger changes")
    assert semantic_signals["key_finding_text"].startswith("transaction-transformer expanded")
    assert trace.process_result.source_item_metadata_updates == {
        source_item.id: {SEMANTIC_SIGNAL_METADATA_KEY: semantic_signals}
    }


def test_llm_plugin_flags_low_value_meta_without_promoting_typed_memory() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"No durable update.","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":true,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
            parsed_json={
                "summary": "No durable update.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": True,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider)
    source_item = SourceItem(
        source_type="assistant_output",
        source_id="meta-1",
        content_type="text/plain",
        content="Task complete. No Slack message needed. Nothing new to report.",
        artifact_kind="assistant_output",
        role="assistant",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 1
    assert result.memory_objects == []
    assert result.thread_rebuild_requested is False
    assert result.annotations[0].payload["semantic_signals"]["is_low_value_meta"] is True
    assert result.source_item_metadata_updates[source_item.id][SEMANTIC_SIGNAL_METADATA_KEY]["is_low_value_meta"] is True


def test_llm_plugin_promotes_investigation_outcome_from_valid_extraction() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Investigation summary","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"arrival-time ordering missed hold updates during sync delays","investigation_evidence_text":"Investigation found that arrival-time ordering missed hold updates during sync delays","rationale_text":"because the catalog provider delivered updates late","is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":"arrival-time ordering missed hold updates during sync delays because the catalog provider delivered updates late"}',
                parsed_json={
                    "summary": "Investigation summary",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "arrival-time ordering missed hold updates during sync delays",
                    "investigation_evidence_text": "Investigation found that arrival-time ordering missed hold updates during sync delays",
                    "rationale_text": "because the catalog provider delivered updates late",
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": "arrival-time ordering missed hold updates during sync delays because the catalog provider delivered updates late",
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-123",
        content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates during sync delays.",
        artifact_kind="tool_use_summary",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 2
    assert result.memory_objects[0].type == "investigation_outcome"
    assert result.memory_objects[0].payload["investigation_outcome"] == "arrival-time ordering missed hold updates during sync delays"
    assert result.memory_objects[0].payload["investigation_evidence_text"] == "Investigation found that arrival-time ordering missed hold updates during sync delays"


def test_llm_plugin_uses_discussion_summary_when_typed_output_lacks_evidence_text() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"We discussed reservation ordering","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"arrival-time ordering missed hold updates","investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "We discussed reservation ordering",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "arrival-time ordering missed hold updates",
                    "investigation_evidence_text": None,
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-123",
        content_type="text/plain",
        content="We discussed reservation ordering options today.",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 1
    assert result.memory_objects[0].type == "discussion_summary"
    assert result.memory_objects[0].schema_id == "llm.discussion_summary"


def test_llm_plugin_rejects_weak_decision_evidence_and_falls_back_to_discussion_summary() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Playbook note","candidate_type":"decision","decision_text":"create a clearer librarian playbook","decision_evidence_text":"The team agreed that we need a clearer librarian playbook for catalog sync incidents.","investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "Playbook note",
                    "candidate_type": "decision",
                    "decision_text": "create a clearer librarian playbook",
                    "decision_evidence_text": "The team agreed that we need a clearer librarian playbook for catalog sync incidents.",
                    "investigation_text": None,
                    "investigation_evidence_text": None,
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": None,
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="meeting_summary",
        source_id="discussion-guard-1",
        content_type="text/plain",
        content="The team agreed that we need a clearer librarian playbook for catalog sync incidents.",
        artifact_kind="assistant_output",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 1
    assert result.memory_objects[0].type == "discussion_summary"


def test_llm_plugin_rejects_weak_investigation_evidence_and_falls_back_to_discussion_summary() -> None:
    plugin = LLMAgentMemoryPlugin(
        provider=StubLLMProvider(
            response=LLMJsonResponse(
                raw_text='{"summary":"Status update","candidate_type":"investigation_outcome","decision_text":null,"decision_evidence_text":null,"investigation_text":"catalog sync delay increased after the provider restart","investigation_evidence_text":"Catalog sync delay increased after the provider restart, and we should watch it closely tonight.","rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":"Watch it closely tonight.","blocker_text":null,"progress_text":null,"key_finding_text":null}',
                parsed_json={
                    "summary": "Status update",
                    "candidate_type": "investigation_outcome",
                    "decision_text": None,
                    "decision_evidence_text": None,
                    "investigation_text": "catalog sync delay increased after the provider restart",
                    "investigation_evidence_text": "Catalog sync delay increased after the provider restart, and we should watch it closely tonight.",
                    "rationale_text": None,
                    "is_low_value_meta": False,
                    "constraint_text": None,
                    "next_step_text": "Watch it closely tonight.",
                    "blocker_text": None,
                    "progress_text": None,
                    "key_finding_text": None,
                },
            )
        )
    )
    source_item = SourceItem(
        source_type="status_update",
        source_id="discussion-guard-2",
        content_type="text/plain",
        content="Catalog sync delay increased after the provider restart, and we should watch it closely tonight.",
        artifact_kind="notification",
    )

    result = plugin.process_item(source_item)

    assert len(result.annotations) == 1
    assert result.memory_objects[0].type == "discussion_summary"


def test_llm_plugin_raises_on_invalid_output() -> None:
    plugin = LLMAgentMemoryPlugin(provider=StubLLMProvider(error=LLMProviderError("malformed output")))
    source_item = SourceItem(
        source_type="decision_note",
        source_id="decision-456",
        content_type="text/plain",
        content="Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
    )

    with pytest.raises(LLMProviderError):
        plugin.process_item(source_item)


def test_build_analysis_request_uses_requested_prompt_variant() -> None:
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-789",
        content_type="text/plain",
        content="We need to decide whether reservation ordering should use arrival time or item event time.",
        artifact_kind="message",
        role="user",
    )

    request = build_analysis_request(source_item, prompt_variant="strict_decision_v1")

    assert request.prompt_variant == "strict_decision_v1"
    assert request.prompt_schema_id == "typed_memory_extraction"
    assert request.prompt_schema_version == "v5"
    assert 'investigation_outcome' in request.schema_description
    assert 'constraint_text' in request.schema_description
    assert 'Artifact kind: message' in request.user_prompt


def test_llm_plugin_with_prompt_variant_uses_variant_prompt() -> None:
    provider = StubLLMProvider(
        response=LLMJsonResponse(
            raw_text='{"summary":"Summary","candidate_type":null,"decision_text":null,"decision_evidence_text":null,"investigation_text":null,"investigation_evidence_text":null,"rationale_text":null,"is_low_value_meta":false,"constraint_text":null,"next_step_text":null,"blocker_text":null,"progress_text":null,"key_finding_text":null}',
            parsed_json={
                "summary": "Summary",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            },
        )
    )
    plugin = LLMAgentMemoryPlugin(provider=provider, prompt_variant="strict_typed_memory_v4_evidence_guarded")
    source_item = SourceItem(
        source_type="investigation_summary",
        source_id="investigation-999",
        content_type="text/plain",
        content="Investigation found that arrival-time ordering missed hold updates during sync delays.",
        artifact_kind="tool_use_summary",
    )

    plugin.process_item(source_item)

    assert provider.last_system_prompt is not None
    assert 'investigation_outcome' in provider.last_system_prompt
    assert 'Evidence rule:' in provider.last_system_prompt
    assert 'we should watch' in provider.last_system_prompt
    assert 'low-value meta chatter' in provider.last_system_prompt
