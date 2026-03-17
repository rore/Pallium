from __future__ import annotations

import json
from dataclasses import replace
from typing import Iterable

from core.indexing import build_index_entry
from core.models import IndexEntry, MemoryObject
from providers.llm.base import LLMProvider
from semantic.common import normalize_for_index
from semantic.prompt_provenance import build_prompt_provenance
from semantic.prompt_roles import get_prompt_role_contract

WRITE_ENRICHMENT_PROMPT_ROLE = get_prompt_role_contract("write_enrichment")
WRITE_ENRICHMENT_TEXT_VIEW = "memory_object.write_enrichment_context"
ENRICHABLE_MEMORY_TYPES = {"thread_summary", "task_checkpoint", "pattern_memory", "continuity_memory"}

WRITE_ENRICHMENT_SCHEMA_DESCRIPTION = json.dumps(
    {
        "action": "ENRICH or NO_OP",
        "retrieval_context": "string or null",
    },
    indent=2,
)

WRITE_ENRICHMENT_SYSTEM_PROMPT = (
    "You add bounded retrieval-helpful context to an existing higher-level memory object. "
    "Return exactly one JSON object and no extra prose. "
    "Use action ENRICH only when you can add a short context string that makes the memory easier to retrieve later without changing its meaning. "
    "Use action NO_OP when the existing payload already contains the needed retrieval cues. "
    "Do not restate full evidence, do not invent facts, and do not replace or rewrite the canonical payload. "
    "Keep retrieval_context to one concise sentence and at most roughly 30 words."
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

    support_text = "\n".join(line for line in support_lines if str(line or "").strip())
    response = provider.generate_json(
        system_prompt=WRITE_ENRICHMENT_SYSTEM_PROMPT,
        user_prompt=(
            f"Memory type: {memory_object.type}\n"
            f"Container ref: {memory_object.payload.get('container_ref') or 'null'}\n"
            f"Thread ref: {memory_object.payload.get('thread_ref') or 'null'}\n"
            f"Session ref: {memory_object.payload.get('session_ref') or 'null'}\n"
            f"Canonical payload context:\n{support_text or '- none'}"
        ),
        schema_description=WRITE_ENRICHMENT_SCHEMA_DESCRIPTION,
    )

    action = str(response.parsed_json.get("action") or "").strip().upper()
    retrieval_context = str(response.parsed_json.get("retrieval_context") or "").strip()
    if action != "ENRICH" or not retrieval_context:
        return memory_object, None

    provenance = build_prompt_provenance(
        semantic_plugin=plugin_name,
        contract=WRITE_ENRICHMENT_PROMPT_ROLE,
        prompt_variant=prompt_variant,
        model_role=WRITE_ENRICHMENT_PROMPT_ROLE.default_model_role,
        llm_metadata=response.metadata,
        extra={"memory_type": memory_object.type},
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
