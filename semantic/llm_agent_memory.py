from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.contracts import ProcessResult
from core.models import MemorySubjectAnchor, SourceItem
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.base import SemanticPlugin
from semantic.common import SemanticExtraction, build_process_result
from semantic.prompt_variant_metrics import prompt_text_metrics
from semantic.prompt_provenance import build_prompt_provenance
from semantic.prompt_roles import get_prompt_role_contract


DEFAULT_PROMPT_VARIANT = "strict_typed_memory_v5_compact_examples"
WRITE_EXTRACTION_PROMPT_ROLE = get_prompt_role_contract("write_extraction")
PROMPT_ROLE = WRITE_EXTRACTION_PROMPT_ROLE.role
PROMPT_SCHEMA_ID = WRITE_EXTRACTION_PROMPT_ROLE.schema_id
PROMPT_SCHEMA_VERSION = WRITE_EXTRACTION_PROMPT_ROLE.schema_version
MODEL_ROLE = WRITE_EXTRACTION_PROMPT_ROLE.default_model_role
PROMPT_VARIANTS: dict[str, str] = {
    "strict_typed_memory_v4_evidence_guarded": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Your task is conservative typed-memory extraction with evidence grounding.
A decision exists only when the source explicitly records a concrete choice that has already been made.
An investigation_outcome exists only when the source explicitly records an established finding, root cause, conclusion, diagnostic outcome, or evidence-backed analytical verdict.
Also extract optional internal-only semantic signals when the source explicitly states them: low-value meta chatter, constraints, blocker state, progress state, next step, and key findings. Also extract optional subject_hints when the source explicitly names a durable workstream, component, or surface.
If the source only states a need, a symptom, a proposal, a preference, a recommendation, a status update, or something to watch, candidate_type must be null.
An interest exists when the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject of interest. Do NOT classify as interest: assistant responses summarizing or recommending things, follow-up questions without a named subject ("is there something lite?"), backward-looking recall ("didn't we discuss X?"), or restatements of prior content. Examples: "Chroma sounds interesting, I should check it some time" -> interest, interest_text about Chroma. "pgvector may be worth looking into" -> interest, interest_text about pgvector. "We talked about Chroma" -> null (no future-oriented interest expressed).

Evidence rule:
- candidate_type may be non-null only if decision_evidence_text or investigation_evidence_text quotes an exact explicit statement from the source that proves the type.
- Valid decision cues are phrasing like: "Decision:", "we decided", "we chose", "chosen approach", or "we will use".
- Valid investigation cues include explicit finding or conclusion phrasing such as: "Root cause:", "Investigation found", "Investigation concluded", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Here's the verdict:", "Conclusion:", or "The conclusion is".
- Explicit analytical verdicts are allowed when they clearly state a resolved conclusion from the source, for example which repo was more significant and why.
- Statements such as "we need", "we should watch", "was detected", "leaned toward", or "prefer" are not valid evidence and must produce candidate_type null.

Source-type guidance:
- For `decision_note`, require explicit committed-choice wording rather than inferred intent.
- For `investigation_summary`, `incident_note`, `tool_summary`, `assistant_artifact`, and `assistant_output`, allow investigation_outcome only when the established finding or analytical verdict is explicit.
- For `chat_message`, `meeting_summary`, `status_update`, and `notification`, default to null unless the text itself contains one of the valid explicit cues above.

When candidate_type is `decision`, fill only decision_text and decision_evidence_text.
When candidate_type is `investigation_outcome`, fill only investigation_text and investigation_evidence_text.
For the optional internal fields, only populate them when the source explicitly states that exact state. subject_hints must be a list of objects with kind and value, using only the kinds workstream, component, or surface. Return an empty list when no explicit anchors are present, and do not invent anchors from weak implication or broad topic guesses.
When the source states a definitive operational constraint — the speaker clearly commits to a requirement, prohibition, or hard rule — also populate constraint_candidates as a list of objects with primary_scope_anchor, target_anchor, action_class, polarity, confidence, and constraint_text. Hedged, tentative, or exploratory language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave constraint_text null and constraint_candidates empty. Use only action_class values use_surface, use_source, or perform_step; use only polarity values prohibit, prefer, or require; and emit an empty list when any required field cannot be normalized safely.
Internal-field rules:
- Populate key_finding_text for explicit verdicts, conclusions, findings, and root causes. For an explicit analytical verdict, key_finding_text should usually restate the resolved conclusion in one sentence.
- If is_low_value_meta is true for pure orchestration chatter (no-op completions, greetings, heartbeats, capability boilerplate), constraint_text, next_step_text, blocker_text, progress_text, and key_finding_text must all be null.
- next_step_text must name an actual future action. Phrases like "no message needed" or other absence-of-action phrasing are not next steps.
- progress_text must name substantive completed or partial work that would help future resumption, not boilerplate completion language.
- key_finding_text should be null for status updates, monitoring notes, or short-lived observations that do not state a durable conclusion.
- Prefer null for optional fields over weak, speculative, or low-value paraphrases.
Examples:
- Input: "Verdict: transaction-transformer had the most significant recent ledger changes. It touched more tickets than ledger-query." -> candidate_type investigation_outcome, investigation_text set, key_finding_text set, is_low_value_meta false.
- Input: "Task complete. No Slack message needed. Nothing new to report." -> candidate_type null, is_low_value_meta true, all optional signal text fields null.
- Input: "Constraint: do not open a browser. Next step: compare ledger-query vs transaction-transformer locally." -> candidate_type null, constraint_text set, next_step_text set, is_low_value_meta false.
- Input: "Catalog sync delay increased after the provider restart, and we should watch it closely tonight." -> candidate_type null; key_finding_text should usually be null because this is a status/monitoring note, not a durable conclusion.
Set is_low_value_meta true only for clearly non-durable orchestration chatter: no-op completion/status messages, greeting/pleasantry chatter ("hello", "thanks", "good morning"), heartbeat/monitoring noise ("still alive", "healthcheck"), and generic capability boilerplate ("I can help with..."). Otherwise false.
If no explicit proof phrase exists, candidate_type must be null.""",
    "strict_typed_memory_v5_compact_examples": """You extract reusable typed memory and explicit semantic signals from one technical source item. Return exactly one JSON object and no extra prose.

Only create typed memory when the source gives explicit proof.
- decision: an explicit concrete choice already made.
- investigation_outcome: an explicit established finding, root cause, conclusion, diagnostic outcome, or analytical verdict.
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject of interest. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.
- a non-null type requires an exact quoted proof phrase in the matching evidence field (except interest, which needs only a non-empty interest_text).
- fill only the decision fields for decision and only the investigation fields for investigation_outcome.

Populate optional signals only when they are explicitly stated: is_low_value_meta, constraint_text, next_step_text, blocker_text, progress_text, key_finding_text, subject_hints, constraint_candidates. constraint_text and constraint_candidates require a definitive commitment — the speaker states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave constraint_text null and constraint_candidates []. Never infer anchors or normalized constraints. subject_hints may use only workstream|component|surface. constraint_candidates may use only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] when anchors or constraints are not safely explicit.

