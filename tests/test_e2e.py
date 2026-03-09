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
            "source_type": "chat_message",
            "source_id": "thread-001-msg-2",
            "content_type": "text/plain",
            "content": "Event time seems safer because ingestion time can skip records when EventHub lag spikes.",
            "metadata": {"topic": "watermarking"},
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
            "actor_ref": "slack:U456",
            "source_ref": "https://example.test/slack/thread-001-msg-2",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "artifact-001",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
            "metadata": {"topic": "watermarking"},
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
            "actor_ref": "agent:assistant",
            "source_ref": "https://example.test/slack/artifact-001",
        },
    ]

    for item in sample_items:
        response = client.post("/items", json=item)
        assert response.status_code == 200

    for item in sample_items:
        repeat_response = client.post("/items", json=item)
        assert repeat_response.status_code == 200

    query_response = client.post(
        "/query",
        json={
            "text": "why did we choose event timestamp watermarking?",
            "limit": 6,
            "thread_ref": "slack:C123:1730000000.000100",
            "session_ref": "agent-session-1",
        },
    )
    assert query_response.status_code == 200

    payload = query_response.json()
    assert payload["results"]
    result_kinds = {item["result_kind"] for item in payload["results"]}
    assert "memory_hit" in result_kinds
    assert "source_hit" in result_kinds

    memory_hits = [item for item in payload["results"] if item["result_kind"] == "memory_hit"]
    source_hits = [item for item in payload["results"] if item["result_kind"] == "source_hit"]
    assert any(item.get("type") == "decision" for item in memory_hits)
    assert any(item.get("type") == "discussion_summary" for item in memory_hits)
    assert any(item.get("source_id") == "artifact-001" for item in source_hits)
    assert len([item for item in source_hits if item.get("source_id") == "artifact-001"]) == 1
    assert all("excerpt" in item for item in source_hits)
    assert all("content" not in item for item in source_hits)
