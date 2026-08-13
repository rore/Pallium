"""Source-only history search (vNext P1).

A source-only query ranks raw source turns on their own — memory objects never
occupy result slots (anti-starvation), the memory injection/abstention path is
bypassed, and the shared visibility / forgotten-gate / redaction / trace stack
still applies. These tests exercise the HTTP path with a routing-capable use
case (memory objects and source hits coexist) plus the storage-level SQL
push-down that provides the anti-starvation guarantee.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider

CONTAINER = "chat:hist"
THREAD = "chat:hist:thread-1"
# Shared vocabulary so every seeded turn matches the query lexically.
_DECISION = "Decision: use item event time for reservation ordering to avoid duplicate holds."
_PLAIN = "We discussed reservation ordering and duplicate holds at length in this thread."


def _build_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    return TestClient(create_app(build_llm_test_config(
        default_use_case="agent_conversation_memory", sqlite_url=test_db_url,
    )))


def _ingest(client: TestClient, *, source_id: str, content: str,
            container_ref: str = CONTAINER, thread_ref: str = THREAD,
            visibility: str = "private") -> str:
    is_decision = content.startswith("Decision:")
    resp = client.post("/items", json=[{
        "source_type": "chat_message" if is_decision else "assistant_artifact",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message" if is_decision else "assistant_output",
        "role": "user" if is_decision else "assistant",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
    }])
    assert resp.status_code == 200, resp.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="src-only-test")
    return resp.json()[0]["source_item_id"]


def _query(client: TestClient, *, source_only: bool, limit: int = 5,
           container_ref: str = CONTAINER, visibility: str = "private",
           debug: bool = False) -> dict:
    resp = client.post(
        "/query/debug" if debug else "/query",
        json={
            "text": "reservation ordering duplicate holds",
            "container_ref": container_ref,
            "thread_ref": THREAD,
            "visibility": visibility,
            "limit": limit,
            "source_only": source_only,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# A. Anti-starvation + shape (Done-When #1)
# ---------------------------------------------------------------------------

def test_source_only_returns_only_source_hits_not_starved(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        # 8 decisions → 8 memory objects (+ 8 source turns); 3 plain source turns.
        for i in range(8):
            _ingest(client, source_id=f"dec-{i}", content=_DECISION)
        for i in range(3):
            _ingest(client, source_id=f"plain-{i}", content=_PLAIN)

        payload = _query(client, source_only=True, limit=5)

        assert payload["decision_reason"] == "source_only_search"
        assert payload["should_inject"] is False
        assert payload["injectable_blocks"] == []
        results = payload["results"]
        assert results, "source-only search returned nothing"
        # Every slot is a source hit — memory objects never occupy source slots,
        # even though 8 memory objects match the same query.
        assert all(r["result_kind"] == "source_hit" for r in results)
        # raw_rank is contiguous 1..N by fused order.
        assert [r["raw_rank"] for r in results] == list(range(1, len(results) + 1))


def test_source_only_does_not_change_default_query(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        for i in range(3):
            _ingest(client, source_id=f"dec-{i}", content=_DECISION)

        default = _query(client, source_only=False, limit=5)
        # The default proactive path is untouched: it does not take the
        # source-only decision reason and retains its normal response shape.
        assert default["decision_reason"] != "source_only_search"
        assert isinstance(default["should_inject"], bool)
        assert isinstance(default["injectable_blocks"], list)
        # And default-mode result items carry no raw_rank.
        assert all(r.get("raw_rank") is None for r in default["results"])


# ---------------------------------------------------------------------------
# B. Visibility fail-closed (Done-When #4)
# ---------------------------------------------------------------------------

def test_source_only_visibility_fail_closed(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="priv-a", content=_PLAIN,
                container_ref="chat:room-a", thread_ref="chat:room-a:thread-1")
        # Query a DIFFERENT container: the private turn must not surface.
        resp = client.post("/query", json={
            "text": "reservation ordering duplicate holds",
            "container_ref": "chat:room-b",
            "thread_ref": "chat:room-b:thread-1",
            "visibility": "private",
            "limit": 5,
            "source_only": True,
        })
        assert resp.status_code == 200, resp.text
        returned = {r.get("source_id") for r in resp.json()["results"]}
        assert "priv-a" not in returned

        # Missing visibility context fails closed (empty), not open.
        resp2 = client.post("/query", json={
            "text": "reservation ordering duplicate holds",
            "limit": 5,
            "source_only": True,
        })
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["results"] == []


# ---------------------------------------------------------------------------
# C. Forgotten-source gate carries into source-only (P0 x P1)
# ---------------------------------------------------------------------------

def test_source_only_excludes_forgotten_turn(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        keep = _ingest(client, source_id="keep", content=_PLAIN)
        drop = _ingest(client, source_id="drop", content=_PLAIN)

        before = {r["source_item_id"] for r in _query(client, source_only=True)["results"]}
        assert {keep, drop} <= before

        resp = client.post("/source/forget", json={"source_item_id": drop, "reason": "user request"})
        assert resp.status_code == 200, resp.text

        after = {r["source_item_id"] for r in _query(client, source_only=True)["results"]}
        assert keep in after
        assert drop not in after


# ---------------------------------------------------------------------------
# D. Redaction on the raw path (governance-mandated)
# ---------------------------------------------------------------------------

def test_source_only_redacts_secrets_in_excerpt(monkeypatch, test_db_url: str) -> None:
    # Build a fake secret-looking token from fragments so scanners (Ruff S105 /
    # leak detectors) don't flag a literal; it still matches the secret redactor.
    test_token = "sk-" + "ABCD1234efgh5678" + "IJKL9012mnop3456" + "qrst7890"
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="secret-turn",
                content=f"reservation ordering duplicate holds token {test_token} end")

        results = _query(client, source_only=True)["results"]
        assert results, "expected the source turn back"
        for r in results:
            assert test_token not in (r.get("excerpt") or "")


# ---------------------------------------------------------------------------
# E. Trace explains the source-only ranking (Done-When #3)
# ---------------------------------------------------------------------------

def test_source_only_trace_has_mode_marker(monkeypatch, test_db_url: str) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="t-1", content=_PLAIN)

        payload = _query(client, source_only=True, debug=True)
        trace = payload["trace"]
        assert trace["routing"] == {"mode": "source_only"}
        assert trace["result_summary"] is not None
