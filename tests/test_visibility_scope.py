from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


def _build_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    return TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))


def _ingest(client: TestClient, *, source_id: str, content: str, container_visibility: str | None, container_ref: str = "chat:privacy", thread_ref: str = "chat:privacy:thread-1") -> dict[str, object]:
    payload: dict[str, object] = {
        "source_type": "assistant_artifact",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "assistant_output",
        "role": "assistant",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
    }
    if container_visibility is not None:
        payload["container_visibility"] = container_visibility
    response = client.post("/items", json=payload)
    assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")
    return response.json()


def _query(client: TestClient, *, container_visibility: str | None, container_ref: str = "chat:privacy", debug: bool = False, text: str = "what did we decide about reservation ordering?") -> dict[str, object]:
    payload: dict[str, object] = {
        "text": text,
        "limit": 10,
        "container_ref": container_ref,
    }
    if container_visibility is not None:
        payload["container_visibility"] = container_visibility
    response = client.post(
        "/query/debug" if debug else "/query",
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def test_public_query_sees_public_items_from_any_container(monkeypatch, test_db_url: str) -> None:
    """Public items are visible everywhere regardless of container_ref."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="limited-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited", container_ref="chat:room-a")
        _ingest(client, source_id="private-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="private", container_ref="chat:room-b")

        payload = _query(client, container_visibility="public", container_ref="chat:room-c")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-1" in returned_source_ids
        assert "limited-1" not in returned_source_ids
        assert "private-1" not in returned_source_ids


def test_limited_query_sees_public_and_same_container_limited(monkeypatch, test_db_url: str) -> None:
    """Limited items are visible within the same container_ref; public items are always visible."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="limited-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited", container_ref="chat:room-a")
        _ingest(client, source_id="limited-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited", container_ref="chat:room-b")
        _ingest(client, source_id="private-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="private", container_ref="chat:room-a")

        payload = _query(client, container_visibility="limited", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-2" in returned_source_ids
        assert "limited-a" in returned_source_ids
        assert "limited-b" not in returned_source_ids


def test_private_query_sees_public_and_same_container_private(monkeypatch, test_db_url: str) -> None:
    """Private items are visible only within the same container_ref; public items are always visible."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-3", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="private-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="private", container_ref="chat:room-a")
        _ingest(client, source_id="private-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="private", container_ref="chat:room-b")
        _ingest(client, source_id="limited-c", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited", container_ref="chat:room-c")

        payload = _query(client, container_visibility="private", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-3" in returned_source_ids
        assert "private-a" in returned_source_ids
        assert "private-b" not in returned_source_ids
        assert "limited-c" not in returned_source_ids


def test_missing_query_visibility_fails_closed(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-4", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public")

        payload = _query(client, container_visibility=None, debug=True)
        assert payload["results"] == []
        assert payload["trace"]["stages"] == []
        assert payload["trace"]["visibility"]["fail_closed_reason"] == "query_visibility_context_required"


def test_missing_ingest_visibility_does_not_promote_or_retrieve(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        create_payload = _ingest(
            client,
            source_id="missing-visibility",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            container_visibility=None,
        )
        assert create_payload["memory_object_ids"] == []
        assert create_payload["processing_status"] == "skipped"

        payload = _query(client, container_visibility="public", debug=True)
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "missing-visibility" not in returned_source_ids
        reasons = {item["reason"] for item in payload["trace"]["visibility"]["excluded_candidates"]}
        assert "candidate_visibility_context_missing" in reasons


def test_thread_aggregation_stays_within_exact_visibility_context(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        client.post(
            "/items",
            json={
                "source_type": "chat_message",
                "source_id": "thread-public-msg",
                "content_type": "text/plain",
                "content": "Why are duplicate holds happening?",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "container_visibility": "public",
            },
        )
        client.post(
            "/items",
            json={
                "source_type": "assistant_artifact",
                "source_id": "thread-limited-artifact",
                "content_type": "text/plain",
                "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "container_visibility": "limited",
            },
        )
        client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")

        storage = client.app.state.pallium_service._storage
        summaries = [item for item in storage.list_memory_objects(memory_types=["thread_summary"], lifecycle="active")]
        assert len(summaries) == 2
        summary_visibilities = {item.container_visibility for item in summaries}
        assert summary_visibilities == {"public", "limited"}
        for summary in summaries:
            evidence = storage.get_evidence_for_memory_object(summary.id)
            assert all(e.container_visibility == summary.container_visibility for e in evidence)


def test_consolidation_does_not_cross_visibility_contexts(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="public-thread-a",
            content="Investigation found that arrival-time ordering reused stale hold updates during delayed sync.",
            container_visibility="public",
            thread_ref="chat:privacy:thread-a",
        )
        _ingest(
            client,
            source_id="limited-thread-b",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            container_visibility="limited",
            thread_ref="chat:privacy:thread-b",
        )

        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case="agent_conversation_memory",
            strategy_name="container_topic_window",
        )
        assert result is not None
        assert result.groups == ()


def test_debug_trace_reports_visibility_exclusions(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public")
        _ingest(client, source_id="limited-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited")

        payload = _query(client, container_visibility="public", debug=True)
        exclusions = payload["trace"]["visibility"]["excluded_candidates"]
        assert exclusions
        assert any(item["reason"] == "query_visibility_context_excludes_candidate" for item in exclusions)
        assert any(item["count"] >= 1 for item in exclusions)
        assert all("target_id" not in item for item in exclusions)
        assert all("candidate_visibility_context" not in item for item in exclusions)



def test_public_query_injectable_blocks_respect_visibility(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public")
        _ingest(client, source_id="limited-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited")

        payload = _query(client, container_visibility="public")
        assert payload["should_inject"] is True
        assert payload["injectable_blocks"]
        visible_result_ids = {item["result_id"] for item in payload["results"]}
        assert {block["result_id"] for block in payload["injectable_blocks"]}.issubset(visible_result_ids)
        for block in payload["injectable_blocks"]:
            for evidence in block["evidence"]:
                assert evidence["container_visibility"] == "public"


def test_is_visible_passes_through_when_no_query_container_ref() -> None:
    from core.visibility import is_visible

    # Public items are always visible
    assert is_visible("public", "container-a", None) is True
    assert is_visible("public", None, None) is True
    # Limited/private items need matching container_ref
    assert is_visible("limited", "container-a", "container-a") is True
    assert is_visible("limited", "container-a", "container-b") is False
    assert is_visible("private", "container-a", "container-a") is True
    assert is_visible("private", "container-a", None) is False


def test_lexical_retrieval_with_require_visibility_and_none_context_returns_empty(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-retrieval-none", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public")
        _ingest(client, source_id="limited-retrieval-none", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited")

        retrieval = client.app.state.pallium_service._retrieval
        result = retrieval.query(
            text="reservation ordering duplicate holds",
            limit=10,
            container_visibility=None,
            require_visibility=True,
        )
        assert result.results == []

        # Without require_visibility, None means "no filtering" (non-scoped plugin path)
        unscoped_result = retrieval.query(
            text="reservation ordering duplicate holds",
            limit=10,
            container_visibility=None,
            require_visibility=False,
        )
        assert len(unscoped_result.results) > 0


def test_debug_sharp_candidate_diagnostics_do_not_leak_hidden_candidates(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="public")
        _ingest(client, source_id="limited-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", container_visibility="limited")

        payload = _query(client, container_visibility="public", debug=True)
        diagnostics = payload["trace"]["routing"]["sharp_candidate_diagnostics"]
        public_result_ids = {item["result_id"] for item in payload["results"] if item.get("container_visibility") == "public"}
        assert diagnostics
        assert all(entry["result_id"] in public_result_ids for entry in diagnostics)
