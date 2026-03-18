from __future__ import annotations

from semantic.agent_conversation_memory_enrichment import describe_write_enrichment_prompt_variants
from semantic.llm_agent_memory import describe_prompt_variants


def test_compact_write_extraction_variants_are_smaller_than_v4() -> None:
    metrics = describe_prompt_variants()

    assert metrics['strict_typed_memory_v5_compact_contract']['estimated_tokens'] < metrics['strict_typed_memory_v4_evidence_guarded']['estimated_tokens']
    assert metrics['strict_typed_memory_v5_compact_examples']['estimated_tokens'] < metrics['strict_typed_memory_v4_evidence_guarded']['estimated_tokens']


def test_compact_write_enrichment_variants_are_smaller_than_baseline() -> None:
    metrics = describe_write_enrichment_prompt_variants()

    assert metrics['search_context_v2_compact']['estimated_tokens'] < metrics['baseline_v1']['estimated_tokens']
    assert metrics['search_context_v2_handles']['estimated_tokens'] < metrics['baseline_v1']['estimated_tokens']
