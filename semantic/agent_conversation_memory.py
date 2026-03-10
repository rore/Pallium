from __future__ import annotations

import json
from collections import OrderedDict

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.models import IndexEntry, MemoryObject, Relation, SourceItem
from providers.llm.base import LLMProvider
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.common import normalize_for_index
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


THREAD_SUMMARY_PROMPT_SCHEMA_ID = "thread_summary_extraction"
THREAD_SUMMARY_PROMPT_SCHEMA_VERSION = "v2"
THREAD_SUMMARY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string"}, indent=2)
THREAD_SUMMARY_SYSTEM_PROMPT = (
    "Summarize one agent-mediated conversation thread for future recall. "
    "Return exactly one JSON object and no extra prose. "
    "Use only facts that are explicitly present in the thread items or carried conclusions. "
    "Do not infer causes, recommendations, next steps, risks, or unresolved conclusions that are not stated. "
    "If the thread is unresolved, say only that it is unresolved. "
    "Keep the summary concise: at most two sentences and roughly 60 words."
)
SUPPORTED_THREAD_ARTIFACTS = {
    ("message", "user"),
    ("assistant_output", "assistant"),
}
CARRIED_CONCLUSION_TYPES = {"decision", "investigation_outcome"}
THREAD_SUMMARY_MAX_TEXT_CHARS = 4000
PATTERN_MEMORY_PROMPT_SCHEMA_ID = "pattern_memory_extraction"
PATTERN_MEMORY_PROMPT_SCHEMA_VERSION = "v1"
PATTERN_MEMORY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string", "pattern_label": "string"}, indent=2)
PATTERN_MEMORY_SYSTEM_PROMPT = (
    "Summarize a bounded set of lower-level conversation memory into one compact higher-level memory object. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied lower-level memory and carried conclusions. "
    "Do not invent recurrence, severity, causality, recommendations, or next steps. "
    "Do not claim anything broader than the supplied support. "
    "Keep the summary concise: at most two sentences and roughly 70 words."
)
PATTERN_MEMORY_MAX_TEXT_CHARS = 3500


