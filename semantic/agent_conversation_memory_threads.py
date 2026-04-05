from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import replace
from typing import Iterable

from capabilities.consolidation import ConsolidationGroup
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import ProcessResult
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, QueryResultItem, Relation, SourceItem
from providers.llm.base import LLMProvider
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY, normalize_for_index
from semantic.agent_conversation_memory_constraints import CONSTRAINT_MARKERS, CONSTRAINT_TOOL_MARKERS, _merge_subject_anchors, _subject_anchors_from_memory_objects, _subject_anchors_from_source_items
from semantic.agent_conversation_memory_embedding import VECTOR_EMBEDDING_PROVIDER_NAME, VECTOR_EMBEDDING_PROVIDER_VERSION, build_embedding_text
from semantic.agent_conversation_memory_enrichment import ENRICHABLE_MEMORY_TYPES, WRITE_ENRICHMENT_PROMPT_ROLE, WRITE_ENRICHMENT_TEXT_VIEW
from semantic.agent_conversation_memory_memory import _build_memory_envelope, _memory_confidence_for_type, _memory_kind_for_type
from semantic.prompt_provenance import build_prompt_provenance

THREAD_SUMMARY_PROMPT_SCHEMA_ID = "thread_summary_extraction"

THREAD_SUMMARY_PROMPT_SCHEMA_VERSION = "v4"

THREAD_SUMMARY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string", "content_quality": "string", "retrieval_context": "string or null"}, indent=2)

THREAD_SUMMARY_SYSTEM_PROMPT = (
    "Summarize one agent-mediated conversation thread for future recall. "
    "Return exactly one JSON object and no extra prose. "
    "Use only facts that are explicitly present in the thread items, selected work artifacts, or carried conclusions. "
    "Selected work artifacts may describe explicit partial progress, blockers, next steps, constraints, or durable findings; include them only when they are explicitly stated. "
    "Do not infer causes, recommendations, next steps, risks, or unresolved conclusions that are not stated. "
    "Only say the thread is unresolved when the supplied content truly lacks any resolved conclusion, durable constraint, progress state, blocker, or supported next step. "
    "Keep the summary concise: at most two sentences and roughly 60 words. "
    "For content_quality, classify the summary you wrote: "
    '"substantive" when the thread contains resolved conclusions, durable findings, constraints, progress state, or work artifacts worth recalling; '
    '"query_only" when the thread contains only a user question or request with no substantive response — an assistant reply that merely acknowledges or promises to investigate does not count as a substantive response; '
    '"unresolved" when the thread has substantive back-and-forth discussion but no resolved conclusions, decisions, or durable findings; '
    '"weak" when the thread is a greeting, phatic exchange, sign-off, or otherwise carries no recallable information. '
    "For retrieval_context: write one short search-friendly context line (12-30 words) that helps this record match later queries, "
    "or null when the summary already has enough search cues. Do not restate the summary."
)

PRIMARY_THREAD_ARTIFACTS = {
    ("message", "user"),
    ("assistant_output", "assistant"),
}

SELECTED_WORK_ARTIFACT_KINDS = {"tool_use_summary", "todo_snapshot"}

SELECTED_THREAD_ARTIFACTS = {
    (artifact_kind, "assistant")
    for artifact_kind in SELECTED_WORK_ARTIFACT_KINDS
}

CARRIED_CONCLUSION_TYPES = {"decision", "investigation_outcome"}

THREAD_SUMMARY_MAX_TEXT_CHARS = 4000

THREAD_SUMMARY_TEXT_VIEW = "memory_object.thread_summary_context"

MAX_SELECTED_WORK_ARTIFACTS = 6

WORK_SIGNAL_PREFIX_TO_TYPE = (
    ("blocked:", "blocker"),
    ("blocker:", "blocker"),
    ("failed attempt:", "blocker"),
    ("failure:", "blocker"),
    ("next step:", "next_step"),
    ("partial progress:", "progress_update"),
    ("partial finding:", "progress_update"),
    ("progress:", "progress_update"),
)

LOW_VALUE_ASSISTANT_META_PATTERNS = (
    re.compile(r"\btask (?:is )?complete\b", re.IGNORECASE),
    re.compile(r"\bnothing new to report\b", re.IGNORECASE),
    re.compile(r"\bno response (?:requested|needed)\b", re.IGNORECASE),
    re.compile(r"\bno (?:chat |email |message )?needed\b", re.IGNORECASE),
    re.compile(r"\bno (?:chat |email |slack )?message needed\b", re.IGNORECASE),
    re.compile(r"\bno [a-z/ ]*(?:auth|authentication)\b.*\bi will use the local (?:repos|cache) only\b", re.IGNORECASE),
)

IMPLICIT_FINDING_MARKERS = (
    "here's the verdict",
    "verdict:",
    "conclusion:",
    "the conclusion is",
    "investigation found",
    "investigation concluded",
    "analysis found",
    "we found that",
)

IMPLICIT_NEXT_STEP_MARKERS = (
    "next step",
    "next steps",
    "best next step",
    "best next steps",
    "plan:",
)

WEAK_THREAD_SUMMARY_TEXT = {"unresolved", "still unresolved", "unknown", "no safe summary"}

# Historical reference: these marker lists were used for write-time content_quality
# classification before LLM self-classification was added (v4). They document what
# "query_only" and "unresolved" summaries look like in LLM output.
#
# query_only examples: "contains only this question", "only this request"
# unresolved examples: "no resolved information", "no answer yet", "single user message",
#   "no prior context", "artifacts, or conclusions were provided"

PATTERN_MEMORY_PROMPT_SCHEMA_ID = "pattern_memory_extraction"

PATTERN_MEMORY_PROMPT_SCHEMA_VERSION = "v2"


_VALID_CONTENT_QUALITY = {"substantive", "query_only", "unresolved", "weak"}


def _compute_thread_summary_content_quality(
    summary: str,
    conclusions: list[object],
    work_artifacts: list[object],
    *,
    llm_content_quality: str | None = None,
) -> str:
    """Classify thread summary quality at write time.

    Returns one of: "substantive", "query_only", "unresolved", "weak".

    Priority order:
    1. Structural shortcut: conclusions or work_artifacts present → "substantive".
    2. Empty summary → "weak".
    3. Weak-text guard: summary text in WEAK_THREAD_SUMMARY_TEXT → "weak".
    4. LLM self-classification (if valid enum value).
    5. Fallback: "substantive".
    """
    if conclusions or work_artifacts:
        return "substantive"
    lowered = summary.lower().strip()
    if not lowered:
        return "weak"
    if lowered in WEAK_THREAD_SUMMARY_TEXT:
        return "weak"
    normalized = llm_content_quality.lower().strip() if isinstance(llm_content_quality, str) else None
    if normalized in _VALID_CONTENT_QUALITY:
        return normalized
    return "substantive"

