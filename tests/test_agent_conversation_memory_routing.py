from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
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
    return TestClient(create_app(build_llm_test_config(default_use_case='agent_conversation_memory', sqlite_url=sqlite_url)))


def _ingest_prior_events(client: TestClient, scenario_id: str) -> dict[str, object]:
    scenario = next(item for item in _load_scenarios() if item['scenario_id'] == scenario_id)
    for event in scenario['prior_events']:
        response = client.post('/items', json=event)
        assert response.status_code == 200
    return scenario


def _run_debug_query(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post('/query/debug', json=payload)
    assert response.status_code == 200
    return response.json()


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
