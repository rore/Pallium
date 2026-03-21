from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.contracts import build_source_item
from core.observability import IntegrationDebugLogger
from core.service import PalliumService
from providers.llm.base import LLMJsonResponse, LLMProviderError
from retrieval.lexical import LexicalRetrievalProvider
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from tests.test_async_worker import BlockingThreadAggregationPlugin, _build_service


class FailingLLMProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        raise LLMProviderError("provider failed")


def test_processing_endpoint_includes_observability_summary_fields(client, drain_queue) -> None:
    create_response = client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-observability-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time ordering so reservation updates are applied deterministically.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        },
    )
    source_item_id = create_response.json()["source_item_id"]

    drain_queue(client)

    response = client.get(f"/items/{source_item_id}/processing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["failure_category"] is None
    assert payload["annotation_count"] == 2
    assert payload["memory_object_types"] == ["decision"]
    assert payload["thread_rebuild_requested"] is False
    assert payload["thread_rebuild_completed"] is False
    assert payload["produced_memory_provenance"]
    assert payload["produced_memory_provenance"][0]["source_item_ids"] == [source_item_id]


def test_thread_rebuild_completion_is_reported_in_processing_status(test_db_url: str) -> None:
    plugin = BlockingThreadAggregationPlugin()
    service = _build_service(
        test_db_url,
        plugins={"blocking_thread_lease": plugin},
        default_use_case="blocking_thread_lease",
    )
    ingest = service.ingest_item(
        source_type="assistant_artifact",
        source_id="thread-observability-1",
        content_type="text/plain",
        content="Decision: preserve the latest blocker summary in thread memory.",
        metadata=None,
        use_case="blocking_thread_lease",
        artifact_kind="assistant_output",
        role="assistant",
        container_ref="chat:library-help",
        thread_ref="chat:library-help:thread-observability",
        container_visibility="public",
    )
    plugin.allow_first_build_finish.set()
    service.drain_processing_queue(worker_id="thread-observability")

    status = service.get_item_processing(ingest.source_item_id)
    assert status.thread_rebuild_requested is True
    assert status.thread_rebuild_completed is True


def test_queue_health_endpoint_reports_unclaimable_pending_and_recent_failure(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: FailingLLMProvider())
    client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="llm_agent_memory",
                llm_provider="openai_compatible",
                llm_model="fake-model",
                llm_base_url="http://fake-provider.local",
                llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
            )
        )
    )

    orphan = build_source_item(
        source_type="legacy_item",
        source_id="legacy-pending-no-use-case",
        content_type="text/plain",
        content="legacy pending content",
        metadata=None,
        use_case=None,
    )
    client.app.state.pallium_service._storage.create_source_item(orphan)

    create_response = client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "llm-failure-observability-1",
            "content_type": "text/plain",
            "content": "Decision: force the llm plugin failure path.",
        },
    )
    assert create_response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="queue-health", max_attempts=1)

    response = client.get("/debug/queue/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_without_use_case_count"] == 1
    assert {item["reason"]: item["count"] for item in payload["unclaimable_pending_counts"]}["missing_use_case"] == 1
    assert payload["recent_failures"][0]["failure_category"] == "llm_failure"
    assert payload["recent_failures"][0]["processing_error"] == "provider failed"


def test_query_debug_includes_candidate_flow_and_result_summary(client, drain_queue) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-query-trace-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time ordering so reservation updates are applied deterministically.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        },
    )
    drain_queue(client)

    response = client.post(
        "/query/debug",
        json={"text": "what did we decide about ordering?", "limit": 5, "artifact_kind": "assistant_output"},
    )
    assert response.status_code == 200
    payload = response.json()
    stage = payload["trace"]["stages"][0]
    assert stage["candidate_hits_before_visibility"] >= stage["candidate_hits_after_visibility"]
    assert stage["candidate_hits_after_visibility"] >= len(stage["candidate_hits"])
    assert payload["trace"]["result_summary"]["returned_result_count"] == len(payload["results"])
    assert payload["trace"]["result_summary"]["returned_result_kinds"]["memory_hit"] >= 1


def test_integration_debug_logging_is_opt_in(test_db_url: str, capsys) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins={"demo_agent_memory": DemoAgentMemoryPlugin()},
        default_use_case="demo_agent_memory",
        observability=IntegrationDebugLogger(enabled=False),
    )
    ingest = service.ingest_item(
        source_type="decision_note",
        source_id="logging-off-1",
        content_type="text/plain",
        content="Decision: do not emit logs by default.",
        metadata=None,
        use_case="demo_agent_memory",
        artifact_kind="assistant_output",
        role="assistant",
    )
    service.drain_processing_queue(worker_id="logging-off")
    assert service.get_item_processing(ingest.source_item_id).processing_status == "completed"
    assert capsys.readouterr().out == ""

    enabled_db_url = test_db_url.replace("test.db", "logging.db")
    storage_enabled = SQLiteStorageProvider(enabled_db_url)
    service_enabled = PalliumService(
        storage=storage_enabled,
        retrieval=LexicalRetrievalProvider(storage_enabled),
        semantic_plugins={"demo_agent_memory": DemoAgentMemoryPlugin()},
        default_use_case="demo_agent_memory",
        observability=IntegrationDebugLogger(enabled=True),
    )
    ingest_enabled = service_enabled.ingest_item(
        source_type="decision_note",
        source_id="logging-on-1",
        content_type="text/plain",
        content="Decision: emit logs only when explicitly enabled.",
        metadata=None,
        use_case="demo_agent_memory",
        artifact_kind="assistant_output",
        role="assistant",
    )
    service_enabled.drain_processing_queue(worker_id="logging-on")
    assert service_enabled.get_item_processing(ingest_enabled.source_item_id).processing_status == "completed"
    output = capsys.readouterr().out
    assert "source_item_processing_outcome" in output
    assert "memory_creation_provenance" in output
