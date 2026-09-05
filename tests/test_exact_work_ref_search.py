from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from sqlalchemy import event, text as sa_text

from core.models import QueryFilters
from core.work_ref import work_refs_from_metadata
from retrieval.vector import VectorRetrievalProvider


def _add(
    client,
    source_id: str,
    refs: str | list[str],
    *,
    content: str = "alpha detail",
    occurred_at: datetime | None = None,
    container: str = "room",
    actor_ref: str | None = None,
) -> str:
    payload = {
        "source_type": "chat",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": container,
        "thread_ref": "thread",
        "visibility": "private",
        "metadata": {
            "pallium_work_refs": [refs] if isinstance(refs, str) else refs,
        },
    }
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.isoformat()
    if actor_ref is not None:
        payload["actor_ref"] = actor_ref
    response = client.post("/items", json=[payload])
    assert response.status_code == 200, response.text
    return response.json()[0]["source_item_id"]


def _exact(
    client,
    query: str,
    ref: str = "proj-1",
    limit: int = 3,
    *,
    container: str = "room",
    actor_ref: str | None = None,
) -> list[dict]:
    payload = {
        "text": query,
        "limit": limit,
        "source_only": True,
        "trigger_origin": "agent_pull_work",
        "work_refs": [ref],
        "container_ref": container,
        "thread_ref": "thread",
        "visibility": "private",
    }
    if actor_ref is not None:
        payload["actor_ref"] = actor_ref
    response = client.post("/query", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _session(client):
    return client.app.state.pallium_service._storage._session_factory()


def test_blank_exact_ref_is_recent_normalized_and_similar_ref_is_excluded(
    client, drain_queue
) -> None:
    now = datetime.now(timezone.utc)
    older = _add(client, "older", "proj-1", occurred_at=now - timedelta(days=1))
    newest = _add(client, "newest", ["proj-1", "other-2"], occurred_at=now)
    _add(client, "similar", "proj-10", occurred_at=now + timedelta(days=1))
    drain_queue(client)

    rows = _exact(client, " ", ref="PROJ 1")
    assert [row["source_item_id"] for row in rows] == [newest, older]
    assert rows[0]["work_refs"] == ["proj-1", "other-2"]


def test_exact_ref_matches_legacy_case_and_separator_variants(client, drain_queue) -> None:
    source_ids = [_add(client, f"legacy-{i}", "proj-1") for i in range(3)]
    drain_queue(client)
    with _session(client) as session:
        for source_id, value in zip(source_ids, ("PROJ 1", "proj_1", "PROJ---1")):
            session.execute(
                sa_text("UPDATE source_items SET metadata_json = :metadata WHERE id = :id"),
                {"id": source_id, "metadata": json.dumps({"pallium_work_refs": [value]})},
            )
        session.commit()

    rows = _exact(client, "", ref="proj-1", limit=3)
    assert {row["source_item_id"] for row in rows} == set(source_ids)
    assert all(row["work_refs"] == ["proj-1"] for row in rows)

def test_blank_exact_ref_uses_created_at_then_stable_id(client, drain_queue) -> None:
    oldest = _add(client, "oldest", "proj-1")
    tied_a = _add(client, "tied-a", "proj-1")
    tied_b = _add(client, "tied-b", "proj-1")
    drain_queue(client)

    with _session(client) as session:
        session.execute(
            sa_text(
                "UPDATE source_items SET occurred_at = NULL, created_at = :created "
                "WHERE id = :id"
            ),
            {"created": "2026-01-01T00:00:00+00:00", "id": oldest},
        )
        for source_id in (tied_a, tied_b):
            session.execute(
                sa_text(
                    "UPDATE source_items SET occurred_at = NULL, created_at = :created "
                    "WHERE id = :id"
                ),
                {"created": "2026-01-02T00:00:00+00:00", "id": source_id},
            )
        session.commit()

    assert [row["source_item_id"] for row in _exact(client, "")] == [
        *sorted((tied_a, tied_b), reverse=True),
        oldest,
    ]


def test_punctuation_is_not_structural_but_unicode_query_is_searchable(
    client, drain_queue
) -> None:
    source_id = _add(client, "unicode", "proj-1", content="résumé 任务 alpha")
    drain_queue(client)

    assert _exact(client, "!!!") == []
    assert [row["source_item_id"] for row in _exact(client, "任务")] == [source_id]


def test_exact_ref_refills_past_deterministic_forgotten_first_page(
    client, drain_queue
) -> None:
    all_ids = [_add(client, f"item-{i}", "proj-1") for i in range(20)]
    drain_queue(client)
    with _session(client) as session:
        first_page = [
            row.target_id
            for row in session.execute(
                sa_text(
                    "SELECT target_id FROM lexical_fts "
                    "WHERE lexical_fts MATCH :query AND target_kind = 'source_item' "
                    "ORDER BY bm25(lexical_fts), index_entry_id LIMIT 12"
                ),
                {"query": "\"alpha\""},
            ).fetchall()
            if row.target_id in all_ids
        ]
    assert len(first_page) == 12
    for source_id in first_page:
        response = client.post(
            "/source/forget",
            json={"source_item_id": source_id, "reason": "test"},
        )
        assert response.status_code == 200, response.text

    exact_statements: list[str] = []
    engine = client.app.state.pallium_service._storage._engine

    def capture_exact_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany,
    ) -> None:
        if "pallium_normalize_work_ref" in statement:
            exact_statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_exact_statement)
    try:
        returned = [
            row["source_item_id"] for row in _exact(client, "alpha", limit=3)
        ]
    finally:
        event.remove(engine, "before_cursor_execute", capture_exact_statement)

    assert len(exact_statements) == 1
    assert len(returned) == len(set(returned)) == 3
    assert set(returned).isdisjoint(first_page)


