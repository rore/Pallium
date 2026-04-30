from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.config import AppConfig
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import _vector_index_path_for_sqlite
from app.main import create_app

from evals.continuity_common import compare_query_contract_payloads
from providers.llm.base import LLMJsonResponse, LLMProviderError

from tests.agent_conversation_replay_helpers import (
    _agent_conversation_client,
    _seed_short_noun_isolation_history,
)


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
        json=[{
            "source_type": "chat_thread",
            "source_id": "thread-123-msg-1",
            "content_type": "text/plain",
            "content": "We should use item event time for reservation ordering. It avoids missed hold updates.",
            "metadata": {"topic": "reservation ordering"},
            "artifact_kind": "message",
            "role": "user",
        }],
    )

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["source_item_id"]
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
        "content": "Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync operations.",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "thread_ref": "thread-1",
    }

    first_response = client.post("/items", json=[request])
    drain_queue(client)
    second_response = client.post("/items", json=[request])

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()[0]["processing_status"] == "pending"
    assert second_response.json()[0]["processing_status"] == "completed"
    assert len(second_response.json()[0]["memory_object_ids"]) == 1
    assert second_response.json()[0]["processing_attempts"] == 1


def test_get_processing_endpoint_reflects_status_after_worker_completion(client, drain_queue) -> None:
    create_response = client.post(
        "/items",
        json=[{
            "source_type": "decision_note",
            "source_id": "decision-status-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync delay operations.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        }],
    )
    source_item_id = create_response.json()[0]["source_item_id"]

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
        json=[{
            "source_type": "decision_note",
            "source_id": "decision-query-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync delay operations.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "thread-query",
        }],
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
                vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
            )
        )
    )

    response = scoped_client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "missing-visibility-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        }],
    )
    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["processing_status"] == "skipped"
    assert payload["memory_object_ids"] == []


def test_query_debug_returns_named_text_views_after_processing(client, drain_queue) -> None:
    client.post(
        "/items",
        json=[{
            "source_type": "decision_note",
            "source_id": "decision-debug-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync delay operations.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
        }],
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
    assert any(hit["text_view_name"] == "memory_object.summary" for hit in stage["selected_hits"])
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
                vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
            )
        )
    )

    create_response = llm_client.post(
        "/items",
        json=[{
            "source_type": "investigation_summary",
            "source_id": "investigation-llm-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering missed hold updates during sync delays. The catalog provider delivered updates late.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
        }],
    )
    assert create_response.status_code == 200
    assert create_response.json()[0]["processing_status"] == "pending"

    llm_client.app.state.pallium_service.drain_processing_queue(worker_id="llm-test")
    status_response = llm_client.get(f"/items/{create_response.json()[0]['source_item_id']}/processing")
    assert status_response.json()["processing_status"] == "completed"


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
                vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
            )
        )
    )

    create_response = llm_client.post(
        "/items",
        json=[{
            "source_type": "decision_note",
            "source_id": "decision-llm-error-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering instead of arrival time to avoid missed hold updates during concurrent sync operations.",
        }],
    )
    assert create_response.status_code == 200

    llm_client.app.state.pallium_service.drain_processing_queue(worker_id="llm-test", max_attempts=1)
    status_response = llm_client.get(f"/items/{create_response.json()[0]['source_item_id']}/processing")
    assert status_response.status_code == 200
    assert status_response.json()["processing_status"] == "failed"
    assert status_response.json()["processing_error"] == "provider failed"



def _ingest_cross_thread_catalog_history(client: TestClient) -> tuple[str, str]:
    container_ref = "chat:team:operations"
    old_thread_ref = "chat:team:operations:thread-history"
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
            "occurred_at": "2026-03-11T10:02:00Z",
        },
    ):
        response = client.post("/items", json=[payload])
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
    return container_ref, old_thread_ref


