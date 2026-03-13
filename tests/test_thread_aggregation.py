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
        if "key_findings" in schema_description and "freshness_signal" in schema_description:
            payload = _build_task_checkpoint_payload(user_prompt)
        elif "Thread items:" in user_prompt:
            lower = user_prompt.lower()
            if "schema change and backfill done" in lower and "admin toggle" in lower:
                payload = {"summary": "Ticket LIB-241 has the schema and backfill done, and the next step is wiring the admin toggle plus retry-path coverage."}
            elif "service token expired" in lower and "batch 313" in lower:
                payload = {"summary": "The sync retry hit a 401 because the service token expired after 312 reservation records, so the next step is refreshing the token and resuming from batch 313."}
            else:
                payload = {"summary": "Reservation ordering thread summary with prior findings and decision."}
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


def _build_task_checkpoint_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if "schema change and backfill done" in lower and "admin toggle" in lower:
        return {
            "summary": "Ticket LIB-241 is partway done and can resume from the remaining flag-enable work.",
            "task": "Resume ticket LIB-241 with the use_item_event_time flag still gated.",
            "current_state": "The reservation ordering fix stays behind the use_item_event_time flag, and the schema change plus backfill are already done.",
            "key_findings": ["reservation ordering fix", "ticket LIB-241 has the schema change and backfill done"],
            "blocker_state": "",
            "next_step": "Wire the admin toggle and add retry-path coverage before enabling the flag.",
            "evidence": ["Partial progress: ticket LIB-241 has the schema change and backfill done.", "Next step: wire the admin toggle and add retry-path coverage before enabling the flag."],
            "freshness_signal": "Latest explicit update at 2026-03-11T11:02:00Z.",
        }
    if "service token expired" in lower and "batch 313" in lower:
        return {
            "summary": "Catalog sync retry is paused at an auth failure after partial progress, with a clear restart point.",
            "task": "Resume the catalog sync retry.",
            "current_state": "Refreshed 312 reservation records before a 401 from the expired catalog service token; resume from batch 313 after auth is refreshed.",
            "key_findings": ["catalog API returned 401 because the service token expired", "refreshed 312 reservation records before the failure"],
            "blocker_state": "Catalog API returned 401 because the service token expired.",
            "next_step": "Refresh the catalog service token and rerun the sync from batch 313.",
            "evidence": ["Partial progress: refreshed 312 reservation records before the catalog sync tool failed.", "Blocked: catalog API returned 401 because the service token expired.", "Next step: refresh the catalog service token and rerun the sync from batch 313."],
            "freshness_signal": "Latest explicit update at 2026-03-11T10:02:00Z.",
        }
    return {
        "summary": "Resume the previously recorded work from this thread.",
        "task": "Resume the previously recorded work from this thread.",
        "current_state": "",
        "key_findings": [],
        "blocker_state": "",
        "next_step": "",
        "evidence": [],
        "freshness_signal": "Latest explicit update time was not recorded.",
    }


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
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: ThreadAwareStubProvider())
    client = TestClient(create_app(_thread_test_config(test_db_url)))
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "visibility_context" not in payload:
            payload = dict(payload)
            payload["visibility_context"] = {"kind": "public", "id": None}
            kwargs["json"] = payload
        response = original_post(url, *args, **kwargs)
        if url == "/items" and response.status_code == 200:
            client.app.state.pallium_service.drain_processing_queue(worker_id="thread-test")
        return response

    client.post = post_with_public_visibility
    return client


def _write_public_visibility_scenario(target_path: Path, source_path: Path) -> Path:
    scenarios = json.loads(source_path.read_text(encoding="utf-8"))
    for scenario in scenarios:
        for event in scenario.get("prior_events", []):
            event.setdefault("visibility_context", {"kind": "public", "id": None})
        current_query = scenario.get("current_query")
        if isinstance(current_query, dict):
            current_query.setdefault("visibility_context", {"kind": "public", "id": None})
    target_path.write_text(json.dumps(scenarios), encoding="utf-8")
    return target_path


