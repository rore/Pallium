from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.contracts import ProcessResult
from core.models import SourceItem
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.base import SemanticPlugin
from semantic.common import SemanticExtraction, build_process_result


DEFAULT_PROMPT_VARIANT = "strict_typed_memory_v4_evidence_guarded"
PROMPT_SCHEMA_ID = "typed_memory_extraction"
PROMPT_SCHEMA_VERSION = "v4"
PROMPT_VARIANTS: dict[str, str] = {
    "baseline": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Use candidate_type as one of: decision, investigation_outcome, or null.""",
    "strict_decision_v1": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Classify candidate_type as \"decision\" only when the source explicitly records a committed choice that has already been made.
Classify candidate_type as \"investigation_outcome\" only when the source explicitly records an established finding, root cause, conclusion, or diagnostic outcome.
Use null for hypotheses, preferences, proposals, observations, symptoms, risks, next steps, recommendations, or statements that something is needed.
If the text discusses options without an explicit choice, candidate_type must be null.
If the text reports symptoms without an explicit finding or conclusion, candidate_type must be null.
When candidate_type is \"decision\", decision_text and decision_evidence_text must be populated and the investigation fields must be null.
When candidate_type is \"investigation_outcome\", investigation_text and investigation_evidence_text must be populated and the decision fields must be null.
If you cannot quote explicit evidence for the chosen candidate_type, candidate_type must be null.""",
    "strict_decision_v2_source_aware": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Your task is conservative typed-memory extraction.
A decision exists only when the source explicitly states that a concrete choice has already been made.
An investigation_outcome exists only when the source explicitly states an established finding, root cause, conclusion, or diagnostic outcome.
If those signals are absent, candidate_type should usually be null.

Source-type guidance:
- For `decision_note`, require explicit committed-choice wording rather than inferred intent.
- For `investigation_summary`, `incident_note`, `tool_summary`, and `assistant_artifact`, allow investigation_outcome only when the finding is explicit and already established.
- For `chat_message`, `meeting_summary`, `status_update`, and `notification`, default to null unless the text explicitly records a committed choice or an established finding.

Do not convert findings into decisions.
Do not convert recommendations, proposals, preferred options, symptoms, action items, or agreed needs into typed memory.
When candidate_type is `decision`, decision_text must restate the chosen action only and decision_evidence_text must quote the phrase proving the choice was made.
When candidate_type is `investigation_outcome`, investigation_text must restate the established finding only and investigation_evidence_text must quote the phrase proving the finding or conclusion.
If no explicit proof phrase exists, candidate_type must be null.""",
    "strict_decision_v3_checklist": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Before setting candidate_type, apply this checklist internally:
1. Does the source explicitly record a committed choice or an established finding?
2. Is the statement concrete rather than a proposal, preference, symptom, observation, or need?
3. Can you quote the exact evidence phrase from the source?
Only if all three answers are yes may candidate_type be non-null.

Use candidate_type null for:
- option comparisons
- tentative language such as may, might, could, should, prefer, or seems
- problem statements without a conclusion
- recommendations or next steps
- agreement that something is needed
- summaries that imply a conclusion but do not explicitly record one

When candidate_type is `decision`, fill only the decision fields.
When candidate_type is `investigation_outcome`, fill only the investigation fields.
If you are not certain the source contains explicit evidence, return candidate_type null.""",
    "strict_typed_memory_v4_evidence_guarded": """You extract reusable memory from technical communication. Return exactly one JSON object and no extra prose.

Your task is conservative typed-memory extraction with evidence grounding.
A decision exists only when the source explicitly records a concrete choice that has already been made.
An investigation_outcome exists only when the source explicitly records an established finding, root cause, conclusion, diagnostic outcome, or evidence-backed analytical verdict.
If the source only states a need, a symptom, a proposal, a preference, a recommendation, a status update, or something to watch, candidate_type must be null.

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
If no explicit proof phrase exists, candidate_type must be null.""",
}

SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "candidate_type": "decision, investigation_outcome, or null",
        "decision_text": "string or null",
        "decision_evidence_text": "string or null",
        "investigation_text": "string or null",
        "investigation_evidence_text": "string or null",
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
            f"Artifact kind: {source_item.artifact_kind or 'null'}\n"
            f"Role: {source_item.role or 'null'}\n"
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
    investigation_text = _normalize_optional_string(payload.get("investigation_text"), field_name="investigation_text")
    investigation_evidence_text = _normalize_optional_string(payload.get("investigation_evidence_text"), field_name="investigation_evidence_text")
    rationale_text = _normalize_optional_string(payload.get("rationale_text"), field_name="rationale_text")

    if candidate_type is not None:
        candidate_type = candidate_type.lower()
        if candidate_type not in {"decision", "investigation_outcome"}:
            candidate_type = None

    return SemanticExtraction(
        summary=summary,
        candidate_type=candidate_type,
        decision_text=decision_text,
        decision_evidence_text=decision_evidence_text,
        investigation_text=investigation_text,
        investigation_evidence_text=investigation_evidence_text,
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