If is_low_value_meta is true, all optional text fields must be null and list fields should be []. Prefer null or [] over weak paraphrases. next_step_text must be a future action. progress_text must be substantive resumption state. key_finding_text is only for durable explicit conclusions, not monitoring chatter. Set is_low_value_meta true for: no-op completions, greeting/pleasantry chatter, heartbeat/monitoring noise, generic capability boilerplate.

Examples:
- "Decision: use item event time for reservation ordering." -> decision.
- "Investigation found that arrival-time ordering missed hold updates during sync delays." -> investigation_outcome.
- "We need to decide whether to change ordering." -> null.
- "Task complete. No message needed. Nothing new to report." -> candidate_type null, is_low_value_meta true.
- "Constraint: do not open a browser. Next step: compare the local repos." -> candidate_type null, constraint_text and next_step_text populated.""",
    "strict_typed_memory_v7_claude_structured": """You extract reusable typed memory and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

## Typed Memory Classification

Only promote to typed memory when the source contains an explicit proof phrase:
- decision: requires committed-choice language ("Decision:", "we decided", "we chose", "chosen approach", "we will use").
- investigation_outcome: requires resolved-finding language ("Root cause:", "Investigation found", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Conclusion:", "Investigation concluded", "The conclusion is").
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject. No proof phrase needed. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.
- A non-null type requires the exact proof phrase quoted in the matching evidence field.
- Fill only decision fields for decision, only investigation fields for investigation_outcome.

REJECT as null: needs, proposals, preferences, recommendations, symptoms, risks, monitoring notes, status updates, and unresolved discussion.

## Work-State Signals

Populate only when the source explicitly states them:
- next_step_text: a concrete future action. Clarifying questions are NOT next steps.
- blocker_text: active impediment or failed attempt.
- progress_text: substantive completed or partial work for later resumption. Not boilerplate completion language.
- key_finding_text: durable conclusion or verdict. Not monitoring chatter.
- constraint_text: a definitive operational constraint — the speaker commits to a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint.
- is_low_value_meta: true only for non-durable orchestration chatter: no-op completion/status messages, greeting/pleasantry chatter ("hello", "thanks", "good morning"), heartbeat/monitoring noise ("still alive", "healthcheck"), and generic capability boilerplate ("I can help with...", "capabilities:"). When true, all signal fields must be null/[].
- subject_hints: explicit workstream|component|surface only. Return [] if not safely explicit.

Prefer null or [] over weak, speculative, or inferred values.

## Examples
- "Verdict: transaction-transformer had the most significant recent ledger changes." -> investigation_outcome, key_finding_text set.
- "Task complete. No message needed." -> null, is_low_value_meta true, all signals null.
- "Hello, good morning!" -> null, is_low_value_meta true, all signals null.
- "I can lower concurrency or bump memory, but I need to confirm which worker first." -> null, all signals null (clarifying question, not actionable state).""",
    "strict_typed_memory_v7_claude_structured_v2": """You extract reusable typed memory and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

## Typed Memory Classification

Only promote to typed memory when the source contains an explicit proof phrase:
- decision: requires committed-choice language ("Decision:", "we decided", "we chose", "chosen approach", "we will use").
- investigation_outcome: requires resolved-finding language ("Root cause:", "Investigation found", "Analysis found", "Findings:", "Outcome:", "We found that", "Verdict:", "Conclusion:", "Investigation concluded", "The conclusion is").
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject. No proof phrase needed. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.
- A non-null type requires the exact proof phrase quoted in the matching evidence field.
- Fill only decision fields for decision, only investigation fields for investigation_outcome.

REJECT as null: needs, proposals, preferences, recommendations, symptoms, risks, monitoring notes, status updates, and unresolved discussion.

## Work-State Signals

Populate only when the source explicitly states them:
- next_step_text: a concrete future action. Clarifying questions are NOT next steps.
- blocker_text: active impediment or failed attempt.
- progress_text: substantive completed or partial work for later resumption. Not boilerplate completion language.
- key_finding_text: durable conclusion or verdict. Not monitoring chatter.
- constraint_text: a definitive operational constraint — the speaker commits to a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint.
- is_low_value_meta: true only for non-durable orchestration chatter: no-op completion/status messages, greeting/pleasantry chatter ("hello", "thanks", "good morning"), heartbeat/monitoring noise ("still alive", "healthcheck"), and generic capability boilerplate ("I can help with...", "capabilities:"). When true, all signal fields must be null/[].
- subject_hints: extract named workstream|component|surface when the source names it as the subject of work. A name is explicit when: it appears as a noun modifier ("recent importer work" → component=importer), the source uses "work on X" / "working on X" phrasing, it identifies a location or locus in a prepositional phrase ("bug in the reservation service" → component=reservation service), or it appears as a possessive subject ("catalog sync's delay" → component=catalog sync). Return [] for negated or peripheral references ("nothing new on the X side", "not sure about X") and for casual mentions with no work content. Worked example: "recent importer work has been slow" → [{kind: "component", value: "importer"}].

Prefer null or [] over weak, speculative, or inferred values.

## Examples
- "Verdict: transaction-transformer had the most significant recent changes." -> investigation_outcome, key_finding_text set.
- "Task complete. No message needed." -> null, is_low_value_meta true, all signals null.
- "Hello, good morning!" -> null, is_low_value_meta true, all signals null.
- "I can lower concurrency or bump memory, but I need to confirm which worker first." -> null, all signals null (clarifying question, not actionable state).""",
    "strict_typed_memory_v7_claude_minimal": """You extract typed memory and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

Typed memory requires explicit proof phrases quoted in the evidence field:
- decision: "Decision:", "we decided", "we chose", "chosen approach", "we will use".
- investigation_outcome: "Root cause:", "Investigation found", "Analysis found", "We found that", "Verdict:", "Conclusion:", "Investigation concluded".
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to action. Fill interest_text. No proof phrase needed. Not for assistant responses, backward-looking recall, or follow-ups without a named subject.
- otherwise null.

Fill only decision fields for decision, only investigation fields for investigation_outcome. Never promote needs, proposals, preferences, symptoms, or monitoring notes.

Optional signals (only when explicitly stated): is_low_value_meta (true for no-op completions, greetings, heartbeats, capability boilerplate), constraint_text (definitive commitment only — hedged or tentative language is not a constraint), next_step_text (concrete action, not clarifying question), blocker_text, progress_text (substantive work, not boilerplate), key_finding_text (durable conclusion only), subject_hints (workstream|component|surface, else []).

If is_low_value_meta is true, all signals must be null/[]. Prefer null over weak inference.""",
    "strict_typed_memory_v7_claude_clean": """You extract reusable knowledge and work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

## Knowledge Classification

Only create a typed record when the source contains an explicit proof phrase:
- decision: the source records a concrete choice already made, using language like "Decision:", "we decided", "we chose", "chosen approach", or "we will use".
- investigation_outcome: the source records a resolved finding, root cause, or conclusion, using language like "Root cause:", "Investigation found", "Analysis found", "We found that", "Verdict:", "Conclusion:", or "Investigation concluded".
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to a concrete action or timeline. Fill interest_text with the subject. No proof phrase needed. Do NOT classify as interest: assistant responses, follow-up questions without a named subject, backward-looking recall, or restatements of prior content.
- otherwise candidate_type = null.
- A non-null type requires the exact proof phrase quoted in the matching evidence field.
- Fill only decision fields for a decision, only investigation fields for a finding.

Return null for: stated needs, open proposals, preferences, recommendations, symptoms, risks, monitoring notes, status updates, and unresolved discussion.

## Work-State Signals

Populate only when the source explicitly states them:
- next_step_text: a concrete future action the author commits to. A question asking for clarification is NOT a next step.
- blocker_text: an active impediment, failed attempt, or stop condition.
- progress_text: substantive completed or partial work that helps someone resume later. Not boilerplate like "task complete."
- key_finding_text: a durable conclusion or resolved sub-finding. Not a monitoring note or short-lived observation.
- constraint_text: a stated operational constraint.
- is_low_value_meta: true only for content with no durable information — no-op completions ("No message needed"), greetings ("hello", "good morning"), heartbeat/monitoring noise ("still alive", "healthcheck"), and generic capability boilerplate ("I can help with..."). When true, all signal fields must be null/[].
- subject_hints: list of topic tags with kind (workstream, component, or surface) and value. Return [] unless the source explicitly names one.

constraint_text requires a definitive commitment — the speaker clearly states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null.

Prefer null or [] over guessed or weakly inferred values.

## Examples
- "Verdict: transaction-transformer had the most significant recent ledger changes." -> investigation_outcome with finding text and evidence.
- "Task complete. No message needed." -> null, is_low_value_meta true.
- "I can lower concurrency or bump memory, but I need to confirm which worker first." -> null, all signals null.""",
    "strict_typed_memory_v6_compact_work_state": """You extract reusable typed memory and explicit work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

Typed memory stays conservative:
- decision only for an explicit concrete choice already made.
- investigation_outcome only for an explicit established finding, root cause, conclusion, diagnostic outcome, or analytical verdict.
- interest when the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to action. Fill interest_text with the subject. Not for assistant responses, backward-looking recall, or follow-ups without a named subject.
- otherwise candidate_type = null.
- a non-null type requires an exact quoted proof phrase in the matching evidence field.
- fill only the decision fields for decision and only the investigation fields for investigation_outcome.

Work-state signals may come from natural operational prose, not only labeled markers. Populate optional signals only when the source explicitly states them: is_low_value_meta, constraint_text, next_step_text, blocker_text, progress_text, key_finding_text, subject_hints, constraint_candidates. constraint_text and constraint_candidates require a definitive commitment — the speaker states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null/[].

Signal rules:
- next_step_text: a concrete future action or restart step the source already states.
- blocker_text: the active impediment, failed attempt, or stop condition the source already states.
- progress_text: substantive completed or partial work that improves later resumption.
- key_finding_text: a durable operational takeaway or resolved sub-finding, but not a typed finding unless the source gives explicit proof.
- use the exact source words when that is the cleanest way to capture the signal.

Never infer anchors or normalized constraints. subject_hints may use only workstream|component|surface. constraint_candidates may use only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] when anchors or constraints are not safely explicit.

