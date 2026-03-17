from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject
from core.visibility import VisibilityContext
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
        "/query/debug",
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



def _ingest_cross_thread_catalog_history(client: TestClient) -> tuple[str, str, str]:
    container_ref = "chat:team:operations"
    old_thread_ref = "chat:team:operations:thread-history"
    old_session_ref = "session:operations-history"
    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "history-msg-1",
            "content_type": "text/plain",
            "content": "Can you summarize the latest catalog sync retry work for the operations channel?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": old_thread_ref,
            "session_ref": old_session_ref,
            "occurred_at": "2026-03-11T09:58:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "history-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: refreshed 312 reservation records before the catalog sync tool failed.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": old_thread_ref,
            "session_ref": old_session_ref,
            "occurred_at": "2026-03-11T10:00:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "history-artifact-2",
            "content_type": "text/plain",
            "content": "Blocked: catalog API returned 401 because the service token expired.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": old_thread_ref,
            "session_ref": old_session_ref,
            "occurred_at": "2026-03-11T10:01:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "history-msg-2",
            "content_type": "text/plain",
            "content": "Please remember not to sign in to the admin portal or open a local browser.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": old_thread_ref,
            "session_ref": old_session_ref,
            "occurred_at": "2026-03-11T10:01:30Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "history-artifact-3",
            "content_type": "text/plain",
            "content": "Next step: refresh the catalog service token and rerun the sync from batch 313.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": old_thread_ref,
            "session_ref": old_session_ref,
            "occurred_at": "2026-03-11T10:02:00Z",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, old_thread_ref)
    active_memory = [
        memory
        for source_item in thread_items
        for memory in storage.list_memory_objects_for_source_item(source_item.id)
        if memory.lifecycle == "active"
    ]
    assert any(memory.type == "thread_summary" for memory in active_memory)
    assert any(memory.type == "task_checkpoint" for memory in active_memory)
    return container_ref, old_thread_ref, old_session_ref

def _ingest_conflicting_cross_thread_catalog_history(client: TestClient) -> tuple[str, str, str]:
    container_ref, old_thread_ref, old_session_ref = _ingest_cross_thread_catalog_history(client)
    conflict_thread_ref = "chat:team:operations:thread-conflicting-history"
    conflict_session_ref = "session:operations-conflicting-history"
    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "conflict-msg-1",
            "content_type": "text/plain",
            "content": "Can you summarize the newer catalog export work after the external workspace stopped responding?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T11:00:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "conflict-artifact-1",
            "content_type": "text/plain",
            "content": "Blocked: the external workspace is unavailable until portal access is restored.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T11:01:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "conflict-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: sign in to the admin portal and reconnect the external workspace once access is restored.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T11:02:00Z",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200
    return container_ref, old_thread_ref, old_session_ref



def _ingest_compatible_cross_thread_catalog_follow_up(client: TestClient) -> tuple[str, str, str]:
    container_ref, old_thread_ref, old_session_ref = _ingest_cross_thread_catalog_history(client)
    follow_up_thread_ref = "chat:team:operations:thread-compatible-history"
    follow_up_session_ref = "session:operations-compatible-history"
    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "compatible-msg-1",
            "content_type": "text/plain",
            "content": "Can you summarize the newer compatible catalog export status?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": follow_up_thread_ref,
            "session_ref": follow_up_session_ref,
            "occurred_at": "2026-03-11T11:10:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "compatible-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: validated the export manifest locally after the workspace timeout.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": follow_up_thread_ref,
            "session_ref": follow_up_session_ref,
            "occurred_at": "2026-03-11T11:11:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "compatible-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: refresh the local export token and rerun the validation from batch 313 without using the admin portal or a local browser.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": follow_up_thread_ref,
            "session_ref": follow_up_session_ref,
            "occurred_at": "2026-03-11T11:12:00Z",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200
    return container_ref, old_thread_ref, old_session_ref


