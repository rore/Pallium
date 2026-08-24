"""End-to-end contract tests for agent-explicit creation provenance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


_PROVENANCE = {
    "container_ref": "git:github.com/example/project",
    "actor_ref": "local-user",
    "thread_ref": "session-123",
    "agent_ref": "codex",
    "visibility": "private",
}


@pytest.fixture
def client(tmp_path) -> TestClient:
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{tmp_path / 'explicit-provenance.db'}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        )
    )
    return TestClient(app)


def _counts(client: TestClient) -> tuple[int, int]:
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        memories = connection.execute(text("SELECT COUNT(*) FROM memory_objects")).scalar_one()
        indexes = connection.execute(text("SELECT COUNT(*) FROM index_entries")).scalar_one()
    return memories, indexes


def _remember_body(**overrides) -> dict:
    body = {**_PROVENANCE, "text": "durable fact", "type": "decision"}
    body.update(overrides)
    return body


def _remember(client: TestClient, **overrides) -> str:
    response = client.post("/memory/remember", json=_remember_body(**overrides))
    assert response.status_code == 200, response.text
    return response.json()["memory_object_id"]


@pytest.mark.parametrize(
    "field",
    ["container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility"],
)
def test_remember_missing_or_blank_provenance_writes_nothing(client: TestClient, field: str) -> None:
    for value in (None, ""):
        body = _remember_body()
        if value is None:
            body.pop(field)
        else:
            body[field] = value
        before = _counts(client)
        response = client.post("/memory/remember", json=body)
        assert response.status_code == 422, response.text
        assert _counts(client) == before


def test_deprecated_origin_aliases_populate_canonical_provenance(client: TestClient) -> None:
    body = _remember_body()
    body["origin_session_id"] = body.pop("thread_ref")
    body["origin_agent_id"] = body.pop("agent_ref")
    response = client.post("/memory/remember", json=body)
    assert response.status_code == 200, response.text

    memory_id = response.json()["memory_object_id"]
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT actor_ref, visibility, origin_session_id, origin_agent_id "
                "FROM memory_objects WHERE id=:id"
            ),
            {"id": memory_id},
        ).one()
    assert tuple(row) == ("local-user", "private", "session-123", "codex")


@pytest.mark.parametrize(
    ("canonical", "alias", "bad_value"),
    [
        ("thread_ref", "origin_session_id", "different-session"),
        ("agent_ref", "origin_agent_id", "different-agent"),
    ],
)
def test_mismatched_deprecated_alias_rejected_without_write(
    client: TestClient, canonical: str, alias: str, bad_value: str
) -> None:
    body = _remember_body()
    body[alias] = bad_value
    before = _counts(client)
    response = client.post("/memory/remember", json=body)
    assert response.status_code == 422, (canonical, response.text)
    assert _counts(client) == before


@pytest.mark.parametrize(
    "container_ref",
    [r"C:\work\repo", "C:/work/repo", "/work/repo", "//server/share", r"\\server\share", " C:/work/repo"],
)
def test_raw_absolute_container_paths_rejected_without_write(
    client: TestClient, container_ref: str
) -> None:
    before = _counts(client)
    response = client.post(
        "/memory/remember", json=_remember_body(container_ref=container_ref)
    )
    assert response.status_code == 400, response.text
    assert _counts(client) == before


@pytest.mark.parametrize(
    ("container_ref", "expected"),
    [
        ("GIT:GITHUB.COM/Owner/Repo.GIT/", "git:github.com/owner/repo"),
        ("repo:abcdef123456", "repo:abcdef123456"),
        ("path:project:123abc", "path:project:123abc"),
        ("chat:ערוץ:צוות", "chat:ערוץ:צוות"),
    ],
)
def test_valid_opaque_container_refs_preserve_canonical_contract(
    client: TestClient, container_ref: str, expected: str
) -> None:
    memory_id = _remember(client, container_ref=container_ref)
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        stored = connection.execute(
            text("SELECT container_ref FROM memory_objects WHERE id=:id"), {"id": memory_id}
        ).scalar_one()
    assert stored == expected


@pytest.mark.parametrize("visibility", ["private", "container", "global"])
def test_actor_attributed_creation_allows_supported_visibility(
    client: TestClient, visibility: str
) -> None:
    memory_id = _remember(client, visibility=visibility)
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        stored = connection.execute(
            text("SELECT visibility FROM memory_objects WHERE id=:id"), {"id": memory_id}
        ).scalar_one()
    assert stored == visibility


def test_actor_attributed_creation_rejects_public_visibility(client: TestClient) -> None:
    before = _counts(client)
    response = client.post(
        "/memory/remember", json=_remember_body(visibility="public")
    )
    assert response.status_code == 422, response.text
    assert _counts(client) == before


@pytest.mark.parametrize("operation", ["supersede", "record-outcome"])
@pytest.mark.parametrize(
    "field",
    ["container_ref", "actor_ref", "thread_ref", "agent_ref", "visibility"],
)
def test_other_creation_operations_require_provenance_before_write(
    client: TestClient, operation: str, field: str
) -> None:
    anchor_id = _remember(
        client, type="operational_fact" if operation == "record-outcome" else "decision"
    )
    body = dict(_PROVENANCE)
    if operation == "supersede":
        body.update(new_text="replacement", supersedes_id=anchor_id)
        endpoint = "/memory/supersede"
    else:
        body.update(procedure_id=anchor_id, outcome="success")
        endpoint = "/memory/record-outcome"
    body.pop(field)

    before = _counts(client)
    response = client.post(endpoint, json=body)
    assert response.status_code == 422, response.text
    assert _counts(client) == before
    if operation == "supersede":
        storage = client.app.state.pallium_service._storage
        assert storage.get_memory_object(anchor_id).lifecycle == "active"


def test_service_boundary_rejects_missing_provenance_before_write(client: TestClient) -> None:
    service = client.app.state.pallium_service
    before = _counts(client)
    with pytest.raises(ValueError, match="actor_ref"):
        service.remember_memory(
            text="direct call",
            type="decision",
            container_ref=_PROVENANCE["container_ref"],
            actor_ref=None,
            thread_ref=_PROVENANCE["thread_ref"],
            agent_ref=_PROVENANCE["agent_ref"],
            visibility=_PROVENANCE["visibility"],
        )
    assert _counts(client) == before


def test_correction_and_forget_preserve_creation_provenance(client: TestClient) -> None:
    memory_id = _remember(client)
    assert client.post(
        f"/memory/{memory_id}/correct",
        json={"corrected_text": "corrected", "reason": "evidence changed"},
    ).status_code == 200
    assert client.post(
        f"/memory/{memory_id}/forget", json={"reason": "no longer needed"}
    ).status_code == 200

    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT actor_ref, origin_session_id, origin_agent_id "
                "FROM memory_objects WHERE id=:id"
            ),
            {"id": memory_id},
        ).one()
    assert tuple(row) == ("local-user", "session-123", "codex")

def _post_other_creation(client: TestClient, operation: str, **scope_overrides):
    anchor_id = _remember(
        client,
        type="operational_fact" if operation == "record-outcome" else "decision",
    )
    baseline = _counts(client)
    body = {**_PROVENANCE, **scope_overrides}
    if operation == "supersede":
        body.update(new_text="replacement", supersedes_id=anchor_id)
        endpoint = "/memory/supersede"
    else:
        body.update(procedure_id=anchor_id, outcome="success")
        endpoint = "/memory/record-outcome"
    return client.post(endpoint, json=body), baseline


def _created_other_memory(storage, operation: str, response, before_ids: set[str]):
    if operation == "supersede":
        return storage.get_memory_object(response.json()["new_memory_object_id"])
    created = [
        memory
        for memory in storage.list_memory_objects()
        if memory.id not in before_ids and memory.type != "operational_fact"
    ]
    assert len(created) == 1
    return created[0]


@pytest.mark.parametrize("operation", ["supersede", "record-outcome"])
@pytest.mark.parametrize(
    "container_ref",
    [
        "C:" + chr(92) + "work" + chr(92) + "repo",
        "C:/work/repo",
        "/work/repo",
        "//server/share",
        chr(92) * 2 + "server" + chr(92) + "share",
        " C:/work/repo",
    ],
)
def test_other_creation_operations_reject_raw_paths_without_write(
    client: TestClient,
    operation: str,
    container_ref: str,
) -> None:
    response, baseline = _post_other_creation(
        client, operation, container_ref=container_ref
    )
    assert response.status_code == 400, response.text
    assert _counts(client) == baseline


@pytest.mark.parametrize("operation", ["supersede", "record-outcome"])
@pytest.mark.parametrize(
    ("container_ref", "expected"),
    [
        ("GIT:GITHUB.COM/Owner/Repo.GIT/", "git:github.com/owner/repo"),
        ("repo:abcdef123456", "repo:abcdef123456"),
        ("path:project:123abc", "path:project:123abc"),
        ("chat:ערוץ:צוות", "chat:ערוץ:צוות"),
    ],
)
def test_other_creation_operations_accept_opaque_container_refs(
    client: TestClient,
    operation: str,
    container_ref: str,
    expected: str,
) -> None:
    storage = client.app.state.pallium_service._storage
    before_ids = {memory.id for memory in storage.list_memory_objects()}
    response, _ = _post_other_creation(
        client, operation, container_ref=container_ref
    )
    assert response.status_code == 200, response.text
    created = _created_other_memory(storage, operation, response, before_ids)
    assert created.container_ref == expected


@pytest.mark.parametrize("operation", ["supersede", "record-outcome"])
@pytest.mark.parametrize("visibility", ["private", "container", "global"])
def test_other_creation_operations_accept_supported_visibility(
    client: TestClient,
    operation: str,
    visibility: str,
) -> None:
    storage = client.app.state.pallium_service._storage
    before_ids = {memory.id for memory in storage.list_memory_objects()}
    response, _ = _post_other_creation(client, operation, visibility=visibility)
    assert response.status_code == 200, response.text
    created = _created_other_memory(storage, operation, response, before_ids)
    assert created.visibility == visibility


@pytest.mark.parametrize("operation", ["supersede", "record-outcome"])
def test_other_creation_operations_reject_public_without_write(
    client: TestClient,
    operation: str,
) -> None:
    response, baseline = _post_other_creation(client, operation, visibility="public")
    assert response.status_code == 422, response.text
    assert _counts(client) == baseline
