"""Atomic caller-visible session disposal must not close a newer incarnation."""
from concurrent.futures import ThreadPoolExecutor

import pytest


def _turn(client, runtime="hermes", container="git:test/disposal", **extra):
    response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": "session",
                                               "container_ref": container, "guarded_lifecycle": True, **extra})
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _close(client, session, **extra):
    return client.post("/relay/sessions/close-if-current", json={
        "runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "expected_endpoint_id": session["endpoint_id"],
        "expected_scope_generation": session["scope_generation"], **extra})


def _read(client, session):
    response = client.get("/relay/sessions", params={"runtime": session["runtime"],
        "session_ref": session["session_ref"], "container_ref": session["container_ref"], "include_inactive": True})
    assert response.status_code == 200, response.text
    return response.json()[0]


@pytest.mark.parametrize("runtime", ["hermes", "codex", "claude-code", "opencode"])
@pytest.mark.parametrize("relay_admission_clock", ["native", "semantic"], indirect=True)
def test_guarded_close_then_reenroll_rejects_old_disposal(client, runtime, relay_admission_clock):
    with relay_admission_clock(client.app.state.pallium_service._storage):
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
    session = _turn(client, guarded_lifecycle=False)
    response = client.post("/relay/sessions/close", json={k: session[k] for k in ("runtime", "session_ref", "container_ref")})
    assert response.status_code == 200 and response.json()["state"] == "closed"



