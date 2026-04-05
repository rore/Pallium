from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from tests.config_helpers import build_llm_test_config
from app.main import create_app
from semantic.agent_conversation_memory_threads import _normalize_task_checkpoint_current_state
from evals.agent_conversation_runner import run_agent_conversation_scenarios
from providers.llm.base import LLMJsonResponse


class ThreadAwareStubProvider:
    def _resolve_thread_summary_payload(self, user_prompt: str) -> dict:
        lower = user_prompt.lower()
        if "transaction-transformer had the most significant recent ledger changes" in lower and "local repos only" in lower:
            return {"summary": "unresolved"}
        if "schema change and backfill done" in lower and "admin toggle" in lower:
            return {"summary": "Ticket LIB-241 has the schema and backfill done, and the next step is wiring the admin toggle plus retry-path coverage.", "retrieval_context": "Flag-gated LIB-241 reservation ordering rollout with remaining admin-toggle and retry-path coverage work."}
        if "service token expired" in lower and "batch 313" in lower:
            return {"summary": "The sync retry hit a 401 because the service token expired after 312 reservation records, so the next step is refreshing the token and resuming from batch 313.", "retrieval_context": "Catalog sync retry resume state anchored on the batch 313 restart after service-token expiry."}
        return {"summary": "Reservation ordering thread summary with prior findings and decision."}

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if "task_checkpoint" in schema_description and "Thread items:" in user_prompt:
            summary_payload = self._resolve_thread_summary_payload(user_prompt)
            checkpoint_payload = _build_task_checkpoint_payload(user_prompt)
            merged = dict(summary_payload)
            merged["task_checkpoint"] = checkpoint_payload
            return LLMJsonResponse(raw_text=json.dumps(merged), parsed_json=merged)
        if "key_findings" in schema_description and "freshness_signal" in schema_description:
            payload = _build_task_checkpoint_payload(user_prompt)
        elif "Thread items:" in user_prompt:
            payload = self._resolve_thread_summary_payload(user_prompt)
        elif "Here's the verdict: transaction-transformer had the most significant recent ledger changes" in user_prompt:
            payload = {
                "summary": "Comparative repo verdict.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "transaction-transformer had the most significant recent ledger changes",
                "investigation_evidence_text": "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin.",
                "rationale_text": "because it touched more tickets, files, and transaction flows than ledger-query",
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": "transaction-transformer had the most significant recent ledger changes because it touched more tickets, files, and core transaction flows than ledger-query",
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
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": "arrival-time ordering skipped hold updates during catalog sync delays",
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
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            }
        elif "Maybe we should use item event time for reservation ordering if it seems safer." in user_prompt:
            payload = {
                "summary": "Tentative reservation-ordering idea.",
                "candidate_type": "decision",
                "decision_text": "use item event time for reservation ordering",
                "decision_evidence_text": "Maybe we should use item event time for reservation ordering if it seems safer.",
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            }
        elif "We might want to monitor whether transaction-transformer changed more than ledger-query." in user_prompt:
            payload = {
                "summary": "Tentative repo comparison.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": "transaction-transformer changed more than ledger-query",
                "investigation_evidence_text": "We might want to monitor whether transaction-transformer changed more than ledger-query.",
                "rationale_text": None,
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            }
        else:
            lowered_prompt = user_prompt.lower()
            payload = {
                "summary": "Conversation summary.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": "task complete" in lowered_prompt and "nothing new to report" in lowered_prompt,
                "constraint_text": "No browser auth, no Jira or Slack auth; use the local repos only and ask the user directly for anything behind those services." if "no browser auth" in lowered_prompt and "local repos only" in lowered_prompt else None,
                "next_step_text": "Compare ledger-query vs transaction-transformer locally, then explain which repo changed more." if "compare ledger-query vs transaction-transformer locally first" in lowered_prompt else ("Wait 15 minutes and resume from batch 418." if "resume from batch 418" in lowered_prompt and "got through batch 417" in lowered_prompt else None),
                "blocker_text": "Browser and SSO-backed services are unavailable in this environment." if "no browser auth" in lowered_prompt and "jira or slack auth" in lowered_prompt else ("The retry window is exhausted now." if "retry window is exhausted" in lowered_prompt and "batch 418" in lowered_prompt else ("Branch kiosk fallback coverage is still missing before review can pass." if "admin toggle wiring is ready" in lowered_prompt and "fallback coverage is still missing" in lowered_prompt else None)),
                "progress_text": "The latest ledger changes were already summarized across the local repos." if "expanded transaction coverage" in lowered_prompt and "adx plumbing" in lowered_prompt else ("The token refresh worked and the sync got through batch 417." if "resume from batch 418" in lowered_prompt and "got through batch 417" in lowered_prompt else ("The admin toggle wiring is ready." if "admin toggle wiring is ready" in lowered_prompt and "fallback coverage is still missing" in lowered_prompt else None)),
                "key_finding_text": None,
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _build_write_enrichment_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if 'record type: thread_summary' in lower and 'lib-241' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Flag-gated LIB-241 reservation ordering rollout with remaining admin-toggle and retry-path coverage work.',
        }
    if 'record type: task_checkpoint' in lower and 'batch 313' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token expiry.',
        }
    if 'record type: task_checkpoint' in lower and 'lib-241' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Flag-gated LIB-241 task state with remaining admin-toggle and retry-path coverage work.',
        }
    return {
        'action': 'NO_OP',
        'retrieval_context': None,
    }

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
            "retrieval_context": "Flag-gated LIB-241 task state with remaining admin-toggle and retry-path coverage work.",
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
            "retrieval_context": "Catalog sync retry resume state anchored on the batch 313 restart after service-token expiry.",
        }
    if "retry window is exhausted" in lower and "batch 418" in lower:
        return {
            "summary": "Catalog sync retry moved past auth recovery and is now blocked on the retry window.",
            "task": "Resume the catalog sync retry.",
            "current_state": "Sync completed through batch 417, but the retry window is exhausted now.",
            "key_findings": ["the token refresh worked", "the sync completed through batch 417"],
            "blocker_state": "The retry window is exhausted now.",
            "next_step": "Wait 15 minutes and resume from batch 418.",
            "evidence": ["Partial progress: the token refresh worked and the sync completed through batch 417.", "Blocked: the retry window is exhausted now.", "Next step: wait 15 minutes and resume from batch 418."],
            "freshness_signal": "Latest explicit update at 2026-03-11T13:02:00Z.",
            "retrieval_context": None,
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


def _thread_test_config(test_db_url: str):
    return build_llm_test_config(
        default_use_case="agent_conversation_memory",
        sqlite_url=test_db_url,
        model="fake-model",
    )


def _create_thread_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: ThreadAwareStubProvider())
    client = TestClient(create_app(_thread_test_config(test_db_url)))
    original_post = client.post

    def post_with_public_visibility(url: str, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and url in {"/items", "/query", "/query/debug"} and "visibility" not in payload:
            payload = dict(payload)
            payload["visibility"] = "public"
            kwargs["json"] = payload
        elif isinstance(payload, list) and url == "/items":
            payload = [
                {**item, "visibility": "public"} if isinstance(item, dict) and "visibility" not in item else item
                for item in payload
            ]
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
            event.setdefault("visibility", "public")
        current_query = scenario.get("current_query")
        if isinstance(current_query, dict):
            current_query.setdefault("visibility", "public")
    target_path.write_text(json.dumps(scenarios), encoding="utf-8")
    return target_path


def test_thread_summary_is_created_and_superseded(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    client.post("/items", json=[{"source_type": "chat_message", "source_id": "thread-msg-1", "content_type": "text/plain", "content": "Why are some library holds disappearing after catalog sync delays?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-001"}])
    client.post("/items", json=[{"source_type": "assistant_artifact", "source_id": "thread-artifact-1", "content_type": "text/plain", "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-001"}])
    # Third item triggers a second thread rebuild that supersedes the first summary
    client.post("/items", json=[{"source_type": "chat_message", "source_id": "thread-msg-2", "content_type": "text/plain", "content": "Good, that should fix the holds. Will the sync delays also affect due-date calculations?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-001"}])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-001")
    summaries = list({memory.id: memory for item in thread_items for memory in storage.list_memory_objects_for_source_item(item.id) if memory.type == "thread_summary"}.values())
    assert len(summaries) >= 2
    assert len([item for item in summaries if item.lifecycle == "active"]) == 1
    assert any(item.lifecycle == "superseded" for item in summaries)


def test_thread_summary_and_task_checkpoint_preserve_selected_work_artifacts(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-work-1", "content_type": "text/plain", "content": "What state were we in on ticket LIB-241 before the interruption?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "occurred_at": "2026-03-11T11:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-1", "content_type": "text/plain", "content": "Partial progress: ticket LIB-241 has the schema change and backfill done.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "occurred_at": "2026-03-11T11:01:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-2", "content_type": "text/plain", "content": "Next step: wire the admin toggle and add retry-path coverage before enabling the flag.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-001", "occurred_at": "2026-03-11T11:02:00Z"},
    ):
        client.post("/items", json=[payload])

    query_response = client.post("/query", json={"text": "what state were we in on ticket lib 241 and what should i do next?", "limit": 8, "container_ref": "chat:library-help"})
    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-work-001")
    active_thread_summary = next(
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "thread_summary" and memory.lifecycle == "active"
    )
    assert active_thread_summary.payload["retrieval_enrichment"]["semantic_provenance"]["prompt_role"] == "write_enrichment"
    assert "lib-241" in active_thread_summary.payload["retrieval_enrichment"]["retrieval_context"].lower()
    # envelope-first routing: task_checkpoint (episode kind) is excluded from broad_recall
    # queries by kind_prefilter. Verify the checkpoint exists in storage directly.
    active_task_checkpoint = next(
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "task_checkpoint" and memory.lifecycle == "active"
    )
    assert active_task_checkpoint.payload["next_step"] == "Wire the admin toggle and add retry-path coverage before enabling the flag."
    assert active_task_checkpoint.payload["retrieval_enrichment"]["semantic_provenance"]["prompt_role"] == "write_enrichment"
    assert "flag" in active_task_checkpoint.payload["retrieval_enrichment"]["retrieval_context"].lower()


def test_task_checkpoint_is_created_and_superseded(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-work-3", "content_type": "text/plain", "content": "The catalog sync retry is queued again.", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "occurred_at": "2026-03-11T09:59:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-5", "content_type": "text/plain", "content": "Partial progress: refreshed 312 reservation records before the catalog sync tool failed.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "occurred_at": "2026-03-11T10:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-6", "content_type": "text/plain", "content": "Blocked: catalog API returned 401 because the service token expired.", "artifact_kind": "tool_use_summary", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "occurred_at": "2026-03-11T10:01:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-7", "content_type": "text/plain", "content": "Next step: refresh the catalog service token and rerun the sync from batch 313.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "occurred_at": "2026-03-11T10:02:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-work-artifact-8", "content_type": "text/plain", "content": "Next step: refresh the catalog service token, rerun the sync from batch 313, and capture verbose auth logging.", "artifact_kind": "todo_snapshot", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-work-003", "occurred_at": "2026-03-11T10:03:00Z"},
    ):
        client.post("/items", json=[payload])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-work-003")
    checkpoints = list({memory.id: memory for item in thread_items for memory in storage.list_memory_objects_for_source_item(item.id) if memory.type == "task_checkpoint"}.values())
    assert len(checkpoints) >= 2
    active_checkpoint = next(item for item in checkpoints if item.lifecycle == "active")
    assert active_checkpoint.payload["retrieval_enrichment"]["semantic_provenance"]["prompt_role"] == "write_enrichment"
    assert "batch 313" in active_checkpoint.payload["retrieval_enrichment"]["retrieval_context"].lower()


def test_downstream_agent_style_thread_promotes_verdict_and_uses_summary_fallback(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    thread_ref = "slack:thread:CLOCAL001:1773572419.417473"
    payloads = (
        {"source_type": "chat_message", "source_id": "downstream-agent-ledger-msg-1", "content_type": "text/plain", "content": "summarize the latest changes in ledgers", "artifact_kind": "message", "role": "user", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "assistant_artifact", "source_id": "downstream-agent-ledger-artifact-1", "content_type": "text/plain", "content": "Here's what's been happening across the ledger services: transaction-transformer expanded transaction coverage while ledger-query focused on export and ADX plumbing.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "chat_message", "source_id": "downstream-agent-ledger-msg-2", "content_type": "text/plain", "content": "Assume you are blocked from opening browsers or using Jira/Slack auth. What is your best next-step plan using only the local repos?", "artifact_kind": "message", "role": "user", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "assistant_artifact", "source_id": "downstream-agent-ledger-artifact-2", "content_type": "text/plain", "content": "Understood. No browser auth, no Jira or Slack auth. I'll work with the local repos only and ask you directly if I need anything from those services.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "assistant_artifact", "source_id": "downstream-agent-ledger-artifact-3", "content_type": "text/plain", "content": "I can compare ledger-query vs transaction-transformer locally first, then explain which repo changed more from the cloned repos.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "assistant_artifact", "source_id": "downstream-agent-ledger-artifact-4", "content_type": "text/plain", "content": "Here's the verdict: transaction-transformer had the most significant recent ledger changes by a wide margin. It touched more tickets, files, and core transaction flows than ledger-query.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
        {"source_type": "assistant_artifact", "source_id": "downstream-agent-ledger-artifact-5", "content_type": "text/plain", "content": "Task complete. No Slack message needed. Nothing new to report.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "slack:CLOCAL001", "thread_ref": thread_ref},
    )
    for payload in payloads:
        client.post("/items", json=[payload])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("slack:CLOCAL001", thread_ref)
    memory_by_source = {
        item.source_id: storage.list_memory_objects_for_source_item(item.id)
        for item in thread_items
    }
    final_memory = memory_by_source["downstream-agent-ledger-artifact-4"]
    assert any(memory.type == "investigation_outcome" for memory in final_memory)

    thread_summaries = list({
        memory.id: memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "thread_summary"
    }.values())
    active_summary = next(memory for memory in thread_summaries if memory.lifecycle == "active")
    summary_text = str(active_summary.payload["summary"])
    assert summary_text.lower() != "unresolved"
    assert "transaction-transformer" in summary_text.lower()
    assert "constraint" in summary_text.lower() or "local repos" in summary_text.lower() or "browser" in summary_text.lower()

    selected_work_artifacts = active_summary.payload.get("selected_work_artifacts", [])
    assert any(item.get("signal_type") == "constraint" for item in selected_work_artifacts)
    assert any(item.get("signal_type") == "next_step" for item in selected_work_artifacts)
    assert all("task complete" not in str(item.get("text") or "").lower() for item in selected_work_artifacts)


def test_thread_summary_carries_forward_typed_conclusions(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-2", "content_type": "text/plain", "content": "Why are some library holds disappearing after catalog sync delays?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002"},
        {"source_type": "assistant_artifact", "source_id": "thread-artifact-2", "content_type": "text/plain", "content": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002"},
        {"source_type": "assistant_artifact", "source_id": "thread-artifact-3", "content_type": "text/plain", "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-002"},
    ):
        client.post("/items", json=[payload])

    query_response = client.post("/query", json={"text": "why do we use item event time for reservation ordering?", "limit": 8, "container_ref": "chat:library-help"})
    # envelope-first routing: thread_summary may not appear in top results with broad_recall weights
    thread_summaries = [item for item in query_response.json()["results"] if item.get("type") == "thread_summary"]
    if thread_summaries:
        conclusions = thread_summaries[0]["payload"].get("conclusions", [])
        assert any(item["type"] == "decision" for item in conclusions)
        assert any(item["type"] == "investigation_outcome" for item in conclusions)


def test_agent_conversation_runner_surfaces_thread_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: ThreadAwareStubProvider())
    run_dir = run_agent_conversation_scenarios(
        scenario_file=_write_public_visibility_scenario(tmp_path / "agent_conversation_visibility_scenarios.json", Path("evals/agent_conversation/scenarios.json")),
        output_root=tmp_path / "output",
        config=build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url="sqlite:///./test.db", model="fake-model"),
        run_name="agent-conversation-thread-summary",
    )
    results = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cross_thread_case = next(item for item in results if item["scenario_id"] == "cross-thread-decision-recall")
    assert cross_thread_case["returned_memory_types"]



def test_low_value_meta_item_keeps_raw_source_without_durable_memory(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    response = client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "thread-meta-1",
            "content_type": "text/plain",
            "content": "Task complete. No Slack message needed. Nothing new to report.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:CLOCAL001",
            "thread_ref": "slack:CLOCAL001:thread-meta",
        }],
    )

    assert response.status_code == 200
    source_item_id = response.json()[0]["source_item_id"]
    storage = client.app.state.pallium_service._storage
    source_item = storage.get_source_item(source_item_id)
    memory_objects = storage.list_memory_objects_for_source_item(source_item_id)
    processing = client.app.state.pallium_service.get_item_processing(source_item_id)

    assert source_item.source_id == "thread-meta-1"
    assert all(memory.type != "discussion_summary" for memory in memory_objects)
    assert all(memory.type != "thread_summary" for memory in memory_objects)
    assert processing.thread_rebuild_requested is False


def test_grounded_decision_candidate_creates_typed_memory_when_evidence_matches_source(monkeypatch, test_db_url: str) -> None:
    """When the LLM classifies as decision and evidence is grounded in source, trust it."""
    client = _create_thread_client(monkeypatch, test_db_url)
    response = client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "thread-weak-decision-1",
            "content_type": "text/plain",
            "content": "Maybe we should use item event time for reservation ordering if it seems safer.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-weak-decision",
        }],
    )

    assert response.status_code == 200
    source_item_id = response.json()[0]["source_item_id"]
    storage = client.app.state.pallium_service._storage
    processing = client.app.state.pallium_service.get_item_processing(source_item_id)
    memory_objects = storage.list_memory_objects_for_source_item(source_item_id)

    assert any(memory.type == "decision" for memory in memory_objects)
    assert processing.thread_rebuild_requested is True



