from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Iterable

from core.indexing import build_index_entry
from core.models import IndexEntry, MemoryObject
from providers.llm.base import LLMJsonResponse, LLMProvider
from semantic.common import normalize_for_index
from semantic.prompt_variant_metrics import prompt_text_metrics
from semantic.prompt_provenance import build_prompt_provenance
from semantic.prompt_roles import get_prompt_role_contract

WRITE_ENRICHMENT_PROMPT_ROLE = get_prompt_role_contract("write_enrichment")
WRITE_ENRICHMENT_TEXT_VIEW = "memory_object.write_enrichment_context"
ENRICHABLE_MEMORY_TYPES = {"thread_summary", "task_checkpoint", "pattern_memory", "continuity_memory"}
DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT = "search_context_v2_compact"

WRITE_ENRICHMENT_SCHEMA_DESCRIPTION = json.dumps(
    {
        "action": "ENRICH or NO_OP",
        "retrieval_context": "string or null",
    },
    indent=2,
)

WRITE_ENRICHMENT_PROMPT_VARIANTS: dict[str, str] = {
    "baseline_v1": (
        "You add bounded retrieval-helpful context to an existing higher-level memory object. "
        "Return exactly one JSON object and no extra prose. "
        "Use action ENRICH only when you can add a short context string that makes the memory easier to retrieve later without changing its meaning. "
        "Use action NO_OP when the existing payload already contains the needed retrieval cues. "
        "Do not restate full evidence, do not invent facts, and do not replace or rewrite the canonical payload. "
        "Keep retrieval_context to one concise sentence and at most roughly 30 words."
    ),
    "search_context_v2_compact": (
        "You are given one stored record and its canonical context. Return exactly one JSON object and no extra prose. "
        "Goal: write one short search-friendly context line that helps this record match later queries. "
        "Use ENRICH only when you can add missing retrieval context without changing meaning. "
        "Use NO_OP when the record already has enough search cues. "
        "Do not rewrite the record, do not add facts, and do not restate full evidence. "
        "Keep retrieval_context to one concrete sentence, about 12 to 30 words."
    ),
    "search_context_v2_handles": (
        "Write one short search context line for an existing stored record. Return exactly one JSON object and no extra prose. "
        "Use ENRICH only if the record is missing retrieval handles such as workstream, artifact, failure mode, carry-forward question, or resume point. "
        "Use NO_OP when the canonical context is already searchable enough. "
        "Do not rewrite the record, do not add facts, do not echo full evidence, and avoid filler like relevant memory or useful context. "
        "Keep retrieval_context to one concrete sentence, about 12 to 30 words."
    ),
    "search_context_v3_precise_record": (
        "You are given one stored record and its canonical context. Return exactly one JSON object and no extra prose. "
        "Write one short search-friendly context line only when the current summary is missing a concrete retrieval handle such as a restart point, failure mode, carry-forward question, or cross-thread lesson. "
        "Use ENRICH only when adding one missing handle would materially improve later lookup without changing meaning. "
        "Use NO_OP when the summary already names the key handle clearly, including specific restart points, failure modes, carry-forward answers, or cross-thread lessons. "
        "Do not rewrite the record, do not add facts, and do not restate full evidence. "
        "Keep retrieval_context to one concrete sentence, about 12 to 30 words."
    ),
}


@dataclass(frozen=True)
class WriteEnrichmentRequest:
    prompt_role: str
    prompt_variant: str
    prompt_schema_id: str
    prompt_schema_version: str
    model_role: str | None
    system_prompt: str
    user_prompt: str
    schema_description: str
    memory_type: str


@dataclass(frozen=True)
class WriteEnrichmentTrace:
    request: WriteEnrichmentRequest
    response: LLMJsonResponse
    action: str
    retrieval_context: str | None


def list_write_enrichment_prompt_variants() -> list[str]:
    return list(WRITE_ENRICHMENT_PROMPT_VARIANTS.keys())


def describe_write_enrichment_prompt_variants() -> dict[str, dict[str, int]]:
    return {name: prompt_text_metrics(text) for name, text in WRITE_ENRICHMENT_PROMPT_VARIANTS.items()}


