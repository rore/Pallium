from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from core.models import EvidenceReference, QueryFilters, QueryResultItem, QueryRuntimeContext, QueryTrace, SourceItem
from core.visibility import VisibilityContext
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
        _ingest_prior_events(client, 'cross-thread-pattern-value')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What general lesson should we remember about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'broad_recall'
        assert routing['preferred_layers'][0] == 'pattern_memory'
        assert routing['selected_layer'] == 'pattern_memory'
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


def test_precise_fact_routes_sharp_decision_ahead_of_higher_level_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'precise-factual-lower-level')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(client, scenario['current_query'])
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'precise_fact'
        assert routing['preferred_layers'][0] == 'decision'
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'decision'
        assert any(
            item['memory_type'] == 'thread_summary'
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

    outcome = plugin.route_query_results(
        text='What blocker remains now and what should we do next on the catalog sync retry?',
        requested_limit=3,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    results = outcome.results
    trace = outcome.trace
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
        _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What general lesson should we remember about duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']
        rendered_results = json.dumps(payload['results']).lower()

        assert routing['query_intent'] == 'broad_recall'
        assert '30-minute batches' not in rendered_results
        assert 'staff inbox spam' not in rendered_results
        assert any(item['type'] == 'decision' for item in payload['results'] if item['result_kind'] == 'memory_hit')


def test_investigative_conclusion_prefers_sharp_conclusions_over_generic_summaries(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'same-container-false-merge-guard')
        client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        payload = _run_debug_query(
            client,
            {
                'text': 'What was our verdict on duplicate holds after catalog sync delays?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        routing = payload['trace']['routing']

        assert routing['query_intent'] == 'investigative_conclusion'
        assert routing['preferred_layers'][:3] == ['investigation_outcome', 'decision', 'source_evidence']
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] in {'investigation_outcome', 'decision'}
        assert payload['results'][1]['type'] in {'investigation_outcome', 'decision'}
        assert all(item.get('type') not in {'thread_summary', 'discussion_summary'} for item in payload['results'][:2])

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


def test_fresher_same_kind_conclusion_ranks_above_older_one() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-old',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering', 'rationale': 'to avoid duplicate holds'},
                freshness_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-freshness',
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-fresh',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering', 'rationale': 'to avoid duplicate holds'},
                freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                score=12,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-freshness',
            ),
        ],
        trace=QueryTrace(
            query_text='What had we concluded about duplicate holds?',
            query_tokens=('concluded', 'duplicate', 'holds'),
            limit=4,
            filters=QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-freshness'),
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-freshness'),
        include_trace=True,
    )

    assert outcome.results[0].memory_object_id == 'decision-fresh'
    assert outcome.trace is not None
    diagnostics = {item['result_id']: item for item in outcome.sharp_candidate_diagnostics}
    assert diagnostics['memory_object:decision-fresh']['selected_for_injection'] is True
    assert diagnostics['memory_object:decision-old']['selected_for_injection'] is True or diagnostics['memory_object:decision-old']['loss_reason_code'] in {'older_same_kind_conclusion', 'final_injection_cap', None}


def test_process_item_emits_same_thread_supersession_hint_for_sharp_conclusion() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    result = plugin.process_item(
        SourceItem(
            source_type='assistant_artifact',
            source_id='decision-source-1',
            content_type='text/plain',
            content='Decision: use item event time for reservation ordering to avoid duplicate holds.',
            artifact_kind='assistant_output',
            role='assistant',
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-supersession',
            session_ref='session:supersession',
            visibility_context=VisibilityContext(kind='public', id=None),
        )
    )

    assert any(memory.type == 'decision' for memory in result.memory_objects)
    assert len(result.supersession_hints) == 1
    hint = result.supersession_hints[0]
    assert hint.memory_type == 'decision'
    assert hint.container_ref == 'chat:library-help'
    assert hint.thread_ref == 'chat:library-help:thread-supersession'
    assert hint.canonical_key == 'use item event time for reservation ordering'


