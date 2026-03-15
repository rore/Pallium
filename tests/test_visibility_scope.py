from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


def _public() -> dict[str, object]:
    return {"kind": "public", "id": None}


def _limited(value: str) -> dict[str, object]:
    return {"kind": "limited", "id": value}


def _user(value: str) -> dict[str, object]:
    return {"kind": "user", "id": value}


def _build_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    return TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))


def _ingest(client: TestClient, *, source_id: str, content: str, visibility_context: dict[str, object] | None, container_ref: str = "chat:privacy", thread_ref: str = "chat:privacy:thread-1") -> dict[str, object]:
    response = client.post(
        "/items",
        json={
            "source_type": "assistant_artifact",
            "source_id": source_id,
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": container_ref,
            "thread_ref": thread_ref,
            "session_ref": f"session:{source_id}",
            "visibility_context": visibility_context,
        },
    )
    assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")
    return response.json()


def _query(client: TestClient, *, visibility_context: dict[str, object] | None, debug: bool = False, text: str = "what did we decide about reservation ordering?") -> dict[str, object]:
    response = client.post(
        "/query/debug" if debug else "/query",
        json={
            "text": text,
            "limit": 10,
            "container_ref": "chat:privacy",
            "visibility_context": visibility_context,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_public_query_only_sees_public_memory(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="limited-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-a"))
        _ingest(client, source_id="user-1", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_user("user-1"))

        payload = _query(client, visibility_context=_public())
        result_contexts = {
            ((item["visibility_context"] or {}).get("kind"), (item["visibility_context"] or {}).get("id"))
            for item in payload["results"]
        }
        assert result_contexts == {("public", None)}
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert returned_source_ids == {"public-1"}


def test_limited_query_sees_public_and_same_limited_only(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="limited-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-a"))
        _ingest(client, source_id="limited-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-b"))
        _ingest(client, source_id="user-2", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_user("user-2"))

        payload = _query(client, visibility_context=_limited("channel-a"))
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert returned_source_ids == {"public-2", "limited-a"}
        visible_contexts = {
            ((item["visibility_context"] or {}).get("kind"), (item["visibility_context"] or {}).get("id"))
            for item in payload["results"]
        }
        assert visible_contexts == {("public", None), ("limited", "channel-a")}


def test_user_query_sees_public_and_same_user_only(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-3", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="user-a", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_user("user-a"))
        _ingest(client, source_id="user-b", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_user("user-b"))
        _ingest(client, source_id="limited-c", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-c"))

        payload = _query(client, visibility_context=_user("user-a"))
        returned_source_ids = {item.get("source_id") for item in payload["results"] if item["result_kind"] == "source_hit"}
        assert returned_source_ids == {"public-3", "user-a"}
        visibility_ids = {(item["visibility_context"] or {}).get("id") for item in payload["results"]}
        assert "user-b" not in visibility_ids
        assert "channel-c" not in visibility_ids


def test_missing_query_visibility_fails_closed(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-4", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())

        payload = _query(client, visibility_context=None, debug=True)
        assert payload["results"] == []
        assert payload["trace"]["stages"] == []
        assert payload["trace"]["visibility"]["fail_closed_reason"] == "query_visibility_context_required"


def test_missing_ingest_visibility_does_not_promote_or_retrieve(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        create_payload = _ingest(
            client,
            source_id="missing-visibility",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            visibility_context=None,
        )
        assert create_payload["memory_object_ids"] == []
        assert create_payload["processing_status"] == "skipped"

        payload = _query(client, visibility_context=_public(), debug=True)
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
                "session_ref": "session:public-thread",
                "visibility_context": _public(),
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
                "session_ref": "session:limited-thread",
                "visibility_context": _limited("channel-thread"),
            },
        )
        client.app.state.pallium_service.drain_processing_queue(worker_id="visibility-test")

        storage = client.app.state.pallium_service._storage
        summaries = [item for item in storage.list_memory_objects(memory_types=["thread_summary"], lifecycle="active")]
        assert len(summaries) == 2
        summary_contexts = {(item.visibility_context.kind, item.visibility_context.id) for item in summaries if item.visibility_context is not None}
        assert summary_contexts == {("public", None), ("limited", "channel-thread")}
        for summary in summaries:
            evidence = storage.get_evidence_for_memory_object(summary.id)
            assert all(e.visibility_context == summary.visibility_context for e in evidence)


def test_consolidation_does_not_cross_visibility_contexts(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="public-thread-a",
            content="Investigation found that arrival-time ordering reused stale hold updates during delayed sync.",
            visibility_context=_public(),
            thread_ref="chat:privacy:thread-a",
        )
        _ingest(
            client,
            source_id="limited-thread-b",
            content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
            visibility_context=_limited("channel-merge"),
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
        _ingest(client, source_id="public-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="limited-5", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-trace"))

        payload = _query(client, visibility_context=_public(), debug=True)
        exclusions = payload["trace"]["visibility"]["excluded_candidates"]
        assert exclusions
        assert any(item["reason"] == "query_visibility_context_excludes_candidate" for item in exclusions)
        assert any(item["count"] >= 1 for item in exclusions)
        assert all("target_id" not in item for item in exclusions)
        assert all("candidate_visibility_context" not in item for item in exclusions)



def test_public_query_injectable_blocks_respect_visibility(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="limited-inject", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-inject"))

        payload = _query(client, visibility_context=_public())
        assert payload["should_inject"] is True
        assert payload["injectable_blocks"]
        visible_result_ids = {item["result_id"] for item in payload["results"]}
        assert {block["result_id"] for block in payload["injectable_blocks"]}.issubset(visible_result_ids)
        for block in payload["injectable_blocks"]:
            for evidence in block["evidence"]:
                assert evidence["visibility_context"] == _public()


def test_debug_sharp_candidate_diagnostics_do_not_leak_hidden_candidates(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="public-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_public())
        _ingest(client, source_id="limited-sharp", content="Decision: use item event time for reservation ordering to avoid duplicate holds.", visibility_context=_limited("channel-sharp"))

        payload = _query(client, visibility_context=_public(), debug=True)
        diagnostics = payload["trace"]["routing"]["sharp_candidate_diagnostics"]
        public_result_ids = {item["result_id"] for item in payload["results"] if (item["visibility_context"] or {}).get("kind") == "public"}
        assert diagnostics
        assert all(entry["result_id"] in public_result_ids for entry in diagnostics)
