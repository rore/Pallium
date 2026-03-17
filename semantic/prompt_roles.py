from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PromptRole = Literal[
    "write_extraction",
    "write_reconciliation",
    "write_enrichment",
    "query_ambiguity_resolution",
]
PromptRoleStatus = Literal["implemented", "contract_only"]


@dataclass(frozen=True)
class PromptRoleContract:
    role: PromptRole
    schema_id: str
    schema_version: str
    purpose: str
    supports_abstain: bool
    abstain_outcome: str | None
    no_op_outcome: str | None
    status: PromptRoleStatus
    owner_feature: str
    default_model_role: str | None = None


PROMPT_ROLE_CONTRACTS: dict[PromptRole, PromptRoleContract] = {
    "write_extraction": PromptRoleContract(
        role="write_extraction",
        schema_id="typed_memory_extraction",
        schema_version="v7",
        purpose="Extract bounded typed memory and semantic signals from one source item.",
        supports_abstain=True,
        abstain_outcome="null_or_empty_fields",
        no_op_outcome=None,
        status="implemented",
        owner_feature="add-semantic-prompt-role-contracts-and-replay-governance",
        default_model_role="write_extraction",
    ),
    "write_reconciliation": PromptRoleContract(
        role="write_reconciliation",
        schema_id="semantic.write_reconciliation",
        schema_version="v1",
        purpose="Choose bounded lifecycle update actions for existing semantic memory.",
        supports_abstain=False,
        abstain_outcome=None,
        no_op_outcome="NONE",
        status="contract_only",
        owner_feature="add-semantic-prompt-role-contracts-and-replay-governance",
        default_model_role="write_reconciliation",
    ),
    "write_enrichment": PromptRoleContract(
        role="write_enrichment",
        schema_id="semantic.write_enrichment",
        schema_version="v1",
        purpose="Add bounded retrieval-helpful context to existing typed memory without replacing evidence-backed payloads.",
        supports_abstain=False,
        abstain_outcome=None,
        no_op_outcome="NO_OP",
        status="contract_only",
        owner_feature="add-semantic-prompt-role-contracts-and-replay-governance",
        default_model_role="write_enrichment",
    ),
    "query_ambiguity_resolution": PromptRoleContract(
        role="query_ambiguity_resolution",
        schema_id="semantic.query_ambiguity_resolution",
        schema_version="v1",
        purpose="Resolve bounded query-policy ambiguity only after deterministic narrowing leaves multiple plausible behaviors.",
        supports_abstain=True,
        abstain_outcome="fallback_to_deterministic_policy",
        no_op_outcome="FALLBACK",
        status="contract_only",
        owner_feature="add-semantic-prompt-role-contracts-and-replay-governance",
        default_model_role="query_ambiguity_resolution",
    ),
}


def get_prompt_role_contract(role: PromptRole) -> PromptRoleContract:
    return PROMPT_ROLE_CONTRACTS[role]


def list_prompt_role_contracts() -> tuple[PromptRoleContract, ...]:
    return tuple(PROMPT_ROLE_CONTRACTS.values())
