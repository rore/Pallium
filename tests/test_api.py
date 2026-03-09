from __future__ import annotations


def test_post_items_creates_fallback_summary_artifacts(client) -> None:
    response = client.post(
        "/items",
        json={
            "source_type": "chat_thread",
            "source_id": "thread-123",
            "content_type": "text/plain",
            "content": "We should use event time for watermarking. It avoids skipped records.",
            "metadata": {"topic": "exports"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert len(payload["annotation_ids"]) == 1
    assert len(payload["memory_object_ids"]) == 1
    assert len(payload["relation_ids"]) == 1
    assert len(payload["index_entry_ids"]) == 2

    query_response = client.post(
        "/query",
        json={"text": "event time watermarking", "limit": 5},
    )
    assert query_response.status_code == 200
    memory_hits = [
        item for item in query_response.json()["results"] if item["result_kind"] == "memory_hit"
    ]
    assert any(item["type"] == "discussion_summary" for item in memory_hits)


def test_post_items_is_idempotent_on_source_reference(client) -> None:
    request = {
        "source_type": "decision_note",
        "source_id": "decision-1",
        "content_type": "text/plain",
        "content": "Decision: use event timestamp watermarking for exports to avoid skipped records.",
    }

    first_response = client.post("/items", json=request)
    second_response = client.post("/items", json=request)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(first_response.json()["annotation_ids"]) == 2
    assert len(first_response.json()["memory_object_ids"]) == 1
    assert second_response.json() == first_response.json()


def test_post_query_returns_decision_memory_and_source_hits(client) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "decision-1",
            "content_type": "text/plain",
            "content": "Decision: use event timestamp watermarking for exports to avoid skipped records during lag.",
        },
    )

    response = client.post(
        "/query",
        json={"text": "what did we decide about watermarking?", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) >= 2
    result_kinds = {result["result_kind"] for result in payload["results"]}
    assert "memory_hit" in result_kinds
    assert "source_hit" in result_kinds

    memory_hit = next(result for result in payload["results"] if result["result_kind"] == "memory_hit")
    assert memory_hit["type"] == "decision"
    assert memory_hit["payload"]["decision"] == "use event timestamp watermarking for exports"
    assert memory_hit["payload"]["rationale"] == "to avoid skipped records during lag"
    assert len(memory_hit["evidence"]) == 1

    source_hit = next(result for result in payload["results"] if result["result_kind"] == "source_hit")
    assert source_hit["source_item_id"]
    assert source_hit["source_type"] == "decision_note"
    assert source_hit["source_id"] == "decision-1"
    assert source_hit["content"]