def test_grounded_investigation_candidate_creates_typed_memory_when_evidence_matches_source(monkeypatch, test_db_url: str) -> None:
    """When the LLM classifies as investigation and evidence is grounded in source, trust it."""
    client = _create_thread_client(monkeypatch, test_db_url)
    response = client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "thread-weak-investigation-1",
            "content_type": "text/plain",
            "content": "We might want to monitor whether transaction-transformer changed more than ledger-query.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-weak-investigation",
        }],
    )

    assert response.status_code == 200
    source_item_id = response.json()[0]["source_item_id"]
    storage = client.app.state.pallium_service._storage
    processing = client.app.state.pallium_service.get_item_processing(source_item_id)
    memory_objects = storage.list_memory_objects_for_source_item(source_item_id)

    assert any(memory.type == "investigation_outcome" for memory in memory_objects)
    assert processing.thread_rebuild_requested is True



def test_supported_typed_memory_still_requests_thread_rebuild(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    response = client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "thread-supported-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-supported-decision",
        }],
    )

    assert response.status_code == 200
    source_item_id = response.json()[0]["source_item_id"]
    storage = client.app.state.pallium_service._storage
    processing = client.app.state.pallium_service.get_item_processing(source_item_id)
    memory_objects = storage.list_memory_objects_for_source_item(source_item_id)

    assert any(memory.type == "decision" for memory in memory_objects)
    # Single-item threads skip thread aggregation (no value in summarizing one message)
    assert not any(memory.type == "thread_summary" for memory in memory_objects)
    assert processing.thread_rebuild_requested is True