def _ingest_newer_constraint_cross_thread_catalog_history(client: TestClient) -> tuple[str, str]:
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)
    newer_constraint_thread_ref = "chat:team:operations:thread-newer-constraint-history"
    newer_constraint_session_ref = "session:operations-newer-constraint-history"
    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "newer-constraint-msg-1",
            "content_type": "text/plain",
            "content": "Can you summarize the latest safe local status for the catalog export retry?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": newer_constraint_thread_ref,
            "session_ref": newer_constraint_session_ref,
            "occurred_at": "2026-03-11T11:20:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "newer-constraint-msg-2",
            "content_type": "text/plain",
            "content": "Please preserve this newer constraint: use only local diagnostics and do not reconnect the remote workspace.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": newer_constraint_thread_ref,
            "session_ref": newer_constraint_session_ref,
            "occurred_at": "2026-03-11T11:21:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "newer-constraint-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: local diagnostics confirmed the export manifest is intact.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": newer_constraint_thread_ref,
            "session_ref": newer_constraint_session_ref,
            "occurred_at": "2026-03-11T11:22:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "newer-constraint-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: refresh the local export token and rerun the validation without reconnecting the remote workspace.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": newer_constraint_thread_ref,
            "session_ref": newer_constraint_session_ref,
            "occurred_at": "2026-03-11T11:23:00Z",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, newer_constraint_thread_ref)
    checkpoint = next(
        memory
        for source_item in thread_items
        for memory in storage.list_memory_objects_for_source_item(source_item.id)
        if memory.lifecycle == "active" and memory.type == "task_checkpoint"
    )
    return container_ref, checkpoint.id



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
        "/query/debug",
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
        "/query/debug",
        json={
            "text": "what did we decide about reservation ordering?",
            "limit": 5,
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-2",
            "session_ref": "session:api-2",
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
    assert payload["trace"]["filter_scope_relaxed"] is True
    assert payload["trace"]["filter_scope_reason"] == "same_thread_scope_relaxed_for_local_context_relevance_check"
    assert payload["trace"]["filters"]["thread_ref"] is None
    assert payload["trace"]["filters"]["session_ref"] is None
    assert payload["trace"]["routing"]["injection_decision"]["same_thread_context_evaluation"]["qualifying_result_ids"]





def test_query_same_thread_trivial_local_context_allows_cross_thread_recall(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)
    current_thread_ref = "chat:team:operations:thread-trivial-same-thread"
    current_session_ref = "session:operations-trivial-same-thread"

    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "same-thread-hi",
            "content_type": "text/plain",
            "content": "hi",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": current_thread_ref,
            "session_ref": current_session_ref,
            "occurred_at": "2026-03-11T12:20:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "same-thread-hold",
            "content_type": "text/plain",
            "content": "yes, one second",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": current_thread_ref,
            "session_ref": current_session_ref,
            "occurred_at": "2026-03-11T12:21:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "same-thread-ledger-question",
            "content_type": "text/plain",
            "content": "so what do we know the latest about the catalog sync retry?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": current_thread_ref,
            "session_ref": current_session_ref,
            "occurred_at": "2026-03-11T12:22:00Z",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    response = client.post(
        "/query/debug",
        json={
            "text": "so what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": current_thread_ref,
            "session_ref": current_session_ref,
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    trace = payload["trace"]
    routing = trace["routing"]
    injection = routing["injection_decision"]
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])

    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert trace["filter_scope_relaxed"] is True
    assert trace["filter_scope_reason"] == "same_thread_scope_relaxed_for_local_context_relevance_check"
    assert trace["requested_filters"]["thread_ref"] == current_thread_ref
    assert trace["requested_filters"]["session_ref"] == current_session_ref
    assert trace["filters"]["thread_ref"] is None
    assert trace["filters"]["session_ref"] is None
    assert injection["same_thread_context_evaluation"]["reason_code"] == "insufficient_same_thread_local_state"
    assert injection["same_thread_context_evaluation"]["external_carry_forward_result_ids"]
    assert routing["selected_layer"] != "source_evidence"
    assert any(block["memory_type"] in {"task_checkpoint", "thread_summary"} for block in payload["injectable_blocks"])
    assert ("batch 313" in rendered_blocks or "service token expired" in rendered_blocks)
    assert "admin portal" in rendered_blocks or "local browser" in rendered_blocks
    returned_block_ids = {block["result_id"] for block in payload["injectable_blocks"]}
    assert "source_item:same-thread-hi" not in returned_block_ids
    assert "source_item:same-thread-hold" not in returned_block_ids
    assert "source_item:same-thread-ledger-question" not in returned_block_ids

def test_query_new_thread_cross_thread_recall_relaxes_thread_session_filters(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)
    fresh_thread_ref = "chat:team:operations:thread-fresh"
    fresh_session_ref = "session:operations-fresh"

    response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    trace = payload["trace"]
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert any(block["memory_type"] in {"task_checkpoint", "thread_summary"} for block in payload["injectable_blocks"])
    assert any("batch 313" in block["text"].lower() or "service token expired" in block["text"].lower() for block in payload["injectable_blocks"])
    assert any("admin portal" in block["text"].lower() or "local browser" in block["text"].lower() for block in payload["injectable_blocks"])
    assert trace["requested_filters"]["thread_ref"] == fresh_thread_ref
    assert trace["requested_filters"]["session_ref"] == fresh_session_ref
    assert trace["filters"]["container_ref"] == container_ref
    assert trace["filters"]["thread_ref"] is None
    assert trace["filters"]["session_ref"] is None
    assert trace["filter_scope_relaxed"] is True
    assert trace["filter_scope_reason"] == "fresh_thread_scope_relaxed_for_cross_thread_recall"
    assert trace["routing"]["selected_layer"] != "source_evidence"



def test_query_new_thread_constraint_recall_uses_structured_memory(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what constraint had I given you about admin portal sign-in and browser use?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-constraint",
            "session_ref": "session:operations-fresh-constraint",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert any("admin portal" in block["text"].lower() or "local browser" in block["text"].lower() for block in payload["injectable_blocks"])
    assert payload["trace"]["routing"]["selected_layer"] != "source_evidence"
    assert all(block["block_type"] == "memory" for block in payload["injectable_blocks"] )

def test_query_debug_replay_keeps_structured_recall_after_new_thread_contamination(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)
    fresh_thread_ref = "chat:team:operations:thread-fresh-contaminated"
    fresh_session_ref = "session:operations-fresh-contaminated"

    initial_response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert initial_response.status_code == 200
    assert all(block["block_type"] == "memory" for block in initial_response.json()["injectable_blocks"])

    duplicate_question = client.post(
        "/items",
        json={
            "source_type": "chat_message",
            "source_id": "duplicate-recall-question",
            "content_type": "text/plain",
            "content": "What do we know the latest about the catalog sync retry?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-old-duplicate",
            "session_ref": "session:operations-old-duplicate",
            "occurred_at": "2026-03-11T10:03:30Z",
        },
    )
    current_question = client.post(
        "/items",
        json={
            "source_type": "chat_message",
            "source_id": "fresh-recall-question",
            "content_type": "text/plain",
            "content": "What do we know the latest about the catalog sync retry?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "occurred_at": "2026-03-11T10:04:00Z",
        },
    )
    capability_note = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "fresh-capability-note",
            "content_type": "text/plain",
            "content": "Capabilities: I can help summarize the latest catalog sync status and search records if needed.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "occurred_at": "2026-03-11T10:04:10Z",
        },
    )
    heartbeat_note = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "fresh-heartbeat-note",
            "content_type": "text/plain",
            "content": "Heartbeat: still monitoring the catalog sync retry for the operations channel.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "occurred_at": "2026-03-11T10:04:20Z",
        },
    )
    assert duplicate_question.status_code == 200
    assert current_question.status_code == 200
    assert capability_note.status_code == 200
    assert heartbeat_note.status_code == 200

    replay_response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert replay_response.status_code == 200
    payload = replay_response.json()
    routing = payload["trace"]["routing"]
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert payload["injectable_blocks"]
    assert all(block["block_type"] == "memory" for block in payload["injectable_blocks"])
    assert any("admin portal" in block["text"].lower() or "local browser" in block["text"].lower() for block in payload["injectable_blocks"])
    assert routing["selected_layer"] != "source_evidence"
    contaminated_result_ids = {
        duplicate_question.json()["source_item_id"],
        current_question.json()["source_item_id"],
        capability_note.json()["source_item_id"],
        heartbeat_note.json()["source_item_id"],
    }
    assert not contaminated_result_ids.intersection({item["source_item_id"] for item in payload["results"] if item["result_kind"] == "source_hit"})
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])
    assert "capabilities:" not in rendered_blocks
    assert "heartbeat:" not in rendered_blocks
    assert "what do we know the latest about the catalog sync retry" not in rendered_blocks