@pytest.mark.parametrize("runtime", ["hermes", "codex", "claude-code", "opencode"])
@pytest.mark.parametrize("generation", [0, 7, 2**63 - 1])
def test_legacy_close_reopen_preserves_non_opted_generation(client, runtime, generation):
    from storage.sqlite_schema import RelayEndpointGenerationRecord

    session = _turn(client, guarded_lifecycle=False)
    storage = client.app.state.pallium_service._storage
    with storage._relay_session_factory.begin() as db:
        db.merge(RelayEndpointGenerationRecord(endpoint_id=session["endpoint_id"], generation=generation, guarded_lifecycle=0))
    response = client.post("/relay/sessions/close", json={k: session[k] for k in ("runtime", "session_ref", "container_ref")})
    assert response.status_code == 200
    reopened = client.post("/relay/turn", json={"runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "guarded_lifecycle": False, "title": "reopened"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["session"]["scope_generation"] == generation
    observed = _read(client, session)
    assert observed["state"] == "recent" and observed["title"] == "reopened"


def test_first_opt_in_does_not_advance_and_false_or_omitted_cannot_downgrade(client):
    first = _turn(client, guarded_lifecycle=False)
    opted_response = client.post("/relay/turn", json={"runtime": first["runtime"], "session_ref": first["session_ref"],
        "container_ref": first["container_ref"], "guarded_lifecycle": True})
    assert opted_response.status_code == 200 and opted_response.json()["session"]["guarded_lifecycle"] is True
    assert opted_response.json()["session"]["scope_generation"] == first["scope_generation"]
    first = opted_response.json()["session"]
    assert _turn(client, guarded_lifecycle=False)["guarded_lifecycle"] is True
    response = client.post("/relay/turn", json={"runtime": first["runtime"], "session_ref": first["session_ref"],
        "container_ref": first["container_ref"]})
    assert response.status_code == 200 and response.json()["session"]["guarded_lifecycle"] is True
    assert response.json()["session"]["scope_generation"] == first["scope_generation"]
    assert _read(client, first)["guarded_lifecycle"] is True


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_guarded_lifecycle_requires_strict_boolean_without_state_change(client, value):
    session = _turn(client, guarded_lifecycle=False)
    response = client.post("/relay/turn", json={"runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "guarded_lifecycle": value})
    assert response.status_code == 422
    observed = _read(client, session)
    assert observed["guarded_lifecycle"] is False and observed["scope_generation"] == session["scope_generation"]


def test_opt_in_with_register_session_false_is_rejected_without_state_change(client):
    session = _turn(client, guarded_lifecycle=False)
    response = client.post("/relay/turn", json={"runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "guarded_lifecycle": True, "register_session": False})
    assert response.status_code == 422
    observed = _read(client, session)
    assert observed["guarded_lifecycle"] is False and observed["state"] == "recent"


def test_conditional_close_requires_opt_in_and_valid_guards(client):
    legacy = _turn(client, guarded_lifecycle=False)
    assert _close(client, legacy).status_code == 409
    assert _read(client, legacy)["state"] == "recent"
    opted = _turn(client)
    assert client.post("/relay/sessions/close-if-current", json={"runtime": opted["runtime"],
        "session_ref": opted["session_ref"], "container_ref": opted["container_ref"]}).status_code == 422
    assert _close(client, opted, expected_scope_generation=True).status_code == 422
    assert _read(client, opted)["state"] == "recent"


def test_legacy_close_reopen_keeps_opt_in_and_rejects_delayed_guard(client):
    original = _turn(client)
    assert client.post("/relay/sessions/close", json={k: original[k] for k in ("runtime", "session_ref", "container_ref")}).status_code == 200
    response = client.post("/relay/turn", json={"runtime": original["runtime"], "session_ref": original["session_ref"],
        "container_ref": original["container_ref"], "guarded_lifecycle": False})
    assert response.status_code == 200, response.text
    current = response.json()["session"]
    assert current["guarded_lifecycle"] is True
    assert current["scope_generation"] == original["scope_generation"] + 1
    assert _close(client, original).status_code == 409
    assert _read(client, current)["state"] == "recent"


def test_guarded_and_legacy_close_chain_advances_once_per_opted_reopen(client):
    original = _turn(client)
    assert _close(client, original).status_code == 200
    assert _close(client, original).status_code == 200
    assert client.post("/relay/sessions/close", json={k: original[k] for k in ("runtime", "session_ref", "container_ref")}).status_code == 200
    response = client.post("/relay/turn", json={"runtime": original["runtime"], "session_ref": original["session_ref"],
        "container_ref": original["container_ref"], "guarded_lifecycle": False})
    assert response.status_code == 200 and response.json()["session"]["scope_generation"] == original["scope_generation"] + 1
    current = response.json()["session"]
    assert client.post("/relay/sessions/close", json={k: current[k] for k in ("runtime", "session_ref", "container_ref")}).status_code == 200
    later = client.post("/relay/turn", json={"runtime": current["runtime"], "session_ref": current["session_ref"],
        "container_ref": current["container_ref"]})
    assert later.status_code == 200 and later.json()["session"]["scope_generation"] == current["scope_generation"] + 1


def test_opted_generation_maximum_reopen_and_project_move_roll_back(client):
    from storage.sqlite_schema import RelayEndpointGenerationRecord

    session = _turn(client)
    storage = client.app.state.pallium_service._storage
    with storage._relay_session_factory.begin() as db:
        db.merge(RelayEndpointGenerationRecord(endpoint_id=session["endpoint_id"], generation=2**63 - 1, guarded_lifecycle=1))
    maximum = _read(client, session)
    assert _close(client, maximum).status_code == 200
    response = client.post("/relay/turn", json={"runtime": session["runtime"], "session_ref": session["session_ref"],
        "container_ref": session["container_ref"], "title": "must not commit"})
    assert response.status_code == 409
    after = _read(client, session)
    assert after["state"] == "closed" and after["scope_generation"] == 2**63 - 1
    assert after["title"] == maximum["title"]

    active = _turn(client, runtime="codex", container="git:test/max-move")
    with storage._relay_session_factory.begin() as db:
        db.merge(RelayEndpointGenerationRecord(endpoint_id=active["endpoint_id"], generation=2**63 - 1, guarded_lifecycle=1))
    move = client.post("/relay/turn", json={"runtime": active["runtime"], "session_ref": active["session_ref"],
        "container_ref": "git:test/moved", "title": "must not move", "previous_container_ref": active["container_ref"],
        "previous_endpoint_id": active["endpoint_id"], "previous_scope_generation": 2**63 - 1})
    assert move.status_code == 409
    assert _read(client, active)["container_ref"] == active["container_ref"]
    assert _read(client, active)["title"] == active["title"]
    assert client.get("/relay/sessions", params={"runtime": active["runtime"], "session_ref": active["session_ref"],
        "container_ref": "git:test/moved", "include_inactive": True}).json() == []

@pytest.mark.parametrize("guarded", [False, True])
def test_project_move_then_legacy_reopen_preserves_opt_in_semantics(client, guarded):
    original = _turn(client, guarded_lifecycle=guarded)
    moved = client.post("/relay/turn", json={"runtime": original["runtime"], "session_ref": original["session_ref"],
        "container_ref": "git:test/moved", "guarded_lifecycle": False,
        "previous_container_ref": original["container_ref"], "previous_endpoint_id": original["endpoint_id"],
        "previous_scope_generation": original["scope_generation"]})
    assert moved.status_code == 200 and moved.json()["session"]["scope_generation"] == 1
    current = moved.json()["session"]
    assert client.post("/relay/sessions/close", json={k: current[k] for k in ("runtime", "session_ref", "container_ref")}).status_code == 200
    reopened = client.post("/relay/turn", json={"runtime": current["runtime"], "session_ref": current["session_ref"],
        "container_ref": current["container_ref"], "guarded_lifecycle": False})
    assert reopened.status_code == 200 and reopened.json()["session"]["scope_generation"] == 1 + int(guarded)
    assert _read(client, current)["guarded_lifecycle"] is guarded

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
        db.get(RelayEndpointGenerationRecord, original["endpoint_id"]).generation = 2**63 - 1
    maximum = _read(client, original)
    assert _close(client, maximum).status_code == 200
    response = client.post("/relay/turn", json={"runtime": "hermes", "session_ref": "session",
        "container_ref": original["container_ref"], "title": "must not commit"})
    assert response.status_code == 409, response.text
    after = _read(client, original)
    assert after["state"] == "closed" and after["scope_generation"] == 2**63 - 1
    assert after["title"] != "must not commit"


def test_legacy_close_keeps_optional_snapshot_validation(client):
    session = _turn(client, guarded_lifecycle=False)
    identity = {k: session[k] for k in ("runtime", "session_ref", "container_ref")}
    endpoint = {"expected_endpoint_id": session["endpoint_id"]}
    missing = client.post("/relay/sessions/close", json={**identity, **endpoint})
    assert missing.status_code == 422
    stale = client.post("/relay/sessions/close", json={**identity, **endpoint,
        "expected_scope_generation": session["scope_generation"] + 1})
    assert stale.status_code == 409
    assert _read(client, session)["state"] == "recent"
    current = client.post("/relay/sessions/close", json={**identity, **endpoint,
        "expected_scope_generation": session["scope_generation"]})
    assert current.status_code == 200
    assert _read(client, session)["state"] == "closed"


@pytest.mark.parametrize("value,register", [(None, True), (0, True), (1, True), ("true", True), (True, False)])
def test_direct_core_opt_in_validation_cannot_register_a_session(client, value, register):
    from core.relay import RelayService

    service = RelayService(client.app.state.pallium_service._storage)
    with pytest.raises(ValueError, match="guarded_lifecycle"):
        service.turn(runtime="hermes", session_ref="invalid-opt-in", container_ref="git:test/core",
                     guarded_lifecycle=value, register_session=register)
    observed = client.get("/relay/sessions", params={"container_ref": "git:test/core", "include_inactive": True})
    assert observed.status_code == 200 and observed.json() == []
