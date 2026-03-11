from __future__ import annotations

import json
from collections import OrderedDict
from typing import Iterable

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import build_index_entry
from core.models import MemoryObject, QueryResultItem, QueryTrace, Relation, SourceItem
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
THREAD_SUMMARY_TEXT_VIEW = "memory_object.thread_summary_context"
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
PATTERN_MEMORY_TEXT_VIEW = "memory_object.pattern_memory_context"
CONTINUITY_MEMORY_PROMPT_SCHEMA_ID = "continuity_memory_extraction"
CONTINUITY_MEMORY_PROMPT_SCHEMA_VERSION = "v1"
CONTINUITY_MEMORY_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "continuity_question": "string",
        "carry_forward_answer": "string",
    },
    indent=2,
)
CONTINUITY_MEMORY_SYSTEM_PROMPT = (
    "Create one compact continuity memory from a bounded single-thread set of lower-level conversation memory. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied memory and carried conclusions. "
    "Frame the output for repeated-answer continuity: what was already answered, and what concise answer should carry forward. "
    "Do not invent recurrence beyond the supplied thread, and do not add recommendations, risks, or new conclusions. "
    "Keep the summary concise: at most two sentences and roughly 70 words."
)
CONTINUITY_MEMORY_MAX_TEXT_CHARS = 3000
CONTINUITY_MEMORY_TEXT_VIEW = "memory_object.continuity_memory_context"
ROUTING_POLICY_NAME = "agent_conversation_memory.intent_routing.v1"
ROUTING_HIGHER_LEVEL_TYPES = {"pattern_memory", "continuity_memory"}
ROUTING_LOWER_LEVEL_EXACT_TYPES = {"decision", "investigation_outcome"}
ROUTING_SUMMARY_TYPES = {"thread_summary", "discussion_summary"}
ROUTING_PREFERRED_LAYERS = {
    "answer_continuity": ("continuity_memory", "lower_level_memory", "source_evidence", "pattern_memory"),
    "broad_recall": ("pattern_memory", "lower_level_memory", "continuity_memory", "source_evidence"),
    "precise_fact": ("lower_level_memory", "source_evidence", "continuity_memory", "pattern_memory"),
    "evidence_trace": ("source_evidence", "lower_level_memory", "continuity_memory", "pattern_memory"),
}
ROUTING_LAYER_WEIGHTS = {
    "answer_continuity": {"continuity_memory": 400, "lower_level_memory": 300, "source_evidence": 200, "pattern_memory": 120},
    "broad_recall": {"pattern_memory": 400, "lower_level_memory": 300, "continuity_memory": 180, "source_evidence": 120},
    "precise_fact": {"lower_level_memory": 420, "source_evidence": 320, "continuity_memory": 140, "pattern_memory": 60},
    "evidence_trace": {"source_evidence": 460, "lower_level_memory": 360, "continuity_memory": 120, "pattern_memory": 40},
}
ROUTING_META_QUERY_TOKENS = {
    "a",
    "about",
    "already",
    "an",
    "before",
    "did",
    "do",
    "exact",
    "have",
    "i",
    "need",
    "previously",
    "show",
    "source",
    "support",
    "supported",
    "the",
    "this",
    "trace",
    "we",
    "what",
    "which",
}
ROUTING_WEAK_HIGHER_LEVEL_MATCH_PENALTY = {
    "answer_continuity": 0,
    "broad_recall": 260,
    "precise_fact": 120,
    "evidence_trace": 120,
}
ANSWER_CONTINUITY_CUES = (
    "already answered",
    "answered before",
    "have we already",
    "asked again",
    "asking again",
    "prior answer",
    "carry forward",
)
BROAD_RECALL_CUES = (
    "what did we previously conclude",
    "what did we conclude before",
    "what did we conclude",
    "what did we learn",
    "why did we choose",
    "why do we use",
    "general lesson",
    "what lesson",
    "should we remember",
    "what should we remember",
)
BROAD_RECALL_ABSTRACTION_CUES = (
    "general lesson",
    "what lesson",
    "should we remember",
    "what should we remember",
)
PRECISE_FACT_CUES = (
    "what ordering",
    "which ordering",
    "what did we choose",
    "what decision",
    "exact choice",
    "exact value",
)
EVIDENCE_TRACE_CUES = (
    "exact finding",
    "what exact finding",
    "what evidence",
    "show evidence",
    "which source",
    "source evidence",
    "supported the",
    "supporting evidence",
    "trace",
    "which prior message",
    "prior message",
    "backed the",
)


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

    @property
    def continuity_memory_schema_id(self) -> str:
        return "agent_conversation_memory.continuity_memory"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self._delegate.process_item(source_item)

    def route_query_results(
        self,
        *,
        text: str,
        requested_limit: int,
        retrieval_result,
    ) -> tuple[list[QueryResultItem], QueryTrace | None]:
        intent = _classify_query_intent(text)
        preferred_layers = ROUTING_PREFERRED_LAYERS[intent]
        query_tokens = _routing_query_tokens(text)
        scored_candidates = [
            _score_routed_candidate(item, intent, query_text=text, query_tokens=query_tokens, lexical_rank=index)
            for index, item in enumerate(retrieval_result.results, start=1)
        ]
        ranked_candidates = sorted(
            scored_candidates,
            key=lambda candidate: (candidate["routing_score"], candidate["lexical_score"]),
            reverse=True,
        )
        for routing_rank, candidate in enumerate(ranked_candidates, start=1):
            candidate["routing_rank"] = routing_rank
        final_candidates = ranked_candidates[:requested_limit]
        final_results = [candidate["item"] for candidate in final_candidates]

        routed_trace = None
        if retrieval_result.trace is not None:
            routed_trace = QueryTrace(
                query_text=retrieval_result.trace.query_text,
                query_tokens=retrieval_result.trace.query_tokens,
                limit=requested_limit,
                filters=retrieval_result.trace.filters,
                stages=retrieval_result.trace.stages,
                routing=_build_routing_trace(
                    intent=intent,
                    preferred_layers=preferred_layers,
                    ranked_candidates=ranked_candidates,
                    final_candidates=final_candidates,
                ),
            )

        return final_results, routed_trace

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
        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
            text_view_name=THREAD_SUMMARY_TEXT_VIEW,
        )
        return ProcessResult(
            annotations=[],
            memory_objects=[memory_object],
            relations=relations,
            index_entries=[index_entry],
        )

    def build_consolidated_memory(self, group: ConsolidationGroup) -> ProcessResult:
        if _should_build_continuity_memory(group):
            return self._build_continuity_memory(group)
        return self.build_pattern_memory(group)

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
            "memory_kind": "pattern_memory",
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
        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
            text_view_name=PATTERN_MEMORY_TEXT_VIEW,
        )
        return ProcessResult(
            annotations=[],
            memory_objects=[memory_object],
            relations=[],
            index_entries=[index_entry],
        )


    def _build_continuity_memory(self, group: ConsolidationGroup) -> ProcessResult:
        conclusion_payload = list(_collect_conclusions(group))
        support_lines = []
        for candidate in group.candidates:
            payload = candidate.memory_object.payload
            candidate_text = payload.get("summary") or payload.get("decision") or payload.get("investigation_outcome") or ""
            if candidate_text:
                support_lines.append(f"- {candidate.memory_object.type}: {candidate_text}")

        group_material = "\n".join(support_lines)
        if len(group_material) > CONTINUITY_MEMORY_MAX_TEXT_CHARS:
            group_material = group_material[:CONTINUITY_MEMORY_MAX_TEXT_CHARS].rstrip() + "\n[group material truncated for token budget]"

        response = self._provider.generate_json(
            system_prompt=CONTINUITY_MEMORY_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact repeated-answer continuity memory from this bounded single-thread memory set. "
                "Use only explicit facts from the supplied memory and conclusions.\n\n"
                f"Strategy: {group.strategy_name}\n"
                f"Container ref: {group.container_ref or 'null'}\n"
                f"Thread ref: {group.thread_ref or 'null'}\n"
                f"Session ref: {group.session_ref or 'null'}\n"
                f"Latest occurred at: {group.latest_occurred_at.isoformat()}\n"
                f"Carried conclusions:\n{_format_conclusions(conclusion_payload)}\n\n"
                f"Lower-level memory:\n{group_material}"
            ),
            schema_description=CONTINUITY_MEMORY_SCHEMA_DESCRIPTION,
        )
        parsed_summary = response.parsed_json.get("summary")
        if not isinstance(parsed_summary, str) or not parsed_summary.strip():
            raise ValueError("continuity memory extraction must return a non-empty summary string")
        continuity_question = response.parsed_json.get("continuity_question")
        if not isinstance(continuity_question, str) or not continuity_question.strip():
            continuity_question = _default_continuity_question(group)
        carry_forward_answer = response.parsed_json.get("carry_forward_answer")
        if not isinstance(carry_forward_answer, str) or not carry_forward_answer.strip():
            carry_forward_answer = _default_carry_forward_answer(conclusion_payload)

        memory_object = MemoryObject(
            type="continuity_memory",
            schema_id=self.continuity_memory_schema_id,
            schema_version="v1",
            payload={
                "summary": parsed_summary.strip(),
                "continuity_question": continuity_question.strip(),
                "carry_forward_answer": carry_forward_answer.strip(),
                "conclusions": conclusion_payload,
                "supporting_memory_ids": list(group.candidate_ids),
                "latest_occurred_at": group.latest_occurred_at.isoformat(),
                "container_ref": group.container_ref,
                "thread_ref": group.thread_ref,
                "session_ref": group.session_ref,
                "group_key": group.group_key,
                "semantic_provenance": {
                    "semantic_plugin": self.name,
                    "prompt_variant": self.prompt_variant,
                },
                "consolidation_provenance": {
                    "memory_kind": "continuity_memory",
                    "strategy_name": group.strategy_name,
                    "strategy_version": group.strategy_version,
                    "prompt_schema_id": CONTINUITY_MEMORY_PROMPT_SCHEMA_ID,
                    "prompt_schema_version": CONTINUITY_MEMORY_PROMPT_SCHEMA_VERSION,
                    "prompt_variant": self.prompt_variant,
                },
            },
        )
        index_source = " ".join(
            [
                parsed_summary.strip(),
                continuity_question.strip(),
                carry_forward_answer.strip(),
                *[conclusion["text"] for conclusion in conclusion_payload if conclusion.get("text")],
            ]
        )
        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
            text_view_name=CONTINUITY_MEMORY_TEXT_VIEW,
        )
        return ProcessResult(
            annotations=[],
            memory_objects=[memory_object],
            relations=[],
            index_entries=[index_entry],
        )