def test_query_debug_broad_recall_excludes_conflicting_structured_checkpoint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_conflicting_cross_thread_catalog_history(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-conflict",
            "session_ref": "session:operations-fresh-conflict",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    routing = payload["trace"]["routing"]
    excluded = {item["excluded_reason_code"] for item in routing["excluded_high_scoring_candidates"]}
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert any("admin portal" in block["text"].lower() or "local browser" in block["text"].lower() for block in payload["injectable_blocks"])
    assert "next step: sign in to the admin portal" not in rendered_blocks
    assert "authenticate to the admin portal to refresh the export summary" not in rendered_blocks
    assert "reconnect the external workspace" not in rendered_blocks
    assert "current fresh-thread query" not in rendered_blocks
    assert "conflicts_with_active_constraint" in excluded
    assert routing["packaging"]["mode"] == "compatible_structured_recall"
    assert routing["packaging"]["active_constraint_profile"]["constraint_text"]



def test_query_debug_constraint_recall_excludes_conflicting_structured_checkpoint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_conflicting_cross_thread_catalog_history(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what constraint had I given you about admin portal sign-in and browser use?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-conflict-constraint",
            "session_ref": "session:operations-fresh-conflict-constraint",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])
    assert payload["should_inject"] is True
    assert payload["decision_reason"] == "carry_forward_available"
    assert "admin portal" in rendered_blocks
    assert "local browser" in rendered_blocks
    assert "next step: sign in to the admin portal" not in rendered_blocks
    assert "authenticate to the admin portal to refresh the export summary" not in rendered_blocks
    assert payload["trace"]["routing"]["packaging"]["constraint_anchor_result_id"].startswith("memory_object:")