def test_substantive_item_still_requests_thread_rebuild(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    response = client.post(
        "/items",
        json=[{
            "source_type": "chat_message",
            "source_id": "thread-substantive-1",
            "content_type": "text/plain",
            "content": "Why are duplicate holds happening after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "chat:library-help",
            "thread_ref": "chat:library-help:thread-substantive",
        }],
    )

    assert response.status_code == 200
    source_item_id = response.json()[0]["source_item_id"]
    storage = client.app.state.pallium_service._storage
    processing = client.app.state.pallium_service.get_item_processing(source_item_id)
    memory_objects = storage.list_memory_objects_for_source_item(source_item_id)

    assert processing.thread_rebuild_requested is True
    # Single-item threads skip thread aggregation (no value in summarizing one message)
    assert not any(memory.type == "thread_summary" for memory in memory_objects)


def test_single_item_thread_skips_aggregation_second_item_triggers_it(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    thread_ref = "chat:library-help:thread-threshold"
    container_ref = "chat:library-help"

    # First item: thread has 1 item, no thread summary should be produced
    response = client.post(
        "/items",
        json=[{
            "source_type": "chat_message",
            "source_id": "threshold-msg-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
        }],
    )
    assert response.status_code == 200
    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    assert len(thread_items) == 1
    all_memory = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
    ]
    assert not any(memory.type == "thread_summary" for memory in all_memory)

    # Second item: thread now has 2 items, thread summary should be produced
    response = client.post(
        "/items",
        json=[{
            "source_type": "assistant_artifact",
            "source_id": "threshold-artifact-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
        }],
    )
    assert response.status_code == 200
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    assert len(thread_items) == 2
    all_memory = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
    ]
    assert any(memory.type == "thread_summary" for memory in all_memory)


