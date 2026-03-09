from __future__ import annotations


def test_end_to_end_simulation_flow(client) -> None:
    sample_items = [
        {
            "source_type": "chat_thread",
            "source_id": "thread-001",
            "content_type": "text/plain",
            "content": "We need to decide whether export watermarking should use ingestion time or event time. Ingestion time may skip records when lag spikes.",
            "metadata": {"topic": "watermarking"},
        },
        {
            "source_type": "investigation_summary",
            "source_id": "investigation-001",
            "content_type": "text/plain",
            "content": "Skipped records were observed when EventHub lag increased. The issue correlates with using ingestion-time progress tracking.",
            "metadata": {"topic": "watermarking"},
        },
        {
            "source_type": "decision_note",
            "source_id": "decision-001",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
            "metadata": {"topic": "watermarking"},
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
        json={"text": "why do we use event timestamp watermarking?", "limit": 6},
    )
    assert query_response.status_code == 200

    payload = query_response.json()
    assert payload["results"]
    result_kinds = {item["result_kind"] for item in payload["results"]}
    assert "memory_hit" in result_kinds
    assert "source_hit" in result_kinds

    memory_hits = [item for item in payload["results"] if item["result_kind"] == "memory_hit"]
    source_hits = [item for item in payload["results"] if item["result_kind"] == "source_hit"]
    assert any(item.get("type") == "discussion_summary" for item in memory_hits)
    assert any(item.get("source_id") == "decision-001" for item in source_hits)
    assert len([item for item in source_hits if item.get("source_id") == "decision-001"]) == 1
