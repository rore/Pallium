from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.contracts import ProcessResult
from core.models import SourceItem
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.base import SemanticPlugin
from semantic.common import SemanticExtraction, build_process_result


DEFAULT_PROMPT_VARIANT = "baseline"
PROMPT_SCHEMA_ID = "decision_extraction"
PROMPT_SCHEMA_VERSION = "v2"
PROMPT_VARIANTS: dict[str, str] = {
    "baseline": """You extract reusable memory from technical discussions.
Return exactly one JSON object and no extra prose.""",
    "strict_decision_v1": """You extract reusable memory from technical discussions.
Return exactly one JSON object and no extra prose.

Classify candidate_type as "decision" only when the text explicitly records a committed choice that has already been made.
Do not mark a decision for hypotheses, preferences, suggestions, observations, diagnoses, risks, next steps, or statements that something is needed.
If the text discusses options or leans toward an approach without an explicit committed choice, candidate_type must be null.
If the text reports an investigation finding or root cause without an explicit committed choice, candidate_type must be null.
If the text says the team agreed that something is needed, but did not choose a concrete action or approach, candidate_type must be null.
When candidate_type is "decision", decision_text must restate the committed choice only, not an inferred fix or recommendation.
When candidate_type is "decision", decision_evidence_text must be an exact quote or close paraphrase of the source phrase that proves the decision was explicitly made. If you cannot point to explicit decision evidence, candidate_type must be null.""",
    "strict_decision_v2_source_aware": """You extract reusable memory from technical discussions.
Return exactly one JSON object and no extra prose.

Your task is conservative decision extraction.
A decision exists only when the source explicitly states that a concrete choice has already been made.
Strong positive decision signals include phrases like: "Decision:", "we decided", "we chose", "chosen approach", or "we will use".
If those signals are absent, candidate_type should usually be null.

Source-type guidance:
- For `investigation_summary`, `incident_note`, `status_update`, and `research_note`, default to candidate_type null unless the text explicitly contains a clear decision signal.
- For `chat_thread` and `meeting_summary`, do not mark a decision when the text only shows discussion, preference, leaning, proposal, agreement that something is needed, or identification of a problem.
- For `decision_note`, still require explicit committed-choice wording rather than inferred intent.

Do not convert findings, recommendations, proposed fixes, root causes, next steps, or identified blockers into decisions.
When candidate_type is "decision", decision_text must restate the chosen action only, and decision_evidence_text must quote the exact phrase that proves the decision was made. If no explicit proof phrase exists, candidate_type must be null.""",
    "strict_decision_v3_checklist": """You extract reusable memory from technical discussions.
Return exactly one JSON object and no extra prose.

Before choosing candidate_type, apply this checklist internally:
1. Does the source explicitly say a choice was made already?
2. Is the choice concrete rather than a preference, suggestion, observation, or need?
3. Can you quote the exact decision evidence from the source?
Only if all three answers are yes may candidate_type be "decision".

Use candidate_type null for:
- option comparisons
- tentative language such as "may", "might", "could", "should", "prefer", or "seems"
- investigation findings or root causes
- statements that the team needs something
- identified blockers or action items without a chosen solution
- summary statements that imply a conclusion but do not explicitly record a committed choice

When candidate_type is "decision":
- decision_text must be a concise restatement of the committed choice
- decision_evidence_text must be a verbatim quote or extremely close extract of the decision phrase from the source
- rationale_text should be null unless the source explicitly states the reason
If you are not certain the source contains an explicit committed choice, return candidate_type null.""",
}

SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "candidate_type": "decision or null",
        "decision_text": "string or null",
        "decision_evidence_text": "string or null",
        "rationale_text": "string or null",
    },
    indent=2,
)


@dataclass(frozen=True)
class LLMAnalysisRequest:
    prompt_variant: str
    prompt_schema_id: str
    prompt_schema_version: str
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
        semantic_metadata = {
            "semantic_plugin": self.name,
            "prompt_variant": request.prompt_variant,
            "prompt_schema_id": request.prompt_schema_id,
            "prompt_schema_version": request.prompt_schema_version,
        }
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
        prompt_variant=resolved_prompt_variant,
        prompt_schema_id=PROMPT_SCHEMA_ID,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        system_prompt=PROMPT_VARIANTS[resolved_prompt_variant],
        user_prompt=(
            f"Source type: {source_item.source_type}\n"
            f"Source id: {source_item.source_id}\n"
            f"Content type: {source_item.content_type}\n"
            f"Metadata: {metadata_text}\n"
            f"Content:\n{source_item.content}"
        ),
        schema_description=SCHEMA_DESCRIPTION,
    )



def list_prompt_variants() -> list[str]:
    return list(PROMPT_VARIANTS.keys())



def _resolve_prompt_variant(prompt_variant: str) -> str:
    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(f"Unsupported prompt variant: {prompt_variant}")
    return prompt_variant



def _normalize_extraction(payload: dict[str, Any]) -> SemanticExtraction:
    summary = _normalize_required_string(payload.get("summary"), field_name="summary")
    candidate_type = _normalize_optional_string(payload.get("candidate_type"), field_name="candidate_type")
    decision_text = _normalize_optional_string(payload.get("decision_text"), field_name="decision_text")
    decision_evidence_text = _normalize_optional_string(payload.get("decision_evidence_text"), field_name="decision_evidence_text")
    rationale_text = _normalize_optional_string(payload.get("rationale_text"), field_name="rationale_text")

    if candidate_type is not None:
        candidate_type = candidate_type.lower()
        if candidate_type != "decision":
            candidate_type = None

    return SemanticExtraction(
        summary=summary,
        candidate_type=candidate_type,
        decision_text=decision_text,
        decision_evidence_text=decision_evidence_text,
        rationale_text=rationale_text,
    )



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