PATTERN_MEMORY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string", "pattern_label": "string", "retrieval_context": "string or null"}, indent=2)

PATTERN_MEMORY_SYSTEM_PROMPT = (
    "Summarize a bounded set of lower-level conversation memory into one compact higher-level memory object. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied lower-level memory and carried conclusions. "
    "Do not invent recurrence, severity, causality, recommendations, or next steps. "
    "Do not claim anything broader than the supplied support. "
    "Keep the summary concise: at most two sentences and roughly 70 words. "
    "For retrieval_context: write one short search-friendly context line (12-30 words) that helps this record match later queries, "
    "or null when the summary already has enough search cues. Do not restate the summary."
)

PATTERN_MEMORY_MAX_TEXT_CHARS = 3500

PATTERN_MEMORY_TEXT_VIEW = "memory_object.pattern_memory_context"

CONTINUITY_MEMORY_PROMPT_SCHEMA_ID = "continuity_memory_extraction"

CONTINUITY_MEMORY_PROMPT_SCHEMA_VERSION = "v2"

CONTINUITY_MEMORY_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "continuity_question": "string",
        "carry_forward_answer": "string",
        "retrieval_context": "string or null",
    },
    indent=2,
)

CONTINUITY_MEMORY_SYSTEM_PROMPT = (
    "Create one compact continuity memory from a bounded single-thread set of lower-level conversation memory. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied memory and carried conclusions. "
    "Frame the output for repeated-answer continuity: what was already answered, and what concise answer should carry forward. "
    "Do not invent recurrence beyond the supplied thread, and do not add recommendations, risks, or new conclusions. "
    "Keep the summary concise: at most two sentences and roughly 70 words. "
    "For retrieval_context: write one short search-friendly context line (12-30 words) that helps this record match later queries, "
    "or null when the summary already has enough search cues. Do not restate the summary."
)

CONTINUITY_MEMORY_MAX_TEXT_CHARS = 3000

CONTINUITY_MEMORY_TEXT_VIEW = "memory_object.continuity_memory_context"

TASK_CHECKPOINT_PROMPT_SCHEMA_ID = "task_checkpoint_extraction"

TASK_CHECKPOINT_PROMPT_SCHEMA_VERSION = "v2"

TASK_CHECKPOINT_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "task": "string",
        "current_state": "string",
        "key_findings": ["string"],
        "blocker_state": "string",
        "next_step": "string",
        "evidence": ["string"],
        "freshness_signal": "string",
        "retrieval_context": "string or null",
    },
    indent=2,
)

TASK_CHECKPOINT_SYSTEM_PROMPT = (
    "Create one compact resumed-work task checkpoint from a bounded single-thread set of lower-level conversation memory. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied memory, carried conclusions, and selected work artifacts. "
    "Capture the task, the current state, key findings, blocker or failed-attempt state when present, the next supported step when present, and a concise freshness signal. "
    "Do not turn this into a workflow graph, transcript replay, or speculative recommendation. "
    "Keep the summary concise: at most two sentences and roughly 80 words. "
    "For retrieval_context: write one short search-friendly context line (12-30 words) that helps this record match later queries, "
    "or null when the summary already has enough search cues. Do not restate the summary."
)

TASK_CHECKPOINT_MAX_TEXT_CHARS = 3200

TASK_CHECKPOINT_TEXT_VIEW = "memory_object.task_checkpoint_context"

# ---------------------------------------------------------------------------
# Merged thread summary + task checkpoint (single LLM call)
# ---------------------------------------------------------------------------

THREAD_SUMMARY_WITH_CHECKPOINT_PROMPT_SCHEMA_ID = "thread_summary_with_checkpoint_extraction"

THREAD_SUMMARY_WITH_CHECKPOINT_PROMPT_SCHEMA_VERSION = "v2"

THREAD_SUMMARY_WITH_CHECKPOINT_SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "content_quality": "string",
        "retrieval_context": "string or null",
        "task_checkpoint": {
            "summary": "string",
            "task": "string",
            "current_state": "string",
            "key_findings": ["string"],
            "blocker_state": "string",
            "next_step": "string",
            "evidence": ["string"],
            "freshness_signal": "string",
            "retrieval_context": "string or null",
        },
    },
    indent=2,
)

THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT = (
    "Summarize one agent-mediated conversation thread for future recall and "
    "create a compact resumed-work task checkpoint from the same thread. "
    "Return exactly one JSON object and no extra prose. "
    "Use only facts that are explicitly present in the thread items, selected work artifacts, or carried conclusions. "
    "Selected work artifacts may describe explicit partial progress, blockers, next steps, constraints, or durable findings; include them only when they are explicitly stated. "
    "Do not infer causes, recommendations, next steps, risks, or unresolved conclusions that are not stated. "
    "Only say the thread is unresolved when the supplied content truly lacks any resolved conclusion, durable constraint, progress state, blocker, or supported next step. "
    "For the top-level summary: keep it concise, at most two sentences and roughly 60 words. "
    "For the top-level content_quality, classify the summary you wrote: "
    '"substantive" when the thread contains resolved conclusions, durable findings, constraints, progress state, or work artifacts worth recalling; '
    '"query_only" when the thread contains only a user question or request with no substantive response — an assistant reply that merely acknowledges or promises to investigate does not count as a substantive response; '
    '"unresolved" when the thread has substantive back-and-forth discussion but no resolved conclusions, decisions, or durable findings; '
    '"weak" when the thread is a greeting, phatic exchange, sign-off, or otherwise carries no recallable information. '
    "For the top-level retrieval_context: write one short search-friendly context line (12-30 words) that helps the summary match later queries, or null when the summary already has enough search cues. Do not restate the summary. "
    "For the task_checkpoint section: capture the task, the current state, key findings, blocker or failed-attempt state when present, the next supported step when present, and a concise freshness signal. "
    "Do not turn the checkpoint into a workflow graph, transcript replay, or speculative recommendation. "
    "Keep the task_checkpoint summary concise: at most two sentences and roughly 80 words. "
    "For task_checkpoint retrieval_context: write one short search-friendly context line (12-30 words) that helps this checkpoint match later queries, or null when the checkpoint summary already has enough search cues. Do not restate the checkpoint summary."
)