def test_processing_reconciles_conflicting_new_checkpoint_against_active_constraint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_cross_thread_catalog_history(client)
    fresh_thread_ref = "chat:team:operations:thread-fresh-generated-conflict"
    fresh_session_ref = "session:operations-fresh-generated-conflict"

    response = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "fresh-conflicting-answer",
            "content_type": "text/plain",
            "content": "Current state: the export summary is ready. Next step: sign in to the admin portal and reconnect the external workspace once access returns.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "occurred_at": "2026-03-11T12:00:00Z",
        },
    )
    assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, fresh_thread_ref)
    checkpoints = [
        memory
        for source_item in thread_items
        for memory in storage.list_memory_objects_for_source_item(source_item.id)
        if memory.lifecycle == "active" and memory.type == "task_checkpoint"
    ]
    assert checkpoints
    checkpoint_payload = checkpoints[-1].payload
    assert "sign in to the admin portal" not in str(checkpoint_payload.get("next_step") or "").lower()
    assert "admin portal" in str(checkpoint_payload.get("blocker_state") or "").lower()
    assert checkpoint_payload.get("semantic_provenance", {}).get("constraint_reconciliation")

    query_response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-after-reconcile",
            "session_ref": "session:operations-fresh-after-reconcile",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert query_response.status_code == 200
    rendered_blocks = " ".join(block["text"].lower() for block in query_response.json()["injectable_blocks"])
    assert "next step: sign in to the admin portal" not in rendered_blocks
    assert "authenticate to the admin portal to refresh the export summary" not in rendered_blocks



def test_query_debug_keeps_compatible_newer_status_beside_constraint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_compatible_cross_thread_catalog_follow_up(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-compatible",
            "session_ref": "session:operations-fresh-compatible",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])
    assert payload["should_inject"] is True
    assert "admin portal" in rendered_blocks
    assert "refresh the local export token" in rendered_blocks
    assert payload["trace"]["routing"]["packaging"]["mode"] == "compatible_structured_recall"