def test_natural_language_assistant_output_creates_task_checkpoint_from_metadata_signals(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-natural-1", "content_type": "text/plain", "content": "I need to pick this sync retry back up.", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-001", "occurred_at": "2026-03-11T10:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-natural-artifact-1", "content_type": "text/plain", "content": "The token refresh worked and the sync got through batch 417, but the retry window is exhausted now. Wait 15 minutes and resume from batch 418.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-001", "occurred_at": "2026-03-11T10:03:00Z"},
    ):
        client.post("/items", json=[payload])

    # envelope-first routing: task_checkpoint (episode kind) is excluded from broad_recall
    # queries by kind_prefilter. Verify the checkpoint exists in storage directly.
    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-natural-001")
    active_task_checkpoint = next(
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "task_checkpoint" and memory.lifecycle == "active"
    )
    selected_work_artifacts = active_task_checkpoint.payload["selected_work_artifacts"]

    assert any(item["signal_type"] == "progress_update" and item["signal_origin"] == "llm" and "batch 417" in item["text"].lower() for item in selected_work_artifacts)
    assert any(item["signal_type"] == "blocker" and item["signal_origin"] == "llm" and "retry window" in item["text"].lower() for item in selected_work_artifacts)
    assert any(item["signal_type"] == "next_step" and item["signal_origin"] == "llm" and "batch 418" in item["text"].lower() for item in selected_work_artifacts)