def _finalize_memory_builder(
    *,
    memory_object: MemoryObject,
    container_ref: str | None,
    thread_ref: str | None,
    producer_kind: str,
    producer_schema_id: str,
    producer_schema_version: str,
    prompt_variant: str,
    subjects: list,
    index_source: str,
    text_view_name: str,
    retrieval_context: str | None,
    plugin_name: str,
    llm_metadata=None,
) -> tuple[MemoryObject, list]:
    """Shared tail for memory builders: envelope, indexing, enrichment, vector embedding."""
    memory_object = replace(
        memory_object,
        envelope=_build_memory_envelope(
            kind=_memory_kind_for_type(memory_object.type),
            container_ref=container_ref,
            thread_ref=thread_ref,
            confidence=_memory_confidence_for_type(memory_object.type),
            producer_kind=producer_kind,
            producer_schema_id=producer_schema_id,
            producer_schema_version=producer_schema_version,
            prompt_variant=prompt_variant,
            kind_basis="inherited_from_children" if subjects else "type_map",
            subjects=subjects,
        ),
    )
    index_entry = build_index_entry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_source),
        text_view_name=text_view_name,
    )
    memory_object, enrichment_index_entry = _apply_inline_enrichment(
        memory_object=memory_object,
        retrieval_context=retrieval_context,
        plugin_name=plugin_name,
        prompt_variant=prompt_variant,
        llm_metadata=llm_metadata,
    )
    index_entries = [index_entry]
    if enrichment_index_entry is not None:
        index_entries.append(enrichment_index_entry)
    embedding_text = build_embedding_text(memory_object)
    if embedding_text is not None:
        index_entries.append(
            build_index_entry(
                target_kind="memory_object",
                target_id=memory_object.id,
                index_type=VECTOR_INDEX_TYPE,
                text_view=embedding_text,
                text_view_name=f"{text_view_name}.embedding",
                provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
            )
        )
    return memory_object, index_entries


def build_thread_summary(*, provider: LLMProvider, prompt_variant: str, plugin_name: str, thread_summary_schema_id: str, task_checkpoint_schema_id: str, aggregate: ThreadAggregate, conclusions: list[MemoryObject]) -> ProcessResult:
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

        selected_work_artifacts = _collect_selected_work_artifacts(aggregate.source_items)
        use_merged_call = _should_build_task_checkpoint(selected_work_artifacts)

        thread_material = _build_thread_material(aggregate.source_items)
        if len(thread_material) > THREAD_SUMMARY_MAX_TEXT_CHARS:
            thread_material = thread_material[:THREAD_SUMMARY_MAX_TEXT_CHARS].rstrip() + "\n[thread items truncated for token budget]"

        user_prompt_text = (
            ("Summarize this thread conservatively for later recall and "
             "create one compact resumed-work checkpoint from the same content. " if use_merged_call else
             "Summarize this thread conservatively for later recall. ") +
            "Use only explicit information from the provided content.\n\n"
            f"Container ref: {aggregate.container_ref}\n"
            f"Thread ref: {aggregate.thread_ref}\n"
            f"Latest occurred at: {aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else 'null'}\n"
            f"Carried conclusions:\n{chr(10).join(conclusion_lines) if conclusion_lines else '- none'}\n\n"
            f"Selected work artifacts:\n{_format_selected_work_artifacts(selected_work_artifacts)}\n\n"
            f"Thread items:\n{thread_material}"
        )
        response = provider.generate_json(
            system_prompt=THREAD_SUMMARY_WITH_CHECKPOINT_SYSTEM_PROMPT if use_merged_call else THREAD_SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt_text,
            schema_description=THREAD_SUMMARY_WITH_CHECKPOINT_SCHEMA_DESCRIPTION if use_merged_call else THREAD_SUMMARY_SCHEMA_DESCRIPTION,
        )
        parsed_summary = response.parsed_json.get("summary")
        if not isinstance(parsed_summary, str) or not parsed_summary.strip():
            raise ValueError("thread summary extraction must return a non-empty summary string")
        summary = _resolve_thread_summary(
            parsed_summary.strip(),
            conclusion_payload=[
                {
                    "type": conclusion.type,
                    "text": conclusion.payload.get("decision")
                    or conclusion.payload.get("investigation_outcome")
                    or conclusion.payload.get("summary")
                    or "",
                }
                for conclusion in carried_conclusions
            ],
            selected_work_artifacts=selected_work_artifacts,
        )
        raw_llm_content_quality = response.parsed_json.get("content_quality")
        llm_content_quality = raw_llm_content_quality if isinstance(raw_llm_content_quality, str) else None

        semantic_provenance = {
            "semantic_plugin": plugin_name,
            "prompt_variant": prompt_variant,
            "prompt_schema_id": THREAD_SUMMARY_PROMPT_SCHEMA_ID,
            "prompt_schema_version": THREAD_SUMMARY_PROMPT_SCHEMA_VERSION,
        }
        conclusion_payload = _build_conclusion_payload(carried_conclusions)
        thread_subjects = _merge_subject_anchors(_subject_anchors_from_memory_objects(carried_conclusions), _subject_anchors_from_source_items(aggregate.source_items))
        thread_summary_memory = MemoryObject(
            type="thread_summary",
            schema_id=thread_summary_schema_id,
            schema_version="v1",
            payload={
                "thread_ref": aggregate.thread_ref,
                "container_ref": aggregate.container_ref,
                "summary": summary,
                "conclusions": conclusion_payload,
                "selected_work_artifacts": selected_work_artifacts,
                "content_quality": _compute_thread_summary_content_quality(summary, conclusion_payload, selected_work_artifacts, llm_content_quality=llm_content_quality),
                "latest_occurred_at": aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else None,
                "semantic_provenance": semantic_provenance,
            },
            visibility=aggregate.visibility,
            container_ref=aggregate.container_ref,
            freshness_at=aggregate.latest_occurred_at,
        )
        relations = [
            Relation(
                from_kind="memory_object",
                from_id=thread_summary_memory.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=source_item_id,
            )
            for source_item_id in aggregate.source_item_ids
        ]
        relations.extend(
            Relation(
                from_kind="memory_object",
                from_id=thread_summary_memory.id,
                relation_type="relates_to",
                to_kind="memory_object",
                to_id=conclusion.id,
            )
            for conclusion in carried_conclusions
        )
        index_source = " ".join(
            [
                summary,
                *[item["text"] for item in conclusion_payload if item.get("text")],
                *[item["text"] for item in selected_work_artifacts if item.get("text")],
            ]
        )
        thread_summary_memory, index_entries = _finalize_memory_builder(
            memory_object=thread_summary_memory,
            container_ref=aggregate.container_ref,
            thread_ref=aggregate.thread_ref,
            producer_kind="thread_aggregation",
            producer_schema_id=THREAD_SUMMARY_PROMPT_SCHEMA_ID,
            producer_schema_version=THREAD_SUMMARY_PROMPT_SCHEMA_VERSION,
            prompt_variant=prompt_variant,
            subjects=thread_subjects,
            index_source=index_source,
            text_view_name=THREAD_SUMMARY_TEXT_VIEW,
            retrieval_context=str(response.parsed_json.get("retrieval_context") or "").strip() or None,
            plugin_name=plugin_name,
            llm_metadata=response.metadata,
        )
        memory_objects = [thread_summary_memory]

        if use_merged_call:
            checkpoint_parsed = response.parsed_json.get("task_checkpoint", {})
            if not isinstance(checkpoint_parsed, dict):
                checkpoint_parsed = {}
            task_checkpoint_memory, task_checkpoint_index_entries = _build_task_checkpoint_from_parsed(
                checkpoint_parsed=checkpoint_parsed,
                aggregate=aggregate,
                summary=summary,
                conclusion_payload=conclusion_payload,
                selected_work_artifacts=selected_work_artifacts,
                prompt_variant=prompt_variant,
                plugin_name=plugin_name,
                task_checkpoint_schema_id=task_checkpoint_schema_id,
                llm_metadata=response.metadata,
            )
            task_checkpoint_memory = replace(
                task_checkpoint_memory,
                envelope=_build_memory_envelope(
                    kind=_memory_kind_for_type(task_checkpoint_memory.type),
                    container_ref=aggregate.container_ref,
                    thread_ref=aggregate.thread_ref,
                    confidence=_memory_confidence_for_type(task_checkpoint_memory.type),
                    producer_kind="thread_aggregation",
                    producer_schema_id=TASK_CHECKPOINT_PROMPT_SCHEMA_ID,
                    producer_schema_version=TASK_CHECKPOINT_PROMPT_SCHEMA_VERSION,
                    prompt_variant=prompt_variant,
                    kind_basis="inherited_from_children" if thread_subjects else "type_map",
                    subjects=thread_subjects,
                ),
            )
            memory_objects.append(task_checkpoint_memory)
            index_entries.extend(task_checkpoint_index_entries)
            relations.extend(
                Relation(
                    from_kind="memory_object",
                    from_id=task_checkpoint_memory.id,
                    relation_type="supported_by",
                    to_kind="source_item",
                    to_id=source_item_id,
                )
                for source_item_id in aggregate.source_item_ids
            )
            relations.extend(
                Relation(
                    from_kind="memory_object",
                    from_id=task_checkpoint_memory.id,
                    relation_type="relates_to",
                    to_kind="memory_object",
                    to_id=conclusion.id,
                )
                for conclusion in carried_conclusions
            )
        return ProcessResult(
            memory_objects=memory_objects,
            relations=relations,
            index_entries=index_entries,
        )

