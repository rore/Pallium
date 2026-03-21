from __future__ import annotations

from core.models import MemoryObject
from providers.llm.base import LLMCallMetadata, LLMJsonResponse
from semantic.agent_conversation_memory_enrichment import (
    DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT,
    WRITE_ENRICHMENT_TEXT_VIEW,
    analyze_write_enrichment,
    apply_write_enrichment,
    build_write_enrichment_request,
    describe_write_enrichment_prompt_variants,
)


class StubEnrichmentProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.last_system_prompt: str | None = None

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        self.last_system_prompt = system_prompt
        return LLMJsonResponse(
            raw_text=str(self._payload),
            parsed_json=self._payload,
            metadata=LLMCallMetadata(provider_name='stub_provider', provider_kind='stub_kind', model='stub-model'),
        )


def test_build_write_enrichment_request_defaults_to_compact_prompt() -> None:
    memory_object = MemoryObject(
        type='task_checkpoint',
        schema_id='semantic.task_checkpoint',
        schema_version='v1',
        payload={'summary': 'Checkpoint summary.'},
    )

    request = build_write_enrichment_request(
        memory_object=memory_object,
        support_lines=['Summary: Checkpoint summary.'],
    )

    assert request.prompt_role == 'write_enrichment'
    assert request.prompt_variant == DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT
    assert request.prompt_schema_id == 'semantic.write_enrichment'
    assert 'stored record' in request.system_prompt.lower()
    assert 'Record type: task_checkpoint' in request.user_prompt


def test_apply_write_enrichment_adds_retrieval_context_and_provenance() -> None:
    memory_object = MemoryObject(
        type='task_checkpoint',
        schema_id='semantic.task_checkpoint',
        schema_version='v1',
        payload={
            'summary': 'Catalog sync retry remains blocked after partial progress.',
            'container_ref': 'chat:library-help',
            'thread_ref': 'chat:library-help:thread-1',
        },
    )
    provider = StubEnrichmentProvider(
        {
            'action': 'ENRICH',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    )

    enriched_memory, index_entry = apply_write_enrichment(
        provider=provider,
        prompt_variant='strict_typed_memory_v5_compact_contract',
        plugin_name='agent_conversation_memory',
        memory_object=memory_object,
        support_lines=['Summary: Catalog sync retry remains blocked after partial progress.'],
    )

    assert index_entry is not None
    assert index_entry.text_view_name == WRITE_ENRICHMENT_TEXT_VIEW
    assert enriched_memory.payload['retrieval_enrichment']['retrieval_context'].startswith('Catalog sync retry resume state')
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['prompt_role'] == 'write_enrichment'
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['prompt_schema_id'] == 'semantic.write_enrichment'
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['prompt_variant'] == DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['provider_name'] == 'stub_provider'
    assert provider.last_system_prompt is not None
    assert 'stored record' in provider.last_system_prompt.lower()


def test_analyze_write_enrichment_accepts_explicit_enrichment_prompt_variant() -> None:
    memory_object = MemoryObject(
        type='thread_summary',
        schema_id='semantic.thread_summary',
        schema_version='v1',
        payload={'summary': 'A compact thread summary.'},
    )
    provider = StubEnrichmentProvider({'action': 'NO_OP', 'retrieval_context': None})

    trace = analyze_write_enrichment(
        provider=provider,
        memory_object=memory_object,
        support_lines=['Summary: A compact thread summary.'],
        prompt_variant='search_context_v3_precise_record',
    )

    assert trace.action == 'NO_OP'
    assert trace.retrieval_context is None
    assert trace.request.prompt_variant == 'search_context_v3_precise_record'
    assert provider.last_system_prompt is not None
    assert 'missing a concrete retrieval handle' in provider.last_system_prompt.lower()


def test_write_enrichment_prompt_variants_are_compact_relative_to_baseline() -> None:
    metrics = describe_write_enrichment_prompt_variants()

    assert metrics[DEFAULT_WRITE_ENRICHMENT_PROMPT_VARIANT]['estimated_tokens'] < metrics['baseline_v1']['estimated_tokens']
    assert metrics['search_context_v2_handles']['estimated_tokens'] < metrics['baseline_v1']['estimated_tokens']
    assert metrics['search_context_v3_precise_record']['estimated_tokens'] < 220