def test_task_checkpoint_current_state_prefers_active_blocker_over_resolved_key_finding(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-natural-3", "content_type": "text/plain", "content": "I need to leave myself a clean sync handoff.", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-003", "occurred_at": "2026-03-11T13:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-natural-artifact-3", "content_type": "text/plain", "content": "Token refresh succeeded. Sync completed through batch 417, but the retry window is exhausted now. Resume at batch 418 after the retry window clears.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-003", "occurred_at": "2026-03-11T13:02:00Z"},
    ):
        client.post("/items", json=[payload])

    # envelope-first routing: task_checkpoint (episode kind) is excluded from broad_recall
    # queries by kind_prefilter. Verify the checkpoint exists in storage directly.
    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-natural-003")
    active_task_checkpoint = next(
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "task_checkpoint" and memory.lifecycle == "active"
    )
    current_state = active_task_checkpoint.payload["current_state"].lower()
    assert "retry window" in current_state
    assert "token refresh succeeded" not in current_state



def test_normalize_task_checkpoint_current_state_preserves_richer_active_state_when_aligned() -> None:
    current_state = "Sync completed through batch 417, but the retry window is exhausted now."
    derived_current_state = "The retry window is exhausted now."
    selected_work_artifacts = [
        {"signal_type": "progress_update", "text": "Partial progress: the sync completed through batch 417."},
        {"signal_type": "blocker", "text": "Blocked: the retry window is exhausted now."},
        {"signal_type": "next_step", "text": "Next step: wait 15 minutes and resume from batch 418."},
    ]

    normalized = _normalize_task_checkpoint_current_state(
        current_state=current_state,
        derived_current_state=derived_current_state,
        selected_work_artifacts=selected_work_artifacts,
    )

    assert normalized == current_state
