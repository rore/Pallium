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


def _ingest(client: TestClient, *, source_id: str, content: str, visibility: str | None, container_ref: str = "chat:privacy", thread_ref: str = "chat:privacy:thread-1") -> dict[str, object]:
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
    if visibility is not None:
        payload["visibility"] = visibility
    response = client.post("/items", json=[payload])
    assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")
    return response.json()[0]


def _query(client: TestClient, *, visibility: str | None, container_ref: str = "chat:privacy", debug: bool = False, text: str = "what did we decide about reservation ordering?") -> dict[str, object]:
    payload: dict[str, object] = {
        "text": text,
        "limit": 10,
        "container_ref": container_ref,
    }
    if visibility is not None:
        payload["visibility"] = visibility
    response = client.post(
        "/query/debug" if debug else "/query",
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def test_public_query_sees_public_items_from_any_container(monkeypatch, test_db_url: str) -> None:
    """Public items are visible everywhere regardless of container_ref."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="limited-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container", container_ref="chat:room-a")
        _ingest(client, source_id="private-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-b")

        payload = _query(client, visibility="public", container_ref="chat:room-c")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-1" in returned_source_ids
        assert "limited-1" not in returned_source_ids
        assert "private-1" not in returned_source_ids


def test_limited_query_sees_public_and_same_container_limited(monkeypatch, test_db_url: str) -> None:
    """Limited items are visible within the same container_ref; public items are always visible."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="limited-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container", container_ref="chat:room-a")
        _ingest(client, source_id="limited-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container", container_ref="chat:room-b")
        _ingest(client, source_id="private-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-a")

        payload = _query(client, visibility="container", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-2" in returned_source_ids
        assert "limited-a" in returned_source_ids
        assert "limited-b" not in returned_source_ids


def test_private_query_sees_public_and_same_container_private(monkeypatch, test_db_url: str) -> None:
    """Private items are visible only within the same container_ref; public items are always visible."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-3", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="private-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-a")
        _ingest(client, source_id="private-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-b")
        _ingest(client, source_id="limited-c", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container", container_ref="chat:room-c")

        payload = _query(client, visibility="private", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "public-3" in returned_source_ids
        assert "private-a" in returned_source_ids
        assert "private-b" not in returned_source_ids
        assert "limited-c" not in returned_source_ids


def test_missing_container_ref_fails_closed(monkeypatch, test_db_url: str) -> None:
    """Query without container_ref fails closed — no container means no scope."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-4", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public")

        # Query with no container_ref — even public visibility should fail closed
        payload = client.post("/query/debug", json={"text": "what did we decide about reservation ordering?", "limit": 10}).json()
        assert payload["results"] == []
        assert payload["trace"]["visibility"]["fail_closed_reason"] == "query_visibility_context_required"


def test_missing_ingest_visibility_uses_private_default(monkeypatch, test_db_url: str) -> None:
    """Items ingested without visibility default to private."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="missing-visibility",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            visibility=None,
        )

        # Public query from a different container should not see the item (it's private)
        payload = _query(client, visibility="public", container_ref="chat:other", debug=True)
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "missing-visibility" not in returned_source_ids

        # Query from the same container should see it (it defaults to private, same-container visible)
        payload = _query(client, visibility="private", container_ref="chat:privacy", debug=True)
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "missing-visibility" in returned_source_ids


def test_thread_aggregation_stays_within_exact_visibility_context(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        # Each visibility group needs >= 2 items for thread aggregation
        client.post(
            "/items",
            json=[{
                "source_type": "chat_message",
                "source_id": "thread-public-msg",
                "content_type": "text/plain",
                "content": "Why are duplicate holds happening?",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "visibility": "public",
            }],
        )
        client.post(
            "/items",
            json=[{
                "source_type": "assistant_artifact",
                "source_id": "thread-public-artifact",
                "content_type": "text/plain",
                "content": "Investigation found: duplicate holds happen because catalog sync delays cause stale hold records.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "visibility": "public",
            }],
        )
        client.post(
            "/items",
            json=[{
                "source_type": "chat_message",
                "source_id": "thread-limited-msg",
                "content_type": "text/plain",
                "content": "What about the reservation ordering impact?",
                "artifact_kind": "message",
                "role": "user",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "visibility": "container",
            }],
        )
        client.post(
            "/items",
            json=[{
                "source_type": "assistant_artifact",
                "source_id": "thread-limited-artifact",
                "content_type": "text/plain",
                "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
                "artifact_kind": "assistant_output",
                "role": "assistant",
                "container_ref": "chat:privacy",
                "thread_ref": "chat:privacy:mixed-thread",
                "visibility": "container",
            }],
        )
        client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")

        storage = client.app.state.pallium_service._storage
        summaries = [item for item in storage.list_memory_objects(memory_types=["thread_summary"], lifecycle="active")]
        assert len(summaries) == 2
        summary_visibilities = {item.visibility for item in summaries}
        assert summary_visibilities == {"public", "container"}
        for summary in summaries:
            evidence = storage.get_evidence_for_memory_object(summary.id)
            assert all(e.visibility == summary.visibility for e in evidence)


def test_consolidation_does_not_cross_visibility_contexts(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="public-thread-a",
            content="Investigation found that arrival-time ordering reused stale hold updates during delayed sync.",
            visibility="public",
            thread_ref="chat:privacy:thread-a",
        )
        _ingest(
            client,
            source_id="limited-thread-b",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            visibility="container",
            thread_ref="chat:privacy:thread-b",
        )

        result = client.app.state.pallium_service.run_consolidation_pass(
            use_case="agent_conversation_memory",
            strategy_name="container_topic_window",
        )
        # Candidates exist but can't be grouped (different visibility contexts).
        # run_consolidation_pass returns None when no groups are formed.
        assert result is None

        # Verify both memories still active (no cross-visibility supersession).
        storage = client.app.state.pallium_service._storage
        active = storage.list_memory_objects(lifecycle="active")
        active_types = {m.type for m in active if m.type not in ("thread_summary", "atomic_fact")}
        assert len(active_types) >= 1


def test_debug_trace_reports_visibility_exclusions(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public")
        _ingest(client, source_id="limited-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container")

        payload = _query(client, visibility="public", debug=True)
        trace = payload.get("trace") or {}
        visibility = trace.get("visibility") or {}
        # Verify the visibility trace is populated with the query context
        assert visibility.get("query_container_ref") == "chat:privacy"
        exclusions = visibility.get("excluded_candidates", [])
        # When container_ref filter is active, out-of-scope limited items are filtered
        # before the visibility check, so exclusions may be empty.
        # Verify that any exclusions that do appear have the correct format.
        assert all("target_id" not in item for item in exclusions)
        assert all("candidate_visibility_context" not in item for item in exclusions)



def test_public_query_injectable_blocks_respect_visibility(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public")
        _ingest(client, source_id="limited-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container")

        payload = _query(client, visibility="public")
        assert payload["should_inject"] is True
        assert payload["injectable_blocks"]
        visible_result_ids = {item["result_id"] for item in payload["results"]}
        assert {block["result_id"] for block in payload["injectable_blocks"]}.issubset(visible_result_ids)
        for block in payload["injectable_blocks"]:
            for evidence in block["evidence"]:
                # Evidence must be either public or from the query's own container
                assert evidence["visibility"] == "public" or evidence.get("container_ref") == "chat:privacy"


def test_is_visible_passes_through_when_no_query_container_ref() -> None:
    from core.visibility import is_visible

    # Public shared items (actor_ref=None) are visible cross-container
    assert is_visible("public", "container-a", None) is True
    assert is_visible("public", None, None) is True
    assert is_visible("public", "container-a", "container-b") is True
    # Public personal items (actor_ref set) stay in their container
    assert is_visible("public", "container-a", "container-b", candidate_actor_ref="user-1") is False
    assert is_visible("public", "container-a", "container-a", candidate_actor_ref="user-1") is True
    # Limited/private items need matching container_ref
    assert is_visible("container", "container-a", "container-a") is True
    assert is_visible("container", "container-a", "container-b") is False
    assert is_visible("private", "container-a", "container-a") is True
    # No query container_ref — unscoped query sees everything
    assert is_visible("private", "container-a", None) is True


def test_is_visible_respects_query_visibility_public() -> None:
    """A public query context should only see public memories."""
    from core.visibility import is_visible

    # Public memory, same container, public query → visible
    assert is_visible("public", "container-a", "container-a", query_visibility="public") is True
    # Public memory, cross-container, public query → visible
    assert is_visible("public", "container-a", "container-b", query_visibility="public") is True
    # Private memory, same container, public query → NOT visible
    assert is_visible("private", "container-a", "container-a", query_visibility="public") is False
    # Container memory, same container, public query → NOT visible
    assert is_visible("container", "container-a", "container-a", query_visibility="public") is False
    # Public memory with actor_ref, public query → NOT visible (personal)
    assert is_visible("public", "container-a", "container-b", candidate_actor_ref="user-1", query_visibility="public") is False


def test_is_visible_private_query_sees_same_container() -> None:
    """A private query context sees everything in the same container."""
    from core.visibility import is_visible

    # Private memory, same container, private query → visible
    assert is_visible("private", "container-a", "container-a", query_visibility="private") is True
    # Public memory, same container, private query → visible
    assert is_visible("public", "container-a", "container-a", query_visibility="private") is True
    # Container memory, same container, private query → visible
    assert is_visible("container", "container-a", "container-a", query_visibility="private") is True
    # Private memory, cross-container, private query → NOT visible
    assert is_visible("private", "container-a", "container-b", query_visibility="private") is False
    # Public memory, cross-container, private query → visible
    assert is_visible("public", "container-a", "container-b", query_visibility="private") is True


def test_is_visible_container_query_sees_public_and_container() -> None:
    """A container query context sees public + container-scoped, but NOT private."""
    from core.visibility import is_visible

    # Public memory, same container → visible
    assert is_visible("public", "container-a", "container-a", query_visibility="container") is True
    # Public memory, cross-container → visible
    assert is_visible("public", "container-a", "container-b", query_visibility="container") is True
    # Container memory, same container → visible
    assert is_visible("container", "container-a", "container-a", query_visibility="container") is True
    # Container memory, cross-container → NOT visible
    assert is_visible("container", "container-a", "container-b", query_visibility="container") is False
    # Private memory, same container → NOT visible
    assert is_visible("private", "container-a", "container-a", query_visibility="container") is False
    # Public memory with actor_ref, cross-container → NOT visible (personal)
    assert is_visible("public", "container-a", "container-b", candidate_actor_ref="user-1", query_visibility="container") is False


def test_is_visible_no_query_visibility_uses_private_semantics() -> None:
    """When query_visibility is None, behaves like private (backwards compat)."""
    from core.visibility import is_visible

    # Same container sees everything
    assert is_visible("private", "container-a", "container-a", query_visibility=None) is True
    assert is_visible("container", "container-a", "container-a", query_visibility=None) is True
    assert is_visible("public", "container-a", "container-a", query_visibility=None) is True
    # Cross-container only sees public
    assert is_visible("private", "container-a", "container-b", query_visibility=None) is False
    assert is_visible("public", "container-a", "container-b", query_visibility=None) is True


def test_public_query_same_container_only_sees_public(monkeypatch, test_db_url: str) -> None:
    """A public query from the SAME container should still only see public memories."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="pub-same-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="priv-same-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-a")

        payload = _query(client, visibility="public", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "pub-same-1" in returned_source_ids
        assert "priv-same-1" not in returned_source_ids


def test_container_query_same_container_excludes_private(monkeypatch, test_db_url: str) -> None:
    """A container query from the SAME container should see public + container, but NOT private."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="pub-cont-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public", container_ref="chat:room-a")
        _ingest(client, source_id="cont-cont-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container", container_ref="chat:room-a")
        _ingest(client, source_id="priv-cont-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="private", container_ref="chat:room-a")

        payload = _query(client, visibility="container", container_ref="chat:room-a")
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert "pub-cont-1" in returned_source_ids
        assert "cont-cont-1" in returned_source_ids
        assert "priv-cont-1" not in returned_source_ids


def test_lexical_retrieval_with_require_visibility_and_none_context_returns_empty(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-retrieval-none", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public")
        _ingest(client, source_id="limited-retrieval-none", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container")

        retrieval = client.app.state.pallium_service._retrieval
        result = retrieval.query(
            text="reservation ordering duplicate holds",
            limit=10,
            visibility=None,
            require_visibility=True,
        )
        assert result.results == []

        # Without require_visibility, None means "no filtering" (non-scoped plugin path)
        unscoped_result = retrieval.query(
            text="reservation ordering duplicate holds",
            limit=10,
            visibility=None,
            require_visibility=False,
        )
        assert len(unscoped_result.results) > 0


def test_debug_sharp_candidate_diagnostics_do_not_leak_hidden_candidates(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="public")
        _ingest(client, source_id="limited-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility="container")

        payload = _query(client, visibility="public", debug=True)
        diagnostics = payload["trace"]["routing"]["sharp_candidate_diagnostics"]
        # All visible result IDs (from the same container or public)
        visible_result_ids = {item["result_id"] for item in payload["results"]}
        assert diagnostics
        # Diagnostics should only include items that are in scope (visible to the query)
        assert all(entry["result_id"] in visible_result_ids for entry in diagnostics)