If is_low_value_meta is true, all optional text fields must be null and list fields should be []. Prefer null or [] over weak paraphrases.""",
    "strict_typed_memory_v6_compact_work_state_negatives": """You extract reusable typed memory and explicit work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

Typed memory stays conservative:
- decision only for an explicit concrete choice already made.
- investigation_outcome only for an explicit established finding, root cause, conclusion, diagnostic outcome, or analytical verdict.
- interest when the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to action. Fill interest_text with the subject. Not for assistant responses, backward-looking recall, or follow-ups without a named subject.
- otherwise candidate_type = null.
- a non-null type requires an exact quoted proof phrase in the matching evidence field.
- fill only the decision fields for decision and only the investigation fields for investigation_outcome.

Work-state signals may come from natural operational prose, not only labeled markers. Populate optional signals only when the source explicitly states them: is_low_value_meta, constraint_text, next_step_text, blocker_text, progress_text, key_finding_text, subject_hints, constraint_candidates. constraint_text and constraint_candidates require a definitive commitment — the speaker states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null/[].

Signal rules:
- next_step_text: a concrete future action or restart step the source already states.
- blocker_text: the active impediment, failed attempt, or stop condition the source already states.
- progress_text: substantive completed or partial work that improves later resumption.
- key_finding_text: a durable operational takeaway or resolved sub-finding that helps later recall, but not a typed finding unless the source gives explicit proof.
- use the exact source words when that is the cleanest way to capture the signal.

