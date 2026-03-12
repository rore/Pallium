from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


SCENARIO_FILE = Path('evals/consolidation/scenarios.json')


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
    return scenario


def _query(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post('/query', json=payload)
    assert response.status_code == 200
    return response.json()


def test_thread_local_strategy_groups_only_same_thread_and_creates_continuity_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'thread-local-safe')
        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_local_carry_forward',
        )

        assert result is not None
        assert len(result.groups) == 1
        group = result.groups[0]
        assert len({item for item in group.candidate_thread_refs if item}) == 1
        assert group.created_memory_types == ('continuity_memory',)


def test_container_topic_window_strategy_can_merge_cross_thread_related_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'cross-thread-linked')
        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )

        assert result is not None
        assert len(result.groups) >= 1
        group = result.groups[0]
        assert len({item for item in group.candidate_thread_refs if item}) >= 2
        assert 'pattern_memory' in group.created_memory_types


def test_thread_summary_anchored_strategy_anchors_on_thread_summary(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'cross-thread-linked')
        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_summary_anchored',
        )

        assert result is not None
        assert result.groups
        group = result.groups[0]
        storage = client.app.state.pallium_service._storage
        selected_types = {storage.get_memory_object(memory_id).type for memory_id in group.selected_candidate_ids}
        assert 'thread_summary' in selected_types


def test_unrelated_same_container_thread_does_not_false_merge(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'same-container-noise-guard')
        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='container_topic_window',
        )
        assert result is not None

        payload = _query(client, scenario['current_query'])
        pattern_hits = [
            item for item in payload['results']
            if item['result_kind'] == 'memory_hit' and item['type'] == 'pattern_memory'
        ]
        pattern_text = ' '.join(json.dumps(item['payload']).lower() for item in pattern_hits)
        for term in scenario['unexpected_terms']:
            assert term.lower() not in pattern_text


def test_continuity_memory_preserves_evidence_and_query_integration(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        scenario = _ingest_prior_events(client, 'thread-local-safe')
        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_local_carry_forward',
        )
        continuity_id = result.groups[0].created_memory_ids[0]

        continuity_memory = client.app.state.pallium_service._storage.get_memory_object(continuity_id)
        assert continuity_memory.type == 'continuity_memory'
        assert continuity_memory.payload['consolidation_provenance']['memory_kind'] == 'continuity_memory'

        evidence = client.app.state.pallium_service._storage.get_evidence_for_memory_object(continuity_id)
        assert len(evidence) == 3

        payload = _query(client, scenario['current_query'])
        memory_types = {
            item['type']
            for item in payload['results']
            if item['result_kind'] == 'memory_hit'
        }
        assert 'continuity_memory' in memory_types
        assert 'decision' in memory_types
        assert 'investigation_outcome' in memory_types


def test_rebuilding_same_group_supersedes_older_continuity_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest_prior_events(client, 'thread-local-safe')
        first = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_local_carry_forward',
        )
        first_continuity_id = first.groups[0].created_memory_ids[0]

        extra_event = {
            'source_type': 'assistant_artifact',
            'source_id': 'cons-thread-1-artifact-3',
            'content_type': 'text/plain',
            'content': 'Investigation found that duplicate-hold corrections also required replaying delayed sync jobs.',
            'artifact_kind': 'assistant_output',
            'role': 'assistant',
            'container_ref': 'chat:library-help',
            'thread_ref': 'chat:library-help:thread-cons-001',
            'session_ref': 'agent-session-cons-001',
            'actor_ref': 'agent:assistant',
            'source_ref': 'memory://consolidation/thread-1-artifact-3',
            'occurred_at': '2026-03-10T08:03:00Z',
            'metadata': {'topic': 'reservation_ordering'},
        }
        response = client.post('/items', json=extra_event)
        assert response.status_code == 200

        second = client.app.state.pallium_service.run_consolidation_pass(
            use_case='agent_conversation_memory',
            strategy_name='thread_local_carry_forward',
        )
        second_continuity_id = second.groups[0].created_memory_ids[0]

        assert first_continuity_id != second_continuity_id
        first_continuity = client.app.state.pallium_service._storage.get_memory_object(first_continuity_id)
        second_continuity = client.app.state.pallium_service._storage.get_memory_object(second_continuity_id)
        assert first_continuity.lifecycle == 'superseded'
        assert second_continuity.lifecycle == 'active'


