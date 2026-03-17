from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from collections import OrderedDict
from typing import Iterable

from capabilities.consolidation import ConsolidationGroup, ConsolidationPolicy
from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import PackageQueryOutcome, ProcessResult, SupersessionHint
from core.indexing import build_index_entry
from core.models import InjectableBlock, MemoryObject, QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace, Relation, SourceItem
from providers.llm.base import LLMProvider
from semantic.base import ConsolidationSemanticPlugin, ThreadAggregationSemanticPlugin
from semantic.common import SEMANTIC_SIGNAL_METADATA_KEY, normalize_for_index
from semantic.llm_agent_memory import LLMAgentMemoryPlugin


THREAD_SUMMARY_PROMPT_SCHEMA_ID = "thread_summary_extraction"
THREAD_SUMMARY_PROMPT_SCHEMA_VERSION = "v2"
THREAD_SUMMARY_SCHEMA_DESCRIPTION = json.dumps({"summary": "string"}, indent=2)
THREAD_SUMMARY_SYSTEM_PROMPT = (
    "Summarize one agent-mediated conversation thread for future recall. "
    "Return exactly one JSON object and no extra prose. "
    "Use only facts that are explicitly present in the thread items, selected work artifacts, or carried conclusions. "
    "Selected work artifacts may describe explicit partial progress, blockers, next steps, constraints, or durable findings; include them only when they are explicitly stated. "
    "Do not infer causes, recommendations, next steps, risks, or unresolved conclusions that are not stated. "
    "Only say the thread is unresolved when the supplied content truly lacks any resolved conclusion, durable constraint, progress state, blocker, or supported next step. "
    "Keep the summary concise: at most two sentences and roughly 60 words."
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
)
CONSTRAINT_TOOL_MARKERS = (
    "browser",
    "jira",
    "slack",
    "auth",
    "authenticate",
    "authentication",
    "login",
    "tracker",
    "portal",
    "workspace",
    "local repo",
    "local repos",
)
CONSTRAINT_MARKERS = (
    "blocked from",
    "use only",
    "instead of",
    "ask you directly",
    "ask the user directly",
    "do not",
    "don't",
    "forbid",
    "forbids",
    "prohibit",
    "prohibits",
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
QUERY_ONLY_SUMMARY_MARKERS = (
    "contains only this question",
    "contains only the question",
    "contains only this request",
    "contains only the request",
    "only this question",
    "only this request",
)
UNRESOLVED_SUMMARY_MARKERS = (
    "no resolved information",
    "no resolved details",
    "no resolved state",
    "no resolved context",
    "no answer yet",
    "no replies yet",
    "nothing else in thread",
    "single user message",
)
STRUCTURED_CONFLICT_MEMORY_TYPES = {"task_checkpoint", "thread_summary", "discussion_summary"}
OPERATIONAL_GUIDANCE_MARKERS = (
    "next step",
    "should ",
    "need to ",
    "must ",
    "attempt ",
    "retry ",
    "resume ",
    "rerun ",
    "refresh ",
    "connect ",
    "authenticate",
    "sign in",
    "log in",
    "login",
    "open ",
    "use ",
)
CONSTRAINT_POLICY_STOPWORDS = {
    "and",
    "avoid",
    "blocked",
    "constraint",
    "constraints",
    "do",
    "dont",
    "forbid",
    "for",
    "forbidden",
    "forbids",
    "from",
    "never",
    "not",
    "only",
    "operator",
    "or",
    "please",
    "remember",
    "using",
    "without",
}
LOW_VALUE_GREETING_NOISE_PREFIXES = (
    "good morning",
    "good afternoon",
    "good evening",
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
)
LOW_VALUE_GREETING_NOISE_QUERIES = {
    "good morning",
    "good afternoon",
    "good evening",
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
}
CONSTRAINT_POLICY_ACTION_TOKENS = {
    "attempt",
    "attempted",
    "attempting",
    "attempts",
    "auth",
    "authenticate",
    "authentication",
    "connect",
    "connected",
    "connecting",
    "fetch",
    "fetched",
    "fetching",
    "log",
    "login",
    "manual",
    "manually",
    "open",
    "refresh",
    "refreshed",
    "refreshing",
    "rerun",
    "resume",
    "restore",
    "restored",
    "retry",
    "sign",
    "signin",
    "use",
    "using",
}
CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS = {
    "local",
    "note",
    "noted",
    "operator",
    "state",
}
CONSTRAINT_FOCUS_TOOL_TOKENS = {
    "auth",
    "authenticate",
    "authentication",
    "browser",
    "jira",
    "login",
    "portal",
    "repo",
    "repos",
    "slack",
    "tracker",
    "workspace",
}
CONSTRAINT_ONLY_RESIDUAL_TOKENS = {
    "and",
    "constraint",
    "constraints",
    "current",
    "note",
    "noted",
    "reminder",
    "remember",
    "state",
}
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
TASK_CHECKPOINT_PROMPT_SCHEMA_ID = "task_checkpoint_extraction"
TASK_CHECKPOINT_PROMPT_SCHEMA_VERSION = "v1"
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
    },
    indent=2,
)
TASK_CHECKPOINT_SYSTEM_PROMPT = (
    "Create one compact resumed-work task checkpoint from a bounded single-thread set of lower-level conversation memory. "
    "Return exactly one JSON object and no extra prose. "
    "Use only explicit facts from the supplied memory, carried conclusions, and selected work artifacts. "
    "Capture the task, the current state, key findings, blocker or failed-attempt state when present, the next supported step when present, and a concise freshness signal. "
    "Do not turn this into a workflow graph, transcript replay, or speculative recommendation. "
    "Keep the summary concise: at most two sentences and roughly 80 words."
)
TASK_CHECKPOINT_MAX_TEXT_CHARS = 3200
TASK_CHECKPOINT_TEXT_VIEW = "memory_object.task_checkpoint_context"
ROUTING_POLICY_NAME = "agent_conversation_memory.intent_routing.v4"
ROUTING_HIGHER_LEVEL_TYPES = {"pattern_memory", "continuity_memory", "task_checkpoint", "thread_summary", "discussion_summary"}
ROUTING_LOWER_LEVEL_EXACT_TYPES = {"decision", "investigation_outcome"}
ROUTING_SUMMARY_TYPES = {"thread_summary", "discussion_summary"}
ROUTING_PREFERRED_LAYERS = {
    "answer_continuity": ("continuity_memory", "investigation_outcome", "decision", "source_evidence", "task_checkpoint", "pattern_memory", "thread_summary", "discussion_summary"),
    "broad_recall": ("pattern_memory", "investigation_outcome", "decision", "continuity_memory", "task_checkpoint", "source_evidence", "thread_summary", "discussion_summary"),
    "work_resumption": ("task_checkpoint", "source_evidence", "investigation_outcome", "decision", "continuity_memory", "pattern_memory", "thread_summary", "discussion_summary"),
    "precise_fact": ("decision", "investigation_outcome", "source_evidence", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory"),
    "evidence_trace": ("source_evidence", "investigation_outcome", "decision", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory"),
    "investigative_conclusion": ("investigation_outcome", "decision", "source_evidence", "thread_summary", "discussion_summary", "continuity_memory", "task_checkpoint", "pattern_memory"),
}
ROUTING_LAYER_WEIGHTS = {
    "answer_continuity": {"continuity_memory": 400, "investigation_outcome": 320, "decision": 300, "source_evidence": 200, "task_checkpoint": 140, "pattern_memory": 120, "thread_summary": 100, "discussion_summary": 70, "lower_level_memory": 260},
    "broad_recall": {"pattern_memory": 400, "investigation_outcome": 330, "decision": 310, "continuity_memory": 180, "task_checkpoint": 150, "source_evidence": 120, "thread_summary": 130, "discussion_summary": 80, "lower_level_memory": 250},
    "work_resumption": {"task_checkpoint": 470, "source_evidence": 390, "investigation_outcome": 300, "decision": 290, "continuity_memory": 180, "pattern_memory": 70, "thread_summary": 130, "discussion_summary": 70, "lower_level_memory": 250},
    "precise_fact": {"decision": 440, "investigation_outcome": 430, "source_evidence": 320, "thread_summary": 110, "discussion_summary": 70, "continuity_memory": 140, "task_checkpoint": 110, "pattern_memory": 60, "lower_level_memory": 340},
    "evidence_trace": {"source_evidence": 460, "investigation_outcome": 380, "decision": 360, "thread_summary": 120, "discussion_summary": 80, "continuity_memory": 120, "task_checkpoint": 90, "pattern_memory": 40, "lower_level_memory": 300},
    "investigative_conclusion": {"investigation_outcome": 480, "decision": 430, "source_evidence": 360, "thread_summary": 220, "discussion_summary": 120, "continuity_memory": 110, "task_checkpoint": 100, "pattern_memory": 80, "lower_level_memory": 320},
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
    "again",
    "can",
    "had",
    "have",
    "here",
    "in",
    "is",
    "lately",
    "latest",
    "me",
    "sir",
    "that",
    "there",
    "you",
}
ROUTING_WEAK_HIGHER_LEVEL_MATCH_PENALTY = {
    "answer_continuity": 0,
    "broad_recall": 260,
    "work_resumption": 200,
    "precise_fact": 120,
    "evidence_trace": 120,
    "investigative_conclusion": 90,
}
ROUTING_SAFE_FALLBACK_LAYERS = {
    "answer_continuity": ("lower_level_memory", "source_evidence"),
    "broad_recall": ("task_checkpoint", "thread_summary", "lower_level_memory", "source_evidence"),
    "work_resumption": ("source_evidence", "lower_level_memory"),
    "precise_fact": ("source_evidence",),
    "evidence_trace": ("lower_level_memory",),
    "investigative_conclusion": ("decision", "source_evidence", "thread_summary"),
}
ROUTING_SUPPORT_THRESHOLD = {"weak": 0, "supported": 60, "strong": 110}
ROUTING_TOPIC_LOW_SIGNAL_TOKENS = {
    "about", "already", "before", "carry", "constraint", "concluded", "did", "do", "earlier",
    "forward", "history", "latest", "lately", "old", "past", "prior", "previously", "remember",
    "remind", "repeat", "repeated", "resume", "state", "use", "using", "what", "which", "why",
}
ROUTING_FALLBACK_MARGIN = 35
ROUTING_FOCUS_BOOST = 120
ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY = 90
ANSWER_CONTINUITY_CUES = (
    "already answered",
    "answered before",
    "have we already",
    "asked again",
    "asking again",
    "prior answer",
    "old answer",
    "not a new brainstorm",
    "carry forward",
)
BROAD_RECALL_CUES = (
    "what public conclusion",
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
BROAD_RECALL_CONCLUSION_CUES = (
    "what public conclusion",
    "what did we previously conclude",
    "what did we conclude before",
    "what did we conclude",
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
    "which exact prior evidence",
    "exact prior evidence",
    "what evidence",
    "show evidence",
    "quote the earlier",
    "quote the earlier note",
    "quote the note",
    "which source",
    "source evidence",
    "supported the",
    "supporting evidence",
    "trace",
    "which prior message",
    "prior message",
    "backed the",
)
INVESTIGATIVE_CONCLUSION_CUES = (
    "what had we concluded",
    "what did the investigation find",
    "what did investigation find",
    "which repo changed more and why",
    "which repo changed more",
    "what was the verdict",
    "what was our verdict",
    "what conclusion did we reach",
)
SHARP_DIAGNOSTIC_MEMORY_TYPES = {"task_checkpoint", "investigation_outcome", "decision"}
WORK_RESUMPTION_CUES = (
    "what blocker",
    "what progress",
    "what progress was preserved",
    "what state were we in",
    "what should i do next",
    "what should we do next",
    "what should we try next",
    "what finding should orient us",
    "queued again",
    "resume work",
)
WORK_RESUMPTION_NEXT_STEP_CUES = (
    "next step",
    "do next",
    "try next",
)
WORK_RESUMPTION_PROGRESS_CUES = (
    "what progress",
    "progress was preserved",
    "what state were we in",
)
WORK_RESUMPTION_BLOCKER_CUES = (
    "what blocker",
    "blocked",
    "failure",
    "failed",
)
WORK_RESUMPTION_SIGNAL_TYPES = ("task", "progress_update", "key_finding", "blocker", "next_step", "evidence", "freshness")
WORK_RESUMPTION_SHARP_CHECKPOINT_THRESHOLD = 44
WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY = 70
WORK_RESUMPTION_STALE_STATE_PENALTY = 55
WORK_RESUMPTION_STALE_SOURCE_PENALTY = 28
WORK_RESUMPTION_FRESH_STATE_BONUS = 18
WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS = 5400
WORK_RESUMPTION_SIGNAL_PRIORITY = ("blocker", "next_step", "progress_update")
ROUTING_QUERY_SHAPE_TOKENS = {
    "history_lookup": {"before", "earlier", "historical", "history", "past", "previously", "prior", "latest", "lately"},
    "big_picture": {"lesson", "pattern", "remember", "takeaway"},
    "analysis_request": {"concluded", "conclusion", "finding", "findings", "land", "outcome", "settled", "true", "verdict"},
    "carry_forward": {"again", "already", "carry", "forward", "old", "remind", "repeat", "repeated"},
    "constraint_recall": {"auth", "authenticate", "authentication", "browser", "constraint", "jira", "login", "portal", "sign", "slack"},
    "resume_state": {"blocked", "blocker", "continue", "continued", "continuing", "left", "next", "progress", "queued", "resume", "resumed", "state", "stuck", "unblock"},
    "evidence_request": {"backed", "evidence", "prove", "quote", "source", "support", "supported", "trace"},
    "precise_lookup": {"exact", "when", "which"},
}
ROUTING_QUERY_SHAPE_PHRASES = {
    "history_lookup": ("what do we know", "what is the latest", "what's the latest", "what had we concluded", "what had you concluded", "what constraint had i given", "remind me what we had latest", "remind me what we had latest about", "remind me what we had about", "what we had about"),
    "big_picture": ("big picture", "general lesson", "larger lesson", "main takeaway", "should we remember", "what should we remember"),
    "analysis_request": ("where did we land", "what ended up being true", "what settled", "how did that shake out"),
    "constraint_recall": ("what constraint had i given", "what constraint did i give", "what had i told you not to use", "what did i tell you not to use"),
    "resume_state": ("pick this back up", "pick that back up", "where did we leave off", "where were we", "what is the latest state", "what's the latest state"),
    "evidence_request": ("what backs that up", "what points to", "what points back to", "where did that come from"),
}
ROUTING_FAMILY_INFERENCE_PRIORITY = (
    "work_resumption",
    "evidence_trace",
    "investigative_conclusion",
    "answer_continuity",
    "broad_recall",
    "precise_fact",
)

class AgentConversationMemoryPlugin(ThreadAggregationSemanticPlugin, ConsolidationSemanticPlugin):
    name = "agent_conversation_memory"

    @property
    def requires_visibility_context(self) -> bool:
        return True

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

    @property
    def task_checkpoint_schema_id(self) -> str:
        return "agent_conversation_memory.task_checkpoint"

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        direct_result = self._delegate.process_item(source_item)
        supersession_hints = self._build_supersession_hints(source_item, direct_result)
        return ProcessResult(
            annotations=direct_result.annotations,
            memory_objects=direct_result.memory_objects,
            relations=direct_result.relations,
            index_entries=direct_result.index_entries,
            source_item_metadata_updates=direct_result.source_item_metadata_updates,
            thread_rebuild_requested=direct_result.thread_rebuild_requested,
            supersession_hints=supersession_hints,
        )

    def reconcile_process_result(
        self,
        result: ProcessResult,
        *,
        storage,
        container_ref: str | None,
        visibility_context,
    ) -> ProcessResult:
        if not container_ref or visibility_context is None or not result.memory_objects:
            return result
        active_constraints = _list_active_constraint_profiles(
            storage,
            container_ref=container_ref,
            visibility_context=visibility_context,
        )
        if not active_constraints:
            return result

        reconciled_memory_objects: list[MemoryObject] = []
        updated_index_entries = list(result.index_entries)
        changed_ids: set[str] = set()
        for memory_object in result.memory_objects:
            reconciled = _reconcile_memory_object_against_active_constraints(
                memory_object,
                active_constraints=active_constraints,
            )
            reconciled_memory_objects.append(reconciled)
            if reconciled is not memory_object:
                changed_ids.add(reconciled.id)

        if not changed_ids:
            return result

        rebuilt_index_entries = {
            memory_object.id: _rebuild_reconciled_memory_index_entry(memory_object)
            for memory_object in reconciled_memory_objects
            if memory_object.id in changed_ids
        }
        updated_index_entries = [
            rebuilt_index_entries.get(index_entry.target_id, index_entry)
            if index_entry.target_kind == "memory_object"
            else index_entry
            for index_entry in updated_index_entries
        ]
        return replace(
            result,
            memory_objects=reconciled_memory_objects,
            index_entries=updated_index_entries,
        )

    def route_query_results(
        self,
        *,
        text: str,
        requested_limit: int,
        retrieval_result,
        query_filters: QueryFilters | None = None,
        runtime_context: QueryRuntimeContext | None = None,
        include_trace: bool = False,
        debug_candidate_loader=None,
    ) -> PackageQueryOutcome:
        query_tokens = _routing_query_tokens(text)
        family_inference = _infer_query_intent(
            text=text,
            query_tokens=query_tokens,
            retrieved_candidates=retrieval_result.results,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        intent = str(family_inference["selected_family"])
        preferred_layers = ROUTING_PREFERRED_LAYERS[intent]
        scored_candidates = [
            _score_routed_candidate(
                item,
                intent,
                query_text=text,
                query_tokens=query_tokens,
                lexical_rank=index,
                query_filters=query_filters,
            )
            for index, item in enumerate(retrieval_result.results, start=1)
        ]
        if scored_candidates:
            _apply_same_kind_freshness_shaping(scored_candidates, intent=intent)
            _apply_fresh_thread_structured_recall_preference(
                scored_candidates,
                intent=intent,
                candidate_signals=family_inference["candidate_signals"],
                runtime_context=runtime_context,
            )
            _apply_recall_source_noise_suppression(
                scored_candidates,
                intent=intent,
                query_text=text,
                query_filters=query_filters,
                runtime_context=runtime_context,
            )
            _apply_recall_structured_summary_suppression(
                scored_candidates,
                intent=intent,
                query_text=text,
                query_filters=query_filters,
                runtime_context=runtime_context,
            )
        packaging_summary = None
        if intent == "work_resumption" and scored_candidates:
            packaging_summary = _apply_work_resumption_packaging(
                scored_candidates,
                query_filters=query_filters,
            )
        layer_summary = _summarize_routing_layers(scored_candidates)
        routing_focus = _select_routing_focus(
            intent=intent,
            preferred_layers=preferred_layers,
            layer_summary=layer_summary,
        )
        for candidate in scored_candidates:
            candidate["routing_score"] = int(candidate["base_routing_score"]) + _routing_focus_adjustment(
                layer=str(candidate["layer"]),
                selected_layer=str(routing_focus["selected_layer"]),
                primary_layer=preferred_layers[0],
                fallback_applied=bool(routing_focus["applied"]),
            )
            candidate["reason"] = _routing_reason(
                intent=intent,
                layer=str(candidate["layer"]),
                content_overlap_tokens=list(candidate["content_overlap_tokens"]),
                support_grade=str(candidate["support_grade"]),
                routing_focus=routing_focus,
                packaging_reasons=list(candidate["packaging_reasons"]),
            )
        ranked_candidates = sorted(
            scored_candidates,
            key=lambda candidate: (candidate["routing_score"], candidate["lexical_score"]),
            reverse=True,
        )
        for routing_rank, candidate in enumerate(ranked_candidates, start=1):
            candidate["routing_rank"] = routing_rank
        final_candidates, packaging_summary = _select_final_candidates(
            intent=intent,
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_filters=query_filters,
            query_shape_tags=list(family_inference["query_shape_tags"]),
            runtime_context=runtime_context,
            packaging_summary=packaging_summary,
            local_constraint_profile=_build_local_query_constraint_profile(text, runtime_context),
        )
        injection_blocks, injection_summary = _build_injectable_blocks(
            final_candidates,
            ranked_candidates=ranked_candidates,
            intent=intent,
            query_text=text,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        _annotate_excluded_candidates(
            ranked_candidates=ranked_candidates,
            final_candidates=final_candidates,
            requested_limit=requested_limit,
            routing_focus=routing_focus,
            packaging_summary=packaging_summary,
        )
        sharp_candidate_diagnostics = _build_sharp_candidate_diagnostics(
            ranked_candidates=ranked_candidates,
            final_candidates=final_candidates,
            injectable_blocks=injection_blocks,
            decision_reason=str(injection_summary["decision_reason"]),
            debug_candidate_loader=debug_candidate_loader if include_trace else None,
        )
        final_results = [candidate["item"] for candidate in final_candidates]

        routed_trace = None
        if include_trace and retrieval_result.trace is not None:
            routed_trace = QueryTrace(
                query_text=retrieval_result.trace.query_text,
                query_tokens=retrieval_result.trace.query_tokens,
                limit=requested_limit,
                filters=retrieval_result.trace.filters,
                stages=retrieval_result.trace.stages,
                visibility=retrieval_result.trace.visibility,
                requested_filters=retrieval_result.trace.requested_filters,
                filter_scope_relaxed=retrieval_result.trace.filter_scope_relaxed,
                filter_scope_reason=retrieval_result.trace.filter_scope_reason,
                routing=_build_routing_trace(
                    intent=intent,
                    family_inference=family_inference,
                    preferred_layers=preferred_layers,
                    layer_summary=layer_summary,
                    routing_focus=routing_focus,
                    ranked_candidates=ranked_candidates,
                    final_candidates=final_candidates,
                    packaging_summary=packaging_summary,
                    runtime_context=runtime_context,
                    injection_summary=injection_summary,
                    sharp_candidate_diagnostics=sharp_candidate_diagnostics,
                ),
            )

        return PackageQueryOutcome(
            results=final_results,
            trace=routed_trace,
            should_inject=bool(injection_summary["should_inject"]),
            decision_reason=str(injection_summary["decision_reason"]),
            injectable_blocks=injection_blocks,
            sharp_candidate_diagnostics=sharp_candidate_diagnostics,
        )

    def _build_supersession_hints(self, source_item: SourceItem, result: ProcessResult) -> list[SupersessionHint]:
        if not source_item.container_ref or not source_item.thread_ref:
            return []
        hints: list[SupersessionHint] = []
        for memory_object in result.memory_objects:
            if memory_object.type not in ROUTING_LOWER_LEVEL_EXACT_TYPES:
                continue
            canonical_key = str(memory_object.payload.get("canonical_key") or "").strip()
            if not canonical_key:
                continue
            hints.append(
                SupersessionHint(
                    replacement_memory_id=memory_object.id,
                    memory_type=memory_object.type,
                    canonical_key=canonical_key,
                    container_ref=source_item.container_ref,
                    thread_ref=source_item.thread_ref,
                    visibility_context=source_item.visibility_context,
                )
            )
        return hints
    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        if not source_item.thread_ref or not source_item.container_ref:
            return False
        if source_item.visibility_context is None:
            return False
        return _supports_thread_aggregation(source_item)

    def supports_consolidation(self, memory_object: MemoryObject) -> bool:
        return memory_object.visibility_context is not None and memory_object.type in {"thread_summary", "decision", "investigation_outcome"}

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

        selected_work_artifacts = _collect_selected_work_artifacts(aggregate.source_items)

        thread_material = _build_thread_material(aggregate.source_items)
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
                f"Selected work artifacts:\n{_format_selected_work_artifacts(selected_work_artifacts)}\n\n"
                f"Thread items:\n{thread_material}"
            ),
            schema_description=THREAD_SUMMARY_SCHEMA_DESCRIPTION,
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

        semantic_provenance = {
            "semantic_plugin": self.name,
            "prompt_variant": self.prompt_variant,
            "prompt_schema_id": THREAD_SUMMARY_PROMPT_SCHEMA_ID,
            "prompt_schema_version": THREAD_SUMMARY_PROMPT_SCHEMA_VERSION,
        }
        conclusion_payload = _build_conclusion_payload(carried_conclusions)
        thread_summary_memory = MemoryObject(
            type="thread_summary",
            schema_id=self.thread_summary_schema_id,
            schema_version="v1",
            payload={
                "thread_ref": aggregate.thread_ref,
                "container_ref": aggregate.container_ref,
                "session_ref": aggregate.session_ref,
                "summary": summary,
                "conclusions": conclusion_payload,
                "selected_work_artifacts": selected_work_artifacts,
                "latest_occurred_at": aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else None,
                "semantic_provenance": semantic_provenance,
            },
            visibility_context=aggregate.visibility_context,
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
        thread_summary_index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=thread_summary_memory.id,
            index_type="lexical",
            text_view=normalize_for_index(index_source),
            text_view_name=THREAD_SUMMARY_TEXT_VIEW,
        )
        memory_objects = [thread_summary_memory]
        index_entries = [thread_summary_index_entry]

        if _should_build_task_checkpoint(selected_work_artifacts):
            task_checkpoint_memory, task_checkpoint_index_entry = self._build_task_checkpoint_memory(
                aggregate=aggregate,
                summary=summary,
                conclusion_payload=conclusion_payload,
                selected_work_artifacts=selected_work_artifacts,
            )
            memory_objects.append(task_checkpoint_memory)
            index_entries.append(task_checkpoint_index_entry)
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
            annotations=[],
            memory_objects=memory_objects,
            relations=relations,
            index_entries=index_entries,
        )

    def _build_task_checkpoint_memory(
        self,
        *,
        aggregate: ThreadAggregate,
        summary: str,
        conclusion_payload: list[dict[str, str]],
        selected_work_artifacts: list[dict[str, str]],
    ) -> tuple[MemoryObject, object]:
        checkpoint_material = "\n".join(
            [
                f"Thread summary: {summary}",
                f"Carried conclusions:\n{_format_conclusions(conclusion_payload)}",
                f"Selected work artifacts:\n{_format_selected_work_artifacts(selected_work_artifacts)}",
            ]
        )
        if len(checkpoint_material) > TASK_CHECKPOINT_MAX_TEXT_CHARS:
            checkpoint_material = checkpoint_material[:TASK_CHECKPOINT_MAX_TEXT_CHARS].rstrip() + "\n[task checkpoint context truncated for token budget]"

        response = self._provider.generate_json(
            system_prompt=TASK_CHECKPOINT_SYSTEM_PROMPT,
            user_prompt=(
                "Create one compact resumed-work checkpoint from this thread context. "
                "Use only explicit information from the provided summary, conclusions, and selected work artifacts.\n\n"
                f"Container ref: {aggregate.container_ref}\n"
                f"Thread ref: {aggregate.thread_ref}\n"
                f"Session ref: {aggregate.session_ref or 'null'}\n"
                f"Latest occurred at: {aggregate.latest_occurred_at.isoformat() if aggregate.latest_occurred_at else 'null'}\n\n"
                f"{checkpoint_material}"
            ),
            schema_description=TASK_CHECKPOINT_SCHEMA_DESCRIPTION,
        )
        parsed_summary = response.parsed_json.get("summary")
        if not isinstance(parsed_summary, str) or not parsed_summary.strip():
            raise ValueError("task checkpoint extraction must return a non-empty summary string")
        parsed_summary = parsed_summary.strip()
        task = str(response.parsed_json.get("task") or "").strip() or _default_task_checkpoint_task(summary, conclusion_payload)
        current_state = str(response.parsed_json.get("current_state") or "").strip() or _default_task_checkpoint_state(summary, selected_work_artifacts)
        key_findings = _parse_string_list(response.parsed_json.get("key_findings")) or _default_task_checkpoint_findings(conclusion_payload, selected_work_artifacts)
        blocker_state = str(response.parsed_json.get("blocker_state") or "").strip() or _default_task_checkpoint_blocker(selected_work_artifacts)
        next_step = str(response.parsed_json.get("next_step") or "").strip() or _default_task_checkpoint_next_step(selected_work_artifacts)
        evidence = _parse_string_list(response.parsed_json.get("evidence")) or _default_task_checkpoint_evidence(conclusion_payload, selected_work_artifacts, summary)
        freshness_signal = str(response.parsed_json.get("freshness_signal") or "").strip() or _default_task_checkpoint_freshness_signal(aggregate.latest_occurred_at)

        memory_object = MemoryObject(
            type="task_checkpoint",
            schema_id=self.task_checkpoint_schema_id,
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
                "session_ref": aggregate.session_ref,
                "semantic_provenance": {
                    "semantic_plugin": self.name,
                    "prompt_variant": self.prompt_variant,
                    "prompt_schema_id": TASK_CHECKPOINT_PROMPT_SCHEMA_ID,
                    "prompt_schema_version": TASK_CHECKPOINT_PROMPT_SCHEMA_VERSION,
                },
            },
            visibility_context=aggregate.visibility_context,
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
        return memory_object, index_entry
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
            visibility_context=group.visibility_context,
            freshness_at=group.latest_occurred_at,
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
            visibility_context=group.visibility_context,
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


def _infer_query_intent(
    *,
    text: str,
    query_tokens: tuple[str, ...],
    retrieved_candidates: list[QueryResultItem],
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> dict[str, object]:
    text_hint_family = _classify_query_intent_from_text(text)
    cue_matches = _matched_query_family_cues(text)
    query_shape_tags = _query_shape_tags(text, query_tokens)
    candidate_signals = _summarize_query_family_candidates(
        retrieved_candidates=retrieved_candidates,
        query_tokens=query_tokens,
        query_filters=query_filters,
    )
    family_scores: dict[str, dict[str, object]] = {}
    for family in ROUTING_FAMILY_INFERENCE_PRIORITY:
        cue_score = _query_family_cue_score(
            family,
            cue_matches=cue_matches,
            text_hint_family=text_hint_family,
        )
        query_shape_score, query_shape_reasons = _query_family_query_shape_score(
            family,
            query_shape_tags=query_shape_tags,
            runtime_context=runtime_context,
        )
        candidate_score, candidate_reasons = _query_family_candidate_score(
            family,
            candidate_signals=candidate_signals,
            query_shape_tags=query_shape_tags,
            runtime_context=runtime_context,
        )
        family_scores[family] = {
            "total": cue_score + query_shape_score + candidate_score,
            "cue_score": cue_score,
            "query_shape_score": query_shape_score,
            "candidate_score": candidate_score,
            "reasons": list(OrderedDict.fromkeys([*query_shape_reasons, *candidate_reasons])),
        }

    ranked_families = sorted(
        ROUTING_FAMILY_INFERENCE_PRIORITY,
        key=lambda family: (
            int(family_scores[family]["total"]),
            int(family_scores[family]["candidate_score"]),
            int(family_scores[family]["cue_score"]),
            -ROUTING_FAMILY_INFERENCE_PRIORITY.index(family),
        ),
        reverse=True,
    )
    selected_family = ranked_families[0] if ranked_families else text_hint_family
    if _preferred_constraint_text(text):
        selected_family = "broad_recall"
    elif text_hint_family == "broad_recall" and "history_lookup" in query_shape_tags and "evidence_request" not in query_shape_tags:
        selected_family = "broad_recall"
    runner_up_family = ranked_families[1] if len(ranked_families) > 1 else None
    return {
        "selected_family": selected_family,
        "text_hint_family": text_hint_family,
        "runner_up_family": runner_up_family,
        "query_shape_tags": query_shape_tags,
        "matched_cues": {family: matches for family, matches in cue_matches.items() if matches},
        "candidate_signals": candidate_signals,
        "family_scores": family_scores,
    }



def _classify_query_intent_from_text(text: str) -> str:
    lowered = text.lower()
    if _preferred_constraint_text(text):
        return "broad_recall"
    if "remind me" in lowered and ("latest" in lowered or "lately" in lowered or "what we had about" in lowered):
        return "broad_recall"
    if any(cue in lowered for cue in EVIDENCE_TRACE_CUES):
        return "evidence_trace"
    if any(cue in lowered for cue in WORK_RESUMPTION_CUES):
        return "work_resumption"
    if any(cue in lowered for cue in ANSWER_CONTINUITY_CUES):
        return "answer_continuity"
    if any(cue in lowered for cue in INVESTIGATIVE_CONCLUSION_CUES):
        return "investigative_conclusion"
    if any(phrase in lowered for phrase in ROUTING_QUERY_SHAPE_PHRASES["history_lookup"]):
        return "broad_recall"
    if any(cue in lowered for cue in BROAD_RECALL_CUES) or lowered.startswith("why "):
        return "broad_recall"
    if any(cue in lowered for cue in PRECISE_FACT_CUES) or lowered.startswith(("what ", "which ", "when ")):
        return "precise_fact"
    return "broad_recall"



def _matched_query_family_cues(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    history_matches = [phrase for phrase in ROUTING_QUERY_SHAPE_PHRASES["history_lookup"] if phrase in lowered][:3]
    matched = {
        "answer_continuity": [cue for cue in ANSWER_CONTINUITY_CUES if cue in lowered][:3],
        "broad_recall": list(OrderedDict.fromkeys([*[cue for cue in BROAD_RECALL_CUES if cue in lowered][:3], *history_matches])),
        "work_resumption": [cue for cue in WORK_RESUMPTION_CUES if cue in lowered][:3],
        "precise_fact": [cue for cue in PRECISE_FACT_CUES if cue in lowered][:3],
        "evidence_trace": [cue for cue in EVIDENCE_TRACE_CUES if cue in lowered][:3],
        "investigative_conclusion": [cue for cue in INVESTIGATIVE_CONCLUSION_CUES if cue in lowered][:3],
    }
    if lowered.startswith("why "):
        matched["broad_recall"] = list(OrderedDict.fromkeys([*matched["broad_recall"], "why*"]))
    if lowered.startswith(("what ", "which ", "when ")) and not history_matches:
        matched["precise_fact"] = list(OrderedDict.fromkeys([*matched["precise_fact"], "wh*"]))
    return matched



def _query_shape_tags(text: str, query_tokens: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    token_set = set(query_tokens)
    detected: set[str] = set()
    for tag, tokens in ROUTING_QUERY_SHAPE_TOKENS.items():
        if token_set.intersection(tokens):
            detected.add(tag)
    for tag, phrases in ROUTING_QUERY_SHAPE_PHRASES.items():
        if any(phrase in lowered for phrase in phrases):
            detected.add(tag)
    if "remind me" in lowered:
        detected.update({"history_lookup", "carry_forward"})
    if "remind me" in lowered and ("lately" in lowered or "latest" in lowered or "what we had about" in lowered):
        detected.update({"history_lookup", "carry_forward"})
    if _preferred_constraint_text(text):
        detected.add("constraint_recall")
    if lowered.startswith("why "):
        detected.add("big_picture")
    if lowered.startswith(("what ", "which ", "when ")):
        detected.add("precise_lookup")
    return [
        tag
        for tag in ("history_lookup", "big_picture", "analysis_request", "carry_forward", "constraint_recall", "resume_state", "evidence_request", "precise_lookup")
        if tag in detected
    ]



def _query_family_cue_score(
    family: str,
    *,
    cue_matches: dict[str, list[str]],
    text_hint_family: str,
) -> int:
    family_matches = cue_matches.get(family, [])
    score = 0
    if family_matches:
        score += 44 + (min(len(family_matches), 3) * 8)
    if family == text_hint_family:
        score += 16
    return score



def _query_family_query_shape_score(
    family: str,
    *,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    weights = {
        "answer_continuity": {"carry_forward": 28, "history_lookup": 8, "constraint_recall": 18},
        "broad_recall": {"history_lookup": 22, "big_picture": 52, "constraint_recall": 28, "carry_forward": 12},
        "work_resumption": {"resume_state": 34, "carry_forward": 8},
        "precise_fact": {"precise_lookup": 18},
        "evidence_trace": {"evidence_request": 44},
        "investigative_conclusion": {"analysis_request": 30, "history_lookup": 10},
    }
    score = 0
    reasons: list[str] = []
    for tag, bonus in weights.get(family, {}).items():
        if tag in query_shape_tags:
            score += bonus
            reasons.append(f"{tag}_query_shape")
    if runtime_context is not None and family == "work_resumption" and runtime_context.turn_kind == "resumed_session":
        score += 12
        reasons.append("resumed_session_runtime")
    if runtime_context is not None and family == "answer_continuity" and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}:
        score += 10
        reasons.append("same_thread_runtime")
    return score, reasons



def _summarize_query_family_candidates(
    *,
    retrieved_candidates: list[QueryResultItem],
    query_tokens: tuple[str, ...],
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    layer_support: dict[str, dict[str, object]] = {}
    continuity_candidates: list[dict[str, object]] = []
    for item in retrieved_candidates:
        layer = _result_layer(item)
        overlap_tokens = _routing_overlap_tokens(item, query_tokens)
        content_overlap_tokens = [token for token in overlap_tokens if token not in ROUTING_META_QUERY_TOKENS]
        support_score = _candidate_evidence_shape_score(
            item,
            layer=layer,
            content_overlap_tokens=content_overlap_tokens,
            query_filters=query_filters,
        )
        same_thread = _candidate_matches_thread(item, query_filters)
        same_container = _candidate_matches_container(item, query_filters)
        work_signal_types = _work_resumption_signal_types(item)
        work_usefulness, work_reasons = _work_resumption_usefulness_score(item, work_signal_types)
        has_rationale = _candidate_has_rationale(item)
        has_explicit_evidence = _candidate_has_explicit_evidence(item)
        stats = layer_support.setdefault(
            layer,
            {
                "count": 0,
                "best_support": 0,
                "same_thread_hits": 0,
                "same_container_hits": 0,
                "evidence_hits": 0,
                "rationale_hits": 0,
                "best_work_usefulness": 0,
                "best_content_overlap_count": 0,
                "best_content_overlap_tokens": [],
                "best_result_id": None,
                "strong_candidate": False,
                "sharp_candidate": False,
                "dominant_work_signals": [],
            },
        )
        stats["count"] = int(stats["count"]) + 1
        stats["same_thread_hits"] = int(stats["same_thread_hits"]) + int(same_thread)
        stats["same_container_hits"] = int(stats["same_container_hits"]) + int(same_container)
        stats["evidence_hits"] = int(stats["evidence_hits"]) + int(has_explicit_evidence or bool(item.evidence))
        stats["rationale_hits"] = int(stats["rationale_hits"]) + int(has_rationale)
        candidate_is_strong = _routing_support_grade(support_score) in {"supported", "strong"}
        if layer == "continuity_memory":
            continuity_candidates.append(
                {
                    "result_id": _routing_result_id(item),
                    "support": support_score,
                    "same_thread": same_thread,
                    "content_overlap_count": len(content_overlap_tokens),
                    "content_overlap_tokens": list(content_overlap_tokens[:6]),
                    "strong_candidate": candidate_is_strong,
                }
            )
        if support_score >= int(stats["best_support"]):
            stats["best_support"] = support_score
            stats["best_work_usefulness"] = work_usefulness
            stats["best_content_overlap_count"] = len(content_overlap_tokens)
            stats["best_content_overlap_tokens"] = list(content_overlap_tokens[:6])
            stats["best_result_id"] = _routing_result_id(item)
            stats["strong_candidate"] = candidate_is_strong
            stats["sharp_candidate"] = bool(
                ("sharp_checkpoint" in work_reasons)
                or (layer in ROUTING_LOWER_LEVEL_EXACT_TYPES and (has_rationale or has_explicit_evidence))
            )
            stats["dominant_work_signals"] = list(work_signal_types[:3])

    bounded_layer_support: dict[str, dict[str, object]] = {}
    for layer, stats in layer_support.items():
        entry = {
            "count": int(stats["count"]),
            "best_support": int(stats["best_support"]),
            "same_thread_hits": int(stats["same_thread_hits"]),
            "same_container_hits": int(stats["same_container_hits"]),
            "evidence_hits": int(stats["evidence_hits"]),
            "rationale_hits": int(stats["rationale_hits"]),
            "best_work_usefulness": int(stats["best_work_usefulness"]),
            "best_content_overlap_count": int(stats["best_content_overlap_count"]),
            "strong_candidate": bool(stats["strong_candidate"]),
            "sharp_candidate": bool(stats["sharp_candidate"]),
        }
        if stats["best_result_id"]:
            entry["best_result_id"] = stats["best_result_id"]
        if stats["best_content_overlap_tokens"]:
            entry["best_content_overlap_tokens"] = list(stats["best_content_overlap_tokens"])
        if stats["dominant_work_signals"]:
            entry["dominant_work_signals"] = list(stats["dominant_work_signals"])
        bounded_layer_support[layer] = entry

    sharp_lower_level_topic_tokens = list(
        OrderedDict.fromkeys(
            token
            for layer in ("investigation_outcome", "decision", "lower_level_memory")
            for token in list((bounded_layer_support.get(layer) or {}).get("best_content_overlap_tokens") or [])
            if isinstance(token, str)
        )
    )
    relevant_continuity_candidates: list[dict[str, object]] = []
    for candidate in continuity_candidates:
        overlap_tokens = [
            token
            for token in list(candidate.get("content_overlap_tokens") or [])
            if isinstance(token, str)
        ]
        alignment_tokens = [token for token in overlap_tokens if token in sharp_lower_level_topic_tokens][:4]
        if (
            bool(candidate.get("strong_candidate"))
            and not bool(candidate.get("same_thread"))
            and int(candidate.get("content_overlap_count") or 0) >= 2
            and len(alignment_tokens) >= 2
        ):
            relevant_continuity_candidates.append(
                {
                    "result_id": candidate.get("result_id"),
                    "support": int(candidate.get("support") or 0),
                    "content_overlap_count": int(candidate.get("content_overlap_count") or 0),
                    "content_overlap_tokens": overlap_tokens,
                    "alignment_tokens": alignment_tokens,
                }
            )
    relevant_continuity_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("support") or 0),
            int(candidate.get("content_overlap_count") or 0),
        ),
        reverse=True,
    )
    best_relevant_cross_thread_continuity = relevant_continuity_candidates[0] if relevant_continuity_candidates else None
    continuity_topic_alignment_tokens = list((best_relevant_cross_thread_continuity or {}).get("alignment_tokens") or [])
    relevant_cross_thread_continuity_in_scope = best_relevant_cross_thread_continuity is not None

    top_layers = [
        {"layer": layer, **stats}
        for layer, stats in sorted(
            bounded_layer_support.items(),
            key=lambda item: (int(item[1].get("best_support", 0)), int(item[1].get("count", 0))),
            reverse=True,
        )[:4]
    ]
    return {
        "layer_support": bounded_layer_support,
        "top_layers": top_layers,
        "sharp_lower_level_in_scope": any(
            bool((bounded_layer_support.get(layer) or {}).get("strong_candidate"))
            for layer in ("investigation_outcome", "decision", "lower_level_memory")
        ),
        "strong_task_checkpoint_in_scope": bool(
            (bounded_layer_support.get("task_checkpoint") or {}).get("strong_candidate")
            or (bounded_layer_support.get("task_checkpoint") or {}).get("sharp_candidate")
        ),
        "strong_source_evidence_in_scope": bool((bounded_layer_support.get("source_evidence") or {}).get("strong_candidate")),
        "relevant_cross_thread_continuity_in_scope": relevant_cross_thread_continuity_in_scope,
        "continuity_topic_alignment_tokens": continuity_topic_alignment_tokens,
        "relevant_cross_thread_continuity": best_relevant_cross_thread_continuity,
    }



def _candidate_has_rationale(item: QueryResultItem) -> bool:
    if item.result_kind != "memory_hit" or not item.payload:
        return False
    return bool(str(item.payload.get("rationale") or "").strip())



def _candidate_has_explicit_evidence(item: QueryResultItem) -> bool:
    if item.result_kind == "source_hit":
        return bool(item.evidence)
    payload = item.payload or {}
    if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
        return True
    if _parse_string_list(payload.get("evidence")):
        return True
    conclusions = payload.get("conclusions", [])
    return isinstance(conclusions, list) and any(isinstance(entry, dict) and str(entry.get("text") or "").strip() for entry in conclusions)



def _query_family_layer_metric(candidate_signals: dict[str, object], layer: str, metric: str) -> int:
    layer_support = candidate_signals.get("layer_support", {})
    if not isinstance(layer_support, dict):
        return 0
    stats = layer_support.get(layer, {})
    if not isinstance(stats, dict):
        return 0
    value = stats.get(metric)
    if isinstance(value, bool):
        return int(value)
    return int(value) if isinstance(value, int) else 0



def _query_family_top_layer(candidate_signals: dict[str, object]) -> str:
    top_layers = candidate_signals.get("top_layers", [])
    if not isinstance(top_layers, list) or not top_layers:
        return "none"
    top_layer = top_layers[0]
    if not isinstance(top_layer, dict):
        return "none"
    return str(top_layer.get("layer") or "none")



def _query_family_candidate_score(
    family: str,
    *,
    candidate_signals: dict[str, object],
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
) -> tuple[int, list[str]]:
    pattern_support = _query_family_layer_metric(candidate_signals, "pattern_memory", "best_support")
    pattern_count = _query_family_layer_metric(candidate_signals, "pattern_memory", "count")
    continuity_support = _query_family_layer_metric(candidate_signals, "continuity_memory", "best_support")
    continuity_same_thread_hits = _query_family_layer_metric(candidate_signals, "continuity_memory", "same_thread_hits")
    checkpoint_support = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_support")
    thread_summary_support = _query_family_layer_metric(candidate_signals, "thread_summary", "best_support")
    discussion_summary_support = _query_family_layer_metric(candidate_signals, "discussion_summary", "best_support")
    checkpoint_same_thread_hits = _query_family_layer_metric(candidate_signals, "task_checkpoint", "same_thread_hits")
    checkpoint_work_usefulness = _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_work_usefulness")
    source_support = _query_family_layer_metric(candidate_signals, "source_evidence", "best_support")
    source_same_thread_hits = _query_family_layer_metric(candidate_signals, "source_evidence", "same_thread_hits")
    source_evidence_hits = _query_family_layer_metric(candidate_signals, "source_evidence", "evidence_hits")
    source_work_usefulness = _query_family_layer_metric(candidate_signals, "source_evidence", "best_work_usefulness")
    decision_support = _query_family_layer_metric(candidate_signals, "decision", "best_support")
    investigation_support = _query_family_layer_metric(candidate_signals, "investigation_outcome", "best_support")
    lower_level_support = _query_family_layer_metric(candidate_signals, "lower_level_memory", "best_support")
    sharp_lower_level_support = max(decision_support, investigation_support, lower_level_support)
    sharp_lower_level_rationale_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "rationale_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    sharp_lower_level_evidence_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "evidence_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    sharp_lower_level_same_thread_hits = sum(
        _query_family_layer_metric(candidate_signals, layer, "same_thread_hits")
        for layer in ("investigation_outcome", "decision", "lower_level_memory")
    )
    top_layer = _query_family_top_layer(candidate_signals)
    supported_floor = ROUTING_SUPPORT_THRESHOLD["supported"]
    structured_recall_support = max(
        pattern_support,
        continuity_support,
        checkpoint_support,
        thread_summary_support,
        discussion_summary_support,
        sharp_lower_level_support,
    )
    fresh_thread_cross_thread_recall = _runtime_context_prefers_cross_thread_recall(runtime_context)
    history_recall_with_relevant_carry_forward = (
        "history_lookup" in query_shape_tags
        and bool(candidate_signals.get("relevant_cross_thread_continuity_in_scope"))
        and sharp_lower_level_support >= supported_floor
    )
    constraint_recall = "constraint_recall" in query_shape_tags
    structured_summary_support = max(checkpoint_support, thread_summary_support, discussion_summary_support)
    score = 0
    reasons: list[str] = []

    if family == "answer_continuity":
        if continuity_support:
            score += (continuity_support // 2) + (continuity_same_thread_hits * 14)
            reasons.append("continuity_memory_support")
        if fresh_thread_cross_thread_recall and structured_recall_support >= supported_floor:
            score += min(structured_recall_support // 2, 52)
            reasons.append("fresh_thread_structured_memory_support")
        if fresh_thread_cross_thread_recall and constraint_recall and structured_summary_support >= supported_floor:
            score += min(structured_summary_support // 3, 28)
            reasons.append("constraint_carry_forward_support")
        if top_layer == "continuity_memory":
            score += 10
            reasons.append("continuity_memory_won_candidate_competition")
        if continuity_support < supported_floor and structured_recall_support < supported_floor:
            score -= 12
            reasons.append("weak_continuity_support")
        if "evidence_request" in query_shape_tags and source_support >= supported_floor:
            score -= 54
            reasons.append("evidence_request_outweighs_continuity")
        return score, reasons

    if family == "broad_recall":
        if pattern_support:
            score += pattern_support + (min(pattern_count, 2) * 10)
            reasons.append("pattern_memory_support")
        if history_recall_with_relevant_carry_forward:
            score += min(continuity_support // 3, 70) + 36
            reasons.append("cross_thread_carry_forward_support")
        if sharp_lower_level_support:
            score += min(sharp_lower_level_support, 44)
            reasons.append("sharp_lower_level_available")
        if fresh_thread_cross_thread_recall and structured_recall_support >= supported_floor:
            score += min(structured_recall_support // 2, 56)
            reasons.append("fresh_thread_structured_memory_support")
        if structured_summary_support >= supported_floor:
            score += min(structured_summary_support // 3, 36)
            reasons.append("structured_summary_support")
        if checkpoint_support >= supported_floor and {"history_lookup", "carry_forward"}.issubset(set(query_shape_tags)):
            score += min(checkpoint_support // 2, 72)
            reasons.append("checkpoint_carry_forward_support")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and structured_recall_support >= supported_floor:
            score += 28
            reasons.append("fresh_thread_history_recall")
        if top_layer == "pattern_memory":
            score += 12
            reasons.append("pattern_memory_won_candidate_competition")
        if history_recall_with_relevant_carry_forward and top_layer == "continuity_memory":
            score += 18
            reasons.append("carry_forward_memory_won_candidate_competition")
        if pattern_support and pattern_support >= sharp_lower_level_support:
            score += 10
            reasons.append("pattern_memory_beats_sharp_lower_level")
        if pattern_support < supported_floor and sharp_lower_level_support > pattern_support and "analysis_request" in query_shape_tags:
            score -= 18
            reasons.append("sharp_lower_level_outweighs_weak_pattern_memory")
        if "evidence_request" in query_shape_tags and source_support >= supported_floor:
            score -= 84
            reasons.append("evidence_request_outweighs_broad_recall")
        return score, reasons

    if family == "work_resumption":
        if checkpoint_support:
            score += (checkpoint_support // 2) + checkpoint_work_usefulness + (checkpoint_same_thread_hits * 16)
            reasons.append("task_checkpoint_support")
        if source_work_usefulness:
            score += min(source_support // 2, 42) + source_work_usefulness + (source_same_thread_hits * 8)
            reasons.append("work_state_source_support")
        if fresh_thread_cross_thread_recall and checkpoint_support >= supported_floor:
            score += min(checkpoint_support // 3, 42)
            reasons.append("fresh_thread_checkpoint_support")
        if bool(candidate_signals.get("strong_task_checkpoint_in_scope")):
            score += 16
            reasons.append("sharp_task_checkpoint_in_scope")
        if top_layer in {"task_checkpoint", "source_evidence"}:
            score += 8
            reasons.append("work_state_won_candidate_competition")
        if runtime_context is not None and runtime_context.turn_kind == "resumed_session":
            score += 6
            reasons.append("resumed_session_candidate_tiebreak")
        if "resume_state" not in query_shape_tags and (runtime_context is None or runtime_context.turn_kind != "resumed_session"):
            score -= 180
            reasons.append("missing_resume_query_shape")
        if checkpoint_support < supported_floor and source_work_usefulness < 18:
            score -= 20
            reasons.append("weak_resumption_state_support")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and "resume_state" not in query_shape_tags:
            score -= 56
            reasons.append("history_lookup_outweighs_resume_state")
        return score, reasons

    if family == "precise_fact":
        if sharp_lower_level_support:
            score += (sharp_lower_level_support // 2) + (sharp_lower_level_same_thread_hits * 8)
            reasons.append("sharp_lower_level_support")
        if source_support:
            score += min(source_support, 36)
            reasons.append("source_evidence_fallback")
        if top_layer in {"decision", "investigation_outcome", "lower_level_memory"}:
            score += 8
            reasons.append("sharp_lower_level_won_candidate_competition")
        if sharp_lower_level_support < supported_floor:
            score -= 12
            reasons.append("weak_precise_fact_support")
        if "big_picture" in query_shape_tags:
            score -= 48
            reasons.append("pattern_memory_points_to_broad_recall")
        if history_recall_with_relevant_carry_forward:
            score -= 74
            reasons.append("carry_forward_history_outweighs_precise_lookup")
        if fresh_thread_cross_thread_recall and "history_lookup" in query_shape_tags and structured_recall_support >= supported_floor:
            score -= 56
            reasons.append("history_lookup_outweighs_precise_lookup")
        return score, reasons

    if family == "evidence_trace":
        if source_support:
            score += (source_support // 2) + (source_evidence_hits * 10)
            reasons.append("source_evidence_support")
        if bool(candidate_signals.get("strong_source_evidence_in_scope")):
            score += 14
            reasons.append("sharp_source_evidence_in_scope")
        if sharp_lower_level_evidence_hits:
            score += sharp_lower_level_evidence_hits * 8
            reasons.append("lower_level_evidence_available")
        if top_layer == "source_evidence":
            score += 12
            reasons.append("source_evidence_won_candidate_competition")
        if source_support < supported_floor:
            score -= 16
            reasons.append("weak_source_evidence_support")
        if checkpoint_support > source_support + 20 and "resume_state" in query_shape_tags:
            score -= 18
            reasons.append("checkpoint_state_outweighs_weak_source_evidence")
        if fresh_thread_cross_thread_recall and structured_recall_support >= max(source_support, supported_floor) and "evidence_request" not in query_shape_tags:
            score -= 72
            reasons.append("structured_recall_outweighs_source_evidence")
        if {"history_lookup", "carry_forward"}.issubset(set(query_shape_tags)) and checkpoint_support >= supported_floor and "evidence_request" not in query_shape_tags:
            score -= 84
            reasons.append("checkpoint_carry_forward_outweighs_evidence_trace")
        if ("history_lookup" in query_shape_tags or constraint_recall) and structured_summary_support >= supported_floor and "evidence_request" not in query_shape_tags:
            score -= 54
            reasons.append("history_lookup_outweighs_evidence_trace")
        return score, reasons

    if sharp_lower_level_support:
        score += (sharp_lower_level_support // 2) + (sharp_lower_level_rationale_hits * 12) + (sharp_lower_level_evidence_hits * 8) + (sharp_lower_level_same_thread_hits * 10)
        reasons.append("sharp_lower_level_support")
    if bool(candidate_signals.get("sharp_lower_level_in_scope")):
        score += 14
        reasons.append("sharp_lower_level_in_scope")
    if source_support:
        score += min(source_support // 2, 32)
        reasons.append("supporting_source_evidence_available")
    if top_layer in {"investigation_outcome", "decision", "lower_level_memory"}:
        score += 10
        reasons.append("sharp_lower_level_won_candidate_competition")
    if sharp_lower_level_support < supported_floor:
        score -= 16
        reasons.append("weak_investigative_support")
    if pattern_support >= sharp_lower_level_support and "big_picture" in query_shape_tags:
        score -= 18
        reasons.append("pattern_memory_outweighs_sharp_conclusion")
    return score, reasons

def _query_family_label(intent: str, *, runtime_context: QueryRuntimeContext | None, injection_summary: dict[str, object] | None = None) -> str:
    turn_kind = runtime_context.turn_kind if runtime_context is not None else None
    session_has_sufficient_local_context = (
        runtime_context.session_has_sufficient_local_context if runtime_context is not None else None
    )
    if turn_kind in {"same_thread", "same_thread_continuation"} and session_has_sufficient_local_context is True:
        decision_reason = str((injection_summary or {}).get("decision_reason") or "")
        should_inject = bool((injection_summary or {}).get("should_inject"))
        if decision_reason == "same_thread_context_sufficient" or not should_inject and decision_reason in {"same_thread_context_sufficient", "no_relevant_memory", "only_low_value_candidates"}:
            return "same_thread_no_value_continuation"
    if intent == "answer_continuity":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
    if intent == "work_resumption":
        if turn_kind == "resumed_session":
            return "resumed_session_continuation"
        if turn_kind in {"new_thread", "new_session"}:
            return "new_thread_continuation"
    if intent == "broad_recall":
        return "broad_recurring_recall"
    return intent

def _score_routed_candidate(
    item: QueryResultItem,
    intent: str,
    *,
    query_text: str,
    query_tokens: tuple[str, ...],
    lexical_rank: int,
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    layer = _result_layer(item)
    lexical_score = int(item.score)
    overlap_tokens = _routing_overlap_tokens(item, query_tokens)
    content_overlap_tokens = [token for token in overlap_tokens if token not in ROUTING_META_QUERY_TOKENS]
    query_topic_tokens = _query_topic_tokens(query_tokens)
    topic_overlap_tokens = [token for token in content_overlap_tokens if token in query_topic_tokens]
    evidence_shape_score = _candidate_evidence_shape_score(
        item,
        layer=layer,
        content_overlap_tokens=content_overlap_tokens,
        query_filters=query_filters,
    )
    base_routing_score = (
        ROUTING_LAYER_WEIGHTS[intent][layer]
        + (lexical_score * 10)
        + _specificity_bonus(item, intent, query_text=query_text)
        + evidence_shape_score
        + _routing_overlap_adjustment(layer, intent, content_overlap_tokens)
        + _topic_alignment_adjustment(layer=layer, query_topic_tokens=query_topic_tokens, topic_overlap_tokens=topic_overlap_tokens)
    )
    support_grade = _routing_support_grade(evidence_shape_score)
    return {
        "item": item,
        "layer": layer,
        "lexical_rank": lexical_rank,
        "lexical_score": lexical_score,
        "base_routing_score": base_routing_score,
        "routing_score": base_routing_score,
        "support_score": evidence_shape_score,
        "support_grade": support_grade,
        "reason": "",
        "strategy_name": _routing_strategy_name(item),
        "content_overlap_tokens": content_overlap_tokens,
        "topic_overlap_tokens": topic_overlap_tokens,
        "evidence_count": len(item.evidence),
        "same_thread": _candidate_matches_thread(item, query_filters),
        "same_container": _candidate_matches_container(item, query_filters),
        "freshness_timestamp_value": _candidate_freshness_timestamp(item),
        "freshness_timestamp": None,
        "packaging_adjustment": 0,
        "packaging_reasons": [],
        "work_signal_types": (),
        "work_usefulness_score": 0,
    }


def _apply_same_kind_freshness_shaping(scored_candidates: list[dict[str, object]], *, intent: str) -> None:
    if intent not in {"investigative_conclusion", "precise_fact", "broad_recall"}:
        return
    for memory_type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        typed_candidates = [candidate for candidate in scored_candidates if getattr(candidate["item"], "type", None) == memory_type]
        if len(typed_candidates) < 2:
            continue
        typed_candidates.sort(
            key=lambda candidate: (
                candidate.get("freshness_timestamp_value") is not None,
                candidate.get("freshness_timestamp_value") or datetime.min.replace(tzinfo=timezone.utc),
                bool(candidate.get("same_thread")),
                int(candidate.get("lexical_score", 0)),
            ),
            reverse=True,
        )
        freshest = typed_candidates[0].get("freshness_timestamp_value")
        for index, candidate in enumerate(typed_candidates):
            freshness_delta = 0
            if index == 0:
                freshness_delta += 42 if intent == "investigative_conclusion" else 24
                if candidate.get("same_thread"):
                    freshness_delta += 16
            else:
                freshness_delta -= min(index * 12, 30)
                if freshest is not None and candidate.get("freshness_timestamp_value") is not None:
                    candidate_time = candidate.get("freshness_timestamp_value")
                    if isinstance(candidate_time, datetime) and freshest > candidate_time:
                        freshness_delta -= 10
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) + freshness_delta
            candidate["support_score"] = max(0, int(candidate["support_score"]) + max(freshness_delta // 2, 0))
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            if freshness_delta > 0:
                candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_same_kind_conclusion"]))
            elif freshness_delta < 0:
                candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], "older_same_kind_conclusion"]))


def _runtime_context_prefers_cross_thread_recall(runtime_context: QueryRuntimeContext | None) -> bool:
    return bool(
        runtime_context is not None
        and runtime_context.turn_kind in {"new_thread", "new_session"}
        and runtime_context.session_has_sufficient_local_context is False
    )


def _apply_fresh_thread_structured_recall_preference(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    candidate_signals: dict[str, object],
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity", "work_resumption"}:
        return
    if not _runtime_context_prefers_cross_thread_recall(runtime_context):
        return

    structured_support = max(
        _query_family_layer_metric(candidate_signals, "task_checkpoint", "best_support"),
        _query_family_layer_metric(candidate_signals, "thread_summary", "best_support"),
        _query_family_layer_metric(candidate_signals, "discussion_summary", "best_support"),
        _query_family_layer_metric(candidate_signals, "continuity_memory", "best_support"),
        _query_family_layer_metric(candidate_signals, "pattern_memory", "best_support"),
        _query_family_layer_metric(candidate_signals, "decision", "best_support"),
        _query_family_layer_metric(candidate_signals, "investigation_outcome", "best_support"),
        _query_family_layer_metric(candidate_signals, "lower_level_memory", "best_support"),
    )
    if structured_support < ROUTING_SUPPORT_THRESHOLD["supported"]:
        return

    structured_layers = {
        "task_checkpoint",
        "thread_summary",
        "discussion_summary",
        "continuity_memory",
        "pattern_memory",
        "decision",
        "investigation_outcome",
        "lower_level_memory",
    }
    for candidate in scored_candidates:
        layer = str(candidate["layer"])
        if layer == "source_evidence":
            penalty = 120 if int(candidate["support_score"]) <= structured_support + 20 else 80
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
            candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 18))
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            candidate["packaging_reasons"] = list(
                OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_thread_structured_memory_preferred"])
            )
        elif layer in structured_layers and str(candidate["support_grade"]) in {"supported", "strong"}:
            bonus = 26 if layer in {"task_checkpoint", "decision", "investigation_outcome"} else 18
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) + bonus
            candidate["support_score"] = int(candidate["support_score"]) + max(bonus // 2, 8)
            candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
            candidate["packaging_reasons"] = list(
                OrderedDict.fromkeys([*candidate["packaging_reasons"], "fresh_thread_structured_memory_preferred"] )
            )

def _apply_recall_source_noise_suppression(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity"}:
        return
    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "source_hit":
            continue
        suppression = _source_noise_suppression_reason(
            item,
            query_text=query_text,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        if suppression is None:
            continue
        reason_code, reason_text = suppression
        penalty = 220 if reason_code in {"current_thread_recall_query", "duplicate_recall_query_source"} else 180
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
        candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 24))
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
        candidate["suppression_reason_code"] = reason_code
        candidate["suppression_reason"] = reason_text


def _source_noise_suppression_reason(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[str, str] | None:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return None
    if _is_low_value_meta_text(excerpt):
        return "low_value_meta_source", "Low-value orchestration source is not useful carry-forward for recall packaging."
    if _source_hit_is_greeting_or_noise_text(excerpt):
        return "greeting_source_noise", "Greeting or pleasantry chatter was excluded from recall packaging."
    if _source_hit_is_heartbeat_text(excerpt):
        return "heartbeat_source_noise", "Heartbeat-style source noise was excluded from recall packaging."
    if _source_hit_is_generic_capability_text(excerpt):
        return "generic_capability_source", "Generic capability chatter was excluded from recall packaging."
    if _source_hit_looks_like_recall_query(item, query_text):
        if _runtime_context_prefers_cross_thread_recall(runtime_context) and query_filters is not None and query_filters.thread_ref and item.thread_ref == query_filters.thread_ref:
            return "current_thread_recall_query", "The current fresh-thread query was excluded from cross-thread recall packaging."
        return "duplicate_recall_query_source", "A duplicate unresolved recall question was excluded from recall packaging."
    return None


def _apply_recall_structured_summary_suppression(
    scored_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> None:
    if intent not in {"broad_recall", "answer_continuity"}:
        return
    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.result_kind != "memory_hit" or item.type not in ROUTING_SUMMARY_TYPES:
            continue
        suppression = _structured_summary_suppression_reason(
            item,
            query_text=query_text,
            query_filters=query_filters,
            runtime_context=runtime_context,
        )
        if suppression is None:
            continue
        reason_code, reason_text = suppression
        penalty = 180
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
        candidate["support_score"] = max(0, int(candidate["support_score"]) - max(penalty // 3, 24))
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
        candidate["suppression_reason_code"] = reason_code
        candidate["suppression_reason"] = reason_text



def _structured_summary_suppression_reason(
    item: QueryResultItem,
    *,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[str, str] | None:
    if item.type != "thread_summary":
        return None
    payload = item.payload or {}
    summary_text = str(payload.get("summary") or "").strip()
    rejection = _summary_low_value_reason(
        item.type,
        payload,
        summary_text=summary_text,
        query_text=query_text,
    )
    if rejection is None:
        return None
    if _runtime_context_prefers_cross_thread_recall(runtime_context) and query_filters is not None and query_filters.thread_ref and item.thread_ref == query_filters.thread_ref:
        if rejection[0] == "query_only_thread_summary":
            return "current_thread_empty_summary", "A current-thread query-only summary was excluded from recall packaging."
        return "current_thread_unresolved_summary", "A current-thread unresolved summary was excluded from recall packaging."
    return rejection



def _summary_low_value_reason(
    memory_type: str,
    payload: dict[str, object],
    *,
    summary_text: str,
    query_text: str,
) -> tuple[str, str] | None:
    if memory_type not in ROUTING_SUMMARY_TYPES or not summary_text:
        return None
    if payload.get("selected_work_artifacts") or payload.get("conclusions"):
        return None
    if _preferred_constraint_text(summary_text) or _summary_text_has_durable_state_cue(summary_text):
        return None
    if _summary_text_looks_query_only(summary_text, query_text):
        return "query_only_thread_summary", "A query-only summary was excluded from recall packaging."
    if _summary_text_looks_unresolved(summary_text):
        return "unresolved_thread_summary", "An unresolved summary without durable state was excluded from recall packaging."
    return None



def _summary_text_looks_query_only(summary_text: str, query_text: str) -> bool:
    lowered = summary_text.lower()
    if any(marker in lowered for marker in QUERY_ONLY_SUMMARY_MARKERS):
        return True
    overlap = len(set(_routing_query_tokens(summary_text)).intersection(set(_routing_query_tokens(query_text))))
    return overlap >= 4 and lowered.startswith("user asked")



def _summary_text_looks_unresolved(summary_text: str) -> bool:
    lowered = summary_text.lower().strip()
    if lowered in WEAK_THREAD_SUMMARY_TEXT or lowered.startswith("unresolved"):
        return True
    return any(marker in lowered for marker in UNRESOLVED_SUMMARY_MARKERS)



def _summary_text_has_durable_state_cue(summary_text: str) -> bool:
    lowered = summary_text.lower().strip()
    return any(
        marker in lowered
        for marker in (
            "constraint:",
            "blocked by",
            "blocker:",
            "next step:",
            "current state:",
            "decision:",
            "investigation outcome:",
            "resolved that",
            "concluded that",
        )
    )



def _structured_constraint_profile_from_item(item: QueryResultItem) -> dict[str, object] | None:
    if item.result_kind != "memory_hit" or item.type not in STRUCTURED_CONFLICT_MEMORY_TYPES:
        return None
    payload = item.payload or {}
    return _structured_constraint_profile_from_payload(
        memory_type=str(item.type or ""),
        payload=payload,
        result_id=_routing_result_id(item),
        freshness_at=item.freshness_at,
    )



def _structured_payload_constraint_fragments(memory_type: str, payload: dict[str, object]) -> list[str]:
    fragments: list[str] = []
    if memory_type == "task_checkpoint":
        fragments.extend(
            str(payload.get(key) or "")
            for key in ("summary", "current_state", "blocker_state")
        )
        fragments.extend(str(value or "") for value in _parse_string_list(payload.get("key_findings")))
        fragments.extend(str(value or "") for value in _parse_string_list(payload.get("evidence")))
    elif memory_type in {"thread_summary", "discussion_summary"}:
        fragments.append(str(payload.get("summary") or ""))
    return fragments



def _structured_payload_guidance_fragments(memory_type: str, payload: dict[str, object]) -> list[str]:
    fragments: list[str] = []
    if memory_type == "task_checkpoint":
        next_step = str(payload.get("next_step") or "").strip()
        if next_step:
            fragments.append(next_step)
        for key in ("summary", "current_state", "blocker_state"):
            value = str(payload.get(key) or "").strip()
            if value and _text_contains_operational_guidance(value):
                fragments.append(value)
    elif memory_type in {"thread_summary", "discussion_summary"}:
        summary = str(payload.get("summary") or "").strip()
        if summary and _text_contains_operational_guidance(summary):
            fragments.append(summary)
    return fragments



def _text_contains_operational_guidance(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    non_constraint = _strip_constraint_snippets(normalized).strip()
    target = non_constraint.lower() if re.search(r"\w", non_constraint) else lowered
    return any(marker in target for marker in OPERATIONAL_GUIDANCE_MARKERS)



def _constraint_policy_tokens(text: str) -> set[str]:
    return {
        token
        for token in _routing_query_tokens(text)
        if (
            len(token) > 2
            and token not in CONSTRAINT_POLICY_STOPWORDS
            and token not in ROUTING_META_QUERY_TOKENS
        )
    }


def _constraint_focus_tokens(tokens: Iterable[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token not in CONSTRAINT_POLICY_ACTION_TOKENS and token not in CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS
    }


def _exclusive_constraint_tokens(text: str) -> set[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return set()
    clauses: list[str] = []
    for pattern in (
        r"use only (?P<clause>.+?)(?: instead of| rather than|$)",
        r"only use (?P<clause>.+?)(?: instead of| rather than|$)",
    ):
        for match in re.finditer(pattern, normalized):
            clause = str(match.group("clause") or "").strip(" .,;:")
            if clause:
                clauses.append(clause)
    if not clauses:
        return set()
    return _constraint_focus_tokens(_constraint_policy_tokens(" ".join(clauses)))


def _prohibited_constraint_focus_tokens(text: str) -> set[str]:
    focus_tokens: set[str] = set()
    for snippet in _extract_constraint_snippets(text):
        lowered = snippet.lower()
        if "use only" in lowered or "only use" in lowered:
            continue
        tokens = _constraint_policy_tokens(snippet)
        tool_tokens = tokens.intersection(CONSTRAINT_FOCUS_TOOL_TOKENS)
        if tool_tokens:
            focus_tokens.update(tool_tokens)
    return focus_tokens


def _candidate_has_self_conflicting_guidance(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    profile = _structured_constraint_profile_from_item(item)
    if profile is None:
        return False
    return _structured_item_conflicts_with_constraint(item, profile)



def _structured_item_conflicts_with_constraint(item: QueryResultItem, constraint_profile: dict[str, object]) -> bool:
    payload = item.payload or {}
    return any(
        _structured_text_conflicts_with_constraint(fragment, constraint_profile)
        for fragment in _structured_payload_guidance_fragments(str(item.type or ""), payload)
    )


def _candidate_conflicts_with_constraint(item: QueryResultItem, constraint_profile: dict[str, object]) -> bool:
    if item.result_kind == "source_hit":
        return _structured_text_conflicts_with_constraint(str(item.excerpt or ""), constraint_profile)
    return _structured_item_conflicts_with_constraint(item, constraint_profile)



def _source_hit_looks_like_recall_query(item: QueryResultItem, query_text: str) -> bool:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return False
    if not _source_hit_looks_like_request_or_question(item):
        return False
    if item.role not in {None, "user"} and (item.source_type or "") not in {"chat_message", "message"}:
        return False
    excerpt_tokens = tuple(_routing_query_tokens(excerpt))
    query_tokens = set(_routing_query_tokens(query_text))
    overlap = len(set(excerpt_tokens).intersection(query_tokens))
    excerpt_tags = set(_query_shape_tags(excerpt, excerpt_tokens))
    return overlap >= 3 and bool(excerpt_tags.intersection({"history_lookup", "carry_forward", "constraint_recall"}))


def _source_hit_looks_like_request_or_question(item: QueryResultItem) -> bool:
    excerpt = str(item.excerpt or "").strip()
    if not excerpt:
        return False
    lowered = excerpt.lower()
    request_prefixes = (
        "can you", "could you", "would you", "will you", "please", "remind me", "what ", "which ", "why ", "how ",
        "when ", "where ", "who ", "do we", "did we", "are we", "is there", "should we", "so what"
    )
    if lowered.startswith(request_prefixes):
        return True
    if item.role == "assistant":
        return False
    if "?" in excerpt:
        return True
    if item.role == "user" and lowered.endswith(("right", "please")) and len(lowered.split()) <= 8:
        return True
    return False


def _assistant_source_is_answer_bearing_local_state(excerpt: str, query_text: str) -> bool:
    lowered_query = query_text.lower()
    if not any(marker in lowered_query for marker in ("paste", "repeat", "rewrite", "again", "exact", "exactly")):
        return False
    normalized_excerpt = str(excerpt or "").strip()
    if len(normalized_excerpt.split()) < 8:
        return False
    lowered_excerpt = normalized_excerpt.lower()
    if lowered_excerpt.startswith(("sure:", "here is", "here's", "try this", "rewrite:")):
        return True
    return '"' in normalized_excerpt or "'" in normalized_excerpt


def _source_hit_is_generic_capability_text(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("capabilities:") or "many talents" in lowered or ("i can" in lowered and "help" in lowered and "status" in lowered)


def _source_hit_is_heartbeat_text(text: str) -> bool:
    lowered = text.lower()
    return "heartbeat" in lowered or "still alive" in lowered or "still monitoring" in lowered or "healthcheck" in lowered


def _result_layer(item: QueryResultItem) -> str:
    if item.result_kind == "source_hit":
        return "source_evidence"
    if item.type == "pattern_memory":
        return "pattern_memory"
    if item.type == "continuity_memory":
        return "continuity_memory"
    if item.type == "task_checkpoint":
        return "task_checkpoint"
    if item.type == "thread_summary":
        return "thread_summary"
    if item.type == "discussion_summary":
        return "discussion_summary"
    if item.type == "investigation_outcome":
        return "investigation_outcome"
    if item.type == "decision":
        return "decision"
    return "lower_level_memory"


def _specificity_bonus(item: QueryResultItem, intent: str, *, query_text: str) -> int:
    bonus = 0
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if intent == "investigative_conclusion":
            bonus += 95 if item.type == "investigation_outcome" else 80
        elif intent in {"precise_fact", "evidence_trace"}:
            bonus += 50 if item.type == "decision" else 45
        else:
            bonus += 20
    if item.result_kind == "memory_hit" and item.type in ROUTING_SUMMARY_TYPES and intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
        bonus -= 40
    if item.result_kind == "memory_hit" and item.type == "thread_summary" and intent == "work_resumption":
        if _memory_hit_has_selected_work_artifacts(item):
            bonus += 35
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        if intent == "work_resumption":
            bonus += 55
            if _query_contains_any(query_text, WORK_RESUMPTION_NEXT_STEP_CUES) and str(item.payload.get("next_step") or "").strip():
                bonus += 25
            if _query_contains_any(query_text, WORK_RESUMPTION_PROGRESS_CUES) and str(item.payload.get("current_state") or "").strip():
                bonus += 20
            if _query_contains_any(query_text, WORK_RESUMPTION_BLOCKER_CUES) and str(item.payload.get("blocker_state") or "").strip():
                bonus += 25
        elif intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
            bonus -= 35
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "answer_continuity":
        bonus += 25
    if item.result_kind == "memory_hit" and item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES and intent == "broad_recall" and _query_contains_any(query_text, BROAD_RECALL_CONCLUSION_CUES):
        bonus += 85 if item.type == "decision" else 75
    if item.result_kind == "memory_hit" and item.type == "continuity_memory" and intent == "broad_recall" and _query_contains_any(query_text, BROAD_RECALL_CONCLUSION_CUES):
        bonus -= 45
    if item.result_kind == "memory_hit" and item.type == "pattern_memory" and intent == "broad_recall":
        bonus += 25
        if _query_contains_any(query_text, BROAD_RECALL_ABSTRACTION_CUES):
            bonus += 45
    if item.result_kind == "source_hit" and intent == "evidence_trace":
        bonus += 30 if item.artifact_kind == "assistant_output" else 10
    if item.result_kind == "source_hit" and intent == "work_resumption":
        bonus += 45 if (item.artifact_kind or "") in SELECTED_WORK_ARTIFACT_KINDS else 20
        if (item.artifact_kind or "") == "todo_snapshot" and _query_contains_any(query_text, WORK_RESUMPTION_NEXT_STEP_CUES):
            bonus += 25
    if item.result_kind == "source_hit" and intent == "investigative_conclusion":
        bonus += 6 if item.artifact_kind == "assistant_output" else 2
    return bonus

def _query_contains_any(text: str, cues: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in cues)


def _edit_distance_with_limit(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]



def _looks_like_low_value_greeting_variant(normalized: str) -> bool:
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    if normalized in LOW_VALUE_GREETING_NOISE_QUERIES:
        return True
    low_value_trailing_tokens = {"again", "sir", "team", "friend", "folks", "maam", "madam"}
    if tokens[0] == "good" and len(tokens) >= 2:
        if any(_edit_distance_with_limit(tokens[1], marker, 2) <= 2 for marker in ("morning", "afternoon", "evening")):
            return all(token in low_value_trailing_tokens for token in tokens[2:])
    for marker in ("hello", "hi", "hey", "thanks"):
        if _edit_distance_with_limit(tokens[0], marker, 1) <= 1:
            return all(token in low_value_trailing_tokens for token in tokens[1:])
    return False


def _source_hit_is_greeting_or_noise_text(text: str) -> bool:
    normalized = normalize_for_index(text)
    if not normalized:
        return False
    if _looks_like_low_value_greeting_variant(normalized):
        return True
    for prefix in LOW_VALUE_GREETING_NOISE_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        remainder = normalized[len(prefix):].strip()
        if not remainder:
            return True
        if _looks_like_low_value_greeting_variant(f"{prefix} {remainder}".strip()):
            return True
        if remainder.startswith(("i can help", "let me know", "when you are ready", "how can i help")):
            return True
    return False


def _query_is_low_value_greeting_or_noise(text: str) -> bool:
    normalized = normalize_for_index(text)
    if not normalized:
        return False
    if _looks_like_low_value_greeting_variant(normalized):
        return True
    return len(normalized.split()) <= 4 and _source_hit_is_greeting_or_noise_text(text)


def _strip_constraint_snippets(text: str) -> str:
    stripped = str(text or "")
    for snippet in _extract_constraint_snippets(stripped):
        stripped = re.sub(re.escape(snippet), " ", stripped, flags=re.IGNORECASE)
    return stripped


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


def _query_topic_tokens(query_tokens: tuple[str, ...]) -> set[str]:
    return {
        token
        for token in query_tokens
        if token not in ROUTING_META_QUERY_TOKENS and token not in ROUTING_TOPIC_LOW_SIGNAL_TOKENS
    }



def _topic_alignment_adjustment(*, layer: str, query_topic_tokens: set[str], topic_overlap_tokens: list[str]) -> int:
    if not query_topic_tokens:
        return 0
    if topic_overlap_tokens:
        return min(len(topic_overlap_tokens), 2) * 36
    if layer in {"task_checkpoint", "thread_summary", "discussion_summary", "continuity_memory", "pattern_memory"}:
        return -140
    if layer == "source_evidence":
        return -110
    return -90


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
        elif item.type == "task_checkpoint":
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "task", "current_state", "blocker_state", "next_step", "freshness_signal")
            )
            for field in ("key_findings", "evidence"):
                values = item.payload.get(field, [])
                if isinstance(values, list):
                    fragments.extend(str(value or "") for value in values)
            for work_artifact in item.payload.get("selected_work_artifacts", []):
                if isinstance(work_artifact, dict):
                    fragments.append(str(work_artifact.get("signal_type") or ""))
                    fragments.append(str(work_artifact.get("text") or ""))
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
        elif item.type in ROUTING_HIGHER_LEVEL_TYPES:
            fragments.extend(
                str(item.payload.get(key) or "")
                for key in ("summary", "pattern_label", "continuity_question", "carry_forward_answer")
            )
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
        elif item.type == "thread_summary":
            fragments.append(str(item.payload.get("summary") or ""))
            for conclusion in item.payload.get("conclusions", []):
                if isinstance(conclusion, dict):
                    fragments.append(str(conclusion.get("text") or ""))
            for work_artifact in item.payload.get("selected_work_artifacts", []):
                if isinstance(work_artifact, dict):
                    fragments.append(str(work_artifact.get("signal_type") or ""))
                    fragments.append(str(work_artifact.get("text") or ""))
        else:
            fragments.append(json.dumps(item.payload, sort_keys=True))
    return " ".join(fragment for fragment in fragments if fragment)

def _routing_reason(
    intent: str,
    layer: str,
    content_overlap_tokens: list[str],
    support_grade: str,
    routing_focus: dict[str, object],
    packaging_reasons: list[str],
) -> str:
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if not content_overlap_tokens and layer in ROUTING_HIGHER_LEVEL_TYPES else ""
    fallback_suffix = _routing_fallback_suffix(
        layer=layer,
        selected_layer=str(routing_focus["selected_layer"]),
        primary_layer=str(routing_focus["primary_layer"]),
        applied=bool(routing_focus["applied"]),
        reason_code=str(routing_focus["reason_code"]),
        support_grade=support_grade,
    )
    packaging_suffix = _routing_packaging_suffix(packaging_reasons)
    if intent == "investigative_conclusion":
        if layer == "investigation_outcome":
            return "Investigative wording favors prior resolved findings before broader summaries." + fallback_suffix + packaging_suffix
        if layer == "decision":
            return "A prior decision remains sharp context, but explicit investigation findings outrank it here." + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Source evidence stays close behind carried conclusions for investigative questions." + fallback_suffix + packaging_suffix
        if layer == "thread_summary":
            return "Thread summaries stay available, but investigative queries prefer sharper findings and decisions first." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Discussion summaries are last-resort context for investigative questions." + weak_match_suffix + fallback_suffix + packaging_suffix
    if intent == "answer_continuity":
        if layer == "continuity_memory":
            return "Repeated-answer wording favors compact carry-forward memory." + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are narrower than repeated-answer carry-forward memory." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "pattern_memory":
            return "Broad pattern memory is demoted because the query is asking whether the answer was already given." + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Exact lower-level memory remains a fallback behind continuity carry-forward." + fallback_suffix + packaging_suffix
        return "Source evidence remains available, but routing prefers compact carry-forward first." + fallback_suffix + packaging_suffix
    if intent == "broad_recall":
        if layer == "pattern_memory":
            return "Broad recall wording favors higher-level pattern memory." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory is narrower than the broad prior-conclusion question." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are narrower than the broad prior-conclusion question." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Lower-level memory stays relevant, but broader recall prefers a consolidated pattern when present." + fallback_suffix + packaging_suffix
        return "Source evidence remains available, but compact prior-conclusion memory is preferred." + fallback_suffix + packaging_suffix
    if intent == "work_resumption":
        if layer == "task_checkpoint":
            return "Resume-oriented wording favors compact task checkpoints that preserve task state, blockers, and next steps." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Resume-oriented wording favors exact prior work artifacts and source evidence." + fallback_suffix + packaging_suffix
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Lower-level memory can orient resumed work, but routing keeps sharper prior work evidence ahead of summaries." + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory can help resumed work, but exact blocker and next-step evidence is preferred first." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Pattern or summary memory is too broad for resume-oriented state carry-forward." + weak_match_suffix + fallback_suffix + packaging_suffix
    if intent == "precise_fact":
        if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
            return "Precise factual wording favors exact lower-level memory over higher-level summaries." + fallback_suffix + packaging_suffix
        if layer == "source_evidence":
            return "Source evidence stays near the top for precise factual lookup." + fallback_suffix + packaging_suffix
        if layer == "task_checkpoint":
            return "Task checkpoints are demoted because they compress state instead of preserving exact factual detail." + weak_match_suffix + fallback_suffix + packaging_suffix
        if layer == "continuity_memory":
            return "Continuity memory is demoted because it can blur exact factual lookup." + weak_match_suffix + fallback_suffix + packaging_suffix
        return "Higher-level summary memory is demoted because it can blur exact factual lookup." + weak_match_suffix + fallback_suffix + packaging_suffix
    if layer == "source_evidence":
        return "Evidence-trace wording favors raw supporting source evidence." + fallback_suffix + packaging_suffix
    if layer in {"investigation_outcome", "decision", "lower_level_memory"}:
        return "Lower-level memory stays close behind source evidence for evidence-trace questions." + fallback_suffix + packaging_suffix
    if layer == "task_checkpoint":
        return "Task checkpoints are demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix
    if layer == "continuity_memory":
        return "Continuity memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix
    return "Pattern or summary memory is demoted because evidence-trace questions need sharper provenance." + weak_match_suffix + fallback_suffix + packaging_suffix

def _routing_strategy_name(item: QueryResultItem) -> str | None:
    if item.result_kind != "memory_hit" or not item.payload:
        return None
    provenance = item.payload.get("consolidation_provenance", {})
    if not isinstance(provenance, dict):
        return None
    strategy_name = provenance.get("strategy_name")
    return str(strategy_name) if isinstance(strategy_name, str) and strategy_name else None


def _routing_result_id(item: QueryResultItem) -> str:
    return str(item.result_id)


def _annotate_excluded_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    requested_limit: int,
    routing_focus: dict[str, object],
    packaging_summary: dict[str, object] | None,
) -> None:
    selected_result_ids = {_routing_result_id(candidate["item"]) for candidate in final_candidates}
    packaging_mode = str((packaging_summary or {}).get("mode") or "")
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if result_id in selected_result_ids:
            candidate["excluded_reason_code"] = None
            candidate["excluded_reason"] = None
            continue
        if candidate.get("suppression_reason_code"):
            candidate["excluded_reason_code"] = candidate.get("suppression_reason_code")
            candidate["excluded_reason"] = candidate.get("suppression_reason")
        elif (
            packaging_mode == "task_checkpoint_plus_adjacent_evidence"
            and int(candidate.get("routing_rank", 0)) <= requested_limit
        ):
            candidate["excluded_reason_code"] = "displaced_by_adjacent_evidence_packaging"
            candidate["excluded_reason"] = "Checkpoint packaging preferred adjacent source evidence for resumed-work coverage."
        elif bool(routing_focus.get("applied")) and str(candidate.get("layer")) == str(routing_focus.get("primary_layer")):
            candidate["excluded_reason_code"] = "fallback_layer_deprioritized"
            candidate["excluded_reason"] = str(routing_focus.get("reason"))
        else:
            candidate["excluded_reason_code"] = "lower_routing_score_than_selected_limit"
            candidate["excluded_reason"] = "Candidate remained below the final routed cutoff."


def _build_routing_trace(
    *,
    intent: str,
    family_inference: dict[str, object],
    preferred_layers: tuple[str, ...],
    layer_summary: dict[str, dict[str, object]],
    routing_focus: dict[str, object],
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    packaging_summary: dict[str, object] | None,
    runtime_context: QueryRuntimeContext | None,
    injection_summary: dict[str, object],
    sharp_candidate_diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    selected_results = [_build_routing_trace_entry(candidate) for candidate in final_candidates]
    demoted_higher_level_hits = [
        _build_routing_trace_entry(candidate)
        for candidate in ranked_candidates
        if candidate["layer"] in ROUTING_HIGHER_LEVEL_TYPES
        and int(candidate["routing_rank"]) > int(candidate["lexical_rank"])
    ][:4]
    excluded_high_scoring_candidates = [
        _build_routing_trace_entry(candidate)
        for candidate in ranked_candidates
        if candidate.get("excluded_reason_code")
    ][:5]
    returned_result_kinds: dict[str, int] = {}
    for candidate in final_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        returned_result_kinds[item.result_kind] = returned_result_kinds.get(item.result_kind, 0) + 1
    trace = {
        "policy_name": ROUTING_POLICY_NAME,
        "query_intent": intent,
        "query_family": _query_family_label(intent, runtime_context=runtime_context, injection_summary=injection_summary),
        "family_inference": family_inference,
        "preferred_layers": list(preferred_layers),
        "selected_layer": routing_focus["selected_layer"],
        "candidate_count_entering_routing": len(ranked_candidates),
        "returned_result_kinds": returned_result_kinds,
        "fallback": {
            "applied": routing_focus["applied"],
            "from_layer": routing_focus["primary_layer"],
            "to_layer": routing_focus["selected_layer"],
            "reason_code": routing_focus["reason_code"],
            "reason": routing_focus["reason"],
        },
        "candidate_summary": layer_summary,
        "selected_results": selected_results,
        "excluded_high_scoring_candidates": excluded_high_scoring_candidates,
        "demoted_higher_level_hits": demoted_higher_level_hits,
        "injection_decision": injection_summary,
        "sharp_candidate_diagnostics": sharp_candidate_diagnostics,
    }
    if packaging_summary:
        trace["packaging"] = packaging_summary
    return trace


def _build_routing_trace_entry(candidate: dict[str, object]) -> dict[str, object]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    entry = {
        "result_id": _routing_result_id(item),
        "result_kind": item.result_kind,
        "result_origin": "memory" if item.result_kind == "memory_hit" else "source",
        "memory_type": item.type,
        "layer": candidate["layer"],
        "lexical_rank": candidate["lexical_rank"],
        "routing_rank": candidate["routing_rank"],
        "lexical_score": candidate["lexical_score"],
        "routing_score": candidate["routing_score"],
        "support_score": candidate["support_score"],
        "support_grade": candidate["support_grade"],
        "reason": candidate["reason"],
    }
    content_overlap_tokens = list(candidate["content_overlap_tokens"])
    if content_overlap_tokens:
        entry["content_overlap_terms"] = content_overlap_tokens
    if candidate["evidence_count"]:
        entry["evidence_count"] = candidate["evidence_count"]
    if candidate["same_thread"]:
        entry["same_thread"] = True
    if candidate["same_container"]:
        entry["same_container"] = True
    if candidate["freshness_timestamp"]:
        entry["freshness_timestamp"] = candidate["freshness_timestamp"]
    if candidate["packaging_adjustment"]:
        entry["packaging_adjustment"] = candidate["packaging_adjustment"]
    if candidate["work_usefulness_score"]:
        entry["work_usefulness_score"] = candidate["work_usefulness_score"]
    if candidate["work_signal_types"]:
        entry["work_signal_types"] = list(candidate["work_signal_types"])
    if candidate["packaging_reasons"]:
        entry["packaging_reasons"] = list(candidate["packaging_reasons"])
    if candidate.get("excluded_reason_code"):
        entry["excluded_reason_code"] = candidate["excluded_reason_code"]
        entry["excluded_reason"] = candidate.get("excluded_reason")
    strategy_name = candidate["strategy_name"]
    if strategy_name is not None:
        entry["strategy_name"] = strategy_name
    return entry


def _build_injectable_blocks(
    final_candidates: list[dict[str, object]],
    *,
    ranked_candidates: list[dict[str, object]],
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> tuple[list[InjectableBlock], dict[str, object]]:
    same_thread_context = _evaluate_same_thread_local_context(
        ranked_candidates,
        intent=intent,
        query_text=query_text,
        query_filters=query_filters,
        runtime_context=runtime_context,
    )
    if same_thread_context["suppress_injection"]:
        return [], {
            "should_inject": False,
            "decision_reason": "same_thread_context_sufficient",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }
    if _query_is_low_value_greeting_or_noise(query_text):
        return [], {
            "should_inject": False,
            "decision_reason": "low_value_query",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }
    if not final_candidates:
        return [], {
            "should_inject": False,
            "decision_reason": "no_relevant_memory",
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    primary_non_discussion_eligible = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            allow_discussion_fallback=False,
            allow_source_companion=False,
        )
    ]
    primary_eligible_candidates = [
        candidate
        for candidate in final_candidates
        if _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            allow_discussion_fallback=not primary_non_discussion_eligible,
            allow_source_companion=False,
        )
    ]
    if not primary_eligible_candidates:
        decision_reason = "only_low_value_candidates" if any(_candidate_is_low_value(candidate) for candidate in final_candidates) else "no_relevant_memory"
        return [], {
            "should_inject": False,
            "decision_reason": decision_reason,
            "returned_block_ids": [],
            "eligible_result_ids": [],
            "dropped_by_cap_result_ids": [],
            "cap": 3,
            "same_thread_context_evaluation": same_thread_context,
        }

    selected_candidates = list(primary_eligible_candidates[:3])
    if intent == "work_resumption" and len(selected_candidates) < 3:
        used_result_ids = {_routing_result_id(candidate["item"]) for candidate in selected_candidates}
        companion_candidates = [
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                allow_discussion_fallback=False,
                allow_source_companion=True,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in used_result_ids
        ]
        for candidate in companion_candidates:
            if len(selected_candidates) >= 3:
                break
            selected_candidates.append(candidate)
            used_result_ids.add(_routing_result_id(candidate["item"]))

    blocks = [_build_injectable_block_from_candidate(candidate, intent=intent) for candidate in selected_candidates]
    returned_ids = [block.result_id for block in blocks]
    eligible_candidates = list(primary_eligible_candidates)
    if intent == "work_resumption":
        eligible_candidates.extend(
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                allow_discussion_fallback=False,
                allow_source_companion=True,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in {_routing_result_id(item["item"]) for item in eligible_candidates}
        )
    eligible_ids = [_routing_result_id(candidate["item"]) for candidate in eligible_candidates]
    dropped_ids = [result_id for result_id in eligible_ids if result_id not in returned_ids]
    return blocks, {
        "should_inject": bool(blocks),
        "decision_reason": "carry_forward_available" if blocks else "no_relevant_memory",
        "returned_block_ids": returned_ids,
        "eligible_result_ids": eligible_ids,
        "dropped_by_cap_result_ids": dropped_ids,
        "cap": 3,
        "same_thread_context_evaluation": same_thread_context,
    }



def _evaluate_same_thread_local_context(
    ranked_candidates: list[dict[str, object]],
    *,
    intent: str,
    query_text: str,
    query_filters: QueryFilters | None,
    runtime_context: QueryRuntimeContext | None,
) -> dict[str, object]:
    if not (
        runtime_context is not None
        and runtime_context.turn_kind in {"same_thread", "same_thread_continuation"}
        and runtime_context.session_has_sufficient_local_context is True
    ):
        return {"evaluated": False, "suppress_injection": False}
    if query_filters is None or not query_filters.thread_ref:
        return {
            "evaluated": True,
            "suppress_injection": True,
            "reason_code": "runtime_same_thread_context_only",
            "qualifying_result_ids": [],
            "external_carry_forward_result_ids": [],
            "rejected_candidates": [],
        }

    qualifying_result_ids: list[str] = []
    external_carry_forward_result_ids: list[str] = []
    rejected_candidates: list[dict[str, str]] = []
    for candidate in ranked_candidates:
        result_id = _routing_result_id(candidate["item"])
        if bool(candidate.get("same_thread")):
            qualifies, reason_code = _candidate_qualifies_as_same_thread_local_state(
                candidate,
                intent=intent,
                query_text=query_text,
            )
            if qualifies:
                qualifying_result_ids.append(result_id)
                continue
            rejected_candidates.append({"result_id": result_id, "reason_code": reason_code})
            continue
        if _candidate_could_supply_external_carry_forward(candidate, intent=intent):
            external_carry_forward_result_ids.append(result_id)

    if qualifying_result_ids:
        reason_code = "relevant_same_thread_local_state"
        suppress_injection = True
    elif not external_carry_forward_result_ids:
        reason_code = "no_external_carry_forward_available"
        suppress_injection = True
    else:
        reason_code = "insufficient_same_thread_local_state"
        suppress_injection = False

    return {
        "evaluated": True,
        "suppress_injection": suppress_injection,
        "reason_code": reason_code,
        "qualifying_result_ids": qualifying_result_ids,
        "external_carry_forward_result_ids": external_carry_forward_result_ids[:6],
        "rejected_candidates": rejected_candidates[:6],
    }



def _candidate_could_supply_external_carry_forward(candidate: dict[str, object], *, intent: str) -> bool:
    if _candidate_is_low_value(candidate):
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            allow_discussion_fallback=False,
            allow_source_companion=False,
        )
    return _candidate_is_injection_eligible(
        candidate,
        intent=intent,
        allow_discussion_fallback=True,
        allow_source_companion=False,
    )


def _candidate_qualifies_as_same_thread_local_state(
    candidate: dict[str, object],
    *,
    intent: str,
    query_text: str,
) -> tuple[bool, str]:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    suppression_reason = str(candidate.get("suppression_reason_code") or "")
    if suppression_reason:
        return False, suppression_reason
    if _candidate_is_low_value(candidate):
        return False, "low_value_same_thread_context"

    support_grade = str(candidate.get("support_grade") or "weak")
    support_score = int(candidate.get("support_score") or 0)
    work_usefulness = int(candidate.get("work_usefulness_score") or 0)
    overlap_tokens = list(candidate.get("content_overlap_tokens") or [])

    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "")
        if normalize_for_index(excerpt) == normalize_for_index(query_text):
            return False, "current_query_same_thread_source"
        if _source_hit_is_greeting_or_noise_text(excerpt):
            return False, "greeting_or_noise_same_thread_source"
        if _source_hit_looks_like_recall_query(item, query_text):
            return False, "query_like_same_thread_source"
        if item.role == "assistant" and _assistant_source_is_answer_bearing_local_state(excerpt, query_text):
            return True, ""
        if work_usefulness >= 18:
            return True, ""
        if support_grade in {"supported", "strong"} and _text_contains_operational_guidance(excerpt):
            if item.role == "assistant" or _preferred_constraint_text(excerpt):
                return True, ""
        if support_grade in {"supported", "strong"} and len(overlap_tokens) >= 2 and not _source_hit_looks_like_request_or_question(item):
            if item.role == "assistant" or intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
                return True, ""
        return False, "weak_same_thread_source"

    if item.type in {"task_checkpoint", "decision", "investigation_outcome"}:
        if support_grade in {"supported", "strong"}:
            return True, ""
        return False, "weak_same_thread_structured_state"

    if item.type in {"thread_summary", "discussion_summary"}:
        payload = item.payload or {}
        summary_text = str(payload.get("summary") or "").strip()
        summary_rejection = _summary_low_value_reason(
            item.type,
            payload,
            summary_text=summary_text,
            query_text=query_text,
        )
        if summary_rejection is not None:
            return False, summary_rejection[0]
        if payload.get("selected_work_artifacts") or payload.get("conclusions"):
            return True, ""
        if _preferred_constraint_text(summary_text) or _summary_text_has_durable_state_cue(summary_text):
            return True, ""
        if support_grade in {"supported", "strong"} and (support_score >= ROUTING_SUPPORT_THRESHOLD["supported"] or len(overlap_tokens) >= 2):
            return True, ""
        return False, "weak_same_thread_summary"

    return False, "non_local_state_candidate"


def _candidate_is_injection_eligible(
    candidate: dict[str, object],
    *,
    intent: str,
    allow_discussion_fallback: bool,
    allow_source_companion: bool,
) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if _candidate_is_low_value(candidate):
        return False
    if item.result_kind == "source_hit":
        if _source_candidate_is_primary_injection_eligible(intent):
            return True
        return allow_source_companion and _source_candidate_is_companion_injection_eligible(intent)
    if item.type in {"decision", "investigation_outcome", "task_checkpoint", "continuity_memory", "pattern_memory", "thread_summary"}:
        return True
    if item.type == "discussion_summary":
        return allow_discussion_fallback
    return False


def _source_candidate_is_primary_injection_eligible(intent: str) -> bool:
    return intent in {"evidence_trace", "investigative_conclusion"}


def _source_candidate_is_companion_injection_eligible(intent: str) -> bool:
    return intent == "work_resumption"


def _candidate_is_low_value(candidate: dict[str, object]) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return _is_low_value_meta_text(str(item.excerpt or ""))
    if item.type in {"discussion_summary", "thread_summary"}:
        payload = item.payload or {}
        return _is_low_value_meta_text(str(payload.get("summary") or ""))
    return False


def _build_injectable_block_from_candidate(candidate: dict[str, object], *, intent: str) -> InjectableBlock:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if item.result_kind == "source_hit":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="source_evidence",
            title="Supporting Evidence",
            text=str(item.excerpt or "").strip(),
            memory_type=None,
            evidence=item.evidence,
        )

    payload = item.payload or {}
    if item.type == "decision":
        text = str(payload.get("decision") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Decision: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Decision",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "investigation_outcome":
        text = str(payload.get("investigation_outcome") or "").strip()
        rationale = str(payload.get("rationale") or "").strip()
        body = f"Investigation outcome: {text}"
        if rationale:
            body += f" Rationale: {rationale}"
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Prior Investigation",
            text=body,
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "task_checkpoint":
        constraint = _preferred_constraint_text(
            str(payload.get("summary") or ""),
            str(payload.get("current_state") or ""),
            str(payload.get("blocker_state") or ""),
            *[str(value or "") for value in _parse_string_list(payload.get("key_findings"))],
            *[str(value or "") for value in _parse_string_list(payload.get("evidence"))],
        )
        parts: list[str] = []
        if constraint:
            parts.append(f"Constraint: {constraint}")
        parts.extend([str(payload.get("summary") or "").strip(), str(payload.get("current_state") or "").strip()])
        blocker = str(payload.get("blocker_state") or "").strip()
        next_step = str(payload.get("next_step") or "").strip()
        if blocker:
            parts.append(f"Blocker: {blocker}")
        if next_step:
            parts.append(f"Next step: {next_step}")
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Task Checkpoint",
            text=_join_unique_text_parts(parts),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "continuity_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Carry Forward",
            text=str(payload.get("carry_forward_answer") or payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type == "pattern_memory":
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Pattern Memory",
            text=str(payload.get("summary") or "").strip(),
            evidence=item.evidence,
            memory_type=item.type,
        )
    if item.type in {"thread_summary", "discussion_summary"}:
        summary_text = str(payload.get("summary") or "").strip()
        constraint = _preferred_constraint_text(summary_text)
        return InjectableBlock(
            result_id=str(item.result_id),
            block_type="memory",
            title="Thread Summary" if item.type == "thread_summary" else "Discussion Summary",
            text=_join_unique_text_parts([f"Constraint: {constraint}" if constraint else "", summary_text]),
            evidence=item.evidence,
            memory_type=item.type,
        )
    return InjectableBlock(
        result_id=str(item.result_id),
        block_type="memory",
        title=item.type or "Memory",
        text=str(payload.get("summary") or "").strip(),
        evidence=item.evidence,
        memory_type=item.type,
    )


def _join_unique_text_parts(parts: list[str]) -> str:
    ordered_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = str(part or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered_parts.append(normalized)
    return " ".join(ordered_parts)


def _preferred_constraint_text(*fragments: str) -> str:
    candidates: list[str] = []
    for fragment in fragments:
        candidates.extend(_extract_constraint_snippets(fragment))
    if not candidates:
        return ""
    unique_candidates = list(OrderedDict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))
    ordered_candidates = sorted(
        unique_candidates,
        key=lambda candidate: (
            "do not" not in candidate.lower() and "don't" not in candidate.lower(),
            "use only" not in candidate.lower() and "instead of" not in candidate.lower(),
            "avoid" not in candidate.lower() and "without" not in candidate.lower(),
            -len(candidate),
        ),
    )
    return _join_unique_text_parts(ordered_candidates)


def _extract_constraint_snippets(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    snippets: list[str] = []
    for fragment in re.split(r"(?<=[.!?])\s+|\n+", normalized):
        fragment_lowered = fragment.lower()
        fragment_has_tool_marker = any(marker in fragment_lowered for marker in CONSTRAINT_TOOL_MARKERS)
        for clause in re.split(r"(?<=[,;])\s+|\s+\b(?:and|but|while)\b\s+", fragment):
            candidate = clause.strip(" -,:;")
            lowered = candidate.lower()
            if not candidate:
                continue
            has_tool_marker = any(marker in lowered for marker in CONSTRAINT_TOOL_MARKERS)
            explicit_local_constraint = any(marker in lowered for marker in ("cannot use", "can't use", "cannot open", "can't open", "cannot connect", "can't connect"))
            has_constraint_marker = any(marker in lowered for marker in (*CONSTRAINT_MARKERS, "avoid", "without")) or explicit_local_constraint
            if has_constraint_marker and (has_tool_marker or fragment_has_tool_marker):
                snippets.append(candidate.rstrip("."))
    return list(OrderedDict.fromkeys(snippets))


def _fragment_is_constraint_only(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    strong_positive_markers = (
        "next step",
        "should ",
        "need to ",
        "must ",
        "attempt ",
        "retry ",
        "resume ",
        "rerun ",
        "refresh ",
        "connect ",
        "authenticate",
        "sign in",
        "log in manually",
        "login manually",
    )
    has_tool_marker = any(marker in lowered for marker in CONSTRAINT_TOOL_MARKERS)
    has_constraint_language = any(marker in lowered for marker in (*CONSTRAINT_MARKERS, "avoid", "without", "no-login", "no browser", "no-browser"))
    if not has_tool_marker or not has_constraint_language:
        return False
    if any(marker in lowered for marker in strong_positive_markers):
        return False
    residual = normalize_for_index(_strip_constraint_snippets(normalized))
    if not residual:
        return True
    residual_tokens = [
        token
        for token in residual.split()
        if token not in CONSTRAINT_ONLY_RESIDUAL_TOKENS and token not in CONSTRAINT_POLICY_STOPWORDS
    ]
    return not residual_tokens or not any(marker in residual for marker in strong_positive_markers)


def _build_sharp_candidate_diagnostics(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    injectable_blocks: list[InjectableBlock],
    decision_reason: str,
    debug_candidate_loader=None,
) -> list[dict[str, object]]:
    selected_injection_ids = {block.result_id for block in injectable_blocks}
    final_result_ids = {_routing_result_id(candidate["item"]) for candidate in final_candidates}
    diagnostics: dict[str, dict[str, object]] = {}

    for candidate in ranked_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        if item.type not in SHARP_DIAGNOSTIC_MEMORY_TYPES:
            continue
        result_id = _routing_result_id(item)
        loss_stage = "selected" if result_id in selected_injection_ids else "routing"
        loss_reason_code = None
        loss_reason = None
        if result_id not in final_result_ids:
            if candidate.get("excluded_reason_code") == "displaced_by_adjacent_evidence_packaging":
                loss_stage = "packaging"
            loss_reason_code = candidate.get("excluded_reason_code")
            loss_reason = candidate.get("excluded_reason")
        elif result_id not in selected_injection_ids:
            if decision_reason == "same_thread_context_sufficient":
                loss_stage = "packaging"
                loss_reason_code = "same_thread_context_sufficient"
                loss_reason = "Current same-thread session already had sufficient local context, so Pallium suppressed injection."
            elif decision_reason in {"only_low_value_candidates", "no_relevant_memory", "same_thread_context_sufficient", "injection_policy_unavailable"}:
                loss_stage = "packaging"
                loss_reason_code = decision_reason
                loss_reason = "Candidate survived routing but was excluded from final injection packaging."
            else:
                loss_stage = "injection_cap"
                loss_reason_code = "final_injection_cap"
                loss_reason = "Candidate remained eligible but was dropped by the final injection cap."
        diagnostics[result_id] = {
            "result_id": result_id,
            "candidate_kind": item.type,
            "result_kind": item.result_kind,
            "score": candidate["routing_score"],
            "injection_eligible": _candidate_is_injection_eligible(
                candidate,
                intent="investigative_conclusion",
                allow_discussion_fallback=False,
                allow_source_companion=False,
            ),
            "selected_for_injection": result_id in selected_injection_ids,
            "loss_stage": loss_stage,
            "loss_reason_code": loss_reason_code,
            "loss_reason": loss_reason,
            "retrieved": True,
            "lexical_rank": candidate.get("lexical_rank"),
            "routing_rank": candidate.get("routing_rank"),
        }

    if callable(debug_candidate_loader):
        for item in debug_candidate_loader(memory_types=list(SHARP_DIAGNOSTIC_MEMORY_TYPES)):
            if item.type not in SHARP_DIAGNOSTIC_MEMORY_TYPES:
                continue
            result_id = str(item.result_id)
            diagnostics.setdefault(
                result_id,
                {
                    "result_id": result_id,
                    "candidate_kind": item.type,
                    "result_kind": item.result_kind,
                    "score": 0,
                    "injection_eligible": True,
                    "selected_for_injection": False,
                    "loss_stage": "retrieval",
                    "loss_reason_code": "not_retrieved",
                    "loss_reason": "Sharp candidate was in scope but not retrieved lexically.",
                    "retrieved": False,
                    "lexical_rank": None,
                    "routing_rank": None,
                },
            )
    return list(diagnostics.values())


def _candidate_evidence_shape_score(
    item: QueryResultItem,
    *,
    layer: str,
    content_overlap_tokens: list[str],
    query_filters: QueryFilters | None,
) -> int:
    score = len(content_overlap_tokens) * 24
    evidence_count = len(item.evidence)
    score += min(evidence_count, 3) * 8
    if _candidate_matches_thread(item, query_filters):
        score += 12
    elif _candidate_matches_container(item, query_filters):
        score += 6

    if item.result_kind == "source_hit":
        artifact_kind = (item.artifact_kind or "").lower()
        if artifact_kind in SELECTED_WORK_ARTIFACT_KINDS:
            score += 34
        elif artifact_kind == "assistant_output":
            score += 28
        else:
            score += 18
        return score

    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        score += 34
        payload = item.payload or {}
        if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
            score += 10
        return score

    payload = item.payload or {}
    if item.type == "task_checkpoint":
        explicit_fields = sum(
            1
            for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
            if str(payload.get(key) or "").strip()
        )
        selected_work_artifacts = payload.get("selected_work_artifacts", [])
        artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
        key_findings = _parse_string_list(payload.get("key_findings"))
        evidence_lines = _parse_string_list(payload.get("evidence"))
        score += 18 + min(explicit_fields, 5) * 8 + min(artifact_count, 4) * 6
        score += min(len(key_findings), 3) * 4 + min(len(evidence_lines), 3) * 5
        if str(payload.get("blocker_state") or "").strip() and str(payload.get("next_step") or "").strip():
            score += 10
        freshness_text = str(payload.get("freshness_signal") or "").lower()
        if freshness_text and any(marker in freshness_text for marker in ("latest", "current", "stale")):
            score += 6
        if not evidence_lines and not key_findings:
            score -= 12
        return score

    if item.type == "continuity_memory":
        score += 18
        if str(payload.get("carry_forward_answer") or "").strip():
            score += 18
    elif item.type == "pattern_memory":
        score += 14
        if str(payload.get("pattern_label") or "").strip() and str(payload.get("pattern_label") or "").strip() != "generic_pattern":
            score += 10
    elif item.type in ROUTING_SUMMARY_TYPES:
        score += 8

    conclusions = payload.get("conclusions", [])
    if isinstance(conclusions, list):
        score += min(len([entry for entry in conclusions if isinstance(entry, dict) and entry.get("text")]), 3) * 8
    return score


def _apply_work_resumption_packaging(
    scored_candidates: list[dict[str, object]],
    *,
    query_filters: QueryFilters | None,
) -> dict[str, object]:
    relevant_candidates = [
        candidate
        for candidate in scored_candidates
        if _candidate_matches_requested_locality(candidate, query_filters)
    ]
    freshest_timestamp = max(
        (
            timestamp
            for timestamp in (
                candidate.get("freshness_timestamp_value")
                for candidate in relevant_candidates
            )
            if isinstance(timestamp, datetime)
        ),
        default=None,
    )

    for candidate in scored_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        signal_types = _work_resumption_signal_types(item)
        candidate["work_signal_types"] = signal_types
        usefulness_score, usefulness_reasons = _work_resumption_usefulness_score(item, signal_types)
        freshness_adjustment, freshness_reasons = _work_resumption_freshness_adjustment(candidate, freshest_timestamp)
        packaging_adjustment = usefulness_score + freshness_adjustment
        candidate["work_usefulness_score"] = usefulness_score
        candidate["packaging_adjustment"] = packaging_adjustment
        candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*usefulness_reasons, *freshness_reasons]))
        timestamp = candidate.get("freshness_timestamp_value")
        candidate["freshness_timestamp"] = timestamp.isoformat() if isinstance(timestamp, datetime) else None
        candidate["base_routing_score"] = int(candidate["base_routing_score"]) + packaging_adjustment
        support_adjustment = (usefulness_score // 2) + freshness_adjustment
        candidate["support_score"] = max(0, int(candidate["support_score"]) + support_adjustment)
        candidate["support_grade"] = _routing_support_grade(int(candidate["support_score"]))

    return {
        "mode": "work_resumption_ranking",
        "freshest_state_timestamp": freshest_timestamp.isoformat() if isinstance(freshest_timestamp, datetime) else None,
    }



def _candidate_matches_requested_locality(candidate: dict[str, object], query_filters: QueryFilters | None) -> bool:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    if query_filters is not None and query_filters.thread_ref:
        return query_filters.thread_ref in _candidate_thread_refs(item)
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in _candidate_container_refs(item)
    return True



def _work_resumption_signal_types(item: QueryResultItem) -> tuple[str, ...]:
    signal_types: set[str] = set()
    if item.result_kind == "source_hit":
        excerpt = str(item.excerpt or "").strip()
        signal_type = _classify_work_signal_text(item.artifact_kind, excerpt)
        if signal_type:
            signal_types.add(signal_type)
        if excerpt:
            signal_types.add("evidence")
        return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)

    payload = item.payload or {}
    if item.type == "task_checkpoint":
        if str(payload.get("task") or "").strip():
            signal_types.add("task")
        if str(payload.get("current_state") or "").strip():
            signal_types.add("progress_update")
        if _parse_string_list(payload.get("key_findings")):
            signal_types.add("key_finding")
        if str(payload.get("blocker_state") or "").strip():
            signal_types.add("blocker")
        if str(payload.get("next_step") or "").strip():
            signal_types.add("next_step")
        if _parse_string_list(payload.get("evidence")):
            signal_types.add("evidence")
        if str(payload.get("freshness_signal") or "").strip():
            signal_types.add("freshness")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        signal_types.add("key_finding")
        if str(payload.get("decision_evidence_text") or payload.get("investigation_evidence_text") or "").strip():
            signal_types.add("evidence")
    elif item.type in ROUTING_SUMMARY_TYPES:
        if str(payload.get("summary") or "").strip():
            signal_types.add("key_finding")
        for artifact in payload.get("selected_work_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_signal = str(artifact.get("signal_type") or "").strip()
            if artifact_signal in {"progress_update", "blocker", "next_step"}:
                signal_types.add(artifact_signal)
    elif item.type == "continuity_memory":
        if str(payload.get("carry_forward_answer") or "").strip():
            signal_types.add("key_finding")
    elif item.type == "pattern_memory" and str(payload.get("summary") or "").strip():
        signal_types.add("key_finding")
    return tuple(signal for signal in WORK_RESUMPTION_SIGNAL_TYPES if signal in signal_types)



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
    if _extract_constraint_signal_text(normalized_text):
        return "constraint"
    if any(marker in lowered for marker in IMPLICIT_FINDING_MARKERS):
        return "key_finding"
    if any(marker in lowered for marker in IMPLICIT_NEXT_STEP_MARKERS):
        return "next_step"
    if any(marker in lowered for marker in ("blocked", "blocker", "failed")):
        return "blocker"
    if artifact_kind_normalized in SELECTED_WORK_ARTIFACT_KINDS:
        return "progress_update"
    return ""



def _work_resumption_usefulness_score(item: QueryResultItem, signal_types: tuple[str, ...]) -> tuple[int, list[str]]:
    signal_set = set(signal_types)
    reasons: list[str] = []
    score = 0
    if item.result_kind == "memory_hit" and item.type == "task_checkpoint":
        payload = item.payload or {}
        if "task" in signal_set:
            score += 6
        if "progress_update" in signal_set:
            score += 8
        if "key_finding" in signal_set:
            score += 6
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "evidence" in signal_set:
            score += 10
        if "freshness" in signal_set:
            score += 8
        selected_work_artifacts = payload.get("selected_work_artifacts", [])
        artifact_count = len(selected_work_artifacts) if isinstance(selected_work_artifacts, list) else 0
        score += min(artifact_count, 3) * 2
        if {"blocker", "next_step", "evidence", "freshness"}.issubset(signal_set) and signal_set.intersection({"progress_update", "key_finding"}):
            score += 10
            reasons.append("sharp_checkpoint")
        if _is_thin_task_checkpoint_payload(payload):
            score -= WORK_RESUMPTION_THIN_CHECKPOINT_PENALTY
            reasons.append("thin_checkpoint")
        return score, reasons

    if item.result_kind == "source_hit":
        if "blocker" in signal_set:
            score += 12
        if "next_step" in signal_set:
            score += 12
        if "progress_update" in signal_set:
            score += 8
        if "evidence" in signal_set:
            score += 4
        return score, reasons

    if item.type in ROUTING_LOWER_LEVEL_EXACT_TYPES:
        if "key_finding" in signal_set:
            score += 10
        if "evidence" in signal_set:
            score += 6
        return score, reasons

    if item.type in ROUTING_SUMMARY_TYPES and signal_set.intersection({"blocker", "next_step", "progress_update"}):
        score += 8
    return score, reasons



def _is_thin_task_checkpoint_payload(payload: dict[str, object]) -> bool:
    explicit_core_fields = sum(
        1
        for key in ("task", "current_state", "blocker_state", "next_step", "freshness_signal")
        if str(payload.get(key) or "").strip()
    )
    has_findings = bool(_parse_string_list(payload.get("key_findings")))
    has_evidence = bool(_parse_string_list(payload.get("evidence")))
    has_operational_state = bool(str(payload.get("blocker_state") or "").strip() or str(payload.get("next_step") or "").strip())
    return explicit_core_fields < 3 or not has_operational_state or (not has_findings and not has_evidence)



def _work_resumption_freshness_adjustment(
    candidate: dict[str, object],
    freshest_timestamp: datetime | None,
) -> tuple[int, list[str]]:
    timestamp = candidate.get("freshness_timestamp_value")
    signal_types = set(candidate.get("work_signal_types") or ())
    if not isinstance(timestamp, datetime):
        return 0, []
    if freshest_timestamp is None:
        if candidate["layer"] == "task_checkpoint" and "freshness" in signal_types:
            return 8, ["explicit_freshness_signal"]
        return 0, []

    delta_seconds = (freshest_timestamp - timestamp).total_seconds()
    if delta_seconds >= WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS:
        if candidate["layer"] == "task_checkpoint":
            return -WORK_RESUMPTION_STALE_STATE_PENALTY, ["stale_against_fresher_state"]
        if candidate["layer"] == "source_evidence":
            return -WORK_RESUMPTION_STALE_SOURCE_PENALTY, ["stale_against_fresher_state"]
        return -(WORK_RESUMPTION_STALE_SOURCE_PENALTY // 2), ["stale_against_fresher_state"]
    if delta_seconds <= 0 and signal_types.intersection({"blocker", "next_step", "progress_update"}):
        return WORK_RESUMPTION_FRESH_STATE_BONUS, ["fresh_explicit_state"]
    if candidate["layer"] == "task_checkpoint" and "freshness" in signal_types:
        return 8, ["explicit_freshness_signal"]
    return 0, []



def _select_final_candidates(
    *,
    intent: str,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_filters: QueryFilters | None,
    query_shape_tags: list[str],
    runtime_context: QueryRuntimeContext | None,
    packaging_summary: dict[str, object] | None,
    local_constraint_profile: dict[str, object] | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    summary = dict(packaging_summary or {})
    if not ranked_candidates:
        return ranked_candidates[:requested_limit], summary or None
    if intent in {"broad_recall", "answer_continuity"}:
        return _select_compatible_recall_candidates(
            ranked_candidates=ranked_candidates,
            requested_limit=requested_limit,
            query_shape_tags=query_shape_tags,
            packaging_summary=summary,
            local_constraint_profile=local_constraint_profile,
        )
    if intent != "work_resumption":
        return ranked_candidates[:requested_limit], summary or None

    ranked_candidates, summary, _constraint_anchor, active_constraint_profile = _apply_structured_constraint_compatibility(
        ranked_candidates=ranked_candidates,
        packaging_summary=summary,
        local_constraint_profile=local_constraint_profile,
    )
    if not ranked_candidates:
        if active_constraint_profile is not None or summary.get("incompatible_structured_candidates"):
            summary["mode"] = "compatible_work_resumption"
        return [], summary or None
    if summary.get("incompatible_structured_candidates") and not any(candidate["layer"] == "task_checkpoint" for candidate in ranked_candidates):
        summary["mode"] = "compatible_work_resumption"
        return [], summary or None
    top_candidate = ranked_candidates[0]
    summary["top_result_layer"] = top_candidate["layer"]
    if top_candidate["layer"] != "task_checkpoint" or requested_limit <= 1:
        demoted_checkpoint = next((candidate for candidate in ranked_candidates if candidate["layer"] == "task_checkpoint"), None)
        if demoted_checkpoint is not None and demoted_checkpoint is not top_candidate:
            summary["demoted_task_checkpoint"] = {
                "result_id": _routing_result_id(demoted_checkpoint["item"]),
                "packaging_reasons": list(demoted_checkpoint["packaging_reasons"]),
            }
        return ranked_candidates[:requested_limit], summary

    selected_candidates = [top_candidate]
    used_result_ids = {_routing_result_id(top_candidate["item"])}
    adjacent_evidence: list[dict[str, str]] = []
    for signal_type in WORK_RESUMPTION_SIGNAL_PRIORITY:
        if len(selected_candidates) >= requested_limit:
            break
        for candidate in ranked_candidates[1:]:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if candidate["layer"] != "source_evidence":
                continue
            if signal_type not in candidate["work_signal_types"]:
                continue
            if not _candidate_locality_compatible_for_packaging(top_candidate["item"], candidate["item"], query_filters):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
            adjacent_evidence.append({"signal_type": signal_type, "result_id": candidate_result_id})
            break

    for candidate in ranked_candidates[1:]:
        if len(selected_candidates) >= requested_limit:
            break
        candidate_result_id = _routing_result_id(candidate["item"])
        if candidate_result_id in used_result_ids:
            continue
        selected_candidates.append(candidate)
        used_result_ids.add(candidate_result_id)

    if adjacent_evidence:
        summary["mode"] = "task_checkpoint_plus_adjacent_evidence"
        summary["adjacent_evidence"] = adjacent_evidence
    elif active_constraint_profile is not None or summary.get("incompatible_structured_candidates"):
        summary["mode"] = "compatible_work_resumption"
    return selected_candidates, summary



def _select_compatible_recall_candidates(
    *,
    ranked_candidates: list[dict[str, object]],
    requested_limit: int,
    query_shape_tags: list[str],
    packaging_summary: dict[str, object],
    local_constraint_profile: dict[str, object] | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    compatible_candidates, packaging_summary, constraint_anchor, active_constraint_profile = _apply_structured_constraint_compatibility(
        ranked_candidates=ranked_candidates,
        packaging_summary=packaging_summary,
        local_constraint_profile=local_constraint_profile,
    )
    if not compatible_candidates:
        if active_constraint_profile is not None or packaging_summary.get("incompatible_structured_candidates"):
            packaging_summary["mode"] = "compatible_structured_recall"
        return [], packaging_summary or None

    explicit_constraint_focus = "constraint_recall" in query_shape_tags
    if explicit_constraint_focus and constraint_anchor is not None and constraint_anchor in compatible_candidates:
        primary_candidate = constraint_anchor
    else:
        primary_candidate = compatible_candidates[0]

    selected_candidates = [primary_candidate]
    used_result_ids = {_routing_result_id(primary_candidate["item"])}
    primary_topic_tokens = set(primary_candidate.get("topic_overlap_tokens") or [])
    strict_primary_topic_filter = bool(primary_topic_tokens)
    primary_aligns_with_active_constraint = _candidate_aligns_with_constraint_profile(primary_candidate, active_constraint_profile)
    if constraint_anchor is not None and constraint_anchor in compatible_candidates:
        anchor_result_id = _routing_result_id(constraint_anchor["item"])
        anchor_topic_tokens = set(constraint_anchor.get("topic_overlap_tokens") or [])
        if (
            anchor_result_id not in used_result_ids
            and len(selected_candidates) < requested_limit
            and (
                explicit_constraint_focus
                or not strict_primary_topic_filter
                or primary_topic_tokens.intersection(anchor_topic_tokens)
            )
        ):
            selected_candidates.append(constraint_anchor)
            used_result_ids.add(anchor_result_id)

    remaining_candidates = [
        candidate
        for candidate in compatible_candidates
        if _routing_result_id(candidate["item"]) not in used_result_ids
    ]
    structured_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) == "memory_hit"
    ]
    source_remaining = [
        candidate
        for candidate in remaining_candidates
        if getattr(candidate["item"], "result_kind", None) != "memory_hit"
    ]
    for candidate_group in (structured_remaining, source_remaining):
        for candidate in candidate_group:
            candidate_result_id = _routing_result_id(candidate["item"])
            if candidate_result_id in used_result_ids:
                continue
            if len(selected_candidates) >= requested_limit:
                break
            candidate_topic_tokens = set(candidate.get("topic_overlap_tokens") or [])
            if strict_primary_topic_filter and not primary_topic_tokens.intersection(candidate_topic_tokens):
                if not (
                    primary_aligns_with_active_constraint
                    and _candidate_aligns_with_constraint_profile(candidate, active_constraint_profile)
                ):
                    continue
            if (
                primary_topic_tokens
                and not candidate_topic_tokens.intersection(primary_topic_tokens)
                and str(candidate.get("layer")) in {"continuity_memory", "pattern_memory", "thread_summary", "discussion_summary"}
            ):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(candidate_result_id)
        if len(selected_candidates) >= requested_limit:
            break

    if packaging_summary.get("incompatible_structured_candidates"):
        packaging_summary["mode"] = "compatible_structured_recall"
    elif active_constraint_profile is not None:
        packaging_summary["mode"] = "compatible_structured_recall"
    return selected_candidates, packaging_summary or None



def _constraint_profile_sort_key(profile: dict[str, object]) -> tuple[datetime, int]:
    freshness_at = profile.get("freshness_at")
    if not isinstance(freshness_at, datetime):
        freshness_at = datetime.min.replace(tzinfo=timezone.utc)
    return freshness_at, len(profile.get("protected_tokens") or [])


def _build_local_query_constraint_profile(
    query_text: str,
    runtime_context: QueryRuntimeContext | None,
) -> dict[str, object] | None:
    if runtime_context is None or runtime_context.turn_kind not in {"same_thread", "same_thread_continuation"}:
        return None
    constraint_text = _preferred_constraint_text(query_text)
    if not constraint_text:
        return None
    return _structured_constraint_profile_from_payload(
        memory_type="thread_summary",
        payload={"summary": constraint_text},
        result_id="query_text:local_constraint",
    )



def _candidate_aligns_with_constraint_profile(candidate: dict[str, object], constraint_profile: dict[str, object] | None) -> bool:
    if constraint_profile is None:
        return False
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    candidate_tokens = set(_routing_item_tokens(item))
    if not candidate_tokens:
        return False
    focus_tokens = set(constraint_profile.get("focus_tokens") or [])
    protected_tokens = set(constraint_profile.get("protected_tokens") or [])
    target_tokens = focus_tokens or protected_tokens
    return bool(target_tokens.intersection(candidate_tokens))



def _apply_structured_constraint_compatibility(
    *,
    ranked_candidates: list[dict[str, object]],
    packaging_summary: dict[str, object],
    local_constraint_profile: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object] | None, dict[str, object] | None]:
    unsuppressed_candidates = [candidate for candidate in ranked_candidates if not candidate.get("suppression_reason_code")]
    if not unsuppressed_candidates:
        return [], packaging_summary, None, None

    compatible_candidates: list[dict[str, object]] = []
    incompatible_candidates: list[dict[str, str]] = []
    constraint_anchor: dict[str, object] | None = None
    active_constraint_profile: dict[str, object] | None = None
    fallback_conflicting_profile: dict[str, object] | None = None
    for candidate in unsuppressed_candidates:
        profile = _structured_constraint_profile_from_item(candidate["item"])
        if profile is None:
            continue
        if _candidate_has_self_conflicting_guidance(candidate):
            if fallback_conflicting_profile is None or _constraint_profile_sort_key(profile) > _constraint_profile_sort_key(fallback_conflicting_profile):
                fallback_conflicting_profile = profile
            continue
        if active_constraint_profile is None or _constraint_profile_sort_key(profile) > _constraint_profile_sort_key(active_constraint_profile):
            active_constraint_profile = profile
            constraint_anchor = candidate
    if local_constraint_profile is not None:
        active_constraint_profile = local_constraint_profile
        packaging_summary["active_constraint_profile_source"] = "local_query_constraint"
    elif active_constraint_profile is None:
        active_constraint_profile = fallback_conflicting_profile

    for candidate in unsuppressed_candidates:
        item = candidate["item"]
        assert isinstance(item, QueryResultItem)
        conflict_reason = None
        if _candidate_has_self_conflicting_guidance(candidate):
            conflict_reason = (
                "conflicts_with_active_constraint",
                "Structured memory included operational guidance that conflicts with an explicit carried constraint.",
            )
        elif active_constraint_profile is not None and candidate is not constraint_anchor and _candidate_conflicts_with_constraint(item, active_constraint_profile):
            conflict_reason = (
                "conflicts_with_active_constraint",
                "Candidate guidance was excluded because it conflicts with the active carried constraint.",
            )
        if conflict_reason is not None:
            reason_code, reason_text = conflict_reason
            candidate["suppression_reason_code"] = reason_code
            candidate["suppression_reason"] = reason_text
            candidate["packaging_reasons"] = list(OrderedDict.fromkeys([*candidate["packaging_reasons"], reason_code]))
            incompatible_candidates.append({
                "result_id": _routing_result_id(item),
                "reason_code": reason_code,
            })
            continue
        compatible_candidates.append(candidate)

    if active_constraint_profile is not None:
        packaging_summary["active_constraint_profile"] = {
            "result_id": str(active_constraint_profile.get("result_id") or ""),
            "memory_type": str(active_constraint_profile.get("memory_type") or ""),
            "constraint_text": str(active_constraint_profile.get("constraint_text") or ""),
            "protected_tokens": list(active_constraint_profile.get("protected_tokens") or []),
            "focus_tokens": list(active_constraint_profile.get("focus_tokens") or []),
            "exclusive_tokens": list(active_constraint_profile.get("exclusive_tokens") or []),
        }
    if constraint_anchor is not None:
        packaging_summary["constraint_anchor_result_id"] = _routing_result_id(constraint_anchor["item"])
    if incompatible_candidates:
        packaging_summary["incompatible_structured_candidates"] = incompatible_candidates

    return compatible_candidates, packaging_summary, constraint_anchor, active_constraint_profile



def _list_active_constraint_profiles(
    storage,
    *,
    container_ref: str,
    visibility_context,
) -> list[dict[str, object]]:
    active_profiles: list[dict[str, object]] = []
    for memory_object in storage.list_memory_objects(
        memory_types=list(STRUCTURED_CONFLICT_MEMORY_TYPES),
        lifecycle="active",
    ):
        payload = memory_object.payload or {}
        if str(payload.get("container_ref") or "") != container_ref:
            continue
        if memory_object.visibility_context != visibility_context:
            continue
        profile = _structured_constraint_profile_from_payload(
            memory_type=memory_object.type,
            payload=payload,
            result_id=f"memory_object:{memory_object.id}",
            freshness_at=memory_object.freshness_at,
        )
        if profile is None:
            continue
        if _structured_payload_conflicts_with_constraint(memory_object.type, payload, profile):
            continue
        active_profiles.append(profile)
    active_profiles.sort(key=_constraint_profile_sort_key, reverse=True)
    return active_profiles



def _structured_constraint_profile_from_payload(
    *,
    memory_type: str,
    payload: dict[str, object],
    result_id: str,
    freshness_at: datetime | None = None,
) -> dict[str, object] | None:
    constraint_text = _preferred_constraint_text(*_structured_payload_constraint_fragments(memory_type, payload))
    if not constraint_text:
        return None
    protected_tokens = set(_constraint_policy_tokens(constraint_text))
    if protected_tokens.intersection({"issue", "jira", "log", "login", "portal", "sign", "slack", "tracker"}):
        protected_tokens.update({"auth", "authenticate", "authentication", "retry"})
    focus_tokens = _prohibited_constraint_focus_tokens(constraint_text) or _constraint_focus_tokens(protected_tokens)
    exclusive_tokens = _exclusive_constraint_tokens(constraint_text)
    protected_tokens = sorted(protected_tokens)
    focus_tokens = sorted(focus_tokens)
    exclusive_tokens = sorted(exclusive_tokens)
    if not protected_tokens:
        return None
    return {
        "result_id": result_id,
        "memory_type": memory_type,
        "constraint_text": constraint_text,
        "protected_tokens": protected_tokens,
        "focus_tokens": focus_tokens,
        "exclusive_tokens": exclusive_tokens,
        "freshness_at": freshness_at,
    }



def _structured_payload_conflicts_with_constraint(memory_type: str, payload: dict[str, object], constraint_profile: dict[str, object]) -> bool:
    return any(
        _structured_text_conflicts_with_constraint(fragment, constraint_profile)
        for fragment in _structured_payload_guidance_fragments(memory_type, payload)
    )



def _reconcile_memory_object_against_active_constraints(
    memory_object: MemoryObject,
    *,
    active_constraints: list[dict[str, object]],
) -> MemoryObject:
    if memory_object.type not in STRUCTURED_CONFLICT_MEMORY_TYPES or not active_constraints:
        return memory_object
    payload = dict(memory_object.payload or {})
    active_constraint = active_constraints[0]
    if not _structured_payload_conflicts_with_constraint(memory_object.type, payload, active_constraint):
        return memory_object

    constraint_text = str(active_constraint.get("constraint_text") or "").strip()
    updated_payload = dict(payload)
    if memory_object.type == "task_checkpoint":
        updated_payload["summary"] = _strip_conflicting_guidance_text(str(payload.get("summary") or ""), active_constraint)
        updated_payload["current_state"] = _strip_conflicting_guidance_text(str(payload.get("current_state") or ""), active_constraint)
        blocker_state = _strip_conflicting_guidance_text(str(payload.get("blocker_state") or ""), active_constraint)
        updated_payload["blocker_state"] = _join_unique_text_parts([constraint_text, blocker_state]) if constraint_text else blocker_state
        updated_payload["next_step"] = _strip_conflicting_guidance_text(str(payload.get("next_step") or ""), active_constraint)
        updated_payload["key_findings"] = [
            text
            for text in _parse_string_list(payload.get("key_findings"))
            if not _structured_text_conflicts_with_constraint(text, active_constraint)
        ]
        evidence_lines = [
            text
            for text in _parse_string_list(payload.get("evidence"))
            if not _structured_text_conflicts_with_constraint(text, active_constraint)
        ]
        if constraint_text and not any(constraint_text.lower() in text.lower() for text in evidence_lines):
            evidence_lines.insert(0, f"Constraint: {constraint_text}")
        updated_payload["evidence"] = evidence_lines
    else:
        summary = _strip_conflicting_guidance_text(str(payload.get("summary") or ""), active_constraint)
        updated_payload["summary"] = _join_unique_text_parts([constraint_text, summary]) if constraint_text else summary
        if memory_object.type == "thread_summary":
            updated_payload["selected_work_artifacts"] = [
                artifact
                for artifact in payload.get("selected_work_artifacts", [])
                if isinstance(artifact, dict)
                and not _structured_text_conflicts_with_constraint(str(artifact.get("text") or ""), active_constraint)
            ]
            updated_payload["conclusions"] = [
                conclusion
                for conclusion in payload.get("conclusions", [])
                if isinstance(conclusion, dict)
                and not _structured_text_conflicts_with_constraint(str(conclusion.get("text") or ""), active_constraint)
            ]
    semantic_provenance = dict(updated_payload.get("semantic_provenance") or {})
    semantic_provenance["constraint_reconciliation"] = {
        "active_constraint_result_id": str(active_constraint.get("result_id") or ""),
        "constraint_text": constraint_text,
    }
    updated_payload["semantic_provenance"] = semantic_provenance
    return replace(memory_object, payload=updated_payload)



def _strip_conflicting_guidance_text(text: str, constraint_profile: dict[str, object]) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    parts = [part.strip(" -") for part in re.split(r"(?<=[.!?;])\s+|\n+", normalized) if part.strip(" -")]
    if not parts:
        return ""
    kept_parts: list[str] = []
    for part in parts:
        if not _structured_text_conflicts_with_constraint(part, constraint_profile):
            kept_parts.append(part)
            continue
        preferred_constraint = _preferred_constraint_text(part)
        if preferred_constraint:
            kept_parts.append(preferred_constraint)
    return _join_unique_text_parts(kept_parts)


def _structured_text_conflicts_with_constraint(text: str, constraint_profile: dict[str, object]) -> bool:
    normalized = str(text or "").strip()
    if not normalized or not _text_contains_operational_guidance(normalized):
        return False
    if _fragment_is_constraint_only(normalized):
        return False
    stripped = _strip_constraint_snippets(normalized).strip()
    candidate_text = stripped if re.search(r"\w", stripped) else normalized
    if candidate_text != normalized and not _text_contains_operational_guidance(candidate_text):
        return False
    protected_tokens = set(constraint_profile.get("protected_tokens") or [])
    if not protected_tokens:
        return False
    candidate_tokens = _constraint_policy_tokens(candidate_text)
    if not candidate_tokens:
        return False
    focus_tokens = set(constraint_profile.get("focus_tokens") or [])
    focus_basis = focus_tokens or {
        token for token in protected_tokens if token not in CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS
    }
    focus_overlap = candidate_tokens.intersection(focus_basis)
    exclusive_tokens = set(constraint_profile.get("exclusive_tokens") or [])
    if len(focus_overlap) >= 2:
        if exclusive_tokens:
            forbidden_focus_overlap = focus_overlap.difference(exclusive_tokens)
            lowered_candidate = candidate_text.lower()
            if candidate_tokens.intersection(exclusive_tokens) and not forbidden_focus_overlap and re.search(r"\buse\b", lowered_candidate):
                return False
            residual_tokens = candidate_tokens.difference(
                exclusive_tokens,
                CONSTRAINT_POLICY_ACTION_TOKENS,
                CONSTRAINT_POLICY_LOW_SIGNAL_TOKENS,
                ROUTING_META_QUERY_TOKENS,
                {"next", "step", "instead", "rather", "than"},
            )
            if candidate_tokens.intersection(exclusive_tokens) and not forbidden_focus_overlap and not residual_tokens:
                return False
        return True
    if focus_overlap and len(focus_basis) <= 2:
        return True
    action_overlap = candidate_tokens.intersection(protected_tokens).intersection(CONSTRAINT_POLICY_ACTION_TOKENS)
    return bool(focus_basis) and len(action_overlap) >= 2



def _rebuild_reconciled_memory_index_entry(memory_object: MemoryObject):
    payload = memory_object.payload or {}
    if memory_object.type != "task_checkpoint":
        return build_index_entry(
            target_kind="memory_object",
            target_id=memory_object.id,
            index_type="lexical",
            text_view=normalize_for_index(str(payload.get("summary") or "")),
            text_view_name=TASK_CHECKPOINT_TEXT_VIEW if memory_object.type == "task_checkpoint" else THREAD_SUMMARY_TEXT_VIEW,
        )
    index_source = " ".join(
        [
            str(payload.get("summary") or ""),
            str(payload.get("task") or ""),
            str(payload.get("current_state") or ""),
            str(payload.get("blocker_state") or ""),
            str(payload.get("next_step") or ""),
            str(payload.get("freshness_signal") or ""),
            *[str(value or "") for value in _parse_string_list(payload.get("key_findings"))],
            *[str(value or "") for value in _parse_string_list(payload.get("evidence"))],
            *[str(item.get("text") or "") for item in payload.get("conclusions", []) if isinstance(item, dict)],
            *[str(item.get("text") or "") for item in payload.get("selected_work_artifacts", []) if isinstance(item, dict)],
        ]
    )
    return build_index_entry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view=normalize_for_index(index_source),
        text_view_name=TASK_CHECKPOINT_TEXT_VIEW,
    )


def _candidate_locality_compatible_for_packaging(
    primary_item: QueryResultItem,
    candidate_item: QueryResultItem,
    query_filters: QueryFilters | None,
) -> bool:
    primary_thread_refs = set(_candidate_thread_refs(primary_item))
    candidate_thread_refs = set(_candidate_thread_refs(candidate_item))
    if query_filters is not None and query_filters.thread_ref:
        return query_filters.thread_ref in primary_thread_refs and query_filters.thread_ref in candidate_thread_refs
    if primary_thread_refs and candidate_thread_refs and primary_thread_refs.intersection(candidate_thread_refs):
        return True

    primary_container_refs = set(_candidate_container_refs(primary_item))
    candidate_container_refs = set(_candidate_container_refs(candidate_item))
    if query_filters is not None and query_filters.container_ref:
        return query_filters.container_ref in primary_container_refs and query_filters.container_ref in candidate_container_refs
    if primary_container_refs and candidate_container_refs:
        return bool(primary_container_refs.intersection(candidate_container_refs))
    return True



def _candidate_freshness_timestamp(item: QueryResultItem) -> datetime | None:
    timestamps: list[datetime] = []
    if item.freshness_at is not None:
        timestamps.append(_normalize_timestamp(item.freshness_at))
    if item.occurred_at is not None:
        timestamps.append(_normalize_timestamp(item.occurred_at))
    if item.payload:
        payload_timestamp = _parse_iso_timestamp(item.payload.get("latest_occurred_at"))
        if payload_timestamp is not None:
            timestamps.append(payload_timestamp)
    for evidence in item.evidence:
        if evidence.occurred_at is not None:
            timestamps.append(_normalize_timestamp(evidence.occurred_at))
    if not timestamps:
        return None
    return max(timestamps)



def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)



def _parse_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_timestamp(parsed)

def _routing_support_grade(support_score: int) -> str:
    if support_score >= ROUTING_SUPPORT_THRESHOLD["strong"]:
        return "strong"
    if support_score >= ROUTING_SUPPORT_THRESHOLD["supported"]:
        return "supported"
    return "weak"


def _summarize_routing_layers(scored_candidates: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    all_layers = {
        "pattern_memory",
        "continuity_memory",
        "task_checkpoint",
        "lower_level_memory",
        "source_evidence",
        "decision",
        "investigation_outcome",
        "thread_summary",
        "discussion_summary",
    }
    lower_level_layers = {"lower_level_memory", "decision", "investigation_outcome"}
    for layer in sorted(all_layers):
        if layer == "lower_level_memory":
            layer_candidates = [candidate for candidate in scored_candidates if str(candidate["layer"]) in lower_level_layers]
        else:
            layer_candidates = [candidate for candidate in scored_candidates if candidate["layer"] == layer]
        if not layer_candidates:
            summary[layer] = {
                "candidate_count": 0,
                "supported_candidate_count": 0,
                "strong_candidate_count": 0,
            }
            continue
        best_candidate = max(
            layer_candidates,
            key=lambda candidate: (int(candidate["support_score"]), int(candidate["lexical_score"])),
        )
        summary[layer] = {
            "candidate_count": len(layer_candidates),
            "supported_candidate_count": sum(
                1 for candidate in layer_candidates if str(candidate["support_grade"]) in {"supported", "strong"}
            ),
            "strong_candidate_count": sum(1 for candidate in layer_candidates if candidate["support_grade"] == "strong"),
            "best_support_score": best_candidate["support_score"],
            "best_support_grade": best_candidate["support_grade"],
            "best_lexical_score": best_candidate["lexical_score"],
            "best_lexical_rank": best_candidate["lexical_rank"],
        }
    return summary

def _select_routing_focus(
    *,
    intent: str,
    preferred_layers: tuple[str, ...],
    layer_summary: dict[str, dict[str, object]],
) -> dict[str, object]:
    primary_layer = preferred_layers[0]
    primary_summary = layer_summary.get(primary_layer, {})
    selected_layer = primary_layer
    applied = False
    reason_code = "preferred_layer_supported"
    reason = "Preferred layer had enough candidate support to stay selected."

    fallback_candidates = [
        (layer, layer_summary.get(layer, {}))
        for layer in ROUTING_SAFE_FALLBACK_LAYERS[intent]
        if int(layer_summary.get(layer, {}).get("candidate_count", 0)) > 0
    ]
    best_fallback_layer = None
    best_fallback_summary = None
    if fallback_candidates:
        if intent == "broad_recall":
            structured_fallback = [
                (layer, summary)
                for layer, summary in fallback_candidates
                if layer in {"task_checkpoint", "thread_summary", "discussion_summary", "lower_level_memory"}
                and str(summary.get("best_support_grade", "weak")) in {"supported", "strong"}
            ]
            supported_lower_level = next(
                (
                    (layer, summary)
                    for layer, summary in fallback_candidates
                    if layer == "lower_level_memory"
                    and str(summary.get("best_support_grade", "weak")) in {"supported", "strong"}
                ),
                None,
            )
            if structured_fallback:
                best_fallback_layer, best_fallback_summary = max(
                    structured_fallback,
                    key=lambda item: (
                        int(item[1].get("best_support_score", 0)),
                        int(item[1].get("best_lexical_score", 0)),
                    ),
                )
            elif supported_lower_level is not None:
                best_fallback_layer, best_fallback_summary = supported_lower_level
            else:
                best_fallback_layer, best_fallback_summary = max(
                    fallback_candidates,
                    key=lambda item: (
                        int(item[1].get("best_support_score", 0)),
                        int(item[1].get("best_lexical_score", 0)),
                    ),
                )
        else:
            best_fallback_layer, best_fallback_summary = max(
                fallback_candidates,
                key=lambda item: (
                    int(item[1].get("best_support_score", 0)),
                    int(item[1].get("best_lexical_score", 0)),
                ),
            )
    primary_count = int(primary_summary.get("candidate_count", 0))
    primary_support = int(primary_summary.get("best_support_score", 0))
    primary_grade = str(primary_summary.get("best_support_grade", "weak"))

    if primary_count == 0 and best_fallback_layer is not None and best_fallback_summary is not None:
        selected_layer = best_fallback_layer
        applied = True
        reason_code = "preferred_layer_missing"
        reason = f"No {primary_layer} candidate was retrieved, so routing fell back to the sharpest safer layer."
    elif primary_layer in ROUTING_HIGHER_LEVEL_TYPES and best_fallback_layer is not None and best_fallback_summary is not None:
        fallback_support = int(best_fallback_summary.get("best_support_score", 0))
        fallback_grade = str(best_fallback_summary.get("best_support_grade", "weak"))
        if (
            intent in {"answer_continuity", "work_resumption"}
            and primary_grade == "weak"
            and fallback_grade == "strong"
            and fallback_support >= primary_support + ROUTING_FALLBACK_MARGIN
        ):
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "weak_higher_level_support"
            reason = "Higher-level memory was retrieved, but its candidate support was materially weaker than a strongly supported safer layer."
        elif intent not in {"answer_continuity", "work_resumption"} and primary_grade == "weak" and fallback_grade in {"supported", "strong"}:
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "weak_higher_level_support"
            reason = "Higher-level memory was retrieved, but its candidate support was weak, so routing chose a safer layer."
        elif fallback_support >= primary_support + ROUTING_FALLBACK_MARGIN:
            selected_layer = best_fallback_layer
            applied = True
            reason_code = "safer_layer_stronger"
            reason = "A safer layer had materially stronger candidate support than the higher-level preference."
    elif (
        primary_layer in {"source_evidence", "lower_level_memory"}
        and best_fallback_layer is not None
        and best_fallback_summary is not None
        and primary_grade == "weak"
        and str(best_fallback_summary.get("best_support_grade", "weak")) in {"supported", "strong"}
    ):
        selected_layer = best_fallback_layer
        applied = True
        reason_code = "primary_support_weak"
        reason = "The preferred sharp layer was weakly supported, so routing used the next safer retrieved layer."

    return {
        "applied": applied,
        "primary_layer": primary_layer,
        "selected_layer": selected_layer,
        "reason_code": reason_code,
        "reason": reason,
    }


def _routing_focus_adjustment(
    *,
    layer: str,
    selected_layer: str,
    primary_layer: str,
    fallback_applied: bool,
) -> int:
    adjustment = ROUTING_FOCUS_BOOST if layer == selected_layer else 0
    if fallback_applied and primary_layer in ROUTING_HIGHER_LEVEL_TYPES and layer == primary_layer and layer != selected_layer:
        adjustment -= ROUTING_DEMOTED_HIGHER_LEVEL_PENALTY
    return adjustment


def _routing_fallback_suffix(
    *,
    layer: str,
    selected_layer: str,
    primary_layer: str,
    applied: bool,
    reason_code: str,
    support_grade: str,
) -> str:
    if not applied:
        return ""
    if layer == selected_layer:
        return f" Candidate-aware fallback selected this layer because `{reason_code}`."
    if layer == primary_layer and layer in ROUTING_HIGHER_LEVEL_TYPES and layer != selected_layer:
        return " Candidate-aware fallback demoted this higher-level layer because retrieved support was weaker than safer evidence."
    if support_grade == "weak":
        return " Candidate-aware fallback kept weakly supported alternatives behind the selected layer."
    return ""


def _routing_packaging_suffix(packaging_reasons: list[str]) -> str:
    suffixes: list[str] = []
    if "sharp_checkpoint" in packaging_reasons:
        suffixes.append(" It preserved blocker, next-step, evidence, and freshness state more explicitly than weaker checkpoint packaging.")
    if "thin_checkpoint" in packaging_reasons:
        suffixes.append(" Thin checkpoint packaging weakened it against sharper resumed-work state.")
    if "stale_against_fresher_state" in packaging_reasons:
        suffixes.append(" Fresher explicit state outranked older carried-forward state.")
    if "fresh_explicit_state" in packaging_reasons:
        suffixes.append(" Fresh explicit state strengthened this candidate.")
    if "explicit_freshness_signal" in packaging_reasons and "fresh_explicit_state" not in packaging_reasons:
        suffixes.append(" Explicit freshness state improved its resumed-work usefulness.")
    return "".join(OrderedDict.fromkeys(suffixes))

def _candidate_matches_thread(item: QueryResultItem, query_filters: QueryFilters | None) -> bool:
    if query_filters is None or not query_filters.thread_ref:
        return False
    candidate_thread_refs = {thread_ref for thread_ref in _candidate_thread_refs(item) if thread_ref}
    return query_filters.thread_ref in candidate_thread_refs


def _candidate_matches_container(item: QueryResultItem, query_filters: QueryFilters | None) -> bool:
    if query_filters is None or not query_filters.container_ref:
        return False
    candidate_container_refs = {container_ref for container_ref in _candidate_container_refs(item) if container_ref}
    return query_filters.container_ref in candidate_container_refs


def _candidate_thread_refs(item: QueryResultItem) -> tuple[str, ...]:
    refs: list[str] = []
    if item.thread_ref:
        refs.append(item.thread_ref)
    refs.extend(evidence.thread_ref for evidence in item.evidence if evidence.thread_ref)
    return tuple(dict.fromkeys(refs))


def _candidate_container_refs(item: QueryResultItem) -> tuple[str, ...]:
    refs: list[str] = []
    if item.container_ref:
        refs.append(item.container_ref)
    refs.extend(evidence.container_ref for evidence in item.evidence if evidence.container_ref)
    return tuple(dict.fromkeys(refs))


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
        fragments.append(progress_updates[0])
    if blockers:
        fragments.append(blockers[0])
    if not fragments:
        next_steps = _signal_texts(selected_work_artifacts, "next_step")
        if next_steps:
            fragments.append(f"Pending: {next_steps[0]}")
    if not fragments and constraints:
        fragments.append(f"Constraint: {constraints[0]}")
    if fragments:
        return " ".join(fragments)
    return summary


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
    return blockers[0] if blockers else ""


def _default_task_checkpoint_next_step(selected_work_artifacts: list[dict[str, str]]) -> str:
    next_steps = _signal_texts(selected_work_artifacts, "next_step")
    return next_steps[0] if next_steps else ""


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
    if artifacts:
        return artifacts
    if _is_low_value_meta_artifact(source_item):
        return []
    signal_type = _classify_work_signal(source_item)
    if not signal_type:
        return []
    return [_build_work_artifact(source_item, signal_type=signal_type, text=text, signal_origin="fallback")]


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


