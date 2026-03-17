from __future__ import annotations

from core.models import MemoryObject
from providers.llm.base import LLMCallMetadata, LLMJsonResponse
from semantic.agent_conversation_memory_enrichment import (
    WRITE_ENRICHMENT_TEXT_VIEW,
    apply_write_enrichment,
)


class StubEnrichmentProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        return LLMJsonResponse(
            raw_text=str(self._payload),
            parsed_json=self._payload,
            metadata=LLMCallMetadata(provider_name='stub_provider', provider_kind='stub_kind', model='stub-model'),
        )


def test_apply_write_enrichment_adds_retrieval_context_and_provenance() -> None:
    memory_object = MemoryObject(
        type='task_checkpoint',
        schema_id='semantic.task_checkpoint',
        schema_version='v1',
        payload={
            'summary': 'Catalog sync retry remains blocked after partial progress.',
            'container_ref': 'chat:library-help',
            'thread_ref': 'chat:library-help:thread-1',
            'session_ref': 'session:1',
        },
    )

    enriched_memory, index_entry = apply_write_enrichment(
        provider=StubEnrichmentProvider(
            {
                'action': 'ENRICH',
                'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
            }
        ),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
        plugin_name='agent_conversation_memory',
        memory_object=memory_object,
        support_lines=['Summary: Catalog sync retry remains blocked after partial progress.'],
    )

    assert index_entry is not None
    assert index_entry.text_view_name == WRITE_ENRICHMENT_TEXT_VIEW
    assert enriched_memory.payload['retrieval_enrichment']['retrieval_context'].startswith('Catalog sync retry resume state')
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['prompt_role'] == 'write_enrichment'
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['prompt_schema_id'] == 'semantic.write_enrichment'
    assert enriched_memory.payload['retrieval_enrichment']['semantic_provenance']['provider_name'] == 'stub_provider'


def test_apply_write_enrichment_keeps_memory_unchanged_on_no_op() -> None:
    memory_object = MemoryObject(
        type='thread_summary',
        schema_id='semantic.thread_summary',
        schema_version='v1',
        payload={'summary': 'A compact thread summary.'},
    )

    enriched_memory, index_entry = apply_write_enrichment(
        provider=StubEnrichmentProvider({'action': 'NO_OP', 'retrieval_context': None}),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
        plugin_name='agent_conversation_memory',
        memory_object=memory_object,
        support_lines=['Summary: A compact thread summary.'],
    )

    assert enriched_memory == memory_object
    assert index_entry is None
    assert 'retrieval_enrichment' not in enriched_memory.payload
