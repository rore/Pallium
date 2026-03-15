from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from providers.llm.base import LLMJsonResponse, LLMProviderError
from tests.stub_providers import TieredMemorySemanticProvider


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



def _agent_conversation_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    client = TestClient(
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
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "visibility_context" not in payload:
            payload = dict(payload)
            payload["visibility_context"] = {"kind": "public", "id": None}
            kwargs["json"] = payload
        response = original_post(url, *args, **kwargs)
        if url == "/items" and response.status_code == 200:
            client.app.state.pallium_service.drain_processing_queue(worker_id="api-contract-test")
        return response

    client.post = post_with_public_visibility
    return client


def test_query_returns_injection_contract_with_runtime_context(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "api-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-1",
            "session_ref": "session:api-1",
        },
    )

    response = client.post(
        "/query",
        json={
            "text": "what did we decide about reservation ordering?",
            "limit": 5,
            "container_ref": "chat:api",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert all(item["result_id"] for item in payload["results"])
    assert payload["injectable_blocks"][0]["result_id"].startswith(("memory_object:", "source_item:"))


def test_query_same_thread_context_sufficient_suppresses_injection(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "api-decision-2",
            "content_type": "text/plain",
            "content": "Decision: keep the reservation ordering fix behind the use_item_event_time flag.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-2",
            "session_ref": "session:api-2",
        },
    )

    response = client.post(
        "/query",
        json={
            "text": "what did we decide about reservation ordering?",
            "limit": 5,
            "container_ref": "chat:api",
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert payload["should_inject"] is False
    assert payload["decision_reason"] == "same_thread_context_sufficient"
    assert payload["injectable_blocks"] == []


def test_query_fallback_plugin_reports_injection_policy_unavailable(client, drain_queue) -> None:
    client.post(
        "/items",
        json={
            "source_type": "note",
            "source_id": "fallback-query-1",
            "content_type": "text/plain",
            "content": "Use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
        },
    )
    drain_queue(client)

    response = client.post(
        "/query",
        json={
            "text": "reservation ordering",
            "limit": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert payload["should_inject"] is False
    assert payload["decision_reason"] == "injection_policy_unavailable"
    assert payload["injectable_blocks"] == []


def test_query_broad_recall_does_not_inject_raw_source_blocks_by_default(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "api-broad-recall-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-broad-recall",
            "session_ref": "session:api-broad-recall",
        },
    )

    response = client.post(
        "/query",
        json={
            "text": "what should we remember about reservation ordering after sync delays?",
            "limit": 5,
            "container_ref": "chat:api",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert any(item["result_kind"] == "source_hit" for item in payload["results"])
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert payload["injectable_blocks"][0]["block_type"] == "memory"
    assert all(block["block_type"] == "memory" for block in payload["injectable_blocks"])



def test_query_debug_exposes_injection_decision_and_sharp_candidate_diagnostics(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "api-debug-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering reused stale hold updates during delayed sync.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-debug",
            "session_ref": "session:api-debug",
        },
    )

    response = client.post(
        "/query/debug",
        json={
            "text": "what had we concluded about duplicate holds?",
            "limit": 5,
            "container_ref": "chat:api",
            "runtime_context": {
                "turn_kind": "resumed_session",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    routing = payload["trace"]["routing"]
    assert routing["injection_decision"]["decision_reason"] == "carry_forward_available"
    assert routing["sharp_candidate_diagnostics"]
    assert any(item["candidate_kind"] in {"investigation_outcome", "decision", "task_checkpoint"} for item in routing["sharp_candidate_diagnostics"])
