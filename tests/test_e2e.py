from __future__ import annotations


def test_end_to_end_simulation_flow(client) -> None:
    sample_items = [
        {
            "source_type": "chat_message",
            "source_id": "thread-001-msg-1",
            "content_type": "text/plain",
            "content": "We need to decide whether reservation ordering should use arrival time or item event time. Arrival time may miss hold updates when catalog sync delays.",
            "metadata": {"topic": "reservation ordering"},
            "artifact_kind": "message",
            "role": "user",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "actor_ref": "slack:U123",
            "source_ref": "https://example.test/slack/thread-001-msg-1",
        },
        {
            "source_type": "tool_summary",
            "source_id": "artifact-001",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering missed hold updates during sync delays because the catalog provider delivered updates late.",
            "metadata": {"topic": "reservation ordering"},
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "actor_ref": "agent:assistant",
            "source_ref": "https://example.test/slack/artifact-001",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "artifact-002",
            "content_type": "text/plain",
            "content": "Decision: use item item event time reservation ordering for reservation ordering to avoid missed hold updates during sync delays.",
            "metadata": {"topic": "reservation ordering"},
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": "slack:C123",
            "thread_ref": "slack:C123:1730000000.000100",
            "actor_ref": "agent:assistant",
            "source_ref": "https://example.test/slack/artifact-002",
        },
    ]

    for item in sample_items:
        assert client.post("/items", json=[item]).status_code == 200
    for item in sample_items:
        assert client.post("/items", json=[item]).status_code == 200

    client.app.state.pallium_service.drain_processing_queue(worker_id="e2e-test")

    decision_query = client.post(
        "/query",
        json={"text": "why did we choose item item event time reservation ordering?", "limit": 6, "thread_ref": "slack:C123:1730000000.000100"},
    )
    decision_payload = decision_query.json()
    assert any(item.get("type") == "decision" for item in decision_payload["results"] if item["result_kind"] == "memory_hit")
    assert any(item.get("source_id") == "artifact-002" for item in decision_payload["results"] if item["result_kind"] == "source_hit")

    investigation_query = client.post(
        "/query",
        json={"text": "what did the investigation find about missed hold updates?", "limit": 6, "thread_ref": "slack:C123:1730000000.000100"},
    )
    investigation_payload = investigation_query.json()
    assert any(item.get("type") == "investigation_outcome" for item in investigation_payload["results"] if item["result_kind"] == "memory_hit")
    assert any(item.get("source_id") == "artifact-001" for item in investigation_payload["results"] if item["result_kind"] == "source_hit")