def _classify_query_intent(text: str) -> str:
    lowered = text.lower()
    if any(cue in lowered for cue in EVIDENCE_TRACE_CUES):
        return "evidence_trace"
    if any(cue in lowered for cue in ANSWER_CONTINUITY_CUES):
        return "answer_continuity"
    if any(cue in lowered for cue in BROAD_RECALL_CUES) or lowered.startswith("why "):
        return "broad_recall"
    if any(cue in lowered for cue in PRECISE_FACT_CUES) or lowered.startswith(("what ", "which ", "when ")):
        return "precise_fact"
    return "broad_recall"


def _score_routed_candidate(
    item: QueryResultItem,
    intent: str,
    *,
    query_text: str,
    query_tokens: tuple[str, ...],
    lexical_rank: int,
) -> dict[str, object]:
    layer = _result_layer(item)
    lexical_score = int(item.score)
    overlap_tokens = _routing_overlap_tokens(item, query_tokens)
    content_overlap_tokens = [token for token in overlap_tokens if token not in ROUTING_META_QUERY_TOKENS]
    routing_score = (
        ROUTING_LAYER_WEIGHTS[intent][layer]
        + (lexical_score * 10)
        + _specificity_bonus(item, intent, query_text=query_text)
        + _routing_overlap_adjustment(layer, intent, content_overlap_tokens)
    )
    return {
        "item": item,
        "layer": layer,
        "lexical_rank": lexical_rank,
        "lexical_score": lexical_score,
        "routing_score": routing_score,
        "reason": _routing_reason(intent, layer, content_overlap_tokens),
        "strategy_name": _routing_strategy_name(item),
        "content_overlap_tokens": content_overlap_tokens,
    }


