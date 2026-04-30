from __future__ import annotations


def test_item_and_query_basic_round_trip(client) -> None:
    response = client.post(
        "/item-and-query",
        json={
            "source_type": "chat_thread",
            "source_id": "iq-msg-1",
            "content_type": "text/plain",
            "content": "We should use item event time for reservation ordering. It avoids missed hold updates.",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert isinstance(payload["results"], list)
    assert isinstance(payload["should_inject"], bool)
    assert isinstance(payload["decision_reason"], str)
    assert isinstance(payload["injectable_blocks"], list)


def test_item_and_query_content_is_used_as_default_query_text(client) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "iq-seed-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid missed hold updates.",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    response = client.post(
        "/item-and-query",
        json={
            "source_type": "chat_thread",
            "source_id": "iq-msg-2",
            "content_type": "text/plain",
            "content": "reservation ordering hold updates",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert any(item["result_kind"] == "source_hit" for item in payload["results"])


def test_item_and_query_query_text_override(client) -> None:
    client.post(
        "/items",
        json={
            "source_type": "decision_note",
            "source_id": "iq-seed-2",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid missed hold updates.",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    response = client.post(
        "/item-and-query",
        json={
            "source_type": "chat_thread",
            "source_id": "iq-msg-3",
            "content_type": "text/plain",
            "content": "Something completely unrelated to the decision about ordering.",
            "artifact_kind": "message",
            "role": "user",
            "query_text": "what did we decide about reservation ordering?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert any(item["result_kind"] == "source_hit" for item in payload["results"])


def test_item_and_query_debug_returns_trace(client) -> None:
    response = client.post(
        "/item-and-query/debug",
        json={
            "source_type": "chat_thread",
            "source_id": "iq-debug-msg-1",
            "content_type": "text/plain",
            "content": "We should use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert "trace" in payload
    assert payload["trace"]["query_text"]
    assert isinstance(payload["trace"]["stages"], list)


def test_item_and_query_missing_content_fails_validation(client) -> None:
    response = client.post(
        "/item-and-query",
        json={
            "source_type": "chat_thread",
            "source_id": "iq-msg-no-content",
            "content_type": "text/plain",
            "artifact_kind": "message",
            "role": "user",
        },
    )

    assert response.status_code == 422


def test_item_and_query_minimal_item_fields(client) -> None:
    response = client.post(
        "/item-and-query",
        json={
            "source_type": "note",
            "source_id": "iq-minimal-1",
            "content_type": "text/plain",
            "content": "A minimal note for testing query behavior.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_item_id"]
    assert isinstance(payload["results"], list)
    assert isinstance(payload["should_inject"], bool)
    assert isinstance(payload["decision_reason"], str)


def test_item_and_query_respects_query_limit(client) -> None:
    for i in range(6):
        client.post(
            "/items",
            json={
                "source_type": "note",
                "source_id": f"iq-limit-seed-{i}",
                "content_type": "text/plain",
                "content": f"Reservation ordering note number {i} about hold updates.",
            },
        )

    response = client.post(
        "/item-and-query",
        json={
            "source_type": "note",
            "source_id": "iq-limit-query",
            "content_type": "text/plain",
            "content": "reservation ordering hold updates",
            "query_limit": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) <= 2


def test_item_and_query_ingest_is_idempotent(client) -> None:
    request_json = {
        "source_type": "chat_thread",
        "source_id": "iq-idempotent-1",
        "content_type": "text/plain",
        "content": "Decision: use item event time for reservation ordering.",
        "artifact_kind": "message",
        "role": "user",
    }

    first = client.post("/item-and-query", json=request_json)
    second = client.post("/item-and-query", json=request_json)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["source_item_id"] == second.json()["source_item_id"]