def build_task_checkpoint_memory(
    *,
    aggregate: ThreadAggregate,
    summary: str,
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
    provider: LLMProvider,
    prompt_variant: str,
    plugin_name: str,
    task_checkpoint_schema_id: str,
) -> tuple[MemoryObject, list[object]]:
        checkpoint_material = "\n".join(
            [
                f"Thread summary: {summary}",
                f"Carried conclusions:\n{_format_conclusions(conclusion_payload)}",
                f"Selected work artifacts:\n{_format_selected_work_artifacts(selected_work_artifacts)}",
            ]
        )
        if len(checkpoint_material) > TASK_CHECKPOINT_MAX_TEXT_CHARS:
            checkpoint_material = checkpoint_material[:TASK_CHECKPOINT_MAX_TEXT_CHARS].rstrip() + "\n[task checkpoint context truncated for token budget]"

        response = provider.generate_json(
            system_prompt=TASK_CHECKPOINT_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact resumed-work checkpoint from this thread context. "
                "Use only explicit information from the provided summary, conclusions, and selected work artifacts.\n\n"
                f"Container ref: {aggregate.container_ref}\n"
                f"Thread ref: {aggregate.thread_ref}\n"
                f"Latest occurred at: {aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else 'null'}\n\n"
                f"{checkpoint_material}"
            ),
            schema_description=TASK_CHECKPOINT_SCHEMA_DESCRIPTION,
        )
        return _build_task_checkpoint_from_parsed(
            checkpoint_parsed=response.parsed_json,
            aggregate=aggregate,
            summary=summary,
            conclusion_payload=conclusion_payload,
            selected_work_artifacts=selected_work_artifacts,
            prompt_variant=prompt_variant,
            plugin_name=plugin_name,
            task_checkpoint_schema_id=task_checkpoint_schema_id,
            llm_metadata=response.metadata,
        )


def _build_task_checkpoint_from_parsed(
    *,
    checkpoint_parsed: dict,
    aggregate: ThreadAggregate,
    summary: str,
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
    prompt_variant: str,
    plugin_name: str,
    task_checkpoint_schema_id: str,
    llm_metadata=None,
) -> tuple[MemoryObject, list[object]]:
        parsed_summary = str(checkpoint_parsed.get("summary") or "").strip()
        if not parsed_summary:
            parsed_summary = _default_task_checkpoint_task(summary, conclusion_payload)
        task = str(checkpoint_parsed.get("task") or "").strip() or _default_task_checkpoint_task(summary, conclusion_payload)
        derived_current_state = _default_task_checkpoint_state(summary, selected_work_artifacts)
        parsed_current_state = str(checkpoint_parsed.get("current_state") or "").strip()
        current_state = _normalize_task_checkpoint_current_state(
            current_state=parsed_current_state,
            derived_current_state=derived_current_state,
            selected_work_artifacts=selected_work_artifacts,
        ) or derived_current_state
        key_findings = _parse_string_list(checkpoint_parsed.get("key_findings")) or _default_task_checkpoint_findings(conclusion_payload, selected_work_artifacts)
        blocker_state = str(checkpoint_parsed.get("blocker_state") or "").strip() or _default_task_checkpoint_blocker(selected_work_artifacts)
        next_step = str(checkpoint_parsed.get("next_step") or "").strip() or _default_task_checkpoint_next_step(selected_work_artifacts)
        evidence = _parse_string_list(checkpoint_parsed.get("evidence")) or _default_task_checkpoint_evidence(conclusion_payload, selected_work_artifacts, summary)
        freshness_signal = str(checkpoint_parsed.get("freshness_signal") or "").strip() or _default_task_checkpoint_freshness_signal(aggregate.latest_occurred_at)

        memory_object = MemoryObject(
            type="task_checkpoint",
            schema_id=task_checkpoint_schema_id,
            schema_version="v1",
            payload={
                "summary": parsed_summary,
                "task": task,
                "current_state": current_state,
                "key_findings": key_findings,
                "blocker_state": blocker_state,
                "next_step": next_step,
                "evidence": evidence,
                "freshness_signal": freshness_signal,
                "conclusions": conclusion_payload,
                "selected_work_artifacts": selected_work_artifacts,
                "latest_occurred_at": aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else None,
                "container_ref": aggregate.container_ref,
                "thread_ref": aggregate.thread_ref,
                "semantic_provenance": {
                    "semantic_plugin": plugin_name,
                    "prompt_variant": prompt_variant,
                    "prompt_schema_id": TASK_CHECKPOINT_PROMPT_SCHEMA_ID,
                    "prompt_schema_version": TASK_CHECKPOINT_PROMPT_SCHEMA_VERSION,
                },
            },
            visibility=aggregate.visibility,
            container_ref=aggregate.container_ref,
            freshness_at=aggregate.latest_occurred_at,
        )
        index_source = " ".join(
            [
                parsed_summary,
                task,
                current_state,
                blocker_state,
                next_step,
                freshness_signal,
                *key_findings,
                *evidence,
                *[item["text"] for item in conclusion_payload if item.get("text")],
                *[item["text"] for item in selected_work_artifacts if item.get("text")],
            ]
        )
        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
            text_view_name=TASK_CHECKPOINT_TEXT_VIEW,
        )
        retrieval_context = str(checkpoint_parsed.get("retrieval_context") or "").strip() or None
        memory_object, enrichment_index_entry = _apply_inline_enrichment(
            memory_object=memory_object,
            retrieval_context=retrieval_context,
            plugin_name=plugin_name,
            prompt_variant=prompt_variant,
            llm_metadata=llm_metadata,
        )
        index_entries = [index_entry]
        if enrichment_index_entry is not None:
            index_entries.append(enrichment_index_entry)
        task_checkpoint_embedding_text = build_embedding_text(memory_object)
        if task_checkpoint_embedding_text is not None:
            index_entries.append(
                build_index_entry(
                    target_kind="memory_object",
                    target_id=memory_object.id,
                    index_type=VECTOR_INDEX_TYPE,
                    text_view=task_checkpoint_embedding_text,
                    text_view_name=f"{TASK_CHECKPOINT_TEXT_VIEW}.embedding",
                    provider_name=VECTOR_EMBEDDING_PROVIDER_NAME,
                    provider_version=VECTOR_EMBEDDING_PROVIDER_VERSION,
                )
            )
        return memory_object, index_entries