def test_query_returns_injection_contract_with_runtime_context(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "api-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-1",
        }],
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
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "api-decision-2",
            "content_type": "text/plain",
            "content": "Decision: keep the reservation ordering fix behind the use_item_event_time flag.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-2",
        }],
    )

    response = client.post(
        "/query/debug",
        json={
            "text": "what did we decide about reservation ordering?",
            "limit": 5,
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-2",
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
    assert payload["trace"]["routing"]["injection_decision"]["same_thread_context_evaluation"]["qualifying_result_ids"]


def test_query_new_thread_cross_thread_recall_relaxes_thread_session_filters(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref = _ingest_cross_thread_catalog_history(client)
    fresh_thread_ref = "chat:team:operations:thread-fresh"

    response = client.post(
        "/query/debug",
        json={
            "text": "what do we know the latest about the catalog sync retry?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": fresh_thread_ref,
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
    assert trace["filters"]["container_ref"] == container_ref
    assert trace["filters"]["thread_ref"] is None
    assert trace["filter_scope_relaxed"] is True
    assert trace["filter_scope_reason"] == "fresh_thread_scope_relaxed_for_cross_thread_recall"
    # Fresh-thread structured recall preference removed (Task 9); will return in Task 9b.
    # source_evidence may now be selected_layer when retrieval scores favor it.



def test_query_new_thread_constraint_recall_uses_structured_memory(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    container_ref, _old_thread_ref = _ingest_cross_thread_catalog_history(client)

    response = client.post(
        "/query/debug",
        json={
            "text": "what constraint had I given you about admin portal sign-in and browser use?",
            "limit": 6,
            "container_ref": container_ref,
            "thread_ref": "chat:team:operations:thread-fresh-constraint",
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
    # Fresh-thread structured recall preference removed (Task 9); will return in Task 9b.
    # source_evidence may now be selected_layer when retrieval scores favor it.


def test_query_fallback_plugin_reports_injection_policy_unavailable(client, drain_queue) -> None:
    client.post(
        "/items",
        json=[{
            "source_type": "note",
            "source_id": "fallback-query-1",
            "content_type": "text/plain",
            "content": "Use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
        }],
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
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "api-broad-recall-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid duplicate holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-broad-recall",
        }],
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
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "api-debug-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering reused stale hold updates because the sync window exceeded the hold TTL.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:api",
            "thread_ref": "chat:api:thread-debug",
        }],
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



def test_query_and_debug_short_noun_isolation_replay_match_injection_contract(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url)
    scenario = _seed_short_noun_isolation_history(client)
    container_ref = scenario["container_ref"]
    visibility = scenario["visibility"]

    query_payloads = (
        {
            "text": "good afternnon sir",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": "chat:workspace:local-memory:diag-good-afternnon-fresh",
            "visibility": visibility,
            "runtime_context": {
                "turn_kind": "new_thread",
                "session_has_sufficient_local_context": False,
            },
        },
        {
            "text": "remind me what we had about the batch digests lately",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": scenario["threads"]["same_thread_x"],
            "visibility": visibility,
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
        {
            "text": "no, remember that we cannot use control-panel sign-in here so there is no point trying to connect that way",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": scenario["threads"]["same_thread_x"],
            "visibility": visibility,
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
        {
            "text": "what is the latest we have in reserve snapshot?",
            "limit": 12,
            "container_ref": container_ref,
            "thread_ref": scenario["threads"]["same_thread_y"],
            "visibility": visibility,
            "runtime_context": {
                "turn_kind": "same_thread_continuation",
                "session_has_sufficient_local_context": True,
            },
        },
    )

    for payload in query_payloads:
        query_response = client.post("/query", json=payload)
        debug_response = client.post("/query/debug", json=payload)

        assert query_response.status_code == 200
        assert debug_response.status_code == 200

        query_json = query_response.json()
        debug_json = debug_response.json()
        comparison = compare_query_contract_payloads(query_json, debug_json)

        assert comparison["consistent"] is True, (
            f"Contract drift for prompt {payload['text']!r}: "
            f"{comparison['mismatch_fields']}"
        )


def test_post_items_batch_returns_list_of_responses(client) -> None:
    items = [
        {
            "source_type": "chat_thread",
            "source_id": "batch-msg-1",
            "content_type": "text/plain",
            "content": "First batch message about catalog ordering.",
            "artifact_kind": "message",
            "role": "user",
        },
        {
            "source_type": "chat_thread",
            "source_id": "batch-msg-2",
            "content_type": "text/plain",
            "content": "Second batch message about reservation sync.",
            "artifact_kind": "message",
            "role": "user",
        },
        {
            "source_type": "chat_thread",
            "source_id": "batch-msg-3",
            "content_type": "text/plain",
            "content": "Third batch message about hold updates.",
            "artifact_kind": "message",
            "role": "assistant",
        },
    ]

    response = client.post("/items", json=items)

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    for item_response in payload:
        assert item_response["source_item_id"]
        assert item_response["processing_status"] == "pending"
        assert item_response["processing_attempts"] == 0
        assert item_response["memory_object_ids"] == []
        assert len(item_response["index_entry_ids"]) == 1

    source_item_ids = [item["source_item_id"] for item in payload]
    assert len(set(source_item_ids)) == 3


def test_post_items_single_item_list_returns_single_element_list(client) -> None:
    response = client.post(
        "/items",
        json=[{
            "source_type": "chat_thread",
            "source_id": "compat-single-1",
            "content_type": "text/plain",
            "content": "Single item backward compatibility test.",
            "artifact_kind": "message",
            "role": "user",
        }],
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["source_item_id"]
    assert payload[0]["processing_status"] == "pending"


def test_post_items_empty_list_returns_empty_list(client) -> None:
    response = client.post("/items", json=[])

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload == []


def test_post_items_batch_with_invalid_item_returns_422(client) -> None:
    items = [
        {
            "source_type": "chat_thread",
            "source_id": "valid-batch-1",
            "content_type": "text/plain",
            "content": "Valid batch item.",
            "artifact_kind": "message",
            "role": "user",
        },
        {
            "source_type": "chat_thread",
            # missing source_id
            "content_type": "text/plain",
            "content": "Invalid batch item missing source_id.",
        },
    ]

    response = client.post("/items", json=items)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(1 in error.get("loc", []) for error in detail)


def test_post_items_batch_idempotent_returns_current_state(client, drain_queue) -> None:
    item = {
        "source_type": "decision_note",
        "source_id": "batch-idempotent-1",
        "content_type": "text/plain",
        "content": "Decision: use item event time for reservation ordering to avoid missed hold updates during sync delays.",
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "thread_ref": "thread-batch-idem",
    }

    first_response = client.post("/items", json=[item])
    assert first_response.status_code == 200
    assert first_response.json()[0]["processing_status"] == "pending"

    drain_queue(client)

    batch_response = client.post("/items", json=[item])
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["processing_status"] == "completed"


def test_item_and_query_returns_source_item_id_and_query_result(client) -> None:
    response = client.post("/item-and-query", json={
        "source_type": "chat_message",
        "source_id": "iaq-test-1",
        "content_type": "text/plain",
        "content": "Why did we choose event time for ordering?",
        "artifact_kind": "message",
        "role": "user",
        "container_ref": "room:test",
        "thread_ref": "thread-iaq-1",
        "visibility": "public",
    })
    assert response.status_code == 200
    data = response.json()
    assert "source_item_id" in data
    assert "should_inject" in data
    assert "decision_reason" in data
    assert "results" in data
    assert "injectable_blocks" in data


def test_item_and_query_uses_content_as_default_query_text(client) -> None:
    response = client.post("/item-and-query", json={
        "source_type": "chat_message",
        "source_id": "iaq-test-2",
        "content_type": "text/plain",
        "content": "What is the status of the migration?",
        "visibility": "public",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["source_item_id"]
    assert isinstance(data["should_inject"], bool)


def test_item_and_query_query_text_overrides_content(client) -> None:
    response = client.post("/item-and-query", json={
        "source_type": "chat_message",
        "source_id": "iaq-test-3",
        "content_type": "text/plain",
        "content": "User asked about the ordering decision in the catalog sync channel.",
        "query_text": "Why did we choose event time?",
        "visibility": "public",
    })
    assert response.status_code == 200


def test_item_and_query_debug_returns_trace(client) -> None:
    response = client.post("/item-and-query/debug", json={
        "source_type": "chat_message",
        "source_id": "iaq-debug-1",
        "content_type": "text/plain",
        "content": "What was the investigation outcome?",
        "visibility": "public",
    })
    assert response.status_code == 200
    data = response.json()
    assert "trace" in data
    assert "source_item_id" in data
    assert data["trace"]["query_text"] == "What was the investigation outcome?"


def test_item_and_query_missing_content_returns_422(client) -> None:
    response = client.post("/item-and-query", json={
        "source_type": "chat_message",
        "source_id": "iaq-test-bad",
        "content_type": "text/plain",
    })
    assert response.status_code == 422