def test_broad_recall_injection_prefers_compact_memory_over_source_hits() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-broad')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='pattern-memory-1',
                type='pattern_memory',
                payload={'summary': 'Duplicate holds usually traced back to stale arrival-time ordering during delayed sync windows.'},
                score=18,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-broad',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-broad-1',
                source_type='assistant_artifact',
                source_id='artifact-broad-1',
                excerpt='Investigation found that stale arrival-time ordering caused duplicate holds during delayed sync windows.',
                occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-broad',
                artifact_kind='assistant_output',
                score=16,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-broad-1',
                        source_type='assistant_artifact',
                        source_id='artifact-broad-1',
                        occurred_at=datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-broad',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='What should we remember about duplicate holds after catalog sync delays?',
            query_tokens=('remember', 'duplicate', 'holds', 'sync'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What should we remember about duplicate holds after catalog sync delays?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.decision_reason == 'carry_forward_available'
    assert outcome.injectable_blocks
    assert outcome.injectable_blocks[0].memory_type == 'pattern_memory'
    assert all(block.block_type == 'memory' for block in outcome.injectable_blocks)



def test_evidence_trace_injection_keeps_source_evidence_injectable() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-evidence')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-evidence-1',
                source_type='assistant_artifact',
                source_id='artifact-evidence-1',
                excerpt='Investigation found that arrival-time ordering skipped hold updates during delayed sync windows.',
                occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-evidence',
                artifact_kind='assistant_output',
                score=18,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-evidence-1',
                        source_type='assistant_artifact',
                        source_id='artifact-evidence-1',
                        occurred_at=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-evidence',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-evidence-1',
                type='decision',
                payload={'decision': 'use item event time for reservation ordering'},
                score=14,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-evidence',
            ),
        ],
        trace=QueryTrace(
            query_text='What evidence supported the reservation ordering conclusion?',
            query_tokens=('evidence', 'supported', 'reservation', 'ordering'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What evidence supported the reservation ordering conclusion?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.injectable_blocks
    assert outcome.injectable_blocks[0].block_type == 'source_evidence'
    assert outcome.injectable_blocks[0].result_id == 'source_item:source-evidence-1'



def test_investigative_conclusion_injection_can_include_source_evidence_when_intended() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-injection-investigative')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='investigation-inject-1',
                type='investigation_outcome',
                payload={
                    'investigation_outcome': 'transaction-transformer changed more than ledger-query',
                    'rationale': 'because it touched more tickets, files, and transaction flows',
                },
                freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                score=20,
                evidence=[],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-investigative',
            ),
            QueryResultItem(
                result_kind='source_hit',
                source_item_id='source-investigative-1',
                source_type='assistant_artifact',
                source_id='artifact-investigative-1',
                excerpt='Investigation found that transaction-transformer changed more than ledger-query because it touched more tickets, files, and transaction flows.',
                occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-injection-investigative',
                artifact_kind='assistant_output',
                score=17,
                evidence=[
                    EvidenceReference(
                        source_item_id='source-investigative-1',
                        source_type='assistant_artifact',
                        source_id='artifact-investigative-1',
                        occurred_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
                        container_ref='chat:library-help',
                        thread_ref='chat:library-help:thread-injection-investigative',
                        artifact_kind='assistant_output',
                    )
                ],
            ),
        ],
        trace=QueryTrace(
            query_text='Which repo changed more and why?',
            query_tokens=('which', 'repo', 'changed', 'more', 'why'),
            limit=4,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='Which repo changed more and why?',
        requested_limit=4,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )

    assert outcome.should_inject is True
    assert outcome.injectable_blocks
    assert outcome.injectable_blocks[0].memory_type == 'investigation_outcome'
    assert any(block.block_type == 'source_evidence' for block in outcome.injectable_blocks)



def test_debug_trace_explains_routing_packaging_cap_and_retrieval_losses() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-debug')
    candidates = [
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='investigation-selected',
            type='investigation_outcome',
            payload={'investigation_outcome': 'arrival-time ordering caused duplicate holds'},
            freshness_at=datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc),
            score=20,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-selected',
            type='decision',
            payload={'decision': 'use item event time for reservation ordering'},
            freshness_at=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
            score=19,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='checkpoint-selected',
            type='task_checkpoint',
            payload={'summary': 'Resume duplicate-hold follow-up', 'current_state': 'Need validation', 'next_step': 'Verify delayed workers'},
            freshness_at=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
            score=18,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-cap',
            type='decision',
            payload={'decision': 'keep the fallback metric enabled during rollout'},
            freshness_at=datetime(2026, 3, 12, 8, 0, tzinfo=timezone.utc),
            score=17,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        ),
    ]
    loader_items = [
        QueryResultItem(
            result_kind='memory_hit',
            memory_object_id='decision-not-retrieved',
            type='decision',
            payload={'decision': 'capture retry telemetry before rollout'},
            score=0,
            evidence=[],
            container_ref='chat:library-help',
            thread_ref='chat:library-help:thread-debug',
        )
    ]

    cap_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=candidates,
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        include_trace=True,
        debug_candidate_loader=lambda **_: loader_items,
    )
    cap_diagnostics = {item['result_id']: item for item in cap_outcome.sharp_candidate_diagnostics}
    assert any(item['loss_stage'] == 'injection_cap' for item in cap_diagnostics.values())
    assert cap_diagnostics['memory_object:decision-not-retrieved']['loss_stage'] == 'retrieval'

    routing_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=2,
        retrieval_result=RetrievalQueryResult(
            results=candidates,
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=2,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        include_trace=True,
    )
    routing_diagnostics = {item['result_id']: item for item in routing_outcome.sharp_candidate_diagnostics}
    assert any(item['loss_stage'] == 'routing' for item in routing_diagnostics.values())

    packaging_outcome = plugin.route_query_results(
        text='What had we concluded about duplicate holds?',
        requested_limit=4,
        retrieval_result=RetrievalQueryResult(
            results=candidates[:3],
            trace=QueryTrace(
                query_text='What had we concluded about duplicate holds?',
                query_tokens=('concluded', 'duplicate', 'holds'),
                limit=4,
                filters=query_filters,
                stages=(),
            ),
        ),
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(
            turn_kind='same_thread_continuation',
            session_has_sufficient_local_context=True,
        ),
        include_trace=True,
    )
    packaging_diagnostics = {item['result_id']: item for item in packaging_outcome.sharp_candidate_diagnostics}
    assert packaging_outcome.decision_reason == 'same_thread_context_sufficient'
    assert any(item['loss_stage'] == 'packaging' for item in packaging_diagnostics.values())