Negative rules:
- clarifying questions are not durable signals.
- brainstorming, option lists, and hedged recommendations are not durable signals.
- monitor/watch language without a stable current state is not a blocker or key finding.
- generic advice without committed state is not progress, blocker, next step, or key finding.
- if the turn mainly asks for more context or lists possibilities, prefer null or [] for every optional field.

Never infer anchors or normalized constraints. subject_hints may use only workstream|component|surface. constraint_candidates may use only use_surface|use_source|perform_step with prohibit|prefer|require. Return [] when anchors or constraints are not safely explicit.

If is_low_value_meta is true, all optional text fields must be null and list fields should be []. Prefer null or [] over weak paraphrases.""",
    "strict_typed_memory_v6_work_state_examples": """You extract reusable typed memory and explicit work-state signals from one technical source item. Return exactly one JSON object and no extra prose.

Only create typed memory when the source gives explicit proof.
- decision: an explicit concrete choice already made.
- investigation_outcome: an explicit established finding, root cause, conclusion, diagnostic outcome, or analytical verdict.
- interest: the user (not the assistant) identifies a specific named subject as worth future attention but does not commit to action. Fill interest_text with the subject. Not for assistant responses, backward-looking recall, or follow-ups without a named subject.
- otherwise candidate_type = null.
- a non-null type requires an exact quoted proof phrase in the matching evidence field (except interest, which needs only a non-empty interest_text).
- fill only the decision fields for decision and only the investigation fields for investigation_outcome.