def build_consolidated_memory(*, provider: LLMProvider, prompt_variant: str, plugin_name: str, pattern_memory_schema_id: str, continuity_memory_schema_id: str, group: ConsolidationGroup) -> ProcessResult:
        if _should_build_continuity_memory(group):
            return build_continuity_memory(provider=provider, prompt_variant=prompt_variant, plugin_name=plugin_name, continuity_memory_schema_id=continuity_memory_schema_id, group=group)
        return build_pattern_memory(provider=provider, prompt_variant=prompt_variant, plugin_name=plugin_name, pattern_memory_schema_id=pattern_memory_schema_id, group=group)

def build_pattern_memory(*, provider: LLMProvider, prompt_variant: str, plugin_name: str, pattern_memory_schema_id: str, group: ConsolidationGroup) -> ProcessResult:
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

        response = provider.generate_json(
            system_prompt=PATTERN_MEMORY_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact higher-level memory from this bounded set of lower-level memory. "
                "Use only explicit facts from the supplied memory and conclusions.\n\n"
                f"Strategy: {group.strategy_name}\n"
                f"Container ref: {group.container_ref or 'null'}\n"
                f"Thread ref: {group.thread_ref or 'null'}\n"
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

        consolidated_subjects = _subject_anchors_from_memory_objects(candidate.memory_object for candidate in group.candidates)
        semantic_provenance = {
            "semantic_plugin": plugin_name,
            "prompt_variant": prompt_variant,
        }
        consolidation_provenance = {
            "memory_kind": "pattern_memory",
            "strategy_name": group.strategy_name,
            "strategy_version": group.strategy_version,
            "prompt_schema_id": PATTERN_MEMORY_PROMPT_SCHEMA_ID,
            "prompt_schema_version": PATTERN_MEMORY_PROMPT_SCHEMA_VERSION,
            "prompt_variant": prompt_variant,
        }
        memory_object = MemoryObject(
            type="pattern_memory",
            schema_id=pattern_memory_schema_id,
            schema_version="v1",
            payload={
                "summary": parsed_summary.strip(),
                "pattern_label": pattern_label.strip(),
                "conclusions": conclusion_payload,
                "supporting_memory_ids": list(group.candidate_ids),
                "latest_occurred_at": group.latest_occurred_at.isoformat(),
                "container_ref": group.container_ref,
                "thread_ref": group.thread_ref,
                "group_key": group.group_key,
                "semantic_provenance": semantic_provenance,
                "consolidation_provenance": consolidation_provenance,
            },
            visibility=group.visibility,
            container_ref=group.container_ref,
            freshness_at=group.latest_occurred_at,
        )
        index_source = " ".join(
            [
                parsed_summary.strip(),
                *[conclusion["text"] for conclusion in conclusion_payload if conclusion.get("text")],
            ]
        )
        memory_object, index_entries = _finalize_memory_builder(
            memory_object=memory_object,
            container_ref=group.container_ref,
            thread_ref=group.thread_ref,
            producer_kind="consolidation",
            producer_schema_id=PATTERN_MEMORY_PROMPT_SCHEMA_ID,
            producer_schema_version=PATTERN_MEMORY_PROMPT_SCHEMA_VERSION,
            prompt_variant=prompt_variant,
            subjects=consolidated_subjects,
            index_source=index_source,
            text_view_name=PATTERN_MEMORY_TEXT_VIEW,
            retrieval_context=str(response.parsed_json.get("retrieval_context") or "").strip() or None,
            plugin_name=plugin_name,
            llm_metadata=response.metadata,
        )
        return ProcessResult(
            memory_objects=[memory_object],
            relations=[],
            index_entries=index_entries,
        )

def build_continuity_memory(*, provider: LLMProvider, prompt_variant: str, plugin_name: str, continuity_memory_schema_id: str, group: ConsolidationGroup) -> ProcessResult:
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

        consolidated_subjects = _subject_anchors_from_memory_objects(candidate.memory_object for candidate in group.candidates)
        response = provider.generate_json(
            system_prompt=CONTINUITY_MEMORY_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact repeated-answer continuity memory from this bounded single-thread memory set. "
                "Use only explicit facts from the supplied memory and conclusions.\n\n"
                f"Strategy: {group.strategy_name}\n"
                f"Container ref: {group.container_ref or 'null'}\n"
                f"Thread ref: {group.thread_ref or 'null'}\n"
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
            schema_id=continuity_memory_schema_id,
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
                "group_key": group.group_key,
                "semantic_provenance": {
                    "semantic_plugin": plugin_name,
                    "prompt_variant": prompt_variant,
                },
                "consolidation_provenance": {
                    "memory_kind": "continuity_memory",
                    "strategy_name": group.strategy_name,
                    "strategy_version": group.strategy_version,
                    "prompt_schema_id": CONTINUITY_MEMORY_PROMPT_SCHEMA_ID,
                    "prompt_schema_version": CONTINUITY_MEMORY_PROMPT_SCHEMA_VERSION,
                    "prompt_variant": prompt_variant,
                },
            },
            visibility=group.visibility,
            container_ref=group.container_ref,
            freshness_at=group.latest_occurred_at,
        )
        index_source = " ".join(
            [
                parsed_summary.strip(),
                continuity_question.strip(),
                carry_forward_answer.strip(),
                *[conclusion["text"] for conclusion in conclusion_payload if conclusion.get("text")],
            ]
        )
        memory_object, index_entries = _finalize_memory_builder(
            memory_object=memory_object,
            container_ref=group.container_ref,
            thread_ref=group.thread_ref,
            producer_kind="consolidation",
            producer_schema_id=CONTINUITY_MEMORY_PROMPT_SCHEMA_ID,
            producer_schema_version=CONTINUITY_MEMORY_PROMPT_SCHEMA_VERSION,
            prompt_variant=prompt_variant,
            subjects=consolidated_subjects,
            index_source=index_source,
            text_view_name=CONTINUITY_MEMORY_TEXT_VIEW,
            retrieval_context=str(response.parsed_json.get("retrieval_context") or "").strip() or None,
            plugin_name=plugin_name,
            llm_metadata=response.metadata,
        )
        return ProcessResult(
            memory_objects=[memory_object],
            relations=[],
            index_entries=index_entries,
        )

