"""End-to-end integration test for thread-level investigation extraction.

Verifies the full pipeline: ingest -> process -> thread rebuild -> investigation_outcome
memory object with correct properties, supported_by relations, and queryability.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from providers.llm.base import LLMJsonResponse
from tests.config_helpers import build_llm_test_config


# ---------------------------------------------------------------------------
# Thread content used across the tests.
# The format matches _build_thread_material: "role/artifact_kind: content"
# ---------------------------------------------------------------------------

INVESTIGATION_THREAD_REF = "chat:library-help:thread-investigation-e2e-001"
CONTAINER_REF = "chat:library-help"

# These messages form the thread.  The assistant's finding is the investigation.
MSG_1_CONTENT = "Why are some library holds disappearing after catalog sync delays and what is the root cause of the ordering problem?"
MSG_2_CONTENT = (
    "I found that arrival-time ordering skipped hold updates during catalog sync delays "
    "because the provider delivered updates late, causing the reservation queue to process "
    "stale timestamps and silently drop pending holds."
)
MSG_2_ARTIFACT_KIND = "assistant_output"

# The thread material (as built by _build_thread_material) will look like:
# "user/message: <MSG_1_CONTENT>\nassistant/assistant_output: <MSG_2_CONTENT>"
#
# Investigation text and evidence MUST be substrings of the thread material
# (after normalization).  We extract from the assistant line.
INVESTIGATION_TEXT = (
    "arrival-time ordering skipped hold updates during catalog sync delays "
    "because the provider delivered updates late, causing the reservation queue to process "
    "stale timestamps and silently drop pending holds"
)
INVESTIGATION_EVIDENCE = (
    "I found that arrival-time ordering skipped hold updates during catalog sync delays "
    "because the provider delivered updates late, causing the reservation queue to process "
    "stale timestamps and silently drop pending holds."
)

# Weak thread content: not enough substance for an investigation
WEAK_MSG_1_CONTENT = "Can you check the sync logs for any issues?"
WEAK_MSG_2_CONTENT = "Looking into it now, I will check the catalog sync status."


class InvestigationStubProvider:
    """Stub LLM provider that returns canned responses for item extraction and thread summary."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        # Thread summary call (with or without task_checkpoint)
        if "Thread items:" in user_prompt:
            return self._thread_summary_response(user_prompt, schema_description)
        # Per-item extraction call
        return self._per_item_response(user_prompt)

    def _thread_summary_response(self, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        lower = user_prompt.lower()
        # Only return investigations for the substantive thread
        if "arrival-time ordering skipped hold updates" in lower:
            payload = {
                "summary": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
                "content_quality": "substantive",
                "retrieval_context": None,
                "decisions": [],
                "investigations": [
                    {
                        "investigation_text": INVESTIGATION_TEXT,
                        "evidence": INVESTIGATION_EVIDENCE,
                    }
                ],
            }
            # If merged call includes task_checkpoint, add a minimal one
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "Investigation complete.",
                    "task": "Investigate hold ordering issue.",
                    "current_state": "Root cause identified.",
                    "key_findings": ["arrival-time ordering causes dropped holds"],
                    "blocker_state": "",
                    "next_step": "",
                    "evidence": [],
                    "freshness_signal": "Latest explicit update at 2026-03-11T11:02:00Z.",
                    "retrieval_context": None,
                }
        else:
            # Weak thread -- no investigations
            payload = {
                "summary": "Checking sync logs.",
                "content_quality": "thin",
                "retrieval_context": None,
                "decisions": [],
                "investigations": [],
            }
            if "task_checkpoint" in schema_description:
                payload["task_checkpoint"] = {
                    "summary": "Checking sync logs.",
                    "task": "Check sync logs.",
                    "current_state": "",
                    "key_findings": [],
                    "blocker_state": "",
                    "next_step": "",
                    "evidence": [],
                    "freshness_signal": "Latest explicit update time was not recorded.",
                    "retrieval_context": None,
                }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)

    def _per_item_response(self, user_prompt: str) -> LLMJsonResponse:
        lower = user_prompt.lower()
        if "arrival-time ordering skipped hold updates" in lower:
            payload = {
                "summary": "Investigation about hold ordering.",
                "candidate_type": "investigation_outcome",
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": INVESTIGATION_TEXT,
                "investigation_evidence_text": INVESTIGATION_EVIDENCE,
                "rationale_text": "because the provider delivered updates late",
                "is_low_value_meta": False,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": "arrival-time ordering skipped hold updates during catalog sync delays because the provider delivered updates late",
            }
        elif "why are some library holds disappearing" in lower:
            # User question -- substantive, requests thread rebuild
            payload = {
                "summary": "Question about disappearing holds.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
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
        else:
            # Default: low-value / thin content
            payload = {
                "summary": "Conversation item.",
                "candidate_type": None,
                "decision_text": None,
                "decision_evidence_text": None,
                "investigation_text": None,
                "investigation_evidence_text": None,
                "rationale_text": None,
                "is_low_value_meta": "check" in lower and "logs" in lower,
                "constraint_text": None,
                "next_step_text": None,
                "blocker_text": None,
                "progress_text": None,
                "key_finding_text": None,
            }
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _create_investigation_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr("app.dependencies.build_llm_provider", lambda config, **_: InvestigationStubProvider())
    config = build_llm_test_config(
        default_use_case="agent_conversation_memory",
        sqlite_url=test_db_url,
        model="fake-model",
    )
    client = TestClient(create_app(config))
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
            client.app.state.pallium_service.drain_processing_queue(worker_id="investigation-e2e-test")
        return response

    client.post = post_with_public_visibility
    return client


# ---------------------------------------------------------------------------
# Test 1: investigation_outcome is extracted from thread rebuild
# ---------------------------------------------------------------------------


def test_thread_investigation_extracted_with_correct_properties(monkeypatch, test_db_url: str) -> None:
    """Full e2e: ingest 2 items -> thread rebuild -> investigation_outcome memory exists."""
    client = _create_investigation_client(monkeypatch, test_db_url)

    # Ingest two items in the same thread (meets MIN_THREAD_SIZE_FOR_SUMMARY)
    client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": "inv-thread-msg-1",
        "content_type": "text/plain",
        "content": MSG_1_CONTENT,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": CONTAINER_REF,
        "thread_ref": INVESTIGATION_THREAD_REF,
    }])
    client.post("/items", json=[{
        "source_type": "assistant_artifact",
        "source_id": "inv-thread-msg-2",
        "content_type": "text/plain",
        "content": MSG_2_CONTENT,
        "artifact_kind": MSG_2_ARTIFACT_KIND,
        "role": "assistant",
        "container_ref": CONTAINER_REF,
        "thread_ref": INVESTIGATION_THREAD_REF,
    }])

    # Verify investigation_outcome memory was created
    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(CONTAINER_REF, INVESTIGATION_THREAD_REF)
    assert len(thread_items) == 2

    all_memory = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
    ]
    investigations = [m for m in all_memory if m.type == "investigation_outcome"]
    assert len(investigations) >= 1, f"Expected investigation_outcome, got types: {[m.type for m in all_memory]}"

    # Filter for thread-detected investigation specifically
    thread_investigations = [m for m in investigations if m.payload.get("source_type") == "thread_detection"]
    assert len(thread_investigations) >= 1, (
        f"Expected thread_detection investigation, got source_types: "
        f"{[m.payload.get('source_type') for m in investigations]}"
    )

    inv = thread_investigations[0]
    # Verify payload structure
    assert inv.payload["source_type"] == "thread_detection"
    assert inv.payload["source_id"] == f"thread:{INVESTIGATION_THREAD_REF}"
    assert inv.payload["investigation_outcome"] == INVESTIGATION_TEXT
    assert inv.payload["investigation_evidence_text"] == INVESTIGATION_EVIDENCE
    assert inv.lifecycle == "active"
    assert inv.container_ref == CONTAINER_REF

    # Verify supported_by relations to source items
    source_item_ids = {item.id for item in thread_items}
    supported_by_count = 0
    for source_item in thread_items:
        relations = storage.list_relations_for_source_item(source_item.id)
        for rel in relations:
            if rel.from_id == inv.id and rel.relation_type == "supported_by":
                supported_by_count += 1
    assert supported_by_count == len(thread_items)