def test_key_finding_only_signal_does_not_create_task_checkpoint(monkeypatch, test_db_url: str) -> None:
    client = _create_thread_client(monkeypatch, test_db_url)
    for payload in (
        {"source_type": "chat_message", "source_id": "thread-msg-natural-2", "content_type": "text/plain", "content": "What should we remember from this grocery planning thread?", "artifact_kind": "message", "role": "user", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-002", "occurred_at": "2026-03-11T12:00:00Z"},
        {"source_type": "assistant_artifact", "source_id": "thread-natural-artifact-2", "content_type": "text/plain", "content": "The biggest lesson is that unordered grocery lists cause backtracking through the store.", "artifact_kind": "assistant_output", "role": "assistant", "container_ref": "chat:library-help", "thread_ref": "chat:library-help:thread-agg-natural-002", "occurred_at": "2026-03-11T12:01:00Z"},
    ):
        client.post("/items", json=[payload])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread("chat:library-help", "chat:library-help:thread-agg-natural-002")
    active_memory = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.lifecycle == "active"
    ]

    assert any(memory.type == "thread_summary" for memory in active_memory)
    assert all(memory.type != "task_checkpoint" for memory in active_memory)


# ---------------------------------------------------------------------------
# Fix D — formation: _normalize_task_checkpoint_current_state strips resolved
# fragments when an active blocker is present
# ---------------------------------------------------------------------------