def _apply_inline_enrichment(
    *,
    memory_object: MemoryObject,
    retrieval_context: str | None,
    plugin_name: str,
    prompt_variant: str,
    llm_metadata=None,
) -> tuple[MemoryObject, object | None]:
    if memory_object.type not in ENRICHABLE_MEMORY_TYPES:
        return memory_object, None
    if not retrieval_context:
        return memory_object, None
    provenance = build_prompt_provenance(
        semantic_plugin=plugin_name,
        contract=WRITE_ENRICHMENT_PROMPT_ROLE,
        prompt_variant=prompt_variant,
        model_role="write_enrichment",
        llm_metadata=llm_metadata,
        extra={"delivery": "inline", "memory_type": memory_object.type},
    )
    updated_payload = dict(memory_object.payload)
    updated_payload["retrieval_enrichment"] = {
        "retrieval_context": retrieval_context,
        "semantic_provenance": provenance,
    }
    enriched_memory = replace(memory_object, payload=updated_payload)
    enrichment_index_entry = build_index_entry(
        target_kind="memory_object",
        target_id=enriched_memory.id,
        index_type="lexical",
        text_view=normalize_for_index(retrieval_context),
        text_view_name=WRITE_ENRICHMENT_TEXT_VIEW,
    )
    return enriched_memory, enrichment_index_entry

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

def _parse_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    parsed: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in parsed:
            parsed.append(text)
    return parsed