def _seed_active_constraint_profiles(client: TestClient) -> tuple[str, str]:
    storage = client.app.state.pallium_service._storage
    container_ref = "chat:team:operations"
    visibility = VisibilityContext(kind="public", id=None)
    older_constraint = MemoryObject(
        type="task_checkpoint",
        schema_id="agent_conversation_memory.task_checkpoint",
        schema_version="v1",
        payload={
            "summary": "Older carry-forward status with a browser restriction.",
            "task": "Resume the catalog sync retry.",
            "current_state": "Use local retries only.",
            "blocker_state": "Do not sign in to the admin portal or open a local browser.",
            "next_step": "Refresh the local token and continue offline.",
            "evidence": ["Constraint: do not sign in to the admin portal or open a local browser."],
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-older-constraint",
            "session_ref": "session:older-constraint",
        },
        visibility_context=visibility,
        freshness_at=datetime(2026, 3, 11, 10, 2, tzinfo=timezone.utc),
    )
    newer_constraint = MemoryObject(
        type="task_checkpoint",
        schema_id="agent_conversation_memory.task_checkpoint",
        schema_version="v1",
        payload={
            "summary": "Newer carry-forward status with a stricter portal restriction.",
            "task": "Resume the catalog sync retry.",
            "current_state": "Prior artifacts are ready for review.",
            "blocker_state": "Do not authenticate to the admin portal while resuming this task.",
            "next_step": "",
            "evidence": ["Constraint: do not authenticate to the admin portal; use only local export snapshots."],
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-newer-constraint",
            "session_ref": "session:newer-constraint",
        },
        visibility_context=visibility,
        freshness_at=datetime(2026, 3, 11, 11, 30, tzinfo=timezone.utc),
    )
    storage.create_memory_object(older_constraint)
    storage.create_memory_object(newer_constraint)
    return container_ref, newer_constraint.id



def test_processing_reconciliation_prefers_fresher_active_constraint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, newer_constraint_checkpoint_id = _seed_active_constraint_profiles(client)
    fresh_thread_ref = "chat:team:operations:thread-fresh-newer-constraint"
    fresh_session_ref = "session:operations-fresh-newer-constraint"

    response = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "fresh-conflicting-answer-newer-constraint",
            "content_type": "text/plain",
            "content": "Current state: the export summary is ready. Next step: authenticate to the admin portal to refresh the export summary.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
            "session_ref": fresh_session_ref,
            "occurred_at": "2026-03-11T12:10:00Z",
        },
    )
    assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, fresh_thread_ref)
    checkpoint = next(
        memory
        for source_item in thread_items
        for memory in storage.list_memory_objects_for_source_item(source_item.id)
        if memory.lifecycle == "active" and memory.type == "task_checkpoint"
    )
    checkpoint_payload = checkpoint.payload
    reconciliation = checkpoint_payload.get("semantic_provenance", {}).get("constraint_reconciliation")

    assert reconciliation is not None
    assert reconciliation["active_constraint_result_id"] == f"memory_object:{newer_constraint_checkpoint_id}"
    assert "use only local export snapshots" in reconciliation["constraint_text"].lower()
    assert "authenticate to the admin portal to refresh the export summary" not in str(checkpoint_payload.get("next_step") or "").lower()
    assert "local export snapshots" in str(checkpoint_payload.get("blocker_state") or "").lower()



