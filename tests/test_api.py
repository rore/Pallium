from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from providers.llm.base import LLMJsonResponse, LLMProviderError


class StubLLMProvider:
    def __init__(self, parsed_json: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._parsed_json = parsed_json
        self._error = error

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if self._error is not None:
            raise self._error
        assert self._parsed_json is not None
        return LLMJsonResponse(raw_text=str(self._parsed_json), parsed_json=self._parsed_json)


def test_post_items_returns_pending_and_raw_index_only(client) -> None:
    response = client.post(
        "/items",
        json={
            "source_type": "chat_thread",
            "source_id": "thread-123-msg-1",
            "content_type": "text/plain",
            "content": "We should use item event time for reservation ordering. It avoids missed hold updates.",
            "metadata": {"topic": "reservation ordering"},
            "artifact_kind": "message",
            "role": "user",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert payload["annotation_ids"] == []
    assert payload["memory_object_ids"] == []
    assert payload["relation_ids"] == []
    assert len(payload["index_entry_ids"]) == 1
    assert payload["processing_status"] == "pending"
    assert payload["processing_attempts"] == 0
    assert payload["processing_error"] is None


def test_post_items_is_idempotent_and_returns_current_processing_snapshot(client, drain_queue) -> None:
    request = {
        "source_type": "decision_note",
        "source_id": "decision-1",
        "content_type": "text/plain",
        "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "thread_ref": "thread-1",
        "session_ref": "session-1",
    }

    first_response = client.post("/items", json=request)
    drain_queue(client)
    second_response = client.post("/items", json=request)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["processing_status"] == "pending"
    assert second_response.json()["processing_status"] == "completed"
    assert len(second_response.json()["annotation_ids"]) == 2
    assert len(second_response.json()["memory_object_ids"]) == 1
    assert second_response.json()["processing_attempts"] == 1


def test_get_processing_endpoint_reflects_status_after_worker_completion(client, drain_queue) -> None:
    create_response = client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-status-1",
            "content_type": "text/plain",
            "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        },
    )
    source_item_id = create_response.json()["source_item_id"]

    pending = client.get(f"/items/{source_item_id}/processing")
    assert pending.status_code == 200
    assert pending.json()["processing_status"] == "pending"
    assert pending.json()["memory_object_ids"] == []

    drain_queue(client)

    completed = client.get(f"/items/{source_item_id}/processing")
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["processing_status"] == "completed"
    assert payload["processing_attempts"] == 1
    assert payload["processing_completed_at"] is not None
    assert payload["memory_object_ids"]


def test_raw_source_is_queryable_before_worker_completion_and_memory_after(client, drain_queue) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-query-1",
            "content_type": "text/plain",
            "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "thread-query",
        },
    )

    before = client.post(
        "/query",
        json={"text": "what did we decide about reservation ordering?", "limit": 5, "artifact_kind": "assistant_output"},
    )
    assert before.status_code == 200
    assert any(item["result_kind"] == "source_hit" for item in before.json()["results"])
    assert not any(item["result_kind"] == "memory_hit" for item in before.json()["results"])

    drain_queue(client)

    after = client.post(
        "/query",
        json={"text": "what did we decide about reservation ordering?", "limit": 5, "artifact_kind": "assistant_output"},
    )
    assert after.status_code == 200
    assert any(item["result_kind"] == "memory_hit" for item in after.json()["results"])
    assert any(item["result_kind"] == "source_hit" for item in after.json()["results"])


def test_missing_required_visibility_creates_skipped_not_pending(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubLLMProvider(
            {
                "summary": "Prior assistant conclusion about reservation ordering.",
                "candidate_type": "decision",
                "decision_text": "use item item event time reservation ordering for reservation ordering",
                "decision_evidence_text": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": "to avoid missed hold updates",
            }
        ),
    )
    scoped_client = TestClient(
        create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="agent_conversation_memory",
                llm_provider="openai_compatible",
                llm_model="fake-model",
                llm_base_url="http://fake-provider.local",
                llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
            )
        )
    )

    response = scoped_client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "missing-visibility-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "skipped"
    assert payload["memory_object_ids"] == []


def test_query_debug_returns_named_text_views_after_processing(client, drain_queue) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-debug-1",
            "content_type": "text/plain",
            "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        },
    )
    drain_queue(client)

    response = client.post(
        "/query/debug",
        json={"text": "what did we decide about reservation ordering?", "limit": 5, "artifact_kind": "assistant_output"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) >= 2
    stage = payload["trace"]["stages"][0]
    assert any(hit["text_view_name"] == "memory_object.decision_context" for hit in stage["selected_hits"])
    assert any(hit["text_view_name"] == "source_item.content" for hit in stage["selected_hits"])


def test_llm_plugin_path_processes_after_worker_completion(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubLLMProvider(
            {
                "summary": "Investigation summary about reservation ordering.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "arrival-time ordering missed hold updates during sync delays",
                "investigation_evidence_text": "Investigation found that arrival-time ordering missed hold updates during sync delays.",
                "rationale_text": "because the catalog provider delivered updates late",
            }
        ),
    )
    llm_client = TestClient(
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

    create_response = llm_client.post(
        "/items",
        json={
            "source_type": "investigation_summary",
            "source_id": "investigation-llm-1",
            "content_type": "text/plain",
            "content": "An LLM should identify this as an investigation outcome about reservation ordering.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["processing_status"] == "pending"

    llm_client.app.state.pallium_service.drain_processing_queue(worker_id="llm-test")
    status_response = llm_client.get(f"/items/{create_response.json()['source_item_id']}/processing")
    assert status_response.json()["processing_status"] == "completed"
    assert len(status_response.json()["annotation_ids"]) == 2


def test_worker_failure_is_reported_via_processing_endpoint(monkeypatch, test_db_url: str) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: StubLLMProvider(error=LLMProviderError("provider failed")),
    )
    llm_client = TestClient(
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

    create_response = llm_client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-llm-error-1",
            "content_type": "text/plain",
            "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates.",
        },
    )
    assert create_response.status_code == 200

    llm_client.app.state.pallium_service.drain_processing_queue(worker_id="llm-test", max_attempts=1)
    status_response = llm_client.get(f"/items/{create_response.json()['source_item_id']}/processing")
    assert status_response.status_code == 200
    assert status_response.json()["processing_status"] == "failed"
    assert status_response.json()["processing_error"] == "provider failed"