def _result_layer(item: QueryResultItem) -> str:
    if item.result_kind == "source_hit":
        return "source_evidence"
    if item.type == "pattern_memory":
        return "pattern_memory"
    if item.type == "continuity_memory":
        return "continuity_memory"
    return "lower_level_memory"


def _specificity_bonus(item: QueryResultItem, intent: str, *, query_text: str) -> int:
    bonus = 0
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        bonus += 40 if intent in {"precise_fact", "evidence_trace"} else 20
    if item.result_kind == "memory_hit" and item.type in ROUTING_SUMMARY_TYPES and intent in {"precise_fact", "evidence_trace"}:
        bonus -= 30
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "answer_continuity":
        bonus += 25
    if item.result_kind == "memory_hit" and item.type == "pattern_memory" and intent == "broad_recall":
        bonus += 25
        if _query_contains_any(query_text, BROAD_RECALL_ABSTRACTION_CUES):
            bonus += 45
    if item.result_kind == "source_hit" and intent == "evidence_trace":
        bonus += 30 if item.artifact_kind == "assistant_output" else 10
    return bonus


def _query_contains_any(text: str, cues: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in cues)


def _routing_query_tokens(text: str) -> tuple[str, ...]:
    normalized = normalize_for_index(text)
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)


def _routing_overlap_adjustment(layer: str, intent: str, content_overlap_tokens: Iterable[str]) -> int:
    overlap_count = len(tuple(content_overlap_tokens))
    if layer not in ROUTING_HIGHER_LEVEL_TYPES:
        return 0
    if overlap_count == 0:
        return -ROUTING_WEAK_HIGHER_LEVEL_MATCH_PENALTY[intent]
    return 0