def test_task_checkpoint_preserves_work_state_and_evidence(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        for payload in (
            {
                'source_type': 'chat_message',
                'source_id': 'task-checkpoint-msg-1',
                'content_type': 'text/plain',
                'content': 'The catalog sync retry is queued again.',
                'artifact_kind': 'message',
                'role': 'user',
                'container_ref': 'chat:library-help',
                'thread_ref': 'chat:library-help:thread-task-checkpoint-001',
                'session_ref': 'agent-session-task-checkpoint-001',
            },
            {
                'source_type': 'assistant_artifact',
                'source_id': 'task-checkpoint-artifact-1',
                'content_type': 'text/plain',
                'content': 'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
                'artifact_kind': 'tool_use_summary',
                'role': 'assistant',
                'container_ref': 'chat:library-help',
                'thread_ref': 'chat:library-help:thread-task-checkpoint-001',
                'session_ref': 'agent-session-task-checkpoint-001',
            },
            {
                'source_type': 'assistant_artifact',
                'source_id': 'task-checkpoint-artifact-2',
                'content_type': 'text/plain',
                'content': 'Blocked: catalog API returned 401 because the service token expired.',
                'artifact_kind': 'tool_use_summary',
                'role': 'assistant',
                'container_ref': 'chat:library-help',
                'thread_ref': 'chat:library-help:thread-task-checkpoint-001',
                'session_ref': 'agent-session-task-checkpoint-001',
            },
            {
                'source_type': 'assistant_artifact',
                'source_id': 'task-checkpoint-artifact-3',
                'content_type': 'text/plain',
                'content': 'Next step: refresh the catalog service token and rerun the sync from batch 313.',
                'artifact_kind': 'todo_snapshot',
                'role': 'assistant',
                'container_ref': 'chat:library-help',
                'thread_ref': 'chat:library-help:thread-task-checkpoint-001',
                'session_ref': 'agent-session-task-checkpoint-001',
            },
        ):
            response = client.post('/items', json=payload)
            assert response.status_code == 200

        storage = client.app.state.pallium_service._storage
        checkpoints = storage.list_memory_objects(memory_types=['task_checkpoint'], lifecycle='active')
        assert len(checkpoints) == 1

        checkpoint = checkpoints[0]
        assert checkpoint.payload['task'] == 'Resume the catalog sync retry.'
        assert '312 reservation records' in checkpoint.payload['current_state']
        assert checkpoint.payload['blocker_state'] == 'Catalog API returned 401 because the service token expired.'
        assert checkpoint.payload['next_step'] == 'Refresh the catalog service token and rerun the sync from batch 313.'
        assert any('service token expired' in item for item in checkpoint.payload['evidence'])
        assert checkpoint.payload['semantic_provenance']['semantic_plugin'] == 'agent_conversation_memory'
        assert checkpoint.payload['semantic_provenance']['prompt_schema_id'] == 'task_checkpoint_extraction'

        evidence = storage.get_evidence_for_memory_object(checkpoint.id)
        assert len(evidence) == 4

        payload = _query(
            client,
            {
                'text': 'What blocker did we hit, what progress was preserved, and what should we do next on the catalog sync retry?',
                'limit': 6,
                'container_ref': 'chat:library-help',
            },
        )
        assert payload['results'][0]['result_kind'] == 'memory_hit'
        assert payload['results'][0]['type'] == 'task_checkpoint'

