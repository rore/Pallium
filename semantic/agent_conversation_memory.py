from __future__ import annotations

import json

from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.models import IndexEntry, MemoryObject, Relation, SourceItem
from providers.llm.base import LLMProvider
from semantic.base import ThreadAggregationSemanticPlugin
from semantic.common import normalize_for_index
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


THREAD_SUMMARY_PROMPT_SCHEMA_ID = "thread_summary_extraction"
THREAD_SUMMARY_PROMPT_SCHEMA_VERSION = "v1"
THREAD_SUMMARY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string"}, indent=2)
THREAD_SUMMARY_SYSTEM_PROMPT = (
    "You summarize one completed agent-mediated conversation thread for future recall. "
    "Return exactly one JSON object and no extra prose. The summary must be concise, evidence-aware, and preserve the thread's main conclusion."
)
SUPPORTED_THREAD_ARTIFACTS = {
    ("message", "user"),
    ("assistant_output", "assistant"),
}
CARRIED_CONCLUSION_TYPES = {"decision", "investigation_outcome"}


class AgentConversationMemoryPlugin(ThreadAggregationSemanticPlugin):
    name = "agent_conversation_memory"

    def __init__(self, provider: LLMProvider, *, prompt_variant: str) -> None:
        self._provider = provider
        self._delegate = LLMAgentMemoryPlugin(provider=provider, prompt_variant=prompt_variant)

    @property
    def prompt_variant(self) -> str:
        return self._delegate.prompt_variant

    @property
    def thread_summary_schema_id(self) -> str:
        return "agent_conversation_memory.thread_summary"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self._delegate.process_item(source_item)

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        if not source_item.thread_ref or not source_item.container_ref:
            return False
        return (source_item.artifact_kind or "", source_item.role or "") in SUPPORTED_THREAD_ARTIFACTS

    def build_thread_summary(self, aggregate: ThreadAggregate, conclusions: list[MemoryObject]) -> ProcessResult:
        carried_conclusions = sorted(
            [
                memory_object
                for memory_object in conclusions
                if memory_object.type in CARRIED_CONCLUSION_TYPES and memory_object.lifecycle == "active"
            ],
            key=lambda item: (item.created_at, item.id),
        )
        conclusion_lines = []
        for conclusion in carried_conclusions:
            payload = conclusion.payload
            text = payload.get("decision") or payload.get("investigation_outcome") or payload.get("summary") or ""
            if text:
                conclusion_lines.append(f"- {conclusion.type}: {text}")

        response = self._provider.generate_json(
            system_prompt=THREAD_SUMMARY_SYSTEM_PROMPT,
            user_prompt=(
                f"Container ref: {aggregate.container_ref}\n"
                f"Thread ref: {aggregate.thread_ref}\n"
                f"Session ref: {aggregate.session_ref or 'null'}\n"
                f"Latest occurred at: {aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else 'null'}\n"
                f"Carried conclusions:\n{chr(10).join(conclusion_lines) if conclusion_lines else '- none'}\n\n"
                f"Thread items:\n{aggregate.aggregate_text}"
            ),
            schema_description=THREAD_SUMMARY_SCHEMA_DESCRIPTION,
        )
        parsed_summary = response.parsed_json.get("summary")
        if not isinstance(parsed_summary, str) or not parsed_summary.strip():
            raise ValueError("thread summary extraction must return a non-empty summary string")
        summary = parsed_summary.strip()

        semantic_provenance = {
            "semantic_plugin": self.name,
            "prompt_variant": self.prompt_variant,
            "prompt_schema_id": THREAD_SUMMARY_PROMPT_SCHEMA_ID,
            "prompt_schema_version": THREAD_SUMMARY_PROMPT_SCHEMA_VERSION,
        }
        conclusion_payload = [
            {
                "type": conclusion.type,
                "text": conclusion.payload.get("decision")
                or conclusion.payload.get("investigation_outcome")
                or conclusion.payload.get("summary")
                or "",
            }
            for conclusion in carried_conclusions
        ]
        memory_object = MemoryObject(
            type="thread_summary",
            schema_id=self.thread_summary_schema_id,
            schema_version="v1",
            payload={
                "thread_ref": aggregate.thread_ref,
                "container_ref": aggregate.container_ref,
                "session_ref": aggregate.session_ref,
                "summary": summary,
                "conclusions": conclusion_payload,
                "latest_occurred_at": aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else None,
                "semantic_provenance": semantic_provenance,
            },
        )
        relations = [
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item_id,
            )
            for source_item_id in aggregate.source_item_ids
        ]
        relations.extend(
            Relation(
                from_kind="memory_object",
                from_id=memory_object.id,
                relation_type="relates_to",
                to_kind="memory_object",
                to_id=conclusion.id,
            )
            for conclusion in carried_conclusions
        )
        index_source = " ".join(
            [summary, *[item["text"] for item in conclusion_payload if item.get("text")]]
        )
        index_entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
        )
        return ProcessResult(
            annotations=[],
            memory_objects=[memory_object],
            relations=relations,
            index_entries=[index_entry],
        )