def test_exact_ref_expands_past_post_retrieval_duplicate_window(
    client, drain_queue
) -> None:
    now = datetime.now(timezone.utc)
    duplicate_ids = [
        _add(
            client,
            f"duplicate-{i}",
            "proj-1",
            content="same repeated content across sessions",
            occurred_at=now - timedelta(minutes=i),
        )
        for i in range(12)
    ]
    unique_ids = [
        _add(
            client,
            f"unique-{i}",
            "proj-1",
            content=f"unique content {i}",
            occurred_at=now - timedelta(days=i + 1),
        )
        for i in range(2)
    ]
    drain_queue(client)

    returned = [row["source_item_id"] for row in _exact(client, "", limit=3)]

    assert len(returned) == 3
    assert set(unique_ids) <= set(returned)
    assert len(set(returned).intersection(duplicate_ids)) == 1

def test_exact_ref_combines_actor_container_and_legacy_safety(
    client, drain_queue
) -> None:
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    keep = _add(client, "keep", "proj-1", actor_ref="actor-a")
    malformed_scalar = _add(client, "malformed-scalar", "proj-1", actor_ref="actor-a")
    malformed_object = _add(client, "malformed-object", "proj-1", actor_ref="actor-a")
    _add(client, "other-actor", "proj-1", actor_ref="actor-b")
    _add(client, "other-container", "proj-1", container="other")
    drain_queue(client)

    with _session(client) as session:
        legacy_metadata = {
            keep: {
                "pallium_work_refs": [
                    "proj-1", secret, "[REDACTED_TOKEN]", 42, None, True
                ]
            },
            malformed_scalar: {"pallium_work_refs": 42},
            malformed_object: {"pallium_work_refs": {"nested": "proj-1"}},
        }
        for source_id, metadata in legacy_metadata.items():
            session.execute(
                sa_text(
                    "UPDATE source_items SET metadata_json = :metadata WHERE id = :id"
                ),
                {"id": source_id, "metadata": json.dumps(metadata)},
            )
        session.commit()

    rows = _exact(client, "", actor_ref="actor-a")
    assert [row["source_item_id"] for row in rows] == [keep]
    assert rows[0]["work_refs"] == ["proj-1"]
    assert secret not in json.dumps(rows)
    assert [row["source_item_id"] for row in _exact(client, "alpha", actor_ref="actor-a")] == [keep]