def get_write_enrichment_prompt_text(prompt_variant: str | None) -> str:
    return WRITE_ENRICHMENT_PROMPT_VARIANTS[_resolve_write_enrichment_prompt_variant(prompt_variant)]


def _resolve_write_enrichment_prompt_variant(prompt_variant: str | None) -> str:
    if prompt_variant in WRITE_ENRICHMENT_PROMPT_VARIANTS:
        return str(prompt_variant)
    return DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT


def build_write_enrichment_request(
    *,
    memory_object: MemoryObject,
    support_lines: Iterable[str],
    prompt_variant: str | None = None,
) -> WriteEnrichmentRequest:
    resolved_prompt_variant = _resolve_write_enrichment_prompt_variant(prompt_variant)
    support_text = "\n".join(line for line in support_lines if str(line or "").strip())
    return WriteEnrichmentRequest(
        prompt_role=WRITE_ENRICHMENT_PROMPT_ROLE.role,
        prompt_variant=resolved_prompt_variant,
        prompt_schema_id=WRITE_ENRICHMENT_PROMPT_ROLE.schema_id,
        prompt_schema_version=WRITE_ENRICHMENT_PROMPT_ROLE.schema_version,
        model_role=WRITE_ENRICHMENT_PROMPT_ROLE.default_model_role,
        system_prompt=WRITE_ENRICHMENT_PROMPT_VARIANTS[resolved_prompt_variant],
        user_prompt=(
            f"Record type: {memory_object.type}\n"
            f"Container ref: {memory_object.payload.get('container_ref') or 'null'}\n"
            f"Thread ref: {memory_object.payload.get('thread_ref') or 'null'}\n"
            f"Canonical record context:\n{support_text or '- none'}"
        ),
        schema_description=WRITE_ENRICHMENT_SCHEMA_DESCRIPTION,
        memory_type=memory_object.type,
    )


def analyze_write_enrichment(
    *,
    provider: LLMProvider,
    memory_object: MemoryObject,
    support_lines: Iterable[str],
    prompt_variant: str | None = None,
) -> WriteEnrichmentTrace:
    request = build_write_enrichment_request(
        memory_object=memory_object,
        support_lines=support_lines,
        prompt_variant=prompt_variant,
    )
    response = provider.generate_json(
        system_prompt=request.system_prompt,
        user_prompt=request.user_prompt,
        schema_description=request.schema_description,
    )
    action = str(response.parsed_json.get("action") or "").strip().upper()
    retrieval_context = str(response.parsed_json.get("retrieval_context") or "").strip() or None
    return WriteEnrichmentTrace(
        request=request,
        response=response,
        action=action,
        retrieval_context=retrieval_context,
    )


def apply_write_enrichment(
    *,
    provider: LLMProvider,
    prompt_variant: str,
    plugin_name: str,
    memory_object: MemoryObject,
    support_lines: Iterable[str],
) -> tuple[MemoryObject, IndexEntry | None]:
    if memory_object.type not in ENRICHABLE_MEMORY_TYPES:
        return memory_object, None

    trace = analyze_write_enrichment(
        provider=provider,
        memory_object=memory_object,
        support_lines=support_lines,
        prompt_variant=prompt_variant,
    )
    if trace.action != "ENRICH" or not trace.retrieval_context:
        return memory_object, None

    provenance = build_prompt_provenance(
        semantic_plugin=plugin_name,
        contract=WRITE_ENRICHMENT_PROMPT_ROLE,
        prompt_variant=trace.request.prompt_variant,
        model_role=trace.request.model_role,
        llm_metadata=trace.response.metadata,
        extra={"memory_type": memory_object.type},
    )
    updated_payload = dict(memory_object.payload)
    updated_payload["retrieval_enrichment"] = {
        "retrieval_context": trace.retrieval_context,
        "semantic_provenance": provenance,
    }
    enriched_memory = replace(memory_object, payload=updated_payload)
    enrichment_index_entry = build_index_entry(
        target_kind="memory_object",
        target_id=enriched_memory.id,
        index_type="lexical",
        text_view=normalize_for_index(trace.retrieval_context),
        text_view_name=WRITE_ENRICHMENT_TEXT_VIEW,
    )
    return enriched_memory, enrichment_index_entry
