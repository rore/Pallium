from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from core.models import (
    EvidenceReference,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemorySubjectAnchor,
    QueryFilters,
    QueryResultItem,
    QueryRuntimeContext,
    QueryTrace,
    SourceItem,
)
from providers.llm.base import LLMJsonResponse
from retrieval.base import RetrievalQueryResult
from semantic.agent_conversation_memory import (
    AgentConversationMemoryPlugin,
)
from tests.config_helpers import build_agent_conversation_client
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider


SCENARIO_FILE = Path('evals/tiered_memory_validation/scenarios.json')


def _load_scenarios() -> list[dict[str, object]]:
    return json.loads(SCENARIO_FILE.read_text(encoding='utf-8'))


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    return build_agent_conversation_client(monkeypatch, sqlite_url)


def _ingest_prior_events(client: TestClient, scenario_id: str) -> dict[str, object]:
    scenario = next(item for item in _load_scenarios() if item['scenario_id'] == scenario_id)
    for event in scenario['prior_events']:
        response = client.post('/items', json=[event])
        assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id='routing-test')
    return scenario


def _run_debug_query(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post('/query/debug', json=payload)
    assert response.status_code == 200
    return response.json()


class _FixedLLMProvider:
    def __init__(self, parsed_json: dict[str, object]) -> None:
        self._parsed_json = parsed_json

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        return LLMJsonResponse(raw_text=json.dumps(self._parsed_json), parsed_json=self._parsed_json)



def _memory_envelope(
    kind: str,
    *,
    confidence: str = 'medium',
    subjects: list[MemorySubjectAnchor] | None = None,
) -> MemoryEnvelope:
    return MemoryEnvelope(
        schema_id='core.memory_envelope',
        schema_version='v1',
        kind=kind,
        scope=MemoryEnvelopeScope(container_ref='chat:library-help'),
        confidence=confidence,
        derivation=MemoryEnvelopeDerivation(
            producer_kind='item_extraction',
            producer_schema_id='typed_memory_extraction',
            producer_schema_version='v7',
            prompt_variant='strict_typed_memory_v4_evidence_guarded',
            model_role='write_time_extraction',
            kind_basis='type_map',
        ),
        subjects=subjects or [],
    )


def _ingest_resumption_work(client: TestClient, *, thread_ref: str) -> None:
    for payload in (
        {
            'source_type': 'chat_message',
            'source_id': f'{thread_ref}-msg-1',
            'content_type': 'text/plain',
            'content': 'The catalog sync retry is queued again.',
            'artifact_kind': 'message',
            'role': 'user',
            'container_ref': 'chat:library-help',
            'thread_ref': thread_ref,
            'occurred_at': '2026-03-11T09:59:00Z',
        },
        {
            'source_type': 'assistant_artifact',
            'source_id': f'{thread_ref}-artifact-1',
            'content_type': 'text/plain',
            'content': 'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
            'artifact_kind': 'tool_use_summary',
            'role': 'assistant',
            'container_ref': 'chat:library-help',
            'thread_ref': thread_ref,
            'occurred_at': '2026-03-11T10:00:00Z',
        },
        {
            'source_type': 'assistant_artifact',
            'source_id': f'{thread_ref}-artifact-2',
            'content_type': 'text/plain',
            'content': 'Blocked: catalog API returned 401 because the service token expired.',
            'artifact_kind': 'tool_use_summary',
            'role': 'assistant',
            'container_ref': 'chat:library-help',
            'thread_ref': thread_ref,
            'occurred_at': '2026-03-11T10:01:00Z',
        },
        {
            'source_type': 'assistant_artifact',
            'source_id': f'{thread_ref}-artifact-3',
            'content_type': 'text/plain',
            'content': 'Next step: refresh the catalog service token and rerun the sync from batch 313.',
            'artifact_kind': 'todo_snapshot',
            'role': 'assistant',
            'container_ref': 'chat:library-help',
            'thread_ref': thread_ref,
            'occurred_at': '2026-03-11T10:02:00Z',
        },
    ):
        response = client.post('/items', json=[payload])
        assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id='routing-test')

def _inventory_batch_constraint_checkpoint_result(*, memory_object_id: str = 'checkpoint-batch-constraint', score: int = 16, envelope: MemoryEnvelope | None = None) -> QueryResultItem:
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='task_checkpoint',
        payload={
            'summary': 'The inventory batch digest is preserved with an explicit no-login and no-browser constraint.',
            'task': 'Resume the inventory batch digest.',
            'current_state': 'The inventory batch digest is prepared for BIN-103, BIN-204, BIN-317, and BIN-418.',
            'key_findings': [
                'The inventory batch digest already covers BIN-103, BIN-204, BIN-317, and BIN-418.',
                'Do not try to sign in to the operations portal or open a local browser.',
            ],
            'blocker_state': 'The operator constraint forbids operations-portal sign-in and local-browser login during this batch digest work.',
            'next_step': 'Refresh the local digest token and rerun the inventory batch digest from the last confirmed batch.',
            'evidence': [
                'Partial progress: prepared the inventory batch digest for BIN-103, BIN-204, BIN-317, and BIN-418.',
                "Constraint: do not try to sign in to the operations portal and don't open a local browser to log in.",
                'Next step: refresh the local digest token and rerun the inventory batch digest from the last confirmed batch.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
        },
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-a',
        envelope=envelope,
    )

