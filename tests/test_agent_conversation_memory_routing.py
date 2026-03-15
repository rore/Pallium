from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from core.models import EvidenceReference, QueryFilters, QueryResultItem, QueryTrace
from retrieval.base import RetrievalQueryResult
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


SCENARIO_FILE = Path('evals/tiered_memory_validation/scenarios.json')


def _load_scenarios() -> list[dict[str, object]]:
    return json.loads(SCENARIO_FILE.read_text(encoding='utf-8'))


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    monkeypatch.setattr(
        'app.dependencies.build_llm_provider',
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    client = TestClient(create_app(build_llm_test_config(default_use_case='agent_conversation_memory', sqlite_url=sqlite_url)))
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get('json')
        if isinstance(payload, dict) and url in {'/items', '/query', '/query/debug'} and 'visibility_context' not in payload:
            payload = dict(payload)
            payload['visibility_context'] = {'kind': 'public', 'id': None}
            kwargs['json'] = payload
        return original_post(url, *args, **kwargs)

    client.post = post_with_public_visibility
    return client


def _ingest_prior_events(client: TestClient, scenario_id: str) -> dict[str, object]:
    scenario = next(item for item in _load_scenarios() if item['scenario_id'] == scenario_id)
    for event in scenario['prior_events']:
        response = client.post('/items', json=event)
        assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id='routing-test')
    return scenario


def _run_debug_query(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post('/query/debug', json=payload)
    assert response.status_code == 200
    return response.json()


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
            'session_ref': 'agent-session-routing-work-001',
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
            'session_ref': 'agent-session-routing-work-001',
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
            'session_ref': 'agent-session-routing-work-001',
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
            'session_ref': 'agent-session-routing-work-001',
            'occurred_at': '2026-03-11T10:02:00Z',
        },
    ):
        response = client.post('/items', json=payload)
        assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id='routing-test')


def test_broad_recall_routes_pattern_memory_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'cross-thread-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'pattern_memory'


def test_repeated_answer_routes_continuity_memory_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'repeated-answer-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'answer_continuity'
        assert routing['preferred_layers'][0] == 'continuity_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'continuity_memory'


def test_precise_fact_routes_lower_level_memory_ahead_of_higher_level(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'precise-factual-lower-level')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'precise_fact'
        assert routing['preferred_layers'][0] == 'lower_level_memory'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'decision'
        assert any(
            item['memory_type'] == 'continuity_memory'
            and item['lexical_rank'] < item['routing_rank']
            for item in routing['demoted_higher_level_hits']
        )


def test_evidence_trace_routes_source_evidence_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'evidence-heavy-lower-level')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'evidence_trace'
        assert routing['preferred_layers'][0] == 'source_evidence'
        assert payload['results'][0]['result_kind'] == 'source_hit'
        assert any(
            item['memory_type'] == 'continuity_memory'
            and item['lexical_rank'] < item['routing_rank']
            for item in routing['demoted_higher_level_hits']
        )


