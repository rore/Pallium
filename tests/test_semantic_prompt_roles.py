from __future__ import annotations

from semantic.prompt_roles import get_prompt_role_contract, list_prompt_role_contracts


def test_prompt_role_registry_contains_expected_roles() -> None:
    contracts = {contract.role: contract for contract in list_prompt_role_contracts()}

    assert set(contracts) == {
        "write_extraction",
        "write_reconciliation",
        "write_enrichment",
        "query_ambiguity_resolution",
    }
    assert contracts["write_extraction"].status == "implemented"
    assert contracts["write_reconciliation"].status == "contract_only"
    assert contracts["write_enrichment"].status == "implemented"
    assert contracts["query_ambiguity_resolution"].status == "contract_only"


def test_prompt_role_contracts_define_explicit_abstain_or_no_op_behavior() -> None:
    write_extraction = get_prompt_role_contract("write_extraction")
    write_reconciliation = get_prompt_role_contract("write_reconciliation")
    write_enrichment = get_prompt_role_contract("write_enrichment")
    query_ambiguity_resolution = get_prompt_role_contract("query_ambiguity_resolution")

    assert write_extraction.supports_abstain is True
    assert write_extraction.abstain_outcome == "null_or_empty_fields"
    assert write_reconciliation.no_op_outcome == "NONE"
    assert write_enrichment.no_op_outcome == "NO_OP"
    assert query_ambiguity_resolution.supports_abstain is True
    assert query_ambiguity_resolution.abstain_outcome == "fallback_to_deterministic_policy"