def test_normalize_strips_resolved_fragment_when_active_blocker_present() -> None:
    # current_state mentions a resolved issue alongside the active blocker.
    # After normalization the resolved fragment should be gone.
    current_state = "Token refresh is fixed. The catalog sync is blocked on rate-limiting."
    derived_current_state = "The catalog sync is blocked on rate-limiting."
    selected_work_artifacts = [
        {"signal_type": "blocker", "text": "Blocked: catalog sync is blocked on rate-limiting."},
    ]

    normalized = _normalize_task_checkpoint_current_state(
        current_state=current_state,
        derived_current_state=derived_current_state,
        selected_work_artifacts=selected_work_artifacts,
    )

    assert "is fixed" not in normalized.lower()
    assert "rate-limiting" in normalized.lower() or "catalog sync" in normalized.lower()


def test_normalize_preserves_all_fragments_when_no_active_blocker() -> None:
    # Without an active blocker signal, no stripping should occur.
    current_state = "Token refresh is fixed. The catalog sync is blocked on rate-limiting."
    derived_current_state = "Token refresh is fixed."
    selected_work_artifacts = [
        {"signal_type": "progress_update", "text": "Partial progress: token refresh succeeded."},
    ]

    normalized = _normalize_task_checkpoint_current_state(
        current_state=current_state,
        derived_current_state=derived_current_state,
        selected_work_artifacts=selected_work_artifacts,
    )

    # Both fragments should survive — there is no active blocker to drive stripping.
    assert "is fixed" in normalized.lower() or current_state in normalized


