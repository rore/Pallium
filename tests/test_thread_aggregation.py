from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from evals.agent_conversation_runner import run_agent_conversation_scenarios
from providers.llm.base import LLMJsonResponse


class ThreadAwareStubProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "Thread items:" in user_prompt:
            payload = {
                "summary": "Reservation ordering thread summary with prior findings and decision.",
            }
        elif "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays." in user_prompt:
            payload = {
                "summary": "Prior investigation about missing holds.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "arrival-time ordering skipped hold updates during catalog sync delays",
                "investigation_evidence_text": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
                "rationale_text": None,
            }
        elif "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays." in user_prompt:
            payload = {
                "summary": "Prior reservation-ordering decision.",
                "candidate_type": "decision",
                "decision_text": "use item event time for reservation ordering",
                "decision_evidence_text": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": "to avoid skipped holds during sync delays",
            }
        else:
            payload = {
                "summary": "Conversation summary.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _thread_test_config(test_db_url: str) -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="agent_conversation_memory",
        llm_provider="openai_compatible",
        llm_model="fake-model",
        llm_base_url="http://fake-provider.local",
        llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )


def _create_thread_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: ThreadAwareStubProvider(),
    )
    return TestClient(create_app(_thread_test_config(test_db_url)))


def test_thread_summary_is_created_and_superseded(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)

    first = client.post(
        "/items",
        json={
            "source_type": "chat_message",
            "source_id": "thread-msg-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-agg-001",
            "session_ref": "agent-session-agg-001",
        },
    )
    assert first.status_code == 200
    assert len(first.json()["memory_object_ids"]) == 2

    second = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": "thread-artifact-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-agg-001",
            "session_ref": "agent-session-agg-001",
        },
    )
    assert second.status_code == 200

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-001")
    thread_summaries = {}
    for item in thread_items:
        for memory_object in storage.list_memory_objects_for_source_item(item.id):
            if memory_object.type == "thread_summary":
                thread_summaries[memory_object.id] = memory_object

    assert len(thread_summaries) >= 2
    active = [item for item in thread_summaries.values() if item.lifecycle == "active"]
    superseded = [item for item in thread_summaries.values() if item.lifecycle == "superseded"]
    assert len(active) == 1
    assert superseded


def test_thread_summary_carries_forward_typed_conclusions(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)

    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "thread-msg-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-agg-002",
            "session_ref": "agent-session-agg-002",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "thread-artifact-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-agg-002",
            "session_ref": "agent-session-agg-002",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "thread-artifact-2",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-agg-002",
            "session_ref": "agent-session-agg-002",
        },
    ):
        response = client.post("/items", json=payload)
        assert response.status_code == 200

    query_response = client.post(
        "/query",
        json={
            "text": "why do we use item event time for reservation ordering?",
            "limit": 8,
            "container_ref": "chat:library-help",
        },
    )
    assert query_response.status_code == 200
    memory_hits = [item for item in query_response.json()["results"] if item["result_kind"] == "memory_hit"]
    thread_summary = next(item for item in memory_hits if item["type"] == "thread_summary")
    conclusion_types = {item["type"] for item in thread_summary["payload"]["conclusions"]}
    assert conclusion_types == {"decision", "investigation_outcome"}
    assert len(thread_summary["evidence"]) == 3


def test_agent_conversation_runner_surfaces_thread_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: ThreadAwareStubProvider(),
    )

    run_dir = run_agent_conversation_scenarios(
        scenario_file=Path("evals/agent_conversation/scenarios.json"),
        output_root=tmp_path / "output",
        config=AppConfig(
            storage_backend="sqlite",
            default_use_case="agent_conversation_memory",
            llm_provider="openai_compatible",
            llm_model="fake-model",
            llm_base_url="http://fake-provider.local",
            llm_prompt_variant="strict_typed_memory_v4_evidence_guarded",
        ),
        run_name="agent-conversation-thread-summary",
    )
    results = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cross_thread_case = next(item for item in results if item["scenario_id"] == "cross-thread-decision-recall")

    assert "thread_summary" in cross_thread_case["returned_memory_types"]
