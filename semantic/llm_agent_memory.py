from __future__ import annotations

import json
from typing import Any

from core.contracts import ProcessResult
from core.models import SourceItem
from providers.llm.base import LLMProvider
from semantic.base import SemanticPlugin
from semantic.common import SemanticExtraction, build_process_result


SYSTEM_PROMPT = """You extract reusable memory from technical discussions.
Return exactly one JSON object and no extra prose."""

SCHEMA_DESCRIPTION = json.dumps(
    {
        "summary": "string",
        "candidate_type": "decision or null",
        "decision_text": "string or null",
        "rationale_text": "string or null",
    },
    indent=2,
)


class LLMAgentMemoryPlugin(SemanticPlugin):
    name = "llm_agent_memory"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        response = self._provider.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(source_item),
            schema_description=SCHEMA_DESCRIPTION,
        )
        extraction = _normalize_extraction(response.parsed_json)
        return build_process_result(source_item, extraction, schema_prefix="llm")


def _build_user_prompt(source_item: SourceItem) -> str:
    metadata_text = json.dumps(source_item.metadata or {}, sort_keys=True)
    return (
        f"Source type: {source_item.source_type}\n"
        f"Source id: {source_item.source_id}\n"
        f"Content type: {source_item.content_type}\n"
        f"Metadata: {metadata_text}\n"
        f"Content:\n{source_item.content}"
    )


def _normalize_extraction(payload: dict[str, Any]) -> SemanticExtraction:
    summary = _normalize_required_string(payload.get("summary"), field_name="summary")
    candidate_type = _normalize_optional_string(payload.get("candidate_type"), field_name="candidate_type")
    decision_text = _normalize_optional_string(payload.get("decision_text"), field_name="decision_text")
    rationale_text = _normalize_optional_string(payload.get("rationale_text"), field_name="rationale_text")

    if candidate_type is not None:
        candidate_type = candidate_type.lower()
        if candidate_type != "decision":
            candidate_type = None

    return SemanticExtraction(
        summary=summary,
        candidate_type=candidate_type,
        decision_text=decision_text,
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