def _build_conclusion_payload(conclusions: Iterable[MemoryObject]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for conclusion in conclusions:
        text = str(
            conclusion.payload.get("decision")
            or conclusion.payload.get("investigation_outcome")
            or conclusion.payload.get("summary")
            or ""
        ).strip()
        if text:
            payload.append({"type": conclusion.type, "text": text})
    return payload

def _should_build_task_checkpoint(selected_work_artifacts: list[dict[str, str]]) -> bool:
    signal_types = {item.get("signal_type") for item in selected_work_artifacts if item.get("text")}
    return bool(signal_types.intersection({"progress_update", "blocker", "next_step"}))

def _strip_work_signal_prefix(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix, _signal_type in WORK_SIGNAL_PREFIX_TO_TYPE:
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped

def _signal_texts(selected_work_artifacts: list[dict[str, str]], signal_type: str) -> list[str]:
    values: list[str] = []
    for item in selected_work_artifacts:
        if item.get("signal_type") != signal_type:
            continue
        text = _strip_work_signal_prefix(str(item.get("text") or ""))
        if text and text not in values:
            values.append(text)
    return values

def _default_task_checkpoint_task(summary: str, conclusions: list[dict[str, str]]) -> str:
    for conclusion in conclusions:
        text = str(conclusion.get("text") or "").strip()
        if text:
            return text
    if summary:
        return summary
    return "Resume the previously recorded task from this thread."

def _default_task_checkpoint_state(summary: str, selected_work_artifacts: list[dict[str, str]]) -> str:
    fragments: list[str] = []
    progress_updates = _signal_texts(selected_work_artifacts, "progress_update")
    blockers = _signal_texts(selected_work_artifacts, "blocker")
    constraints = _signal_texts(selected_work_artifacts, "constraint")
    if progress_updates:
        fragments.append(progress_updates[-1])
    if blockers:
        fragments.append(blockers[-1])
    if not fragments:
        next_steps = _signal_texts(selected_work_artifacts, "next_step")
        if next_steps:
            fragments.append(f"Pending: {next_steps[-1]}")
    if not fragments and constraints:
        fragments.append(f"Constraint: {constraints[-1]}")
    if fragments:
        return " ".join(fragments)
    return summary

def _normalize_task_checkpoint_current_state(
    *,
    current_state: str,
    derived_current_state: str,
    selected_work_artifacts: list[dict[str, str]],
) -> str:
    if not current_state:
        return derived_current_state
    if not derived_current_state:
        return current_state
    blockers = _signal_texts(selected_work_artifacts, "blocker")
    progress_updates = _signal_texts(selected_work_artifacts, "progress_update")
    next_steps = _signal_texts(selected_work_artifacts, "next_step")
    latest_blocker = blockers[-1] if blockers else ""
    stale_blockers = blockers[:-1]
    active_signals = [text for text in (latest_blocker, progress_updates[-1] if progress_updates else "", next_steps[-1] if next_steps else "") if text]
    current_state_normalized = normalize_for_index(current_state)
    derived_state_normalized = normalize_for_index(derived_current_state)
    if stale_blockers:
        stale_norms = [normalize_for_index(text) for text in stale_blockers if text]
        fragments = [fragment.strip() for fragment in re.split(r"(?<=[.!?])\s+|\s*;\s*", current_state) if fragment.strip()]
        kept_fragments = [
            fragment
            for fragment in fragments
            if not any(stale_norm in normalize_for_index(fragment) for stale_norm in stale_norms)
        ]
        if kept_fragments:
            cleaned_state = " ".join(kept_fragments)
            cleaned_norm = normalize_for_index(cleaned_state)
            if latest_blocker and normalize_for_index(latest_blocker) not in cleaned_norm:
                cleaned_state = f"{cleaned_state} {latest_blocker}".strip()
                cleaned_norm = normalize_for_index(cleaned_state)
            if any(normalize_for_index(text) in cleaned_norm for text in active_signals):
                return cleaned_state
    # When an active blocker is present and current_state is a multi-fragment mix,
    # strip fragments that describe already-resolved items (e.g. "token refresh is fixed")
    # so that the payload reflects active state only.
    if latest_blocker and normalize_for_index(latest_blocker) in current_state_normalized:
        fragments = [f.strip() for f in re.split(r"(?<=[.!?])\s+|\s*;\s*", current_state) if f.strip()]
        if len(fragments) > 1:
            blocker_norm = normalize_for_index(latest_blocker)
            _RESOLUTION_MARKERS = (
                "is fixed", "was fixed", "has been fixed",
                "is resolved", "was resolved", "has been resolved",
                "is completed", "was completed", "has been completed",
                "is done", "was done", "no longer blocked", "no longer failing",
            )
            active_fragments = [
                f for f in fragments
                if blocker_norm in normalize_for_index(f)
                or not any(marker in f.lower() for marker in _RESOLUTION_MARKERS)
            ]
            if active_fragments and len(active_fragments) < len(fragments):
                return " ".join(active_fragments)
    if any(normalize_for_index(text) in current_state_normalized for text in active_signals):
        return current_state
    if active_signals and current_state_normalized != derived_state_normalized:
        return derived_current_state
    return current_state


def _default_task_checkpoint_findings(conclusions: list[dict[str, str]], selected_work_artifacts: list[dict[str, str]]) -> list[str]:
    findings: list[str] = []
    for conclusion in conclusions:
        text = str(conclusion.get("text") or "").strip()
        if text and text not in findings:
            findings.append(text)
    for signal_type in ("key_finding", "progress_update", "constraint"):
        for text in _signal_texts(selected_work_artifacts, signal_type):
            if text not in findings:
                findings.append(text)
    return findings[:3]

def _default_task_checkpoint_blocker(selected_work_artifacts: list[dict[str, str]]) -> str:
    blockers = _signal_texts(selected_work_artifacts, "blocker")
    return blockers[-1] if blockers else ""

def _default_task_checkpoint_next_step(selected_work_artifacts: list[dict[str, str]]) -> str:
    next_steps = _signal_texts(selected_work_artifacts, "next_step")
    return next_steps[-1] if next_steps else ""

def _default_task_checkpoint_evidence(conclusions: list[dict[str, str]], selected_work_artifacts: list[dict[str, str]], summary: str) -> list[str]:
    evidence: list[str] = []
    for conclusion in conclusions:
        text = str(conclusion.get("text") or "").strip()
        if text and text not in evidence:
            evidence.append(text)
    for item in selected_work_artifacts:
        text = str(item.get("text") or "").strip()
        if text and text not in evidence:
            evidence.append(text)
    if not evidence and summary:
        evidence.append(summary)
    return evidence[:4]

def _default_task_checkpoint_freshness_signal(latest_occurred_at) -> str:
    if latest_occurred_at is None:
        return "Latest explicit update time was not recorded."
    return f"Latest explicit update at {latest_occurred_at.isoformat()}."

def _supports_thread_aggregation(source_item: SourceItem) -> bool:
    artifact_key = ((source_item.artifact_kind or "").lower(), (source_item.role or "").lower())
    return artifact_key in PRIMARY_THREAD_ARTIFACTS or artifact_key in SELECTED_THREAD_ARTIFACTS

def _thread_is_query_only_recall_noise(
    source_items: list[SourceItem],
    *,
    selected_work_artifacts: list[dict[str, str]],
    carried_conclusions: list[MemoryObject],
) -> bool:
    if selected_work_artifacts or carried_conclusions:
        return False
    meaningful_items = [
        item
        for item in source_items
        if item.content.strip() and not _is_low_value_meta_artifact(item)
    ]
    if not meaningful_items:
        return False
    return all(
        (item.role or "").lower() == "user" and _text_looks_like_query(item.content)
        for item in meaningful_items
    )

def _text_looks_like_query(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return "?" in normalized or normalized.startswith(("what ", "which ", "why ", "how ", "can ", "could ", "do ", "does ", "did ", "is ", "are ", "will ", "would ", "please "))

def _build_thread_material(source_items: list[SourceItem]) -> str:
    filtered_lines = [
        f"{item.role or 'unknown'}/{item.artifact_kind or 'unknown'}: {item.content.strip()}"
        for item in source_items
        if item.content.strip() and not _is_low_value_meta_artifact(item)
    ]
    if filtered_lines:
        return "`n".join(filtered_lines)
    return "`n".join(
        f"{item.role or 'unknown'}/{item.artifact_kind or 'unknown'}: {item.content.strip()}"
        for item in source_items
        if item.content.strip()
    )

def _resolve_thread_summary(
    summary: str,
    *,
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
) -> str:
    if not _thread_summary_needs_fallback(summary, conclusion_payload, selected_work_artifacts):
        return summary
    return _build_thread_summary_fallback(conclusion_payload, selected_work_artifacts)

def _thread_summary_needs_fallback(
    summary: str,
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
) -> bool:
    stripped = summary.strip()
    if not stripped:
        return True
    if not (
        conclusion_payload
        or _signal_texts(selected_work_artifacts, "key_finding")
        or _signal_texts(selected_work_artifacts, "constraint")
        or _signal_texts(selected_work_artifacts, "progress_update")
        or _signal_texts(selected_work_artifacts, "blocker")
        or _signal_texts(selected_work_artifacts, "next_step")
    ):
        return False
    lowered = stripped.lower()
    if lowered in WEAK_THREAD_SUMMARY_TEXT or lowered.startswith("unresolved"):
        return True
    return _is_low_value_meta_text(stripped)

def _build_thread_summary_fallback(
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
) -> str:
    sentences: list[str] = []
    primary = _first_thread_state_text(conclusion_payload, selected_work_artifacts, ("key_finding", "progress_update", "blocker", "next_step"), prefer_conclusions=True)
    if primary:
        sentences.append(_ensure_sentence(primary))
    constraint = _first_thread_state_text(conclusion_payload, selected_work_artifacts, ("constraint",))
    if constraint and _normalize_summary_fragment(constraint) != _normalize_summary_fragment(primary):
        sentences.append(_ensure_sentence(f"Constraint: {constraint}"))
    elif not constraint:
        blocker = _first_thread_state_text(conclusion_payload, selected_work_artifacts, ("blocker",))
        next_step = _first_thread_state_text(conclusion_payload, selected_work_artifacts, ("next_step",))
        progress = _first_thread_state_text(conclusion_payload, selected_work_artifacts, ("progress_update",))
        secondary = ""
        if blocker and next_step:
            secondary = f"Blocked by {blocker}; next step is {next_step}"
        elif next_step:
            secondary = f"Next step: {next_step}"
        elif blocker:
            secondary = f"Blocked by {blocker}"
        elif progress and _normalize_summary_fragment(progress) != _normalize_summary_fragment(primary):
            secondary = f"Progress: {progress}"
        if secondary:
            sentences.append(_ensure_sentence(secondary))
    if not sentences:
        return "The thread recorded explicit conversation state for future recall."
    return " ".join(sentences[:2])

def _first_thread_state_text(
    conclusion_payload: list[dict[str, str]],
    selected_work_artifacts: list[dict[str, str]],
    signal_types: tuple[str, ...],
    *,
    prefer_conclusions: bool = False,
) -> str:
    if prefer_conclusions:
        for conclusion in conclusion_payload:
            text = str(conclusion.get("text") or "").strip()
            if text:
                return text
    for signal_type in signal_types:
        texts = _signal_texts(selected_work_artifacts, signal_type)
        if texts:
            return texts[0]
    if not prefer_conclusions:
        return ""
    return ""

def _ensure_sentence(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    normalized = normalized[0].upper() + normalized[1:]
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized

def _normalize_summary_fragment(text: str) -> str:
    return str(text or "").strip().lower().rstrip(".!?")

def _collect_selected_work_artifacts(source_items: list[SourceItem]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source_item in source_items:
        for artifact in _build_selected_work_artifacts(source_item):
            key = (str(artifact["signal_type"]), str(artifact["text"]))
            if key in seen:
                continue
            seen.add(key)
            selected.append(artifact)
    if len(selected) <= MAX_SELECTED_WORK_ARTIFACTS:
        return selected
    return selected[-MAX_SELECTED_WORK_ARTIFACTS:]

def _build_selected_work_artifacts(source_item: SourceItem) -> list[dict[str, str]]:
    text = source_item.content.strip()
    if not text:
        return []
    semantic_signals = _source_item_semantic_signals(source_item)
    if semantic_signals.get("is_low_value_meta") is True:
        return []
    artifacts = _collect_metadata_signal_artifacts(source_item, semantic_signals)
    if _is_low_value_meta_artifact(source_item):
        return artifacts
    signal_type = _classify_work_signal(source_item)
    if not signal_type:
        return artifacts
    fallback_artifact = _build_work_artifact(source_item, signal_type=signal_type, text=text, signal_origin="fallback")
    if any(
        item.get("signal_type") == fallback_artifact["signal_type"] and item.get("text") == fallback_artifact["text"]
        for item in artifacts
    ):
        return artifacts
    artifacts.append(fallback_artifact)
    return artifacts
def _collect_metadata_signal_artifacts(source_item: SourceItem, semantic_signals: dict[str, object]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for field_name, signal_type in (
        ("constraint_text", "constraint"),
        ("blocker_text", "blocker"),
        ("progress_text", "progress_update"),
        ("next_step_text", "next_step"),
        ("key_finding_text", "key_finding"),
    ):
        text = str(semantic_signals.get(field_name) or "").strip()
        if not text:
            continue
        artifacts.append(_build_work_artifact(source_item, signal_type=signal_type, text=text, signal_origin="llm"))
    return artifacts

def _build_work_artifact(
    source_item: SourceItem,
    *,
    signal_type: str,
    text: str,
    signal_origin: str,
) -> dict[str, str]:
    artifact_kind = str(source_item.artifact_kind or source_item.source_type)
    return {
        "artifact_kind": artifact_kind,
        "signal_type": signal_type,
        "signal_origin": signal_origin,
        "source_item_id": source_item.id,
        "occurred_at": source_item.occurred_at.isoformat() if source_item.occurred_at else "",
        "text": text,
    }

def _source_item_semantic_signals(source_item: SourceItem) -> dict[str, object]:
    metadata = source_item.metadata or {}
    if not isinstance(metadata, dict):
        return {}
    signals = metadata.get(SEMANTIC_SIGNAL_METADATA_KEY)
    return signals if isinstance(signals, dict) else {}

def _is_selected_work_artifact(source_item: SourceItem) -> bool:
    return (source_item.artifact_kind or "").lower() in SELECTED_WORK_ARTIFACT_KINDS and (source_item.role or "").lower() == "assistant"

def _classify_work_signal(source_item: SourceItem) -> str:
    artifact_kind = (source_item.artifact_kind or "").lower()
    text = source_item.content.strip()
    if not text:
        return ""
    if _is_selected_work_artifact(source_item):
        return _classify_work_signal_text(artifact_kind, text)
    artifact_key = (artifact_kind, (source_item.role or "").lower())
    if artifact_key not in PRIMARY_THREAD_ARTIFACTS:
        return ""
    return _classify_implicit_work_signal(source_item)

def _classify_implicit_work_signal(source_item: SourceItem) -> str:
    text = source_item.content.strip()
    lowered = text.lower()
    if _extract_constraint_signal_text(text):
        return "constraint"
    if any(marker in lowered for marker in IMPLICIT_FINDING_MARKERS):
        return "key_finding"
    if any(marker in lowered for marker in IMPLICIT_NEXT_STEP_MARKERS):
        return "next_step"
    if any(prefix in lowered for prefix in ("blocked:", "blocker:", "failed attempt:", "failure:")):
        return "blocker"
    return ""


def _classify_work_signal_text(artifact_kind: str | None, text: str) -> str:
    normalized_text = text.strip()
    if not normalized_text:
        return ""
    lowered = normalized_text.lower()
    artifact_kind_normalized = (artifact_kind or "").lower()
    if artifact_kind_normalized == "todo_snapshot":
        return "next_step"
    for prefix, signal_type in WORK_SIGNAL_PREFIX_TO_TYPE:
        if lowered.startswith(prefix):
            return signal_type
    if artifact_kind_normalized == "tool_use_summary":
        if any(marker in lowered for marker in ("next step", "do next", "try next", "follow-up")):
            return "next_step"
        if any(marker in lowered for marker in ("blocked", "blocker", "failure", "failed", "error", "401", "403", "denied")):
            return "blocker"
        if any(marker in lowered for marker in ("progress", "partial", "done", "completed", "refreshed", "updated", "investigated")):
            return "progress_update"
    return ""


def _extract_constraint_signal_text(text: str) -> str:
    lowered = text.lower()
    if not any(marker in lowered for marker in CONSTRAINT_MARKERS):
        return ""
    if not any(tool_marker in lowered for tool_marker in CONSTRAINT_TOOL_MARKERS):
        return ""
    return text.strip()

def _is_low_value_meta_artifact(source_item: SourceItem) -> bool:
    semantic_signals = _source_item_semantic_signals(source_item)
    if semantic_signals.get("is_low_value_meta") is True:
        return True
    if (source_item.role or "").lower() != "assistant":
        return False
    artifact_kind = (source_item.artifact_kind or "").lower()
    if artifact_kind not in {"assistant_output", "tool_use_summary", "unknown", ""}:
        return False
    return _is_low_value_meta_text(source_item.content)

def _is_low_value_meta_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in LOW_VALUE_ASSISTANT_META_PATTERNS)

def _format_selected_work_artifacts(selected_work_artifacts: list[dict[str, str]]) -> str:
    if not selected_work_artifacts:
        return "- none"
    return "\n".join(
        f"- {item['signal_type']} ({item['artifact_kind']}): {item['text']}"
        for item in selected_work_artifacts
    )

def _memory_hit_has_selected_work_artifacts(item: QueryResultItem) -> bool:
    if item.result_kind != "memory_hit" or not item.payload:
        return False
    selected = item.payload.get("selected_work_artifacts", [])
    return isinstance(selected, list) and any(isinstance(entry, dict) and entry.get("text") for entry in selected)
