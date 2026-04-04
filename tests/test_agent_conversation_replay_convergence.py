from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow

from tests.agent_conversation_replay_helpers import (
    _agent_conversation_client,
    _drain_processing_queue,
    _render_injected_text,
)


def test_batch_digest_recall_converges_from_pending_source_evidence_to_structured_memory(monkeypatch, test_db_url: str) -> None:
    client = _agent_conversation_client(monkeypatch, test_db_url, auto_drain_items=False)
    container_ref = "chat:workspace:local-memory"
    thread_ref = "chat:workspace:local-memory:thread-pending-convergence"
    visibility = "public"

    payloads = (
        {
            "source_type": "chat_message",
            "source_id": "pending-msg-1",
            "content_type": "text/plain",
            "content": "Please summarize the latest batch digest work for this workspace.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "occurred_at": "2026-03-11T10:00:00Z",
            "visibility": visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "pending-artifact-1",
            "content_type": "text/plain",
            "content": "Partial progress: prepared the batch digest for SLOT-103, SLOT-204, SLOT-317, and SLOT-418.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "occurred_at": "2026-03-11T10:01:00Z",
            "visibility": visibility,
        },
        {
            "source_type": "chat_message",
            "source_id": "pending-msg-2",
            "content_type": "text/plain",
            "content": "Please remember not to use control-panel sign-in, and do not open a browser sign-in flow.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "occurred_at": "2026-03-11T10:01:30Z",
            "visibility": visibility,
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "pending-artifact-2",
            "content_type": "text/plain",
            "content": "Next step: refresh the local digest token and rerun the batch digest from the last confirmed segment.",
            "artifact_kind": "todo_snapshot",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "occurred_at": "2026-03-11T10:02:00Z",
            "visibility": visibility,
        },
    )
    for payload in payloads:
        response = client.post("/items", json=[payload])
        assert response.status_code == 200
        assert response.json()[0]["processing_status"] == "pending"

    query_payload = {
        "text": "can you remind me what we had latest about batch digests?",
        "limit": 12,
        "container_ref": container_ref,
        "thread_ref": "chat:workspace:local-memory:thread-pending-query",
        "visibility": visibility,
        "runtime_context": {
            "turn_kind": "new_thread",
            "session_has_sufficient_local_context": False,
        },
    }

    pending_response = client.post("/query/debug", json=query_payload)
    assert pending_response.status_code == 200
    pending_payload = pending_response.json()
    pending_routing = pending_payload["trace"]["routing"]
    assert pending_payload["should_inject"] is False
    assert pending_payload["decision_reason"] == "no_relevant_memory"
    assert pending_routing["query_family"] == "recall"
    assert pending_routing["selected_layer"] == "source_evidence"
    assert pending_payload["results"][0]["result_kind"] == "source_hit"
    assert pending_payload["results"][0]["memory_object_id"] is None
    assert pending_payload["injectable_blocks"] == []

    _drain_processing_queue(client, worker_id="replay-convergence-test")

    after_response = client.post("/query/debug", json=query_payload)
    assert after_response.status_code == 200
    after_payload = after_response.json()
    after_routing = after_payload["trace"]["routing"]
    after_text = _render_injected_text(after_payload)
    assert after_payload["should_inject"] is True
    assert after_payload["decision_reason"] == "carry_forward_available"
    assert after_routing["query_family"] == "recall"
    assert after_routing["selected_layer"] in {"task_checkpoint", "thread_summary"}
    assert after_payload["results"][0]["result_kind"] == "memory_hit"
    assert after_payload["results"][0]["type"] in {"task_checkpoint", "thread_summary"}
    assert all(block["block_type"] == "memory" for block in after_payload["injectable_blocks"])
    assert "batch digest" in after_text or "last confirmed segment" in after_text
    assert "control-panel sign-in" in after_text or "browser sign-in" in after_text
    assert "attempt control-panel sign-in" not in after_text
    assert pending_routing["selected_layer"] != after_routing["selected_layer"]
