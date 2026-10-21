"""Optional mutation guards and requester visibility through the public HTTP seam."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text

from core.models import MemoryObject, Relation, SourceItem

SCOPE = {"container_ref": "git:scope", "actor_ref": "actor-a", "visibility": "private"}
PROVENANCE = {**SCOPE, "thread_ref": "thread-new", "agent_ref": "agent-a"}


@pytest.fixture
def client(tmp_path):
    from app.config import AppConfig
    from app.main import create_app
    from fastapi.testclient import TestClient
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    app = create_app(AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'scope.db'}",
        default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    return TestClient(app)


def remember(client, **overrides):
    response = client.post("/memory/remember", json={
        **PROVENANCE, "text": "Durable synthetic decision", "type": "decision", **overrides,
    })
    assert response.status_code == 200, response.text
    return response.json()["memory_object_id"]


def source(client, **overrides):
    from uuid import uuid4
    response = client.post("/items", json=[{
        **PROVENANCE, "source_type": "test", "source_id": str(uuid4()),
        "content_type": "text/plain", "content": "Synthetic source שלום 日本語",
        "artifact_kind": "note", **overrides,
    }])
    assert response.status_code == 200, response.text
    return response.json()[0]["source_item_id"]


def memories(client, **params):
    response = client.get("/dashboard/api/memories", params=params)
    assert response.status_code == 200, response.text
    return response.json()["memories"]


def mutate(client, operation, mid, **extra):
    if operation == "supersede":
        url, body = "/memory/supersede", {**PROVENANCE, "supersedes_id": mid, "new_text": "Replacement"}
    elif operation == "outcome":
        url, body = "/memory/record-outcome", {**PROVENANCE, "procedure_id": mid, "outcome": "success"}
    else:
        url = f"/memory/{mid}/{operation}"
        body = {
            "correct": {"corrected_text": "Corrected שלום", "reason": "synthetic correction"},
            "forget": {"reason": "synthetic forget"},
            "flag": {"reason": "synthetic flag", "source_ref": "source-a", "immediate": True},
            "feedback": {"rating": "relevant"},
        }[operation]
    return client.post(url, json={**body, **extra})


@pytest.mark.parametrize("operation", ["correct", "forget", "supersede", "flag", "feedback", "outcome"])
@pytest.mark.parametrize("foreign", [
    {"container_ref": "git:foreign"}, {"actor_ref": "actor-b"}, {"visibility": "container"},
])
def test_foreign_and_missing_mutations_are_indistinguishable_without_side_effects(client, operation, foreign):
    mid = remember(client)
    before = memories(client, include_soft_deleted=True)
    rejected = mutate(client, operation, mid, target_scope={**SCOPE, **foreign})
    missing = mutate(client, operation, "missing", target_scope=SCOPE)
    assert rejected.status_code == missing.status_code == 404
    assert rejected.json() == missing.json()
    assert memories(client, include_soft_deleted=True) == before
    assert client.get(f"/memory/{mid}/expand").json()["payload"]["statement"] == "Durable synthetic decision"
    for suffix in ("flags", "feedback"):
        assert client.get(f"/dashboard/api/memories/{mid}/{suffix}").json()["items"] == []


@pytest.mark.parametrize("operation", ["correct", "forget", "supersede", "flag", "feedback", "outcome"])
def test_matching_target_and_creation_provenance_are_independent(client, operation):
    mid = remember(client)
    response = mutate(client, operation, mid, target_scope=SCOPE)
    assert response.status_code == 200, response.text
    rows = memories(client, include_soft_deleted=True)
    row = next(row for row in rows if row["id"] == mid)
    assert row["origin_session_id"] == PROVENANCE["thread_ref"]
    if operation == "correct":
        assert client.get(f"/memory/{mid}/expand").json()["payload"]["statement"] == "Corrected שלום"
    elif operation == "forget":
        assert mid not in {row["id"] for row in memories(client)}
        assert mutate(client, operation, mid, target_scope=SCOPE).json()["forgotten"] is False
    elif operation == "flag":
        assert row["lifecycle"] == "suppressed"
        assert len(client.get(f"/dashboard/api/memories/{mid}/flags").json()["items"]) == 1
    elif operation == "feedback":
        assert len(client.get(f"/dashboard/api/memories/{mid}/feedback").json()["items"]) == 1
    else:
        assert len(rows) == 2


@pytest.mark.parametrize("scope", [
    {}, {"container_ref": "git:scope"}, {"actor_ref": "actor-a", "visibility": "private"},
    {**SCOPE, "container_ref": " "}, {**SCOPE, "container_ref": " git:scope"},
    {**SCOPE, "container_ref": "C:/synthetic"}, {**SCOPE, "actor_ref": " "},
    {**SCOPE, "actor_ref": " actor-a"}, {**SCOPE, "visibility": "invalid"},
    {**SCOPE, "actor_ref": None},
])
def test_invalid_or_partial_scope_rejected_at_boundary(client, scope):
    mid = remember(client)
    assert mutate(client, "forget", mid, target_scope=scope).status_code == 422
    assert len(memories(client)) == 1


@pytest.mark.parametrize("operation", ["correct", "forget", "supersede", "flag", "feedback", "outcome"])
@pytest.mark.parametrize("scope", [None, "omitted"])
def test_omitted_and_null_scope_preserve_legacy_mutations(client, operation, scope):
    mid = remember(client)
    extra = {} if scope == "omitted" else {"target_scope": None}
    assert mutate(client, operation, mid, **extra).status_code == 200
    if operation == "feedback":
        assert mutate(client, operation, "missing", **extra).status_code == 200


def test_canonical_target_and_creation_scope_stay_separate(client):
    mid = remember(client, container_ref="git:github.com/Example/Synthetic.git")
    response = mutate(client, "supersede", mid, target_scope={**SCOPE, "container_ref": "git:github.com/EXAMPLE/Synthetic/"})
    assert response.status_code == 200, response.text
    replacement = next(row for row in memories(client) if row["id"] == response.json()["new_memory_object_id"])
    assert replacement["container_ref"] == SCOPE["container_ref"]


@pytest.mark.parametrize("foreign", [{"container_ref": "git:foreign"}, {"actor_ref": "actor-b"}, {"visibility": "container"}])
def test_single_source_forget_is_scoped_and_idempotent(client, foreign):
    sid = source(client, thread_ref="old-thread")
    def forget(target, scope):
        return client.post("/source/forget", json={"source_item_id": target, "reason": "forget", "target_scope": scope})
    assert forget(sid, {**SCOPE, **foreign}).status_code == forget("missing", SCOPE).status_code == 404
    assert client.get(f"/source/{sid}/context", params={"container_ref": SCOPE["container_ref"]}).status_code == 200
    assert forget(sid, SCOPE).json()["forgotten"] is True
    assert forget(sid, SCOPE).json()["forgotten"] is False
    assert client.get(f"/source/{sid}/context").status_code == 404


@pytest.mark.parametrize("thread_ref", ["old-thread", None])
def test_bulk_source_forget_combines_exact_scope_and_optional_thread(client, thread_ref):
    old = source(client, thread_ref="old-thread")
    newer = source(client, thread_ref="new-thread")
    unrelated = [source(client, actor_ref="actor-b"), source(client, visibility="container"), source(client, container_ref="git:other")]
    body = {"container_ref": SCOPE["container_ref"], "reason": "synthetic bulk", "actor_ref": "audit-only", "target_scope": SCOPE}
    if thread_ref is not None:
        body["thread_ref"] = thread_ref
    response = client.post("/source/forget", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["count"] == (1 if thread_ref else 2)
    for sid in [old, newer, *unrelated]:
        expected = 404 if sid == old or (sid == newer and thread_ref is None) else 200
        assert client.get(f"/source/{sid}/context").status_code == expected
    assert client.post("/source/forget", json=body).json()["count"] == 0
    late = source(client, thread_ref="old-thread")
    assert client.get(f"/source/{late}/context").status_code == 200


def test_bulk_legacy_actor_remains_audit_only_and_invalid_target_is_rejected(client):
    source(client, actor_ref="actor-b")
    body = {"container_ref": SCOPE["container_ref"], "reason": "bulk", "actor_ref": "audit-only"}
    assert client.post("/source/forget", json={**body, "target_scope": {**SCOPE, "container_ref": "git:other"}}).status_code == 422
    assert client.post("/source/forget", json=body).json()["count"] == 1


def test_supersession_chain_and_concurrent_loser_leave_no_replacement_or_index(client, monkeypatch):
    first = remember(client)
    second = mutate(client, "supersede", first, target_scope=SCOPE).json()["new_memory_object_id"]
    service = client.app.state.pallium_service
    original = service._memory_target
    barrier = Barrier(2)
    def synchronized(mid, scope):
        result = original(mid, scope)
        if mid == second:
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(service, "_memory_target", synchronized)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: mutate(client, "supersede", second, target_scope=SCOPE), range(2)))
    monkeypatch.setattr(service, "_memory_target", original)
    assert sorted(result.status_code for result in results) == [200, 409]
    third = next(result.json()["new_memory_object_id"] for result in results if result.status_code == 200)
    assert mutate(client, "supersede", first, target_scope=SCOPE).status_code == 409
    assert mutate(client, "correct", second, target_scope=SCOPE).status_code == 409
    assert len(memories(client)) == 3
    assert {row["id"] for row in memories(client, lifecycle="active")} == {third}
    storage = service._storage
    with storage._engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM index_entries WHERE target_kind='memory_object'")).scalar() == 6
        assert connection.execute(text("SELECT count(*) FROM lexical_fts WHERE target_kind='memory_object'")).scalar() == 3
    assert mutate(client, "forget", first, target_scope=SCOPE).status_code == 200
    assert next(row for row in memories(client, include_soft_deleted=True) if row["id"] == first)["lifecycle"] == "superseded"
    # Tombstones are independent of lifecycle: existing explicit behavior permits this.
    assert mutate(client, "forget", third, target_scope=SCOPE).status_code == 200
    assert mutate(client, "supersede", third, target_scope=SCOPE).status_code == 200


def test_explicit_supersession_rolls_back_all_persistence_on_index_failure(client, monkeypatch):
    mid = remember(client)
    storage = client.app.state.pallium_service._storage
    original = storage._add_index_entry
    def fail(session, entry):
        original(session, entry)
        raise RuntimeError("synthetic index failure")
    monkeypatch.setattr(storage, "_add_index_entry", fail)
    with pytest.raises(RuntimeError, match="synthetic index failure"):
        mutate(client, "supersede", mid, target_scope=SCOPE)
    assert len(memories(client)) == 1
    assert memories(client)[0]["lifecycle"] == "active"
    with storage._engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM index_entries WHERE target_kind='memory_object'")).scalar() == 2
        assert connection.execute(text("SELECT count(*) FROM lexical_fts WHERE target_kind='memory_object'")).scalar() == 1


def test_explicit_supersession_preserves_best_effort_vector_indexing(client, monkeypatch):
    mid = remember(client)
    storage = client.app.state.pallium_service._storage
    original = storage._add_index_entry
    def fail_vector(session, entry):
        original(session, entry)
        if entry.index_type == "vector":
            session.flush()
            raise RuntimeError("synthetic vector failure")
    monkeypatch.setattr(storage, "_add_index_entry", fail_vector)
    response = mutate(client, "supersede", mid, target_scope=SCOPE)
    assert response.status_code == 200, response.text
    new = response.json()["new_memory_object_id"]
    assert {row["id"] for row in memories(client, lifecycle="active")} == {new}
    with storage._engine.connect() as connection:
        assert connection.execute(text("SELECT index_type FROM index_entries WHERE target_id=:mid"), {"mid": new}).scalars().all() == ["lexical"]
        assert connection.execute(text("SELECT count(*) FROM lexical_fts WHERE target_id=:mid"), {"mid": new}).scalar() == 1


def _assert_explicit_memory_is_lexically_retrievable(client, mid, statement):
    expanded = client.get(f"/memory/{mid}/expand")
    assert expanded.status_code == 200, expanded.text
    assert expanded.json()["payload"]["statement"] == statement
    before = memories(client)
    row = next(row for row in before if row["id"] == mid)
    assert row["lifecycle"] == "active"
    assert row["origin_session_id"] == PROVENANCE["thread_ref"]
    response = client.post("/query", json={
        **SCOPE, "text": "opal lantern", "limit": 20,
        "thread_ref": "later-session", "active_session_ref": "later-session",
    })
    assert response.status_code == 200, response.text
    hits = response.json()["results"]
    assert [hit["memory_object_id"] for hit in hits] == [mid]
    assert hits[0]["payload"]["statement"] == statement
    assert memories(client) == before


@pytest.mark.parametrize("operation", ["remember", "correct", "supersede"])
@pytest.mark.parametrize("failure", ["import", "build"])
def test_explicit_writes_keep_lexical_retrieval_when_vector_construction_fails(client, monkeypatch, operation, failure):
    import builtins
    import core.indexing as indexing

    previous = remember(client, text="Cobalt compass remains in cabinet") if operation != "remember" else None
    statement = "Opal lantern remains in archive שלום"
    faults = []
    with monkeypatch.context() as fault:
        if failure == "import":
            original = builtins.__import__

            def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
                if (name == "semantic.agent_conversation_memory_embedding"
                        and fromlist and "VECTOR_EMBEDDING_PROVIDER_NAME" in fromlist):
                    faults.append(name)
                    raise ImportError("synthetic vector provider import failure")
                return original(name, globals, locals, fromlist, level)

            fault.setattr(builtins, "__import__", fail_import)
        else:
            original = indexing.build_index_entry

            def fail_build(**kwargs):
                if kwargs["index_type"] == indexing.VECTOR_INDEX_TYPE:
                    faults.append(kwargs["target_id"])
                    raise RuntimeError("synthetic vector entry construction failure")
                return original(**kwargs)

            fault.setattr(indexing, "build_index_entry", fail_build)
        if operation == "remember":
            response = client.post("/memory/remember", json={**PROVENANCE, "type": "decision", "text": statement})
        elif operation == "correct":
            response = mutate(client, operation, previous, target_scope=SCOPE, corrected_text=statement)
        else:
            response = mutate(client, operation, previous, target_scope=SCOPE, new_text=statement)
    assert len(faults) == 1
    assert response.status_code == 200, response.text
    result = response.json()
    if operation == "supersede":
        mid = result["new_memory_object_id"]
        assert result["old_memory_object_id"] == previous and mid != previous
        assert result["superseded"] is True
        assert next(row for row in memories(client) if row["id"] == previous)["lifecycle"] == "superseded"
        assert {row["id"] for row in memories(client, lifecycle="active")} == {mid}
    else:
        mid = result["memory_object_id"]
        if operation == "correct":
            assert mid == previous and result["corrected"] is True
    if failure == "build":
        assert faults == [mid]
    _assert_explicit_memory_is_lexically_retrievable(client, mid, statement)
    if previous is not None:
        stale = client.post("/query", json={**SCOPE, "text": "cobalt compass", "limit": 20,
            "thread_ref": "later-session", "active_session_ref": "later-session"})
        assert stale.status_code == 200 and stale.json()["results"] == []


def test_remember_keeps_lexical_retrieval_when_vector_persistence_fails(client, monkeypatch):
    storage = client.app.state.pallium_service._storage
    original = storage.create_index_entry
    failed_ids = []

    def fail_vector(entry):
        if entry.index_type == "vector":
            failed_ids.append(entry.target_id)
            raise RuntimeError("synthetic vector persistence failure")
        return original(entry)

    monkeypatch.setattr(storage, "create_index_entry", fail_vector)
    statement = "Opal lantern remains in archive שלום"
    mid = remember(client, text=statement)
    assert failed_ids == [mid]
    _assert_explicit_memory_is_lexically_retrievable(client, mid, statement)


def test_remember_lexical_persistence_failure_still_propagates(client, monkeypatch):
    storage = client.app.state.pallium_service._storage
    attempted = []

    def fail_lexical(entry):
        attempted.append(entry.index_type)
        raise RuntimeError("synthetic lexical persistence failure")

    monkeypatch.setattr(storage, "create_index_entry", fail_lexical)
    statement = "Opal lantern remains in archive שלום"
    with pytest.raises(RuntimeError, match="synthetic lexical persistence failure"):
        remember(client, text=statement)
    assert attempted == ["lexical"]
    rows = memories(client)
    assert len(rows) == 1 and rows[0]["lifecycle"] == "active"
    assert client.get(f"/memory/{rows[0]['id']}/expand").json()["payload"]["statement"] == statement
    response = client.post("/query", json={**SCOPE, "text": "opal lantern", "limit": 20,
        "thread_ref": "later-session", "active_session_ref": "later-session"})
    assert response.status_code == 200 and response.json()["results"] == []


@pytest.mark.parametrize(("stored", "requester", "expected"), [
    ({}, {}, 200),
    ({}, {"query_actor_ref": "actor-b", "query_visibility": "private"}, 200),
    ({}, {"query_visibility": "container"}, 404),
    ({}, {"container_ref": "git:other", "query_actor_ref": "actor-a", "query_visibility": "private"}, 404),
    ({"visibility": "global"}, {"container_ref": "git:other", "query_actor_ref": "actor-a", "query_visibility": "private"}, 200),
    ({"visibility": "global"}, {"query_actor_ref": "actor-b", "query_visibility": "private"}, 404),
    ({"visibility": "global"}, {"query_visibility": "private"}, 404),
    ({"visibility": "container"}, {"query_actor_ref": "actor-b", "query_visibility": "container"}, 200),
])
def test_expand_anchor_uses_canonical_requester_visibility(client, stored, requester, expected):
    mid = remember(client, **stored)
    response = client.get(f"/memory/{mid}/expand", params={"container_ref": SCOPE["container_ref"], **requester})
    assert response.status_code == expected, response.text
    assert client.get(f"/memory/{mid}/expand", params={"query_visibility": "invalid"}).status_code == 422


def test_expand_checks_every_evidence_preserves_notes_forgetting_and_retrieval_not_use(client):
    mid = remember(client)
    fixtures = [
        ({"actor_ref": "actor-b"}, True),
        ({"container_ref": "git:other"}, False),
        ({"container_ref": "git:other", "visibility": "global"}, True),
        ({"visibility": "global", "actor_ref": "actor-b"}, False),
        ({"visibility": "public", "actor_ref": None, "container_ref": "git:other"}, True),
    ]
    storage = client.app.state.pallium_service._storage
    expected = set()
    for fields, visible in fixtures:
        sid = source(client, **fields)
        storage.create_relation(Relation(from_kind="memory_object", from_id=mid, relation_type="supported_by", to_kind="source_item", to_id=sid))
        if visible:
            expected.add(sid)
    forgotten = source(client)
    storage.create_relation(Relation(from_kind="memory_object", from_id=mid, relation_type="supported_by", to_kind="source_item", to_id=forgotten))
    assert client.post("/source/forget", json={"source_item_id": forgotten, "reason": "forget", "target_scope": SCOPE}).status_code == 200
    before = memories(client)
    before_object = storage.get_memory_object(mid)
    for _ in range(2):
        response = client.get(f"/memory/{mid}/expand", params={"container_ref": SCOPE["container_ref"], "query_actor_ref": "actor-a", "query_visibility": "private"})
        assert response.status_code == 200, response.text
        assert {item["source_item_id"] for item in response.json()["items"]} == expected
        assert all(item["content"] == "Synthetic source שלום 日本語" for item in response.json()["items"])
    assert memories(client) == before
    assert storage.get_memory_object(mid) == before_object


def test_expand_public_anchor_obeys_canonical_visibility(client):
    storage = client.app.state.pallium_service._storage
    memory = MemoryObject(type="decision", schema_id="test", schema_version="1", payload={"statement": "Shared decision"},
                          container_ref="git:other", actor_ref=None, visibility="public")
    storage.create_memory_object(memory)
    response = client.get(f"/memory/{memory.id}/expand", params={"container_ref": SCOPE["container_ref"], "query_visibility": "public"})
    assert response.status_code == 200, response.text
    assert response.json()["payload"]["statement"] == "Shared decision"


@pytest.mark.parametrize("artifact_kind", ["message", "note"])
def test_scoped_expansion_retains_redaction_and_verbatim_note_barriers(client, artifact_kind):
    storage = client.app.state.pallium_service._storage
    synthetic_secret = "sk-ant-api03-" + "Q" * 40
    memory = MemoryObject(type="decision", schema_id="test", schema_version="1", payload={"statement": synthetic_secret}, **SCOPE)
    item = SourceItem(source_type="test", source_id="synthetic", content_type="text/plain",
                      content=synthetic_secret, metadata={"token": synthetic_secret}, artifact_kind=artifact_kind, **SCOPE)
    storage.create_memory_object(memory)
    storage.create_source_item(item)
    storage.create_relation(Relation(from_kind="memory_object", from_id=memory.id, relation_type="supported_by", to_kind="source_item", to_id=item.id))
    persisted_item = storage.get_source_item(item.id)
    response = client.get(f"/memory/{memory.id}/expand", params={"container_ref": SCOPE["container_ref"], "query_actor_ref": SCOPE["actor_ref"], "query_visibility": "private"})
    assert response.status_code == 200, response.text
    assert synthetic_secret not in str(response.json()["payload"])
    content = response.json()["items"][0]["content"]
    assert (synthetic_secret in content) is (artifact_kind == "note")
    assert storage.get_source_item(item.id) == persisted_item