class AgentConversationMemoryPlugin(ThreadAggregationSemanticPlugin, ConsolidationSemanticPlugin):
    name = "agent_conversation_memory"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_variant: str,
        consolidation_config: ConsolidationPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._delegate = LLMAgentMemoryPlugin(provider=provider, prompt_variant=prompt_variant)
        self._consolidation_config = consolidation_config

    @property
    def prompt_variant(self) -> str:
        return self._delegate.prompt_variant

    @property
    def thread_summary_schema_id(self) -> str:
        return "agent_conversation_memory.thread_summary"

    @property
    def consolidation_policy(self) -> ConsolidationPolicy | None:
        return self._consolidation_config

    @property
    def pattern_memory_schema_id(self) -> str:
        return "agent_conversation_memory.pattern_memory"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self._delegate.process_item(source_item)

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        if not source_item.thread_ref or not source_item.container_ref:
            return False
        return (source_item.artifact_kind or "", source_item.role or "") in SUPPORTED_THREAD_ARTIFACTS

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        return memory_object.type in {"thread_summary", "decision", "investigation_outcome"}

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

        thread_material = aggregate.aggregate_text
        if len(thread_material) > THREAD_SUMMARY_MAX_TEXT_CHARS:
            thread_material = thread_material[:THREAD_SUMMARY_MAX_TEXT_CHARS].rstrip() + "\n[thread items truncated for token budget]"

        response = self._provider.generate_json(
            system_prompt=THREAD_SUMMARY_SYSTEM_PROMPT,
            user_prompt=(
                "Summarize this thread conservatively for later recall. "
                "Use only explicit information from the provided content.\n\n"
                f"Container ref: {aggregate.container_ref}\n"
                f"Thread ref: {aggregate.thread_ref}\n"
                f"Session ref: {aggregate.session_ref or 'null'}\n"
                f"Latest occurred at: {aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else 'null'}\n"
                f"Carried conclusions:\n{chr(10).join(conclusion_lines) if conclusion_lines else '- none'}\n\n"
                f"Thread items:\n{thread_material}"
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

    def build_pattern_memory(self, group: ConsolidationGroup) -> ProcessResult:
        conclusion_payload = list(_collect_conclusions(group))
        support_lines = []
        for candidate in group.candidates:
            payload = candidate.memory_object.payload
            candidate_text = payload.get("summary") or payload.get("decision") or payload.get("investigation_outcome") or ""
            if candidate_text:
                support_lines.append(f"- {candidate.memory_object.type}: {candidate_text}")

        group_material = "\n".join(support_lines)
        if len(group_material) > PATTERN_MEMORY_MAX_TEXT_CHARS:
            group_material = group_material[:PATTERN_MEMORY_MAX_TEXT_CHARS].rstrip() + "\n[group material truncated for token budget]"

        response = self._provider.generate_json(
            system_prompt=PATTERN_MEMORY_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact higher-level memory from this bounded set of lower-level memory. "
                "Use only explicit facts from the supplied memory and conclusions.\n\n"
                f"Strategy: {group.strategy_name}\n"
                f"Container ref: {group.container_ref or 'null'}\n"
                f"Thread ref: {group.thread_ref or 'null'}\n"
                f"Session ref: {group.session_ref or 'null'}\n"
                f"Latest occurred at: {group.latest_occurred_at.isoformat()}\n"
                f"Carried conclusions:\n{_format_conclusions(conclusion_payload)}\n\n"
                f"Lower-level memory:\n{group_material}"
            ),
            schema_description=PATTERN_MEMORY_SCHEMA_DESCRIPTION,
        )
        parsed_summary = response.parsed_json.get("summary")
        if not isinstance(parsed_summary, str) or not parsed_summary.strip():
            raise ValueError("pattern memory extraction must return a non-empty summary string")
        pattern_label = response.parsed_json.get("pattern_label")
        if not isinstance(pattern_label, str) or not pattern_label.strip():
            pattern_label = group.strategy_name

        semantic_provenance = {
            "semantic_plugin": self.name,
            "prompt_variant": self.prompt_variant,
        }
        consolidation_provenance = {
            "strategy_name": group.strategy_name,
            "strategy_version": group.strategy_version,
            "prompt_schema_id": PATTERN_MEMORY_PROMPT_SCHEMA_ID,
            "prompt_schema_version": PATTERN_MEMORY_PROMPT_SCHEMA_VERSION,
            "prompt_variant": self.prompt_variant,
        }
        memory_object = MemoryObject(
            type="pattern_memory",
            schema_id=self.pattern_memory_schema_id,
            schema_version="v1",
            payload={
                "summary": parsed_summary.strip(),
                "pattern_label": pattern_label.strip(),
                "conclusions": conclusion_payload,
                "supporting_memory_ids": list(group.candidate_ids),
                "latest_occurred_at": group.latest_occurred_at.isoformat(),
                "container_ref": group.container_ref,
                "thread_ref": group.thread_ref,
                "session_ref": group.session_ref,
                "group_key": group.group_key,
                "semantic_provenance": semantic_provenance,
                "consolidation_provenance": consolidation_provenance,
            },
        )
        index_source = " ".join(
            [
                parsed_summary.strip(),
                *[conclusion["text"] for conclusion in conclusion_payload if conclusion.get("text")],
            ]
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
            relations=[],
            index_entries=[index_entry],
        )


def _collect_conclusions(group: ConsolidationGroup) -> list[dict[str, str]]:
    ordered: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
    for candidate in group.candidates:
        payload = candidate.memory_object.payload
        if candidate.memory_object.type == "thread_summary":
            for conclusion in payload.get("conclusions", []):
                if not isinstance(conclusion, dict):
                    continue
                conclusion_type = str(conclusion.get("type", "")).strip()
                conclusion_text = str(conclusion.get("text", "")).strip()
                if not conclusion_type or not conclusion_text:
                    continue
                ordered.setdefault((conclusion_type, conclusion_text), {"type": conclusion_type, "text": conclusion_text})
        elif candidate.memory_object.type == "decision":
            text = str(payload.get("decision", "")).strip()
            if text:
                ordered.setdefault(("decision", text), {"type": "decision", "text": text})
        elif candidate.memory_object.type == "investigation_outcome":
            text = str(payload.get("investigation_outcome", "")).strip()
            if text:
                ordered.setdefault(("investigation_outcome", text), {"type": "investigation_outcome", "text": text})
    return list(ordered.values())


def _format_conclusions(conclusions: list[dict[str, str]]) -> str:
    if not conclusions:
        return "- none"
    return "\n".join(f"- {item['type']}: {item['text']}" for item in conclusions)