def test_query_debug_work_resumption_excludes_conflicting_structured_checkpoint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref, _old_session_ref = _ingest_conflicting_cross_thread_catalog_history(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what blocker did we hit and what should we do next on the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-work-resumption-conflict",
            "session_ref": "session:operations-fresh-work-resumption-conflict",
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    routing = payload["trace"]["routing"]
    excluded = {item["excluded_reason_code"] for item in routing["excluded_high_scoring_candidates"]}
    rendered_blocks = " ".join(block["text"].lower() for block in payload["injectable_blocks"])
    checkpoint_results = [item for item in payload["results"] if item["result_kind"] == "memory_hit" and item.get("type") == "task_checkpoint"]
    assert payload["should_inject"] is True
    assert routing["query_intent"] == "work_resumption"
    assert routing["selected_layer"] == "task_checkpoint"
    assert checkpoint_results
    assert "next step: sign in to the admin portal" not in rendered_blocks
    assert "authenticate to the admin portal to refresh the export summary" not in rendered_blocks
    assert "reconnect the external workspace" not in rendered_blocks
    assert "conflicts_with_active_constraint" in excluded
    assert routing["packaging"]["active_constraint_profile"]["constraint_text"]



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



def _inventory_batch_visibility_context() -> dict[str, str]:
    return {"kind": "limited", "id": "slack:channel:CLOCAL001"}



def _ingest_inventory_batch_polluted_history(client: TestClient) -> dict[str, object]:
    container_ref = "slack:channel:CLOCAL001"
    visibility_context = _inventory_batch_visibility_context()
    threads = {
        "constraint": "slack:thread:CLOCAL001:inventory-batch-constraint",
        "auth_retry_old": "slack:thread:CLOCAL001:inventory-batch-auth-retry-old",
        "auth_retry_new": "slack:thread:CLOCAL001:inventory-batch-auth-retry-new",
        "same_thread": "slack:thread:CLOCAL001:inventory-batch-reminder",
    }
    sessions = {
        "constraint": "agent-session:inventory-batch-constraint",
        "auth_retry_old": "agent-session:inventory-batch-auth-retry-old",
        "auth_retry_new": "agent-session:inventory-batch-auth-retry-new",
        "same_thread": "agent-session:inventory-batch-reminder",
    }
    payloads = (
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-a-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the latest inventory batch digest work for the local channel.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"],
            "session_ref": sessions["constraint"],
            "occurred_at": "2026-03-11T10:00:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-a-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: prepared the inventory batch digest for BIN-103, BIN-204, BIN-317, and BIN-418.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"],
            "session_ref": sessions["constraint"],
            "occurred_at": "2026-03-11T10:01:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-a-msg-2",
            "content_type": "text/plain",
            "content": "Please remember not to try to sign in to the operations portal, and don't open a local browser to log in.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"],
            "session_ref": sessions["constraint"],
            "occurred_at": "2026-03-11T10:01:30Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-a-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: refresh the local digest token and rerun the inventory batch digest from the last confirmed batch.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["constraint"],
            "session_ref": sessions["constraint"],
            "occurred_at": "2026-03-11T10:02:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-b-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the older inventory batch digest blocker.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"],
            "session_ref": sessions["auth_retry_old"],
            "occurred_at": "2026-03-11T11:00:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-b-artifact-0",
            "content_type": "text/plain",
            "content": "Partial progress: batch manifests, channel filters, and digest scheduling are staged.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"],
            "session_ref": sessions["auth_retry_old"],
            "occurred_at": "2026-03-11T11:00:30Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-b-artifact-1",
            "content_type": "text/plain",
            "content": "Blocked: the inventory batch digest is unauthenticated for the remote channel filter.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"],
            "session_ref": sessions["auth_retry_old"],
            "occurred_at": "2026-03-11T11:01:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-b-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: retry the inventory batch digest after authentication is restored.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_old"],
            "session_ref": sessions["auth_retry_old"],
            "occurred_at": "2026-03-11T11:02:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-c-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the newer batch digest blocker.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"],
            "session_ref": sessions["auth_retry_new"],
            "occurred_at": "2026-03-11T12:00:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-c-artifact-0",
            "content_type": "text/plain",
            "content": "Partial progress: built the mirror-based batch digest for the batch manifests.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"],
            "session_ref": sessions["auth_retry_new"],
            "occurred_at": "2026-03-11T12:00:30Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-c-artifact-1",
            "content_type": "text/plain",
            "content": "Blocked: the mirror-based batch digest cannot proceed until remote authentication succeeds.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"],
            "session_ref": sessions["auth_retry_new"],
            "occurred_at": "2026-03-11T12:01:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-c-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: attempt to authenticate to the operations portal and the message console before retrying the inventory batch digest.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["auth_retry_new"],
            "session_ref": sessions["auth_retry_new"],
            "occurred_at": "2026-03-11T12:02:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-d-msg-1",
            "content_type": "text/plain",
            "content": "good morning",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"],
            "session_ref": sessions["same_thread"],
            "occurred_at": "2026-03-11T13:00:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-d-artifact-1",
            "content_type": "text/plain",
            "content": "Good morning. I can help with the latest batch status when you are ready.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"],
            "session_ref": sessions["same_thread"],
            "occurred_at": "2026-03-11T13:00:10Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "chat_message",
            "source_id": "inventory-batch-d-msg-2",
            "content_type": "text/plain",
            "content": "can you remind me what we had latest about batches?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": threads["same_thread"],
            "session_ref": sessions["same_thread"],
            "occurred_at": "2026-03-11T13:00:20Z",
            "visibility_context": visibility_context,
        },
    )
    for payload in payloads:
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    def active_memory(thread_ref: str, memory_type: str) -> list[MemoryObject]:
        return [
            memory
            for source_item in storage.list_source_items_for_thread(container_ref, thread_ref)
            for memory in storage.list_memory_objects_for_source_item(source_item.id)
            if memory.lifecycle == "active" and memory.type == memory_type
        ]

    def rendered_memory(thread_ref: str) -> list[str]:
        rendered: list[str] = []
        for memory_type in ("task_checkpoint", "thread_summary"):
            for memory in active_memory(thread_ref, memory_type):
                payload = memory.payload or {}
                rendered.append(
                    " ".join(
                        [
                            str(payload.get("summary") or ""),
                            str(payload.get("current_state") or ""),
                            str(payload.get("blocker_state") or ""),
                            str(payload.get("next_step") or ""),
                            *[str(value or "") for value in payload.get("key_findings", []) if isinstance(value, str)],
                            *[str(value or "") for value in payload.get("evidence", []) if isinstance(value, str)],
                        ]
                    ).lower()
                )
        return rendered

    constraint_rendered = rendered_memory(threads["constraint"])
    auth_retry_old_rendered = rendered_memory(threads["auth_retry_old"])
    auth_retry_new_rendered = rendered_memory(threads["auth_retry_new"])
    assert any("inventory batch digest" in rendered for rendered in constraint_rendered)
    assert any("local browser" in rendered for rendered in constraint_rendered)
    assert any("authentication is restored" in rendered for rendered in auth_retry_old_rendered)
    assert any("attempting authentication" in rendered or "operations portal and the message console" in rendered for rendered in auth_retry_new_rendered)

    return {
        "container_ref": container_ref,
        "visibility_context": visibility_context,
        "threads": threads,
        "sessions": sessions,
    }



