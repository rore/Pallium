from __future__ import annotations


def test_end_to_end_simulation_flow(client) -> None:
    sample_items = [
        {
            "source_type": "chat_message",
            "source_id": "thread-001-msg-1",
            "content_type": "text/plain",
            "content": "We need to decide whether export watermarking should use ingestion time or event time. Ingestion time may skip records when lag spikes.",
            "metadata": {"topic": "watermarking"},
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
            "actor_ref": "slack:U123",
            "source_ref": "https://example.test/slack/thread-001-msg-1",
        },
        {
            "source_type": "tool_summary",
            "source_id": "artifact-001",
            "content_type": "text/plain",
            "content": "Investigation found that ingestion-time progress tracking skipped records during lag because EventHub lag delayed ingestion.",
            "metadata": {"topic": "watermarking"},
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
            "actor_ref": "agent:assistant",
            "source_ref": "https://example.test/slack/artifact-001",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "artifact-002",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
            "metadata": {"topic": "watermarking"},
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
            "actor_ref": "agent:assistant",
            "source_ref": "https://example.test/slack/artifact-002",
        },
    ]

    for item in sample_items:
        response = client.post("/items", json=item)
        assert response.status_code == 200

    for item in sample_items:
        repeat_response = client.post("/items", json=item)
        assert repeat_response.status_code == 200

    decision_query = client.post(
        "/query",
        json={
            "text": "why did we choose event timestamp watermarking?",
            "limit": 6,
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
        },
    )
    assert decision_query.status_code == 200
    decision_payload = decision_query.json()
    assert any(item.get("type") == "decision" for item in decision_payload["results"] if item["result_kind"] == "memory_hit")
    assert any(item.get("source_id") == "artifact-002" for item in decision_payload["results"] if item["result_kind"] == "source_hit")

    investigation_query = client.post(
        "/query",
        json={
            "text": "what did the investigation find about skipped records?",
            "limit": 6,
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
        },
    )
    assert investigation_query.status_code == 200
    investigation_payload = investigation_query.json()
    assert any(item.get("type") == "investigation_outcome" for item in investigation_payload["results"] if item["result_kind"] == "memory_hit")
    assert any(item.get("source_id") == "artifact-001" for item in investigation_payload["results"] if item["result_kind"] == "source_hit")