# ---------------------------------------------------------------------------
# Test 2: investigation is retrievable via query
# ---------------------------------------------------------------------------


def test_thread_investigation_queryable(monkeypatch, test_db_url: str) -> None:
    """The thread-extracted investigation_outcome should be retrievable via /query."""
    client = _create_investigation_client(monkeypatch, test_db_url)

    client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": "inv-query-msg-1",
        "content_type": "text/plain",
        "content": MSG_1_CONTENT,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": CONTAINER_REF,
        "thread_ref": INVESTIGATION_THREAD_REF,
    }])
    client.post("/items", json=[{
        "source_type": "assistant_artifact",
        "source_id": "inv-query-msg-2",
        "content_type": "text/plain",
        "content": MSG_2_CONTENT,
        "artifact_kind": MSG_2_ARTIFACT_KIND,
        "role": "assistant",
        "container_ref": CONTAINER_REF,
        "thread_ref": INVESTIGATION_THREAD_REF,
    }])

    # Query for the investigation
    query_response = client.post("/query", json={
        "text": "why do hold updates get skipped during catalog sync delays",
        "limit": 10,
        "container_ref": CONTAINER_REF,
    })
    assert query_response.status_code == 200
    results = query_response.json()["results"]

    # The investigation should appear somewhere in results
    investigation_results = [r for r in results if r.get("type") == "investigation_outcome"]
    assert len(investigation_results) >= 1, (
        f"Expected investigation_outcome in query results, got types: {[r.get('type') for r in results]}"
    )
    inv_result = investigation_results[0]
    assert "arrival-time ordering" in inv_result["payload"]["investigation_outcome"]


# ---------------------------------------------------------------------------
# Test 3: weak thread does NOT produce investigation
# ---------------------------------------------------------------------------


def test_weak_thread_does_not_produce_investigation(monkeypatch, test_db_url: str) -> None:
    """A thread with thin content should not produce investigation_outcome memory."""
    client = _create_investigation_client(monkeypatch, test_db_url)
    weak_thread_ref = "chat:library-help:thread-investigation-e2e-weak"

    client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": "inv-weak-msg-1",
        "content_type": "text/plain",
        "content": WEAK_MSG_1_CONTENT,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": CONTAINER_REF,
        "thread_ref": weak_thread_ref,
    }])
    client.post("/items", json=[{
        "source_type": "assistant_artifact",
        "source_id": "inv-weak-msg-2",
        "content_type": "text/plain",
        "content": WEAK_MSG_2_CONTENT,
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "container_ref": CONTAINER_REF,
        "thread_ref": weak_thread_ref,
    }])

    storage = client.app.state.pallium_service._storage
    thread_items = storage.list_source_items_for_thread(CONTAINER_REF, weak_thread_ref)
    all_memory = [
        memory
        for item in thread_items
        for memory in storage.list_memory_objects_for_source_item(item.id)
    ]
    investigations = [m for m in all_memory if m.type == "investigation_outcome"]
    assert len(investigations) == 0, (
        f"Weak thread should not produce investigation_outcome, got {len(investigations)}"
    )