def test_unknown_exact_is_empty_and_broad_compatibility_filter_still_works(
    client, drain_queue
) -> None:
    ref_id = _add(client, "ref", "proj-1", content="alpha detail")
    plain_id = _add(client, "plain", "other-2", content="alpha detail")
    drain_queue(client)

    assert _exact(client, "", "missing-9") == []
    broad = client.post(
        "/query",
        json={
            "text": "alpha",
            "limit": 5,
            "source_only": True,
            "container_ref": "room",
            "thread_ref": "thread",
            "visibility": "private",
        },
    )
    assert broad.status_code == 200, broad.text
    assert {row["source_item_id"] for row in broad.json()["results"]} >= {
        ref_id,
        plain_id,
    }

    compatible = client.post(
        "/query",
        json={
            "text": "alpha",
            "limit": 5,
            "source_only": True,
            "work_refs": ["PROJ 1"],
            "container_ref": "room",
            "thread_ref": "thread",
            "visibility": "private",
        },
    )
    assert compatible.status_code == 200, compatible.text
    assert [row["source_item_id"] for row in compatible.json()["results"]] == [
        ref_id
    ]


def test_legacy_projection_filters_each_unsafe_or_malformed_value() -> None:
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    assert work_refs_from_metadata("not-a-dict") == ()
    assert work_refs_from_metadata({"pallium_work_refs": "proj-1"}) == ()
    assert work_refs_from_metadata(
        {"pallium_work_refs": ["PROJ 1", secret, "[REDACTED_TOKEN]", 42]}
    ) == ("proj-1",)


def test_blank_exact_ref_never_embeds_vector_query() -> None:
    embedding = MagicMock()
    provider = VectorRetrievalProvider(
        MagicMock(),
        embedding,
        index_holder=MagicMock(index=MagicMock()),
    )
    result = provider.query(
        "   ",
        1,
        QueryFilters(work_refs=("proj-1",)),
        target_kind="source_item",
    )
    assert result.results == []
    embedding.embed.assert_not_called()
def test_exact_http_records_origin_and_expands_with_parent_lookup(
    client, drain_queue
) -> None:
    source_id = _add(client, "lifecycle", "proj-1", content="alpha lifecycle")
    drain_queue(client)
    search = client.post(
        "/query",
        json={
            "text": "alpha",
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": ["proj-1"],
            "container_ref": "room",
            "thread_ref": "active-session",
            "visibility": "private",
        },
    )
    assert search.status_code == 200, search.text
    lookup_id = search.json()["lookup_event_id"]
    assert lookup_id

    expansion = client.get(
        f"/source/{source_id}/context",
        params={
            "container_ref": "room",
            "query_visibility": "private",
            "active_session_ref": "active-session",
            "parent_lookup_id": lookup_id,
        },
    )
    assert expansion.status_code == 200, expansion.text
    assert expansion.json()["parent_lookup_id"] == lookup_id

    with _session(client) as session:
        row = session.execute(
            sa_text(
                "SELECT trigger_origin, parent_lookup_id "
                "FROM historical_lookup_reuse_event "
                "WHERE id = :id OR parent_lookup_id = :id "
                "ORDER BY created_at"
            ),
            {"id": lookup_id},
        ).fetchall()
    assert row[0].trigger_origin == "agent_pull_work"
    assert any(item.parent_lookup_id == lookup_id for item in row)