def test_query_debug_inventory_batch_pollution_replay_uses_structured_carry_forward(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    scenario = _ingest_inventory_batch_polluted_history(client)
    container_ref = scenario["container_ref"]
    visibility_context = scenario["visibility_context"]

    greeting_response = client.post(
        "/query/debug",
        json={
            "text": "good morning",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": "slack:thread:CLOCAL001:diag-good-morning-fresh",
            "session_ref": "agent-session:diag-good-morning-fresh",
            "visibility_context": visibility_context,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert greeting_response.status_code == 200
    greeting_payload = greeting_response.json()
    assert greeting_payload["should_inject"] is False
    assert greeting_payload["injectable_blocks"] == []

    same_thread_response = client.post(
        "/query/debug",
        json={
            "text": "can you remind me what we had latest about batches?",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": scenario["threads"]["same_thread"],
            "session_ref": scenario["sessions"]["same_thread"],
            "visibility_context": visibility_context,
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
    )
    assert same_thread_response.status_code == 200
    same_thread_payload = same_thread_response.json()
    same_thread_routing = same_thread_payload["trace"]["routing"]
    same_thread_text = " ".join(block["text"].lower() for block in same_thread_payload["injectable_blocks"])
    assert same_thread_payload["should_inject"] is True
    assert same_thread_payload["decision_reason"] != "same_thread_context_sufficient"
    assert same_thread_routing["query_intent"] == "broad_recall"
    assert same_thread_routing["query_family"] == "broad_recurring_recall"
    assert same_thread_routing["selected_layer"] != "source_evidence"
    assert same_thread_routing["injection_decision"]["same_thread_context_evaluation"]["reason_code"] == "insufficient_same_thread_local_state"
    assert any(block["memory_type"] in {"task_checkpoint", "thread_summary"} for block in same_thread_payload["injectable_blocks"])
    assert "inventory batch digest" in same_thread_text or "last confirmed batch" in same_thread_text
    assert "can you remind me what we had latest about batches" not in same_thread_text
    assert "good morning" not in same_thread_text

    fresh_thread_response = client.post(
        "/query/debug",
        json={
            "text": "can you remind me what we had latest about batches?",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": "slack:thread:CLOCAL001:diag-batch-reminder-fresh",
            "session_ref": "agent-session:diag-batch-reminder-fresh",
            "visibility_context": visibility_context,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert fresh_thread_response.status_code == 200
    fresh_thread_payload = fresh_thread_response.json()
    fresh_thread_routing = fresh_thread_payload["trace"]["routing"]
    fresh_thread_text = " ".join(block["text"].lower() for block in fresh_thread_payload["injectable_blocks"])
    assert fresh_thread_payload["should_inject"] is True
    assert fresh_thread_routing["query_intent"] == "broad_recall"
    assert fresh_thread_routing["query_family"] == "broad_recurring_recall"
    assert fresh_thread_routing["selected_layer"] != "source_evidence"
    assert all(block["block_type"] == "memory" for block in fresh_thread_payload["injectable_blocks"])
    assert "can you remind me what we had latest about batches" not in fresh_thread_text
    assert "good morning" not in fresh_thread_text
    assert "attempt to authenticate" not in fresh_thread_text

    constraint_response = client.post(
        "/query/debug",
        json={
            "text": "what constraint had I given you about operations portal sign-in and browser use?",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": "slack:thread:CLOCAL001:diag-constraint-fresh",
            "session_ref": "agent-session:diag-constraint-fresh",
            "visibility_context": visibility_context,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
    )
    assert constraint_response.status_code == 200
    constraint_payload = constraint_response.json()
    constraint_routing = constraint_payload["trace"]["routing"]
    constraint_text = " ".join(block["text"].lower() for block in constraint_payload["injectable_blocks"])
    excluded = {item["excluded_reason_code"] for item in constraint_routing["excluded_high_scoring_candidates"]}
    assert constraint_payload["should_inject"] is True
    assert constraint_routing["query_intent"] == "broad_recall"
    assert constraint_routing["query_family"] == "broad_recurring_recall"
    assert constraint_routing["selected_layer"] == "task_checkpoint"
    assert "do not try to sign in to the operations portal" in constraint_text
    assert "local browser" in constraint_text
    assert "sign in to the operations portal manually" not in constraint_text
    assert "attempt to authenticate" not in constraint_text
    assert "retry after authentication is restored" not in constraint_text
    assert "conflicts_with_active_constraint" in excluded



def test_processing_reconciles_new_inventory_batch_structured_memory_against_active_constraint(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    scenario = _ingest_inventory_batch_polluted_history(client)
    container_ref = scenario["container_ref"]
    visibility_context = scenario["visibility_context"]
    conflict_thread_ref = "slack:thread:CLOCAL001:inventory-batch-generated-conflict"
    conflict_session_ref = "agent-session:inventory-batch-generated-conflict"

    conflict_payloads = (
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-generated-conflict-constraint",
            "content_type": "text/plain",
            "content": "Constraint reminder: do not try to sign in to the operations portal and don't open a local browser to log in.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T13:05:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-generated-conflict-state",
            "content_type": "text/plain",
            "content": "Partial progress: the inventory batch digest summary is ready for the latest batch manifest group.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T13:06:00Z",
            "visibility_context": visibility_context,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "inventory-batch-generated-conflict-next-step",
            "content_type": "text/plain",
            "content": "Next step: sign in to the operations portal manually, provide a reference code, and retry after authentication is restored.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": conflict_thread_ref,
            "session_ref": conflict_session_ref,
            "occurred_at": "2026-03-11T13:07:00Z",
            "visibility_context": visibility_context,
        },
    )
    for payload in conflict_payloads:
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    storage = client.app.state.pallium_service._storage
    active_structured_memory = [
        memory
        for source_item in storage.list_source_items_for_thread(container_ref, conflict_thread_ref)
        for memory in storage.list_memory_objects_for_source_item(source_item.id)
        if memory.lifecycle == "active" and memory.type in {"task_checkpoint", "thread_summary", "discussion_summary"}
    ]
    assert any(memory.type == "task_checkpoint" for memory in active_structured_memory)
    assert any(memory.type == "thread_summary" for memory in active_structured_memory)

    for memory in active_structured_memory:
        payload = memory.payload or {}
        rendered = " ".join(
            [
                str(payload.get("summary") or ""),
                str(payload.get("current_state") or ""),
                str(payload.get("blocker_state") or ""),
                str(payload.get("next_step") or ""),
                *[str(value or "") for value in payload.get("key_findings", []) if isinstance(value, str)],
                *[str(value or "") for value in payload.get("evidence", []) if isinstance(value, str)],
            ]
        ).lower()
        if memory.type in {"task_checkpoint", "thread_summary"}:
            assert "do not try to sign in to the operations portal" in rendered
            assert "local browser" in rendered
            assert "sign in to the operations portal manually" not in rendered
            assert "retry after authentication is restored" not in rendered
            assert "attempt to authenticate" not in rendered


