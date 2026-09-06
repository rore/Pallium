"""Source-only history search (vNext P1).

A source-only query ranks raw source turns on their own — memory objects never
occupy result slots (anti-starvation), the memory injection/abstention path is
bypassed, and the shared visibility / forgotten-gate / redaction / trace stack
still applies. These tests exercise the HTTP path with a routing-capable use
case (memory objects and source hits coexist) plus the storage-level SQL
push-down that provides the anti-starvation guarantee.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import EmbeddingProviderConfig
from app.main import create_app
from core.models import IndexEntry, MemoryObject, QueryResultItem
from core.query import QueryExecutor
from retrieval.base import RetrievalQueryResult
from providers.embedding.base import EmbeddingProvider
from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION
from storage.vector_index import VectorIndexConfig
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


def test_source_only_max_page_keeps_bounded_refill_headroom(
    monkeypatch, test_db_url: str
) -> None:
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(client, source_id="seed", content=_PLAIN)
        retrieval = client.app.state.pallium_service._query_executor._retrieval
        original_query = retrieval.query
        requested_limits: list[int] = []

        def recording_query(*args, **kwargs):
            requested_limits.append(kwargs["limit"])
            return original_query(*args, **kwargs)

        monkeypatch.setattr(retrieval, "query", recording_query)

        _query(client, source_only=True, limit=50)

    assert requested_limits == [200]

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
        drop = _ingest(client, source_id="drop", content=_PLAIN + " Follow-up differs.")

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
# ---------------------------------------------------------------------------
# F. HTTP vector-only starvation lifecycle
# ---------------------------------------------------------------------------


class _StubEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def dimensions(self) -> int:
        return 4

    def model_name(self) -> str:
        return "test-embedding"


class _ControlledVectorIndex:
    """Vector-index test double with caller-controlled similarity order."""

    model_name = "test-embedding"
    embedding_schema_version = EMBEDDING_SCHEMA_VERSION

    def __init__(self) -> None:
        self._hits: list[tuple[str, float]] = []
        self._ids: set[str] = set()

    def set_hits(self, hits: list[tuple[str, float]]) -> None:
        self._hits = hits
        self._ids.update(entry_id for entry_id, _similarity in hits)

    def add(self, entry_id: str, _vector: list[float]) -> None:
        self._ids.add(entry_id)

    def remove(self, entry_id: str) -> None:
        if entry_id not in self._ids:
            raise KeyError(entry_id)
        self._ids.remove(entry_id)
        self._hits = [hit for hit in self._hits if hit[0] != entry_id]

    def search(self, _query_vector: list[float], k: int) -> list[tuple[str, float]]:
        return self._hits[:k]

    def entry_count(self) -> int:
        return len(self._hits) if self._hits else len(self._ids)

    def known_entry_ids(self) -> frozenset[str]:
        return frozenset(self._ids)

    def save(self) -> None:
        pass


def _build_vector_client(monkeypatch, test_db_url: str) -> tuple[TestClient, _ControlledVectorIndex]:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    embedding = _StubEmbeddingProvider()
    vector_index = _ControlledVectorIndex()
    monkeypatch.setattr(
        "app.dependencies.build_embedding_provider",
        lambda config, *, provider_name: embedding,
    )
    monkeypatch.setattr(
        "app.dependencies._load_or_create_vector_index",
        lambda config, provider: vector_index,
    )
    config = replace(
        build_llm_test_config(
            default_use_case="agent_conversation_memory",
            sqlite_url=test_db_url,
        ),
        vector_index=VectorIndexConfig(
            enabled=True,
            index_path="unused-test.index",
            embedding_provider="test",
            min_similarity=0.3,
        ),
        embedding_providers={
            "test": EmbeddingProviderConfig(
                name="test",
                kind="onnx",
                model="test-embedding",
                dimensions=4,
            ),
        },
    )
    return TestClient(create_app(config)), vector_index


def test_vector_source_only_http_expands_then_forgets_unicode_source(
    monkeypatch,
    test_db_url: str,
    request: pytest.FixtureRequest,
) -> None:
    client = _build_vector_client(monkeypatch, test_db_url)[0]
    request.addfinalizer(client.close)
    vector_index = client.app.state.pallium_service._vector_index
    assert isinstance(vector_index, _ControlledVectorIndex)
    health = client.get("/health").json()
    assert health["embedding_provider_ok"] is True

    storage = client.app.state.pallium_service._storage
    derived_entry_ids: list[str] = []
    for index in range(97):  # source-only provider receives K=12: exceed 8*K.
        memory = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={"decision": f"derived clutter {index}"},
            visibility="private",
            container_ref=CONTAINER,
        )
        storage.create_memory_object(memory)
        entry = IndexEntry(
            target_kind="memory_object",
            target_id=memory.id,
            index_type="vector",
            text_view=f"derived clutter {index}",
            text_view_name="test.embedding",
            provider_name="test-embedding",
            provider_version="v1",
        )
        storage.create_index_entry(entry)
        derived_entry_ids.append(entry.id)

    other_source_id = _ingest(
        client,
        source_id="unicode-other-container",
        content="האחסון יתבסס על מסד אחר",
        container_ref="chat:other",
        thread_ref="chat:other:thread-1",
    )
    target_source_id = _ingest(
        client,
        source_id="unicode-target",
        content="האחסון יתבסס על PostgreSQL",
    )
    source_entry_ids: dict[str, str] = {}
    for source_id in (other_source_id, target_source_id):
        entry = IndexEntry(
            target_kind="source_item",
            target_id=source_id,
            index_type="vector",
            text_view="controlled source vector",
            text_view_name="test.embedding",
            provider_name="test-embedding",
            provider_version="v1",
        )
        storage.create_index_entry(entry)
        source_entry_ids[source_id] = entry.id
    vector_index.set_hits(
        [
            (entry_id, 0.99 - index * 0.001)
            for index, entry_id in enumerate(derived_entry_ids)
        ]
        + [
            (source_entry_ids[other_source_id], 0.80),
            (source_entry_ids[target_source_id], 0.79),
        ]
    )

    query_payload = {
        "text": "מהי טכנולוגיית הנתונים שסוכמה?",
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "visibility": "private",
        "limit": 1,
        "source_only": True,
    }
    response = client.post("/query", json=query_payload)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decision_reason"] == "source_only_search"
    assert payload["should_inject"] is False
    assert payload["injectable_blocks"] == []
    assert [row["source_item_id"] for row in payload["results"]] == [target_source_id]
    assert [row["raw_rank"] for row in payload["results"]] == [1]

    forgotten = client.post(
        "/source/forget",
        json={"source_item_id": target_source_id, "reason": "E2E lifecycle"},
    )
    assert forgotten.status_code == 200, forgotten.text
    after = client.post("/query", json=query_payload)
    assert after.status_code == 200, after.text
    assert after.json()["results"] == []


def test_source_only_exclusion_filters_identity_before_limit_and_refills() -> None:
    retrieval = MagicMock()
    retrieval.query.return_value = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind="source_hit",
                score=3,
                evidence=[],
                source_item_id="row-1",
                source_type="chat",
                source_id="same",
                source_content_fingerprint="a",
            ),
            QueryResultItem(
                result_kind="source_hit",
                score=2,
                evidence=[],
                source_item_id="row-2",
                source_type="chat",
                source_id="same",
                source_content_fingerprint="b",
            ),
            QueryResultItem(
                result_kind="source_hit",
                score=1,
                evidence=[],
                source_item_id="row-3",
                source_type="chat",
                source_id="different",
                source_content_fingerprint="c",
            ),
            QueryResultItem(
                result_kind="source_hit",
                score=0,
                evidence=[],
                source_item_id="row-4",
                source_type="chat",
                source_id="同じ-日本語",
                source_content_fingerprint="d",
            ),
        ]
    )
    plugin = MagicMock(requires_visibility_context=False)
    executor = QueryExecutor(MagicMock(), retrieval, {"test": plugin}, "test")

    result = executor.query(
        "x", 1, source_only=True, container_ref="test", visibility="private", exclude_source_identity=("chat", "same")
    )
    assert [item.source_item_id for item in result.results] == ["row-3"]

    unchanged = executor.query("x", 2, source_only=True, container_ref="test", visibility="private")
    assert [item.source_item_id for item in unchanged.results] == ["row-1", "row-2"]

    unicode_result = executor.query(
        "x",
        3,
        source_only=True,
        container_ref="test",
        visibility="private",
        exclude_source_identity=("chat", "同じ-日本語"),
    )
    assert "row-4" not in [item.source_item_id for item in unicode_result.results]
    assert "row-3" in [item.source_item_id for item in unicode_result.results]

    retrieval.query.return_value = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind="source_hit",
                score=200 - index,
                evidence=[],
                source_item_id=f"legacy-{index}",
                source_type="chat",
                source_id="same",
                source_content_fingerprint=f"legacy-{index}",
            )
            for index in range(150)
        ]
        + [
            QueryResultItem(
                result_kind="source_hit",
                score=50 - index,
                evidence=[],
                source_item_id=f"eligible-{index}",
                source_type="chat",
                source_id=f"eligible-{index}",
                source_content_fingerprint=f"eligible-{index}",
            )
            for index in range(50)
        ]
    )
    max_page = executor.query(
        "x", 50, source_only=True, container_ref="test", visibility="private", exclude_source_identity=("chat", "same")
    )
    assert [item.source_item_id for item in max_page.results] == [
        f"eligible-{index}" for index in range(50)
    ]

    retrieval.query.return_value = RetrievalQueryResult(results=[])
    assert (
        executor.query(
            "x", 50, source_only=True, container_ref="test", visibility="private", exclude_source_identity=("chat", "same")
        ).results
        == []
    )
