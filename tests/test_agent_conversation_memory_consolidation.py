from __future__ import annotations

import json

from core.models import MemoryObject, SourceItem, new_id
from providers.llm.base import LLMJsonResponse
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


class _NullTypeButTypedFieldsProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = {
            "summary": "Publish process status summaries in 30-minute batches to reduce downstream noise.",
            "candidate_type": None,
            "decision_text": "Publish process status summaries in 30-minute batches",
            "decision_evidence_text": "Publish process status summaries in 30-minute batches to reduce downstream noise.",
            "investigation_text": None,
            "investigation_evidence_text": None,
            "rationale_text": "to reduce downstream noise",
            "interest_text": None,
            "is_low_value_meta": False,
            "constraint_text": None,
            "next_step_text": None,
            "blocker_text": None,
            "progress_text": None,
            "key_finding_text": None,
            "subject_hints": [],
            "work_refs": [],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class _SummaryOnlyProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = {
            "summary": "Decision: send overdue notices in 30-minute batches to avoid staff inbox spam.",
            "candidate_type": None,
            "decision_text": None,
            "decision_evidence_text": None,
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
            "work_refs": [],
        }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def test_supports_consolidation_accepts_atomic_fact() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    fact = MemoryObject(
        id=new_id(),
        type="atomic_fact",
        schema_id="test.atomic_fact",
        schema_version="v1",
        payload={"statement": "process status summaries are published in 30-minute batches"},
        lifecycle="active",
    )

    assert plugin.supports_consolidation(fact) is True


def test_typed_fields_promote_candidate_type_when_llm_omits_it() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=_NullTypeButTypedFieldsProvider(),
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    item = SourceItem(
        source_type="assistant_artifact",
        source_id="decision-fallback-typed-fields-1",
        content_type="text/plain",
        content="Publish process status summaries in 30-minute batches to reduce downstream noise.",
        artifact_kind="assistant_output",
        role="user",
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-1",
        visibility="public",
    )

    result = plugin.process_item(item)

    decisions = [memory for memory in result.memory_objects if memory.type == "decision"]
    assert len(decisions) == 1
    assert decisions[0].payload["decision"] == "Publish process status summaries in 30-minute batches"


def test_explicit_assistant_output_summary_only_does_not_recover_decision_from_phrase_table() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=_SummaryOnlyProvider(),
        prompt_variant="strict_typed_memory_v8b_work_refs_separate",
    )
    item = SourceItem(
        source_type="assistant_artifact",
        source_id="decision-summary-only-1",
        content_type="text/plain",
        content="Decision: send overdue notices in 30-minute batches to avoid staff inbox spam and reduce notification fatigue across library branches.",
        artifact_kind="assistant_output",
        role="assistant",
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-7",
        visibility="public",
    )

    result = plugin.process_item(item)

    decisions = [memory for memory in result.memory_objects if memory.type == "decision"]
    assert decisions == []
    assert [memory.type for memory in result.memory_objects] == ["turn_summary"]