def test_thread_summary_is_created_and_superseded(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    client.post("/items", json={"source_type": "chat_message", "source_id": "thread-msg-1", "content_type": "text/plain", "content": "Why are some library holds disappearing after catalog sync delays?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-001", "session_ref": "agent-session-agg-001"})
    client.post("/items", json={"source_type": "assistant_artifact", "source_id": "thread-artifact-1", "content_type": "text/plain", "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-001", "session_ref": "agent-session-agg-001"})

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-001")
    summaries = list({memory.id: memory for item in thread_items for memory in storage.list_memory_objects_for_source_item(item.id) if memory.type == "thread_summary"}.values())
    assert len(summaries) >= 2
    assert len([item for item in summaries if item.lifecycle == "active"]) == 1
    assert any(item.lifecycle == "superseded" for item in summaries)


def test_thread_summary_and_task_checkpoint_preserve_selected_work_artifacts(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-work-1", "content_type": "text/plain", "content": "What state were we in on ticket LIB-241 before the interruption?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "session_ref": "agent-session-agg-work-001", "occurred_at": "2026-03-11T11:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-1", "content_type": "text/plain", "content": "Partial progress: ticket LIB-241 has the schema change and backfill done.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "session_ref": "agent-session-agg-work-001", "occurred_at": "2026-03-11T11:01:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-2", "content_type": "text/plain", "content": "Next step: wire the admin toggle and add retry-path coverage before enabling the flag.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "session_ref": "agent-session-agg-work-001", "occurred_at": "2026-03-11T11:02:00Z"},
    ):
        client.post("/items", json=payload)

    query_response = client.post("/query", json={"text": "what state were we in on ticket lib 241 and what should i do next?", "limit": 8, "container_ref": "chat:library-help"})
    memory_hits = [item for item in query_response.json()["results"] if item["result_kind"] == "memory_hit"]
    assert any(item["type"] == "thread_summary" for item in memory_hits)
    task_checkpoint = next(item for item in memory_hits if item["type"] == "task_checkpoint")
    assert task_checkpoint["payload"]["next_step"] == "Wire the admin toggle and add retry-path coverage before enabling the flag."


def test_task_checkpoint_is_created_and_superseded(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-work-3", "content_type": "text/plain", "content": "The catalog sync retry is queued again.", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "session_ref": "agent-session-agg-work-003", "occurred_at": "2026-03-11T09:59:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-5", "content_type": "text/plain", "content": "Partial progress: refreshed 312 reservation records before the catalog sync tool failed.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "session_ref": "agent-session-agg-work-003", "occurred_at": "2026-03-11T10:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-6", "content_type": "text/plain", "content": "Blocked: catalog API returned 401 because the service token expired.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "session_ref": "agent-session-agg-work-003", "occurred_at": "2026-03-11T10:01:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-7", "content_type": "text/plain", "content": "Next step: refresh the catalog service token and rerun the sync from batch 313.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "session_ref": "agent-session-agg-work-003", "occurred_at": "2026-03-11T10:02:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-8", "content_type": "text/plain", "content": "Next step: refresh the catalog service token, rerun the sync from batch 313, and capture verbose auth logging.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "session_ref": "agent-session-agg-work-003", "occurred_at": "2026-03-11T10:03:00Z"},
    ):
        client.post("/items", json=payload)

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-work-003")
    checkpoints = list({memory.id: memory for item in thread_items for memory in storage.list_memory_objects_for_source_item(item.id) if memory.type == "task_checkpoint"}.values())
    assert len(checkpoints) >= 2
    assert len([item for item in checkpoints if item.lifecycle == "active"]) == 1


def test_thread_summary_carries_forward_typed_conclusions(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-2", "content_type": "text/plain", "content": "Why are some library holds disappearing after catalog sync delays?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002", "session_ref": "agent-session-agg-002"},
        {"source_type": "assistant_artifact", "source_id": "thread-artifact-2", "content_type": "text/plain", "content": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002", "session_ref": "agent-session-agg-002"},
        {"source_type": "assistant_artifact", "source_id": "thread-artifact-3", "content_type": "text/plain", "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002", "session_ref": "agent-session-agg-002"},
    ):
        client.post("/items", json=payload)

    query_response = client.post("/query", json={"text": "why do we use item event time for reservation ordering?", "limit": 8, "container_ref": "chat:library-help"})
    thread_summary = next(item for item in query_response.json()["results"] if item.get("type") == "thread_summary")
    conclusions = thread_summary["payload"].get("conclusions", [])
    assert any(item["type"] == "decision" for item in conclusions)
    assert any(item["type"] == "investigation_outcome" for item in conclusions)


def test_agent_conversation_runner_surfaces_thread_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: ThreadAwareStubProvider())
    run_dir = run_agent_conversation_scenarios(
        scenario_file=_write_public_visibility_scenario(tmp_path / "agent_conversation_visibility_scenarios.json", Path("evals/agent_conversation/scenarios.json")),
        output_root=tmp_path / "output",
        config=AppConfig(storage_backend="sqlite", default_use_case="agent_conversation_memory", llm_provider="openai_compatible", llm_model="fake-model", llm_base_url="http://fake-provider.local", llm_prompt_variant="strict_typed_memory_v4_evidence_guarded"),
        run_name="agent-conversation-thread-summary",
    )
    results = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cross_thread_case = next(item for item in results if item["scenario_id"] == "cross-thread-decision-recall")
    assert cross_thread_case["returned_memory_types"]
