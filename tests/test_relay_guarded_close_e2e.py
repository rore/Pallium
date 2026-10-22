"""Atomic caller-visible session disposal must not close a newer incarnation."""
from concurrent.futures import ThreadPoolExecutor

import pytest


def _turn(client, runtime="hermes", container="git:test/disposal", **extra):
    response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": "session",
                                               "container_ref": container, **extra})
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _close(client, session, **extra):
    return client.post("/relay/sessions/close", json={
        "runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "expected_endpoint_id": session["endpoint_id"],
        "expected_scope_generation": session["scope_generation"], **extra})


def _read(client, session):
    response = client.get("/relay/sessions", params={"runtime": session["runtime"],
        "session_ref": session["session_ref"], "container_ref": session["container_ref"], "include_inactive": True})
    assert response.status_code == 200, response.text
    return response.json()[0]


@pytest.mark.parametrize("runtime", ["hermes", "codex", "claude-code", "opencode"])
def test_guarded_close_then_reenroll_rejects_old_disposal(client, runtime):
    original = _turn(client, runtime)
    assert _turn(client, runtime)["scope_generation"] == original["scope_generation"]
    assert _close(client, original).status_code == 200
    assert _close(client, original).status_code == 200
    resumed = _turn(client, runtime)
    assert resumed["endpoint_id"] == original["endpoint_id"]
    assert resumed["scope_generation"] == original["scope_generation"] + 1
    named = client.post("/relay/sessions/name", json={"runtime": runtime, "session_ref": "session",
        "container_ref": resumed["container_ref"], "alias": "resumed"})
    assert named.status_code == 200, named.text
    assert _close(client, original).status_code == 409
    observed = _read(client, resumed)
    assert observed["state"] == "recent" and observed["alias"] == "resumed"
    assert observed["scope_generation"] == resumed["scope_generation"]
    assert _close(client, resumed).status_code == 200


def test_guarded_close_rejects_project_aba_and_wrong_endpoint(client):
    first = _turn(client)
    current = first
    for container in ["git:test/b", "git:test/c", first["container_ref"]]:
        current = _turn(client, container=container, previous_container_ref=current["container_ref"],
                        previous_endpoint_id=current["endpoint_id"], previous_scope_generation=current["scope_generation"])
    assert current["scope_generation"] == first["scope_generation"] + 3
    assert _close(client, first).status_code == 409
    assert _close(client, current, expected_endpoint_id="relay-session-" + "f" * 32).status_code == 409
    assert _read(client, current)["state"] == "recent"
    missing = _close(client, current, container_ref="git:test/absent")
    assert missing.status_code == 404


@pytest.mark.parametrize("changes", [
    {"expected_endpoint_id": None}, {"expected_scope_generation": None},
    {"expected_endpoint_id": "bad"}, {"expected_scope_generation": -1},
    {"expected_scope_generation": 2**63}, {"expected_scope_generation": True},
    {"expected_scope_generation": "0"},
])
def test_invalid_close_snapshot_never_changes_session(client, changes):
    session = _turn(client)
    assert _close(client, session, **changes).status_code == 422
    assert _read(client, session)["state"] == "recent"


def test_legacy_unguarded_close_is_unchanged(client):
    session = _turn(client)
    response = client.post("/relay/sessions/close", json={k: session[k] for k in ("runtime", "session_ref", "container_ref")})
    assert response.status_code == 200 and response.json()["state"] == "closed"


def test_concurrent_close_and_reenroll_never_accept_stale_incarnation(client):
    original = _turn(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        close = pool.submit(_close, client, original)
        enroll = pool.submit(_turn, client)
        assert close.result().status_code == 200
        enroll.result()
    current = _turn(client)
    assert current["scope_generation"] == original["scope_generation"] + 1
    assert _close(client, original).status_code == 409
    assert _read(client, current)["state"] == "recent"


def test_generation_exhaustion_refuses_reenrollment_without_partial_write(client):
    from storage.sqlite_schema import RelayEndpointGenerationRecord

    original = _turn(client)
    storage = client.app.state.pallium_service._storage
    with storage._relay_session_factory.begin() as db:
        db.add(RelayEndpointGenerationRecord(endpoint_id=original["endpoint_id"], generation=2**63 - 1))
    maximum = _read(client, original)
    assert _close(client, maximum).status_code == 200
    response = client.post("/relay/turn", json={"runtime": "hermes", "session_ref": "session",
        "container_ref": original["container_ref"], "title": "must not commit"})
    assert response.status_code == 409, response.text
    after = _read(client, original)
    assert after["state"] == "closed" and after["scope_generation"] == 2**63 - 1
    assert after["title"] != "must not commit"
