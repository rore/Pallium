from __future__ import annotations

from typing import Any

from providers.llm.base import LLMCallMetadata
from semantic.prompt_roles import PromptRoleContract


def build_prompt_provenance(
    *,
    semantic_plugin: str,
    contract: PromptRoleContract,
    prompt_variant: str | None = None,
    model_role: str | None = None,
    llm_metadata: LLMCallMetadata | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "semantic_plugin": semantic_plugin,
        "prompt_role": contract.role,
        "prompt_schema_id": contract.schema_id,
        "prompt_schema_version": contract.schema_version,
    }
    resolved_model_role = model_role or contract.default_model_role
    if prompt_variant:
        provenance["prompt_variant"] = prompt_variant
    if resolved_model_role:
        provenance["model_role"] = resolved_model_role
    if llm_metadata is not None:
        provenance["provider_name"] = llm_metadata.provider_name
        provenance["provider_kind"] = llm_metadata.provider_kind
        provenance["model"] = llm_metadata.model
    if extra:
        provenance.update(extra)
    return provenance