@pytest.mark.parametrize(
    ("work_refs", "text", "source_only"),
    [
        (None, "", True),
        (["---"], "", True),
        (["ok", "extra"], "", True),
        (["x" * 129], "topic", True),
        (["ok"], "", False),
    ],
)
def test_exact_http_rejects_invalid_shape_without_echo(
    client,
    work_refs: list[str] | None,
    text: str,
    source_only: bool,
) -> None:
    response = client.post(
        "/query",
        json={
            "text": text,
            "source_only": source_only,
            "trigger_origin": "agent_pull_work",
            "work_refs": work_refs,
            "container_ref": "room",
            "visibility": "private",
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "exact work search requires one valid work_ref"
    }


def test_exact_http_rejects_unsafe_ref_without_echo(client) -> None:
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    response = client.post(
        "/query",
        json={
            "text": "",
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": [secret],
            "container_ref": "room",
            "visibility": "private",
        },
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json() == {
        "detail": "exact work search requires one valid work_ref"
    }
@pytest.mark.parametrize(
    "work_refs",
    [
        {"credential": "secret-bearing-wrong-type"},
        [{"value": "secret-bearing-wrong-type"}],
        ["ghp_" + "secret-bearing-wrong-type", {"nested": "secret"}],
    ],
)
def test_exact_http_rejects_secret_bearing_wrong_types_without_echo(
    client, work_refs
) -> None:
    response = client.post(
        "/query",
        json={
            "text": "",
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": work_refs,
            "container_ref": "room",
            "visibility": "private",
        },
    )
    assert response.status_code == 422
    assert "secret-bearing-wrong-type" not in response.text
    assert "nested" not in response.text

def test_exact_http_maximum_and_over_maximum_result_journey(
    client, drain_queue
) -> None:
    for i in range(55):
        _add(
            client,
            f"boundary-{i}",
            "proj-1",
            content=f"unique boundary content {i}",
        )
    drain_queue(client)

    rows = _exact(client, "", limit=50)
    assert len(rows) == len({row["source_item_id"] for row in rows}) == 50

    response = client.post(
        "/query",
        json={
            "text": "",
            "limit": 51,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": ["proj-1"],
            "container_ref": "room",
            "visibility": "private",
        },
    )
    assert response.status_code == 422


def test_exact_work_ref_search_through_enabled_vector_http(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("usearch")
    from app.config import AppConfig
    from app.main import create_app
    from core.models import IndexEntry, SourceItem
    from fastapi.testclient import TestClient
    from providers.embedding.base import EmbeddingProvider
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    class FixedEmbedding(EmbeddingProvider):
        def embed(self, texts, *, mode="passage"):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        def dimensions(self) -> int:
            return 4

        def model_name(self) -> str:
            return "exact-work-e2e"

    monkeypatch.setattr(
        "app.dependencies.build_embedding_provider",
        lambda _config, *, provider_name: FixedEmbedding(),
    )
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{tmp_path / 'vector.db'}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(tmp_path / "vector.index"),
                embedding_provider="onnx",
                min_similarity=0.0,
            ),
        )
    )
    service = app.state.pallium_service
    assert service._vector_index is not None

    right_ids = []
    for i in range(22):
        is_right = i >= 20
        source = SourceItem(
            source_type="chat",
            source_id=f"vector-{i}",
            content_type="text/plain",
            content=f"vector-only content {i}",
            artifact_kind="message",
            role="user",
            container_ref="room",
            thread_ref="thread",
            visibility="private",
            metadata={
                "pallium_work_refs": ["PROJ 1" if is_right else "other-2"]
            },
        )
        service._storage.create_source_item(source)
        entry = IndexEntry(
            target_kind="source_item",
            target_id=source.id,
            index_type="vector",
            text_view=source.content,
            provider_name="exact-work-e2e",
        )
        service._storage.create_index_entry(entry)
        service._vector_index.add(
            entry.id,
            [0.8, 0.2, 0.0, 0.0] if is_right else [1.0, 0.0, 0.0, 0.0],
        )
        if is_right:
            right_ids.append(source.id)

    response = TestClient(app).post(
        "/query",
        json={
            "text": "semantic-only-query",
            "limit": 2,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": ["proj-1"],
            "container_ref": "room",
            "thread_ref": "thread",
            "visibility": "private",
        },
    )
    assert response.status_code == 200, response.text
    returned = [row["source_item_id"] for row in response.json()["results"]]
    assert len(returned) == 2
    assert set(returned) == set(right_ids)