def _routing_overlap_tokens(item: QueryResultItem, query_tokens: tuple[str, ...]) -> list[str]:
    if not query_tokens:
        return []
    item_tokens = set(_routing_item_tokens(item))
    return sorted(token for token in set(query_tokens) if token in item_tokens)


def _routing_item_tokens(item: QueryResultItem) -> tuple[str, ...]:
    normalized = normalize_for_index(_routing_item_text(item))
    if not normalized:
        return ()
    return tuple(token for token in normalized.split() if token)


def _routing_item_text(item: QueryResultItem) -> str:
    fragments: list[str] = []
    if item.excerpt:
        fragments.append(item.excerpt)
    if item.payload:
        if item.type == "decision":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("decision", "decision_evidence_text", "rationale")
            )
        elif item.type == "investigation_outcome":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("investigation_outcome", "investigation_evidence_text", "rationale")
            )
        elif item.type in ROUTING_HIGHER_LEVEL_TYPES:
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "pattern_label", "continuity_question", "carry_forward_answer")
            )
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
        else:
            fragments.append(json.dumps(item.payload, sort_keys=True))
    return " ".join(fragment for fragment in fragments if fragment)


def _routing_reason(intent: str, layer: str, content_overlap_tokens: list[str]) -> str:
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if not content_overlap_tokens and layer in ROUTING_HIGHER_LEVEL_TYPES else ""
    if intent == "answer_continuity":
        if layer == "continuity_memory":
            return "Repeated-answer wording favors compact carry-forward memory."
        if layer == "pattern_memory":
            return "Broad pattern memory is demoted because the query is asking whether the answer was already given."
        if layer == "lower_level_memory":
            return "Exact lower-level memory remains a fallback behind continuity carry-forward."
        return "Source evidence remains available, but routing prefers compact carry-forward first."
    if intent == "broad_recall":
        if layer == "pattern_memory":
            return "Broad recall wording favors higher-level pattern memory." + weak_match_suffix
        if layer == "continuity_memory":
            return "Continuity memory is narrower than the broad prior-conclusion question." + weak_match_suffix
        if layer == "lower_level_memory":
            return "Lower-level memory stays relevant, but broader recall prefers a consolidated pattern when present."
        return "Source evidence remains available, but compact prior-conclusion memory is preferred."
    if intent == "precise_fact":
        if layer == "lower_level_memory":
            return "Precise factual wording favors exact lower-level memory over higher-level summaries."
        if layer == "source_evidence":
            return "Source evidence stays near the top for precise factual lookup."
        if layer == "continuity_memory":
            return "Continuity memory is demoted because it can blur exact factual lookup." + weak_match_suffix
        return "Pattern memory is demoted because it can blur exact factual lookup." + weak_match_suffix
    if layer == "source_evidence":
        return "Evidence-trace wording favors raw supporting source evidence."
    if layer == "lower_level_memory":
        return "Lower-level memory stays close behind source evidence for evidence-trace questions."
    if layer == "continuity_memory":
        return "Continuity memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix
    return "Pattern memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix


def _routing_strategy_name(item: QueryResultItem) -> str | None:
    if item.result_kind != "memory_hit" or not item.payload:
        return None
    provenance = item.payload.get("consolidation_provenance", {})
    if not isinstance(provenance, dict):
        return None
    strategy_name = provenance.get("strategy_name")
    return str(strategy_name) if isinstance(strategy_name, str) and strategy_name else None


def _routing_result_id(item: QueryResultItem) -> str:
    if item.result_kind == "memory_hit":
        return f"memory_object:{item.memory_object_id}"
    return f"source_item:{item.source_item_id}"


def _build_routing_trace(
    *,
    intent: str,
    preferred_layers: tuple[str, ...],
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
) -> dict[str, object]:
    selected_results = [_build_routing_trace_entry(candidate) for candidate in final_candidates]
    demoted_higher_level_hits = [
        _build_routing_trace_entry(candidate)
        for candidate in ranked_candidates
        if candidate["layer"] in ROUTING_HIGHER_LEVEL_TYPES
        and int(candidate["routing_rank"]) > int(candidate["lexical_rank"])
    ][:4]
    return {
        "policy_name": ROUTING_POLICY_NAME,
        "query_intent": intent,
        "preferred_layers": list(preferred_layers),
        "selected_results": selected_results,
        "demoted_higher_level_hits": demoted_higher_level_hits,
    }


def _build_routing_trace_entry(candidate: dict[str, object]) -> dict[str, object]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    entry = {
        "result_id": _routing_result_id(item),
        "result_kind": item.result_kind,
        "memory_type": item.type,
        "layer": candidate["layer"],
        "lexical_rank": candidate["lexical_rank"],
        "routing_rank": candidate["routing_rank"],
        "lexical_score": candidate["lexical_score"],
        "routing_score": candidate["routing_score"],
        "reason": candidate["reason"],
    }
    content_overlap_tokens = list(candidate["content_overlap_tokens"])
    if content_overlap_tokens:
        entry["content_overlap_terms"] = content_overlap_tokens
    strategy_name = candidate["strategy_name"]
    if strategy_name is not None:
        entry["strategy_name"] = strategy_name
    return entry


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


def _is_single_thread_group(group: ConsolidationGroup) -> bool:
    thread_refs = {candidate.thread_ref for candidate in group.candidates if candidate.thread_ref}
    return bool(group.thread_ref) and len(thread_refs) <= 1


def _should_build_continuity_memory(group: ConsolidationGroup) -> bool:
    return group.strategy_name in {
        "thread_local_carry_forward",
        "thread_summary_anchored",
    } and _is_single_thread_group(group)


def _default_continuity_question(group: ConsolidationGroup) -> str:
    for candidate in group.candidates:
        if candidate.memory_object.type == "thread_summary":
            summary = str(candidate.memory_object.payload.get("summary", "")).strip()
            if summary:
                return f"What prior answer should carry forward? {summary}"
    return "What prior answer should carry forward from this conversation thread?"


def _default_carry_forward_answer(conclusions: list[dict[str, str]]) -> str:
    if conclusions:
        return " ".join(item["text"] for item in conclusions)
    return "A prior answer was recorded in this conversation thread."