Optional signals may come from natural operational prose. Populate is_low_value_meta, constraint_text, next_step_text, blocker_text, progress_text, key_finding_text, subject_hints, and constraint_candidates only when the source explicitly states them. constraint_text and constraint_candidates require a definitive commitment — the speaker states a requirement, prohibition, or hard rule. Hedged or tentative language ("I think", "maybe", "probably", "leaning towards", "not sure") is not a constraint; leave null/[].
- next_step_text: a concrete future action or restart step.
- blocker_text: the active impediment or failed attempt.
- progress_text: substantive completed or partial work.
- key_finding_text: a durable operational takeaway that helps later recall.

Negative rules:
- clarifying questions, brainstorming, hedged recommendations, monitor/watch notes, and generic advice without committed state should keep optional signals null or [].
- if is_low_value_meta is true, all optional text fields must be null and list fields should be [].

Examples:
- "The token refresh worked and the sync got through batch 417, but the retry window is exhausted now. Wait 15 minutes and resume from batch 418." -> candidate_type null, progress_text about reaching batch 417, blocker_text about the retry window, next_step_text about waiting 15 minutes and resuming from batch 418.
- "I can lower concurrency or bump memory, but I need to confirm which worker you mean first." -> candidate_type null, all optional signals null.
- "The admin toggle wiring is ready, but branch kiosk fallback coverage is still missing before review can pass." -> candidate_type null, progress_text about the admin toggle wiring, blocker_text about the missing branch kiosk fallback coverage.""",
}

SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "candidate_type": "decision, investigation_outcome, interest, or null",
        "decision_text": "string or null",
        "decision_evidence_text": "string or null",
        "investigation_text": "string or null",
        "investigation_evidence_text": "string or null",
        "rationale_text": "string or null",
        "interest_text": "string or null",
        "is_low_value_meta": "boolean",
        "constraint_text": "string or null",
        "next_step_text": "string or null",
        "blocker_text": "string or null",
        "progress_text": "string or null",
        "key_finding_text": "string or null",
        "subject_hints": "array of {kind: workstream|component|surface, value: string} or null",
    },
    indent=2,
)


@dataclass(frozen=True)
class LLMAnalysisRequest:
    prompt_role: str
    prompt_variant: str
    prompt_schema_id: str
    prompt_schema_version: str
    model_role: str | None
    system_prompt: str
    user_prompt: str
    schema_description: str


@dataclass(frozen=True)
class LLMSemanticTrace:
    request: LLMAnalysisRequest
    response: LLMJsonResponse
    extraction: SemanticExtraction
    process_result: ProcessResult


class LLMAgentMemoryPlugin(SemanticPlugin):
    name = "llm_agent_memory"

    def __init__(self, provider: LLMProvider, *, prompt_variant: str = DEFAULT_PROMPT_VARIANT) -> None:
        self._provider = provider
        self._prompt_variant = _resolve_prompt_variant(prompt_variant)

    @property
    def prompt_variant(self) -> str:
        return self._prompt_variant

    def with_prompt_variant(self, prompt_variant: str) -> "LLMAgentMemoryPlugin":
        return LLMAgentMemoryPlugin(provider=self._provider, prompt_variant=prompt_variant)

    def analyze_item(self, source_item: SourceItem) -> LLMSemanticTrace:
        request = build_analysis_request(source_item, prompt_variant=self._prompt_variant)
        response = self._provider.generate_json(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            schema_description=request.schema_description,
        )
        extraction = _normalize_extraction(response.parsed_json)
        semantic_metadata = build_prompt_provenance(
            semantic_plugin=self.name,
            contract=WRITE_EXTRACTION_PROMPT_ROLE,
            prompt_variant=request.prompt_variant,
            model_role=request.model_role,
            llm_metadata=response.metadata,
        )
        process_result = build_process_result(
            source_item,
            extraction,
            schema_prefix="llm",
            semantic_metadata=semantic_metadata,
        )
        return LLMSemanticTrace(
            request=request,
            response=response,
            extraction=extraction,
            process_result=process_result,
        )

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        return self.analyze_item(source_item).process_result


def build_analysis_request(source_item: SourceItem, *, prompt_variant: str = DEFAULT_PROMPT_VARIANT) -> LLMAnalysisRequest:
    resolved_prompt_variant = _resolve_prompt_variant(prompt_variant)
    metadata_text = json.dumps(source_item.metadata or {}, sort_keys=True)
    return LLMAnalysisRequest(
        prompt_role=PROMPT_ROLE,
        prompt_variant=resolved_prompt_variant,
        prompt_schema_id=PROMPT_SCHEMA_ID,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        model_role=MODEL_ROLE,
        system_prompt=PROMPT_VARIANTS[resolved_prompt_variant],
        user_prompt=(
            f"Source type: {source_item.source_type}\n"
            f"Source id: {source_item.source_id}\n"
            f"Content type: {source_item.content_type}\n"
            f"Artifact kind: {source_item.artifact_kind or 'null'}\n"
            f"Role: {source_item.role or 'null'}\n"
            f"Metadata: {metadata_text}\n"
            f"Content:\n{source_item.content}"
        ),
        schema_description=SCHEMA_DESCRIPTION,
    )


def list_prompt_variants() -> list[str]:
    return list(PROMPT_VARIANTS.keys())


def get_prompt_variant_text(prompt_variant: str) -> str:
    return PROMPT_VARIANTS[_resolve_prompt_variant(prompt_variant)]


def describe_prompt_variants() -> dict[str, dict[str, int]]:
    return {name: prompt_text_metrics(text) for name, text in PROMPT_VARIANTS.items()}


def _resolve_prompt_variant(prompt_variant: str) -> str:
    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(f"Unsupported prompt variant: {prompt_variant}")
    return prompt_variant


def resolve_prompt_variant_for_role(
    role: str,
    *,
    prompt_variants: dict[str, str] | None,
    prompt_variant: str | None,
    default: str = DEFAULT_PROMPT_VARIANT,
) -> str:
    if prompt_variants and role in prompt_variants:
        return prompt_variants[role]
    if prompt_variant:
        return prompt_variant
    return default


def _normalize_extraction(payload: dict[str, Any]) -> SemanticExtraction:
    summary = _normalize_required_string(payload.get("summary"), field_name="summary")
    candidate_type = _normalize_optional_string(payload.get("candidate_type"), field_name="candidate_type")
    decision_text = _normalize_optional_string(payload.get("decision_text"), field_name="decision_text")
    decision_evidence_text = _normalize_optional_string(payload.get("decision_evidence_text"), field_name="decision_evidence_text")
    investigation_text = _normalize_optional_string(payload.get("investigation_text"), field_name="investigation_text")
    investigation_evidence_text = _normalize_optional_string(payload.get("investigation_evidence_text"), field_name="investigation_evidence_text")
    rationale_text = _normalize_optional_string(payload.get("rationale_text"), field_name="rationale_text")
    interest_text = _normalize_optional_string(payload.get("interest_text"), field_name="interest_text")
    is_low_value_meta = _normalize_optional_bool(payload.get("is_low_value_meta"), field_name="is_low_value_meta")
    constraint_text = _normalize_optional_string(payload.get("constraint_text"), field_name="constraint_text")
    next_step_text = _normalize_optional_string(payload.get("next_step_text"), field_name="next_step_text")
    blocker_text = _normalize_optional_string(payload.get("blocker_text"), field_name="blocker_text")
    progress_text = _normalize_optional_string(payload.get("progress_text"), field_name="progress_text")
    key_finding_text = _normalize_optional_string(payload.get("key_finding_text"), field_name="key_finding_text")
    subject_hints = _normalize_subject_hints(payload.get("subject_hints"))

    if candidate_type is not None:
        candidate_type = candidate_type.lower()
        if candidate_type not in {"decision", "investigation_outcome", "interest"}:
            candidate_type = None

    return SemanticExtraction(
        summary=summary,
        candidate_type=candidate_type,
        decision_text=decision_text,
        decision_evidence_text=decision_evidence_text,
        investigation_text=investigation_text,
        investigation_evidence_text=investigation_evidence_text,
        rationale_text=rationale_text,
        interest_text=interest_text,
        is_low_value_meta=bool(is_low_value_meta),
        constraint_text=constraint_text,
        next_step_text=next_step_text,
        blocker_text=blocker_text,
        progress_text=progress_text,
        key_finding_text=key_finding_text,
        subject_hints=subject_hints,
    )


def _normalize_subject_anchor(value: Any) -> MemorySubjectAnchor | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "").strip().lower()
    anchor_value = str(value.get("value") or "").strip()
    if kind not in {"workstream", "component", "surface"}:
        return None
    if not anchor_value or anchor_value.lower() == "unknown":
        return None
    return MemorySubjectAnchor(kind=kind, value=anchor_value)


def _normalize_subject_hints(value: Any) -> tuple[MemorySubjectAnchor, ...]:
    if value is None or value == "unknown":
        return ()
    if not isinstance(value, list):
        return ()
    normalized: list[MemorySubjectAnchor] = []
    for item in value:
        anchor = _normalize_subject_anchor(item)
        if anchor is None:
            continue
        normalized.append(anchor)
    return tuple(normalized)


def _normalize_required_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    normalized = value.strip()
    return normalized or None


def _normalize_optional_bool(value: Any, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean or null")
    return value