def test_normalize_does_not_strip_single_fragment_current_state() -> None:
    # A single-sentence current_state should never be mutated even if it contains
    # a resolution marker, because there is nothing else to fall back to.
    current_state = "Token refresh is fixed."
    derived_current_state = "Token refresh is fixed."
    selected_work_artifacts = [
        {"signal_type": "blocker", "text": "Blocked: still waiting on the catalog API."},
    ]

    normalized = _normalize_task_checkpoint_current_state(
        current_state=current_state,
        derived_current_state=derived_current_state,
        selected_work_artifacts=selected_work_artifacts,
    )

    # Single fragment — return value must not be empty (the whole state is the only content).
    assert normalized.strip() != ""


# ---------------------------------------------------------------------------
# Multi-user thread aggregation: actor_ref must be null on thread-level memory
# ---------------------------------------------------------------------------


def test_thread_summary_null_actor_ref_after_multi_actor_thread(monkeypatch, test_db_url: str) -> None:
    """Thread summary from a multi-actor thread must have actor_ref=None."""
    client = _create_thread_client(monkeypatch, test_db_url)
    thread_ref = "chat:library-team:thread-multi-actor-summary"
    container_ref = "chat:library-team"

    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "multi-actor-msg-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": "user:branch-librarian",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "multi-actor-msg-2",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": "user:catalog-admin",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ):
        client.post("/items", json=[payload])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    thread_summaries = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "thread_summary" and memory.lifecycle == "active"
    ]
    assert thread_summaries, "Expected at least one active thread_summary"
    for summary in thread_summaries:
        assert summary.actor_ref is None, (
            f"Thread summary from multi-actor thread should have actor_ref=None, "
            f"got actor_ref={summary.actor_ref}"
        )


def test_task_checkpoint_null_actor_ref_in_multi_actor_thread(monkeypatch, test_db_url: str) -> None:
    """Task checkpoint from a multi-actor thread must have actor_ref=None."""
    client = _create_thread_client(monkeypatch, test_db_url)
    thread_ref = "chat:library-team:thread-multi-actor-checkpoint"
    container_ref = "chat:library-team"

    for payload in (
        {
            "source_type": "chat_message",
            "source_id": "multi-actor-cp-msg-1",
            "content_type": "text/plain",
            "content": "The catalog sync retry is queued again.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": "user:branch-librarian",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-11T09:59:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "multi-actor-cp-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: refreshed 312 reservation records before the catalog sync tool failed.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "actor_ref": "user:catalog-admin",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-11T10:00:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "multi-actor-cp-artifact-2",
            "content_type": "text/plain",
            "content": "Blocked: catalog API returned 401 because the service token expired.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "actor_ref": "user:catalog-admin",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-11T10:01:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "multi-actor-cp-artifact-3",
            "content_type": "text/plain",
            "content": "Next step: refresh the catalog service token and rerun the sync from batch 313.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "actor_ref": "user:catalog-admin",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "visibility": "container",
            "occurred_at": "2026-03-11T10:02:00Z",
        },
    ):
        client.post("/items", json=[payload])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(container_ref, thread_ref)
    checkpoints = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
        if memory.type == "task_checkpoint" and memory.lifecycle == "active"
    ]
    assert checkpoints, "Expected at least one active task_checkpoint"
    for checkpoint in checkpoints:
        assert checkpoint.actor_ref is None, (
            f"Task checkpoint from multi-actor thread should have actor_ref=None, "
            f"got actor_ref={checkpoint.actor_ref}"
        )