def test_work_resumption_routes_task_checkpoint_first(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-work-001')

        payload = _run_debug_query(
            client,
            {
                'text': 'What blocker did we hit, what progress was preserved, and what should we do next on the catalog sync retry?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'work_resumption'
        assert routing['preferred_layers'][0] == 'task_checkpoint'
        assert routing['packaging']['mode'] == 'task_checkpoint_plus_adjacent_evidence'
        assert [item['signal_type'] for item in routing['packaging']['adjacent_evidence'][:2]] == ['blocker', 'next_step']
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'task_checkpoint'
        assert {payload['results'][1]['artifact_kind'], payload['results'][2]['artifact_kind']} == {'tool_use_summary', 'todo_snapshot'}
        checkpoint_payload = payload['results'][0]['payload']
        assert 'service token expired' in checkpoint_payload['blocker_state'].lower()
        assert 'refresh the catalog service token' in checkpoint_payload['next_step'].lower()
        assert 'blocker' in routing['selected_results'][0]['work_signal_types']
        assert 'freshness' in routing['selected_results'][0]['work_signal_types']


def test_work_resumption_demotes_thin_checkpoint_when_fresher_source_state_is_sharper() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='checkpoint-thin',
                type='task_checkpoint',
                payload={
                    'summary': 'Older catalog sync retry state.',
                    'task': 'Resume the catalog sync retry.',
                    'current_state': 'Earlier retry paused after the auth failure.',
                    'latest_occurred_at': '2026-03-11T10:02:00Z',
                },
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-old',
                        source_type='assistant_artifact',
                        source_id='artifact-old',
                        occurred_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-fresh-blocker',
                source_type='assistant_artifact',
                source_id='artifact-fresh-blocker',
                excerpt='Blocked: catalog API returned 429 after batch 417 because the retry window was exhausted.',
                occurred_at=datetime(2026, 3, 11, 12, 1, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-work-thin',
                artifact_kind='tool_use_summary',
                score=14,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-fresh-blocker',
                        source_type='assistant_artifact',
                        source_id='artifact-fresh-blocker',
                        occurred_at=datetime(2026, 3, 11, 12, 1, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='tool_use_summary',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-fresh-next-step',
                source_type='assistant_artifact',
                source_id='artifact-fresh-next-step',
                excerpt='Next step: wait 15 minutes and resume from batch 418 with the refreshed token.',
                occurred_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-routing-work-thin',
                artifact_kind='todo_snapshot',
                score=13,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-fresh-next-step',
                        source_type='assistant_artifact',
                        source_id='artifact-fresh-next-step',
                        occurred_at=datetime(2026, 3, 11, 12, 2, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-routing-work-thin',
                        artifact_kind='todo_snapshot',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What blocker remains now and what should we do next on the catalog sync retry?',
            query_tokens=('blocker', 'next', 'retry', 'sync'),
            limit=3,
            filters=query_filters,
            stages=(),
        ),
    )

    results, trace = plugin.route_query_results(
        text='What blocker remains now and what should we do next on the catalog sync retry?',
        requested_limit=3,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
    )

    assert results[0].result_kind == 'source_hit'
    assert results[1].result_kind == 'source_hit'
    assert {results[0].artifact_kind, results[1].artifact_kind} == {'tool_use_summary', 'todo_snapshot'}
    assert any(item.result_kind == 'memory_hit' and item.type == 'task_checkpoint' for item in results)
    assert trace is not None
    assert trace.routing is not None
    assert trace.routing['packaging']['demoted_task_checkpoint']['result_id'] == 'memory_object:checkpoint-thin'
    assert 'thin_checkpoint' in trace.routing['packaging']['demoted_task_checkpoint']['packaging_reasons']

def test_evidence_trace_with_task_checkpoint_still_prefers_source_evidence(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-work-002')

        payload = _run_debug_query(
            client,
            {
                'text': 'What evidence shows the catalog service token expired on the catalog sync retry?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'evidence_trace'
        assert routing['preferred_layers'][0] == 'source_evidence'
        assert payload['results'][0]['result_kind'] == 'source_hit'
        assert any(
            item['result_kind'] == 'memory_hit' and item['type'] == 'task_checkpoint'
            for item in payload['results']
        )


def test_broad_recall_filters_unrelated_continuity_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']
        rendered_results = json.dumps(payload['results']).lower()

        assert routing['query_intent'] == 'broad_recall'
        assert '30-minute batches' not in rendered_results
        assert 'staff inbox spam' not in rendered_results
        assert any(
            item['memory_type'] == 'continuity_memory'
            and item.get('content_overlap_terms')
            for item in routing['selected_results']
            if item['memory_type'] == 'continuity_memory'
        )


def test_broad_recall_missing_pattern_applies_explicit_fallback_to_lower_level(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['selected_layer'] == 'lower_level_memory'
        assert routing['fallback'] == {
            'applied': True,
            'from_layer': 'pattern_memory',
            'to_layer': 'lower_level_memory',
            'reason_code': 'preferred_layer_missing',
            'reason': 'No pattern_memory candidate was retrieved, so routing fell back to the sharpest safer layer.',
        }
        assert routing['candidate_summary']['pattern_memory']['candidate_count'] == 0
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'decision'

def test_routing_trace_reports_excluded_candidates_and_result_origins(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_resumption_work(client, thread_ref='chat:library-help:thread-routing-observability')

        payload = _run_debug_query(
            client,
            {
                'text': 'What blocker did we hit and what should we do next on the catalog sync retry?',
                'limit': 4,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['candidate_count_entering_routing'] >= len(payload['results'])
        assert routing['returned_result_kinds']['memory_hit'] >= 1
        assert routing['selected_results'][0]['result_origin'] in {'memory', 'source'}
        assert routing['excluded_high_scoring_candidates']
        assert all(item['excluded_reason_code'] for item in routing['excluded_high_scoring_candidates'])