def _inventory_batch_constraint_summary_result(*, memory_object_id: str = 'summary-batch-constraint', score: int = 15, envelope: MemoryEnvelope | None = None) -> QueryResultItem:
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='thread_summary',
        payload={
            'summary': 'The thread preserved the inventory batch digest context for BIN-103, BIN-204, BIN-317, and BIN-418, and the standing constraint is to avoid operations-portal sign-in or opening a local browser.',
            'conclusions': [],
            'selected_work_artifacts': [
                {'signal_type': 'progress_update', 'text': 'Prepared the inventory batch digest.'},
                {'signal_type': 'constraint', 'text': "Do not try to sign in to the operations portal and don't open a local browser to log in."},
            ],
        },
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-a',
        envelope=envelope,
    )

def _inventory_batch_conflicting_retry_checkpoint_result(*, memory_object_id: str = 'checkpoint-batch-auth-retry', score: int = 14, envelope: MemoryEnvelope | None = None) -> QueryResultItem:
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='task_checkpoint',
        payload={
            'summary': 'A newer mirror-based batch digest is blocked by remote authentication.',
            'task': 'Resume the mirror-based batch digest.',
            'current_state': 'The mirror-based batch digest is prepared, but remote authentication still blocks it.',
            'key_findings': [
                'The mirror-based batch digest is prepared for the batch manifests.',
                'Remote authentication still blocks it.',
            ],
            'blocker_state': 'The mirror-based batch digest cannot proceed until remote authentication succeeds.',
            'next_step': 'Attempt to authenticate to the operations portal and the message console before retrying the inventory batch digest.',
            'evidence': [
                'Partial progress: built the mirror-based batch digest for the batch manifests.',
                'Blocked: the mirror-based batch digest cannot proceed until remote authentication succeeds.',
                'Next step: attempt to authenticate to the operations portal and the message console before retrying the inventory batch digest.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:02:00Z.',
        },
        freshness_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-c',
        envelope=envelope,
    )

def _inventory_batch_typed_constraint_result(*, memory_object_id: str = 'constraint-batch-portal', score: int = 19) -> QueryResultItem:
    scope_anchor = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    target_anchor = MemorySubjectAnchor(kind='surface', value='operations portal')
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='constraint_memory',
        payload={
            'summary': 'Constraint: do not use operations portal.',
            'constraint_text': 'Do not use the operations portal for the inventory batch digest.',
            'primary_scope_anchor': {'kind': 'workstream', 'value': 'inventory batch digest'},
            'target_anchor': {'kind': 'surface', 'value': 'operations portal'},
            'action_class': 'use_surface',
            'polarity': 'prohibit',
            'strength': 'hard',
            'status': 'active',
            'evidence': ['Do not use the operations portal for the inventory batch digest.'],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:10:00Z.',
            'confidence': 'high',
            'canonical_key': 'workstream:inventory batch digest|surface:operations portal|use_surface',
            'compatibility_domain_key': 'workstream:inventory batch digest|use_surface',
            'precise_coverage_key': 'workstream:inventory batch digest|surface:operations portal|use_surface',
            'container_ref': 'slack:channel:CLOCAL001',
            'thread_ref': 'slack:thread:CLOCAL001:thread-typed-constraint',
            'semantic_provenance': {
                'semantic_plugin': 'llm_agent_memory',
                'prompt_variant': 'strict_typed_memory_v4_evidence_guarded',
                'prompt_schema_id': 'typed_memory_extraction',
                'prompt_schema_version': 'v7',
            },
        },
        freshness_at=datetime(2026, 3, 11, 12, 10, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-typed-constraint',
        envelope=_memory_envelope('constraint', confidence='high', subjects=[scope_anchor, target_anchor]),
    )

def _wallet_snapshot_checkpoint_result(*, memory_object_id: str = 'checkpoint-wallet-snapshot', score: int = 16) -> QueryResultItem:
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='task_checkpoint',
        payload={
            'summary': 'The wallet reserve snapshot is ready for the local wallet review.',
            'task': 'Resume the wallet reserve snapshot review.',
            'current_state': 'The wallet reserve snapshot is reconciled for WAL-102 and WAL-208.',
            'key_findings': [
                'The wallet reserve snapshot is reconciled for WAL-102 and WAL-208.',
                'The reserve note still needs the local snapshot confirmation before publication.',
            ],
            'blocker_state': '',
            'next_step': 'Publish the wallet reserve note after confirming the local snapshot.',
            'evidence': [
                'Partial progress: the wallet reserve snapshot is reconciled for WAL-102 and WAL-208.',
                'Next step: publish the wallet reserve note after confirming the local snapshot.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:35:00Z.',
        },
        freshness_at=datetime(2026, 3, 11, 12, 35, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-wallet',
    )

def _wallet_snapshot_summary_result(*, memory_object_id: str = 'summary-wallet-snapshot', score: int = 15) -> QueryResultItem:
    return QueryResultItem(
        result_kind='memory_hit',
        memory_object_id=memory_object_id,
        type='thread_summary',
        payload={
            'summary': 'The thread preserved the wallet reserve snapshot for WAL-102 and WAL-208, and the next step is to publish the wallet reserve note after confirming the local snapshot.',
            'conclusions': [],
            'selected_work_artifacts': [
                {'signal_type': 'progress_update', 'text': 'Reconciled the wallet reserve snapshot for WAL-102 and WAL-208.'},
                {'signal_type': 'next_step', 'text': 'Publish the wallet reserve note after confirming the local snapshot.'},
            ],
        },
        freshness_at=datetime(2026, 3, 11, 12, 35, tzinfo=timezone.utc),
        score=score,
        evidence=[],
        container_ref='slack:channel:CLOCAL001',
        thread_ref='slack:thread:CLOCAL001:thread-wallet',
    )

__all__ = [name for name in globals() if not (name.startswith('__') and name.endswith('__'))]

