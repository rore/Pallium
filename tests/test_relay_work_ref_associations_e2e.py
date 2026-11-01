from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

import pytest

from sqlalchemy import event, select, text, update

from core.relay import RelayService
from core.work_ref import readable_work_ref
from storage.sqlite_schema import RelaySessionRecord, RelaySessionWorkRefRecord


CONTAINER = "git:example.test/team/relay"
FEATURE = {
    "scope_ref": "roadmap:v1:git:example.test/team/relay#roadmap",
    "local_ref": "feature:relay-session-work-associations",
}
BRANCH = {
    "scope_ref": "git:example.test/team/relay",
    "local_ref": "branch:feat/relay-session-work-associations",
}


def _turn(client, session="worker", structural_work_refs=None):
    payload = {
        "runtime": "codex",
        "session_ref": session,
        "container_ref": CONTAINER,
    }
    if structural_work_refs is not None:
        payload["structural_work_refs"] = structural_work_refs
    response = client.post("/relay/turn", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _attach(client, value, session="worker"):
    return client.post(
        "/relay/sessions/work-refs/attach",
        json={
            "runtime": "codex",
            "session_ref": session,
            "container_ref": CONTAINER,
            **value,
        },
    )


def _list(client, session="worker"):
    response = client.get(
        "/relay/sessions/work-refs",
        params={
            "runtime": "codex",
            "session_ref": session,
            "container_ref": CONTAINER,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_attach_overlap_overflow_detach_and_exact_participants(client):
    turn = _turn(client, structural_work_refs=[BRANCH, FEATURE])
    assert turn["structural_work_refs_status"] == "complete"
    feature_key = readable_work_ref(**FEATURE).key
    assert {item["work_ref"] for item in turn["work_refs"]} == {
        readable_work_ref(**BRANCH).key,
        feature_key,
    }

    attached = _attach(client, FEATURE)
    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert body["attached"]["work_ref"] == feature_key
    assert body["attached"]["scope_ref"] == FEATURE["scope_ref"]
    assert "existing exact History" in body["history_guidance"]

    for index in range(2):
        response = _attach(
            client,
            {
                "scope_ref": "tracker:v1:example.test#relay",
                "local_ref": f"ticket:PAL-{index}",
            },
        )
        assert response.status_code == 200, response.text

    overflow = _attach(
        client,
        {
            "scope_ref": "tracker:v1:example.test#relay",
            "local_ref": "ticket:PAL-overflow",
        },
    )
    assert overflow.status_code == 409
    assert overflow.json()["detail"]["code"] == "association_limit"
    assert len([row for row in _list(client)["work_refs"] if row["origin"] == "explicit"]) == 3

    readable = client.get("/relay/work-refs/participants", params=FEATURE)
    assert readable.status_code == 200, readable.text
    participant = readable.json()["participants"]
    assert len(participant) == 1
    assert participant[0]["association"]["origins"] == ["explicit", "structural"]

    advanced = client.get(
        "/relay/work-refs/participants",
        params={"work_ref": feature_key},
    )
    assert advanced.status_code == 200
    assert advanced.json()["participants"][0]["endpoint_id"] == participant[0]["endpoint_id"]

    detached = client.post(
        "/relay/sessions/work-refs/detach",
        json={
            "runtime": "codex",
            "session_ref": "worker",
            "container_ref": CONTAINER,
            **FEATURE,
        },
    )
    assert detached.status_code == 200, detached.text
    assert detached.json()["detached"] is True
    assert detached.json()["structural_remains"] is True
    assert client.post(
        "/relay/sessions/work-refs/detach",
        json={
            "runtime": "codex",
            "session_ref": "worker",
            "container_ref": CONTAINER,
            **FEATURE,
        },
    ).json()["detached"] is False


def test_structural_refresh_is_replace_only_and_failure_does_not_block_turn(client, monkeypatch):
    _turn(client, structural_work_refs=[BRANCH, FEATURE])
    ticket = {
        "scope_ref": "tracker:v1:example.test#relay",
        "local_ref": "ticket:PAL-412",
    }
    assert _attach(client, ticket).status_code == 200

    refreshed = _turn(client, structural_work_refs=[FEATURE])
    assert refreshed["structural_work_refs_status"] == "complete"
    rows = _list(client)["work_refs"]
    assert {(row["local_ref"], row["origin"]) for row in rows} == {
        (FEATURE["local_ref"], "structural"),
        (ticket["local_ref"], "explicit"),
    }

    duplicate = _turn(
        client, session="duplicate", structural_work_refs=[FEATURE, FEATURE]
    )
    assert duplicate["structural_work_refs_status"] == "complete"
    assert len(duplicate["work_refs"]) == 1

    store = client.app.state.pallium_service._storage

    def fail_refresh(**_kwargs):
        raise RuntimeError("association store unavailable")

    monkeypatch.setattr(store, "relay_refresh_structural_work_refs", fail_refresh)
    admitted = _turn(client, session="admitted", structural_work_refs=[FEATURE])
    assert admitted["session"]["session_ref"] == "admitted"
    assert admitted["structural_work_refs_status"] == "unavailable"

    malformed = _turn(
        client,
        session="malformed",
        structural_work_refs=[FEATURE, BRANCH, ticket],
    )
    assert malformed["session"]["session_ref"] == "malformed"
    assert malformed["structural_work_refs_status"] == "unavailable"



def test_participants_include_dormant_but_closed_is_opt_in(client):
    turn = _turn(client, session="lifecycle", structural_work_refs=[FEATURE])
    endpoint_id = turn["session"]["endpoint_id"]
    duplicate = _turn(
        client, session="duplicate", structural_work_refs=[FEATURE, FEATURE]
    )
    assert duplicate["structural_work_refs_status"] == "complete"
    assert len(duplicate["work_refs"]) == 1

    store = client.app.state.pallium_service._storage
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with store._relay_engine.begin() as connection:
        connection.execute(
            text("UPDATE relay_sessions SET last_seen_at=:old WHERE id=:endpoint_id"),
            {"old": old, "endpoint_id": endpoint_id},
        )

    current = client.get("/relay/work-refs/participants", params=FEATURE)
    assert current.status_code == 200
    participant = next(
        row for row in current.json()["participants"] if row["endpoint_id"] == endpoint_id
    )
    assert participant["state"] == "active"
    assert participant["lifecycle"] == "dormant"

    closed = client.post(
        "/relay/sessions/close",
        json={
            "runtime": "codex",
            "session_ref": "lifecycle",
            "container_ref": CONTAINER,
        },
    )
    assert closed.status_code == 200
    remaining = client.get(
        "/relay/work-refs/participants", params=FEATURE
    ).json()["participants"]
    assert {row["session_ref"] for row in remaining} == {"duplicate"}
    included = client.get(
        "/relay/work-refs/participants",
        params={**FEATURE, "include_closed": True},
    )
    assert included.status_code == 200
    closed_participant = next(
        row for row in included.json()["participants"] if row["endpoint_id"] == endpoint_id
    )
    assert closed_participant["state"] == "closed"
    assert closed_participant["lifecycle"] == "closed"
    assert _attach(client, FEATURE, session="lifecycle").status_code == 409


def test_invalid_identity_and_participant_selector_errors_do_not_mutate(client):
    _turn(client)
    invalid = _attach(
        client,
        {"scope_ref": "tracker:v1:example.test#relay", "local_ref": " password=sk-ant-api03-" + "x" * 40},
    )
    assert invalid.status_code == 422
    assert _list(client)["work_refs"] == []

    both = client.get(
        "/relay/work-refs/participants",
        params={**FEATURE, "work_ref": readable_work_ref(**FEATURE).key},
    )
    assert both.status_code == 422
    neither = client.get("/relay/work-refs/participants")
    assert neither.status_code == 422

def test_concurrent_capacity_admission_keeps_exactly_three_explicit_refs(client):
    _turn(client, session="concurrent")
    scope = "tracker:v1:example.test#relay"
    for index in range(2):
        assert _attach(
            client,
            {"scope_ref": scope, "local_ref": f"ticket:existing-{index}"},
            session="concurrent",
        ).status_code == 200

    def attach(local_ref):
        return _attach(
            client,
            {"scope_ref": scope, "local_ref": local_ref},
            session="concurrent",
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(attach, ("ticket:third", "ticket:fourth")))
    assert statuses == [200, 409]
    assert len([
        row for row in _list(client, session="concurrent")["work_refs"]
        if row["origin"] == "explicit"
    ]) == 3


@pytest.fixture
def relay_settlement_control(client, monkeypatch):
    store = client.app.state.pallium_service._storage
    factory, attach = store._relay_session_factory, store.relay_attach_work_ref
    local = threading.local()
    control = SimpleNamespace(
        mode="close", cleanup_error=None, hold_b=False,
        held=threading.Event(), release=threading.Event(),
        b_active=threading.Event(), release_b=threading.Event(),
        begins=[], failures=[], closes=[], commit_returned=False, rollback_returned=False,
        pool=ThreadPoolExecutor(max_workers=2),
    )

    def pause(connection):
        control.native_active = connection.connection.driver_connection.in_transaction
        control.held.set()
        assert control.release.wait(5), "transaction control was not released"

    def session_factory():
        session = factory()
        role = getattr(local, "role", None)
        if role is None:
            return session
        connection, close = session.connection, session.close

        def observed_connection(*args, **kwargs):
            conn = connection(*args, **kwargs)
            execute = conn.execute

            def observed_execute(statement, *args, **kwargs):
                sql = str(statement).strip().upper()
                if sql == "BEGIN IMMEDIATE":
                    control.begins.append(role)
                if role == "A":
                    if sql == "COMMIT" and control.mode == "active":
                        pause(conn)
                    if sql == "COMMIT" and control.mode in {"rollback-failed", "rollback-inflight"}:
                        raise RuntimeError("controlled commit failure")
                    if sql == "ROLLBACK" and control.mode == "rollback-failed":
                        raise RuntimeError("controlled rollback failure")
                if role == "B" and sql == "COMMIT" and control.hold_b:
                    assert conn.connection.driver_connection.in_transaction
                    control.b_active.set()
                    assert control.release_b.wait(5), "successor transaction was not released"
                result = execute(statement, *args, **kwargs)
                if role == "A":
                    if sql == "COMMIT":
                        control.commit_returned = True
                        if control.mode == "commit-ambiguous":
                            raise RuntimeError("controlled commit failure")
                    if sql == "ROLLBACK":
                        control.rollback_returned = True
                    if ((sql == "COMMIT" and control.mode == "commit-inflight")
                            or (sql == "ROLLBACK" and control.mode == "rollback-inflight")
                            or (sql == f"PRAGMA BUSY_TIMEOUT={store._DEFAULT_BUSY_TIMEOUT_MS}"
                                and control.mode == "reset")):
                        pause(conn)
                        if control.cleanup_error == "reset":
                            raise RuntimeError("controlled reset failure")
                return result

            monkeypatch.setattr(conn, "execute", observed_execute)
            if role == "A":
                control.connection = conn
            return conn

        def observed_close(*args, **kwargs):
            control.closes.append(role)
            if role == "A" and control.mode in {"close", "rollback-failed", "commit-ambiguous"}:
                pause(control.connection)
            result = close(*args, **kwargs)
            if role == "A" and control.cleanup_error == "close":
                raise RuntimeError("controlled close failure")
            return result

        monkeypatch.setattr(session, "connection", observed_connection)
        monkeypatch.setattr(session, "close", observed_close)
        return session

    def labelled_attach(**kwargs):
        previous = getattr(local, "role", None)
        value = kwargs["work_ref"]["local_ref"]
        local.role = value[-1] if value in {"item:A", "item:B", "item:C"} else None
        try:
            return attach(**kwargs)
        except BaseException as exc:
            control.failures.append((local.role, getattr(exc, "acquisition_stage", None)))
            raise
        finally:
            local.role = previous

    monkeypatch.setattr(store, "_relay_session_factory", session_factory)
    monkeypatch.setattr(store, "relay_attach_work_ref", labelled_attach)
    try:
        yield control
    finally:
        control.release.set()
        control.release_b.set()
        control.pool.shutdown(wait=False, cancel_futures=True)
        for worker in tuple(control.pool._threads):
            worker.join(5)
            assert not worker.is_alive(), "owned HTTP worker did not settle"


def _association_pairs(client, session="worker"):
    return {(row["scope_ref"], row["local_ref"], row["origin"])
            for row in _list(client, session)["work_refs"]}


@pytest.mark.parametrize("settlement", ["commit", "rollback"])
@pytest.mark.parametrize("cleanup,error", [
    ("close", None), ("reset", None), ("close", "close"), ("reset", "reset"),
])
def test_settled_relay_write_releases_gate_before_cleanup(
    client, relay_settlement_control, settlement, cleanup, error,
):
    control = relay_settlement_control
    control.mode, control.cleanup_error = cleanup, error
    scope = "scope:gate-cleanup"
    _turn(client)
    seeds = [f"item:seed-{index}" for index in range(2 if settlement == "commit" else 3)]
    for value in seeds:
        assert _attach(client, {"scope_ref": scope, "local_ref": value}).status_code == 200
    expected = {(scope, value, "explicit") for value in seeds}
    if settlement == "commit":
        expected.add((scope, "item:A", "explicit"))

    first = control.pool.submit(_attach, client, {"scope_ref": scope, "local_ref": "item:A"})
    assert control.held.wait(5), "writer A did not enter settled cleanup"
    assert not first.done() and control.native_active is False
    assert control.commit_returned == (settlement == "commit")
    assert control.rollback_returned == (settlement == "rollback")
    second = control.pool.submit(_attach, client, {"scope_ref": scope, "local_ref": "item:B"})
    response = second.result(timeout=3)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "association_limit"
    assert control.begins == ["A", "B"]
    assert _association_pairs(client) == expected
    assert not first.done(), "A cleanup was not held during B admission"
    control.release.set()
    if error == "close":
        with pytest.raises(RuntimeError, match="controlled close failure"):
            first.result(timeout=5)
    else:
        assert first.result(timeout=5).status_code == (200 if settlement == "commit" else 409)
    assert control.closes == (["A", "B"] if cleanup == "close" else ["B", "A"])
    assert _association_pairs(client) == expected


@pytest.mark.parametrize("close_error", [False, True])
def test_settled_writer_cleanup_cannot_release_active_successor_gate(
    client, relay_settlement_control, close_error,
):
    control = relay_settlement_control
    control.cleanup_error = "close" if close_error else None
    control.hold_b = True
    scope = "scope:gate-successor"
    _turn(client)
    _turn(client, "successor")
    first = control.pool.submit(_attach, client, {"scope_ref": scope, "local_ref": "item:A"})
    assert control.held.wait(5)
    second = control.pool.submit(_attach, client, {"scope_ref": scope, "local_ref": "item:B"}, "successor")
    assert control.b_active.wait(3), "B could not begin during A's settled cleanup"
    control.release.set()
    if close_error:
        with pytest.raises(RuntimeError, match="controlled close failure"):
            first.result(timeout=3)
    else:
        assert first.result(timeout=3).status_code == 200
    assert not second.done()
    third = _attach(client, {"scope_ref": scope, "local_ref": "item:C"}, "successor")
    assert third.status_code == 503, third.text
    assert third.json()["detail"] == {"code": "relay_busy", "retryable": True}
    assert ("C", "local_gate") in control.failures and control.begins == ["A", "B"]
    assert _association_pairs(client) == {(scope, "item:A", "explicit")}
    assert _association_pairs(client, "successor") == set()
    control.release_b.set()
    assert second.result(timeout=5).status_code == 200
    assert _association_pairs(client, "successor") == {(scope, "item:B", "explicit")}
    assert control.closes == ["A", "B"]


@pytest.mark.parametrize("stage", [
    "active", "commit-inflight", "rollback-failed", "rollback-inflight", "commit-ambiguous",
])
def test_unsettled_relay_write_keeps_gate_until_observed_terminal_return(
    client, relay_settlement_control, stage,
):
    control = relay_settlement_control
    control.mode = stage
    scope = "scope:gate-unsettled"
    _turn(client)
    first = control.pool.submit(_attach, client, {"scope_ref": scope, "local_ref": "item:A"})
    assert control.held.wait(5), "A did not enter the unsettled boundary"
    assert control.native_active == (stage in {"active", "rollback-failed"})
    assert not first.done()
    second = _attach(client, {"scope_ref": scope, "local_ref": "item:B"})
    assert second.status_code == 503, second.text
    assert second.json()["detail"] == {"code": "relay_busy", "retryable": True}
    assert ("B", "local_gate") in control.failures and control.begins == ["A"]
    committed = stage in {"commit-inflight", "commit-ambiguous"}
    expected = {(scope, "item:A", "explicit")} if committed else set()
    assert _association_pairs(client) == expected
    control.release.set()
    if stage in {"rollback-failed", "rollback-inflight", "commit-ambiguous"}:
        with pytest.raises(RuntimeError, match="controlled commit failure"):
            first.result(timeout=5)
    else:
        assert first.result(timeout=5).status_code == 200
        expected = {(scope, "item:A", "explicit")}
    assert control.closes == ["A"]
    assert _association_pairs(client) == expected
    assert _attach(client, {"scope_ref": scope, "local_ref": "item:B"}).status_code == 200
    assert control.begins == ["A", "B"]
    assert _association_pairs(client) == expected | {(scope, "item:B", "explicit")}


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_alias_transfer_does_not_transfer_associations_and_reopen_retains_them(
    client, drain_queue, relay_admission_clock,
):
    ticket = {
        "scope_ref": "tracker:v1:example.test#relay",
        "local_ref": "ticket:owner",
    }
    store = client.app.state.pallium_service._storage
    with relay_admission_clock(store, expected_admissions=2):
        first = _turn(client, session="first")
        second = _turn(client, session="second")
    assert _attach(client, ticket, session="first").status_code == 200
    key = readable_work_ref(**ticket).key
    captured = client.post("/items", json=[{
        "source_type": "chat", "source_id": "captured-before-name-transfer",
        "content_type": "text/plain", "content": "preserved exact session evidence é",
        "role": "user", "artifact_kind": "message", "container_ref": CONTAINER,
        "thread_ref": "first", "visibility": "private",
        "metadata": {"pallium_work_refs": [key]},
    }])
    assert captured.status_code == 200, captured.text
    source_id = captured.json()[0]["source_item_id"]
    for session, replace in (("first", False), ("second", True)):
        response = client.post(
            "/relay/sessions/name",
            json={
                "runtime": "codex",
                "session_ref": session,
                "container_ref": CONTAINER,
                "alias": "shared-owner",
                "replace_existing": replace,
            },
        )
        assert response.status_code == 200, response.text
    participants = client.get("/relay/work-refs/participants", params=ticket).json()
    assert [row["endpoint_id"] for row in participants["participants"]] == [
        first["session"]["endpoint_id"]
    ]
    assert second["session"]["endpoint_id"] not in str(participants)
    assert _counts(client, [ticket]).json()["counts"][0]["participant_count"] == 1
    drain_queue(client)
    for session, expected in (("first", [source_id]), ("second", [])):
        history = client.post("/query", json={
            "text": " ", "limit": 5, "source_only": True,
            "trigger_origin": "agent_pull_work", "work_refs": [key],
            "container_ref": CONTAINER, "thread_ref": session, "visibility": "private",
        })
        assert history.status_code == 200, history.text
        assert [row["source_item_id"] for row in history.json()["results"]] == expected

    assert client.post(
        "/relay/sessions/close",
        json={
            "runtime": "codex",
            "session_ref": "first",
            "container_ref": CONTAINER,
        },
    ).status_code == 200
    assert _counts(client, [ticket]).json()["counts"][0]["participant_count"] == 0
    reopened = _turn(client, session="first")
    assert reopened["session"]["endpoint_id"] == first["session"]["endpoint_id"]
    assert {row["local_ref"] for row in _list(client, session="first")["work_refs"]} == {
        ticket["local_ref"]
    }
    assert _counts(client, [ticket]).json()["counts"][0]["participant_count"] == 1

@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
def test_detach_changes_future_history_but_not_captured_snapshot(
    client, drain_queue, relay_admission_clock,
):
    from storage import sqlite_queue

    store = client.app.state.pallium_service._storage
    native_time = sqlite_queue.time
    with relay_admission_clock(store, expected_admissions=1):
        _turn(client, session="history")
    assert sqlite_queue.time is native_time
    assert _attach(client, FEATURE, session="history").status_code == 200
    listed = _list(client, session="history")
    key = next(row["work_ref"] for row in listed["work_refs"] if row["origin"] == "explicit")
    first_payload = {
        "source_type": "chat",
        "source_id": "captured-before-detach",
        "content_type": "text/plain",
        "content": "association snapshot evidence",
        "role": "user",
        "artifact_kind": "message",
        "container_ref": CONTAINER,
        "thread_ref": "history",
        "visibility": "private",
        "metadata": {"pallium_work_refs": [key]},
    }
    first = client.post("/items", json=[first_payload])
    assert first.status_code == 200, first.text
    first_id = first.json()[0]["source_item_id"]

    detached = client.post(
        "/relay/sessions/work-refs/detach",
        json={
            "runtime": "codex",
            "session_ref": "history",
            "container_ref": CONTAINER,
            **FEATURE,
        },
    )
    assert detached.status_code == 200 and detached.json()["detached"] is True
    replay = client.post("/items", json=[first_payload])
    assert replay.status_code == 200
    assert replay.json()[0]["source_item_id"] == first_id
    later = client.post(
        "/items",
        json=[{
            **first_payload,
            "source_id": "captured-after-detach",
            "content": "later association snapshot evidence",
            "metadata": {},
        }],
    )
    assert later.status_code == 200, later.text
    later_id = later.json()[0]["source_item_id"]
    drain_queue(client)

    exact = client.post(
        "/query",
        json={
            "text": " ",
            "limit": 5,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "work_refs": [key],
            "container_ref": CONTAINER,
            "thread_ref": "history",
            "visibility": "private",
        },
    )
    assert exact.status_code == 200, exact.text
    found = [row["source_item_id"] for row in exact.json()["results"]]
    assert found == [first_id]
    assert later_id not in found

def test_malformed_structural_shapes_preserve_turn_admission(client):
    for index, value in enumerate(("bad", 7, {"scope_ref": "scope"}, ["bad"])):
        response = client.post(
            "/relay/turn",
            json={
                "runtime": "codex",
                "session_ref": f"malformed-shape-{index}",
                "container_ref": CONTAINER,
                "structural_work_refs": value,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session"]["session_ref"] == f"malformed-shape-{index}"
        assert body["structural_work_refs_status"] == "unavailable"


def test_participant_container_filter_applies_before_pagination(client):
    other = "git:example.test/team/other"
    for session, container in (("target", CONTAINER), ("newer-other", other)):
        turn = client.post(
            "/relay/turn",
            json={
                "runtime": "codex",
                "session_ref": session,
                "container_ref": container,
                "structural_work_refs": [FEATURE],
            },
        )
        assert turn.status_code == 200, turn.text

    filtered = client.get(
        "/relay/work-refs/participants",
        params={**FEATURE, "container_ref": CONTAINER, "limit": 1},
    )
    assert filtered.status_code == 200, filtered.text
    assert [row["session_ref"] for row in filtered.json()["participants"]] == ["target"]

def test_participant_lookup_keeps_page_full_during_concurrent_final_detach(client, monkeypatch):
    from itertools import count
    from types import SimpleNamespace
    import time
    from storage import sqlite_queue

    for index in range(6):
        session = f"worker-{index}"
        _turn(client, session=session)
        assert _attach(client, FEATURE, session=session).status_code == 200
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    entered = detached = False
    native_time = sqlite_queue.time
    native_monotonic = time.monotonic

    def detach_before_participant_projection(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        nonlocal entered, detached
        if entered or "relay_session_work_refs" not in statement:
            return
        entered = True
        # This interleaving needs a completed detach, independent of host setup speed.
        private_time = SimpleNamespace(**vars(native_time))
        private_time.monotonic = count(step=0.001).__next__
        with monkeypatch.context() as detach_patch:
            detach_patch.setattr(sqlite_queue, "time", private_time)
            assert private_time.sleep is time.sleep and time.monotonic is native_monotonic
            result = relay.detach_work_ref(
                runtime="codex",
                session_ref="worker-5",
                container_ref=CONTAINER,
                **FEATURE,
            )
        assert sqlite_queue.time is native_time and time.monotonic is native_monotonic
        assert result["detached"] is True and result["work_refs"] == []
        detached = True

    event.listen(
        storage._relay_engine,
        "before_cursor_execute",
        detach_before_participant_projection,
    )
    try:
        response = client.get(
            "/relay/work-refs/participants",
            params={**FEATURE, "limit": 5},
        )
    finally:
        event.remove(
            storage._relay_engine,
            "before_cursor_execute",
            detach_before_participant_projection,
        )

    assert entered is True and detached is True
    assert response.status_code == 200, response.text
    participants = response.json()["participants"]
    assert len(participants) == 5
    assert {row["session_ref"] for row in participants} == {
        f"worker-{index}" for index in range(5)
    }
def test_cross_container_association_discovery_select_send_and_reply(client):
    source = "git:example.test/team/source-worktree"
    target = "git:example.test/team/target-worktree"
    sessions = {}
    for session, container in (("sender", source), ("target", target)):
        response = client.post(
            "/relay/turn",
            json={
                "runtime": "codex",
                "session_ref": session,
                "container_ref": container,
                "structural_work_refs": [FEATURE],
            },
        )
        assert response.status_code == 200, response.text
        sessions[session] = response.json()["session"]

    participants = client.get(
        "/relay/work-refs/participants", params=FEATURE
    ).json()["participants"]
    assert {row["container_ref"] for row in participants} == {source, target}
    recipient = next(row for row in participants if row["session_ref"] == "target")

    sent = client.post(
        "/relay/messages",
        json={
            "sender_runtime": "codex",
            "sender_session_ref": "sender",
            "recipient": recipient["endpoint_id"],
            "payload": "Please review the shared feature.",
            "container_ref": source,
        },
    )
    assert sent.status_code == 200, sent.text
    claim = client.post(
        "/relay/turn",
        json={
            "runtime": "codex",
            "session_ref": "target",
            "container_ref": target,
        },
    ).json()["deliveries"][0]
    reply = client.post(
        "/relay/replies",
        json={
            "delivery_id": claim["delivery_id"],
            "receipt": claim["receipt"],
            "payload": "Reviewed and approved.",
            "container_ref": target,
        },
    )
    assert reply.status_code == 200, reply.text
    received = client.post(
        "/relay/turn",
        json={
            "runtime": "codex",
            "session_ref": "sender",
            "container_ref": source,
        },
    ).json()["deliveries"]
    assert received[0]["message_id"] == reply.json()["message_id"]
    assert received[0]["sender_endpoint_id"] == sessions["target"]["endpoint_id"]


def _counts(client, references):
    return client.post(
        "/relay/work-refs/participant-counts", json={"references": references}
    )


def _count_row(ref, total, recent=None):
    recent = total if recent is None else recent
    return {**ref, "participant_count": total, "recent_participant_count": recent,
            "dormant_participant_count": total - recent}


def test_batch_detail_share_inclusive_clock_and_age_without_writes(client, monkeypatch):
    current = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return current if tz else current.replace(tzinfo=None)

    monkeypatch.setattr("core.relay.datetime", Clock)
    monkeypatch.setattr("storage.sqlite_relay.datetime", Clock)
    store = client.app.state.pallium_service._storage
    endpoint_times = {}
    for state in ("active", "unreachable"):
        for delta in (-1, 0, 1):
            session = f"{state}-{delta}"
            endpoint = _turn(client, session, [FEATURE])["session"]["endpoint_id"]
            assert _attach(client, FEATURE, session).status_code == 200
            seen = current - timedelta(seconds=86400) + timedelta(microseconds=delta)
            endpoint_times[endpoint] = seen.replace(tzinfo=None)
            with store._relay_engine.begin() as db:
                db.execute(update(RelaySessionRecord).where(RelaySessionRecord.id == endpoint).values(
                    last_seen_at=seen, state=state))
    _turn(client, "closed", [FEATURE])
    assert client.post("/relay/sessions/close", json={
        "runtime": "codex", "session_ref": "closed", "container_ref": CONTAINER,
    }).status_code == 200

    def assert_views(recent, dormant):
        Clock.calls = 0
        batch = _counts(client, [FEATURE, BRANCH])
        assert batch.status_code == 200, batch.text
        assert Clock.calls == 1
        body = batch.json()
        assert datetime.fromisoformat(body["as_of"]) == current
        assert body["recent_seconds"] == 86400
        assert body["counts"] == [_count_row(FEATURE, recent + dormant, recent), _count_row(BRANCH, 0)]
        Clock.calls = 0
        detail = client.get("/relay/work-refs/participants", params=FEATURE)
        assert detail.status_code == 200, detail.text
        assert Clock.calls == 1
        page = detail.json()
        assert page["as_of"] == body["as_of"] and page["recent_seconds"] == body["recent_seconds"]
        assert sum(row["lifecycle"] == "recent" for row in page["participants"]) == recent
        assert sum(row["lifecycle"] == "dormant" for row in page["participants"]) == dormant

    assert_views(4, 2)
    current += timedelta(microseconds=1)
    assert_views(2, 4)
    with store._relay_engine.connect() as db:
        actual = dict(db.execute(select(RelaySessionRecord.id, RelaySessionRecord.last_seen_at)).all())
    assert {endpoint: actual[endpoint] for endpoint in endpoint_times} == endpoint_times
    with_closed = client.get("/relay/work-refs/participants", params={**FEATURE, "include_closed": True}).json()
    assert len(with_closed["participants"]) == 7
    assert [row["lifecycle"] for row in with_closed["participants"]].count("closed") == 1
    refreshed = _turn(client, "unreachable--1")
    assert refreshed["session"]["state"] == "recent"
    assert_views(3, 3)
    empty = client.get("/relay/work-refs/participants", params=BRANCH).json()
    assert empty["participants"] == []
    assert datetime.fromisoformat(empty["as_of"]) == current and empty["recent_seconds"] == 86400


@pytest.mark.parametrize("size,relay_admission_clock", [
    pytest.param(1, "semantic", id="1"),
    pytest.param(200, "semantic", id="200"),
], indirect=["relay_admission_clock"])
def test_batch_counts_use_one_indexed_filtered_aggregate(client, size, relay_admission_clock):
    store = client.app.state.pallium_service._storage
    with relay_admission_clock(store, expected_admissions=3):
        _turn(client, structural_work_refs=[FEATURE])
        assert _attach(client, FEATURE).status_code == 200
    table = RelaySessionWorkRefRecord.__table__
    with store._relay_engine.begin() as db:
        template = dict(db.execute(select(table).where(table.c.origin == "structural")).mappings().one())
        noise = []
        for scope in (FEATURE["scope_ref"], "scope:unrelated-é"):
            for index in range(100):
                ref = readable_work_ref(scope, f"unrequested:{index}")
                noise.append({**template, "work_ref": ref.key, "scope_ref": ref.scope_ref, "local_ref": ref.local_ref})
        db.execute(table.insert(), noise)
    statements = []

    def record(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    refs = [FEATURE] + [{**FEATURE, "local_ref": f"missing:{index}"} for index in range(size - 1)]
    event.listen(store._relay_engine, "before_cursor_execute", record)
    try:
        response = _counts(client, refs)
    finally:
        event.remove(store._relay_engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == [_count_row(ref, int(ref == FEATURE)) for ref in refs]
    assert len(statements) == 1
    statement, parameters = statements[0]
    with store._relay_engine.connect() as db:
        plan = db.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
    assert any("SEARCH" in row[3] and "idx_relay_work_refs_lookup" in row[3] for row in plan), plan
    assert not any("SCAN relay_session_work_refs" in row[3] for row in plan), plan


def test_batch_counts_order_bounds_and_validation(client):
    _turn(client, structural_work_refs=[FEATURE])
    refs = [
        {"scope_ref": FEATURE["scope_ref"], "local_ref": f"item:{index}"}
        for index in range(199)
    ] + [FEATURE]
    response = _counts(client, refs)
    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["as_of"]).utcoffset() == timedelta(0)
    assert body == {
        "contract": "relay-work-ref-counts/v1",
        "as_of": body["as_of"], "recent_seconds": 86400,
        "counts": [
            _count_row(ref, int(ref == FEATURE)) for ref in refs
        ],
    }
    assert _counts(client, [FEATURE]).json()["counts"] == [
        _count_row(FEATURE, 1)
    ]
    for body in (
        {},
        {"references": []},
        {"references": refs + [BRANCH]},
        {"references": [FEATURE, FEATURE]},
        {"references": [FEATURE, {**FEATURE, "local_ref": FEATURE["local_ref"] + "\x00"}]},
        {"references": [{"scope_ref": "", "local_ref": "item"}]},
        {"references": [{"scope_ref": "scope", "local_ref": " password=sk-ant-api03-" + "x" * 40}]},
        {"references": [{**FEATURE, "work_ref": "unrequested"}]},
    ):
        response = client.post("/relay/work-refs/participant-counts", json=body)
        assert response.status_code == 422, (body, response.text)


def test_batch_counts_canonical_scope_case_and_lifecycle(client):
    composed = {"scope_ref": "scope:é", "local_ref": "item:é"}
    decomposed = {"scope_ref": "scope:e\u0301", "local_ref": "item:e\u0301"}
    case_variant = {"scope_ref": "scope:É", "local_ref": "item:é"}
    other_scope = {"scope_ref": "scope:other", "local_ref": "item:é"}
    assert _counts(client, [composed, decomposed]).status_code == 422
    first = _turn(client, session="first", structural_work_refs=[composed])
    assert _attach(client, composed, session="first").status_code == 200
    other_container = "git:example.test/team/other"
    admitted = client.post(
        "/relay/turn",
        json={
            "runtime": "claude-code",
            "session_ref": "second",
            "container_ref": other_container,
            "structural_work_refs": [composed, other_scope],
        },
    )
    assert admitted.status_code == 200, admitted.text
    assert _attach(client, case_variant, session="first").status_code == 200
    refs = [other_scope, case_variant, composed, BRANCH]
    expected = [1, 1, 2, 0]

    def assert_counts():
        result = _counts(client, refs)
        assert result.status_code == 200, result.text
        rows = result.json()["counts"]
        assert [row["participant_count"] for row in rows] == expected
        assert [{key: row[key] for key in ("scope_ref", "local_ref")} for row in rows] == refs
        assert all(row["participant_count"] == row["recent_participant_count"] + row["dormant_participant_count"] for row in rows)

    store = client.app.state.pallium_service._storage
    with store._relay_engine.connect() as connection:
        before = connection.execute(
            text("SELECT count(*) FROM relay_session_work_refs")
        ).scalar_one()
    assert_counts()
    with store._relay_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE relay_sessions SET state='unreachable', "
                "last_seen_at=:old WHERE id=:endpoint_id"
            ),
            {
                "old": datetime.now(timezone.utc) - timedelta(days=2),
                "endpoint_id": first["session"]["endpoint_id"],
            },
        )
    assert_counts()
    with store._relay_engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM relay_session_work_refs")
        ).scalar_one() == before
    assert _counts(client, [decomposed]).json()["counts"] == [
        _count_row(composed, 2, 1)
    ]

    detach = client.post(
        "/relay/sessions/work-refs/detach",
        json={
            "runtime": "codex",
            "session_ref": "first",
            "container_ref": CONTAINER,
            **composed,
        },
    )
    assert detach.status_code == 200
    assert detach.json()["structural_remains"] is True
    assert_counts()
    assert client.post(
        "/relay/turn",
        json={
            "runtime": "codex",
            "session_ref": "first",
            "container_ref": CONTAINER,
            "structural_work_refs": [],
        },
    ).status_code == 200
    expected[2] = 1
    assert_counts()
    assert client.post(
        "/relay/sessions/close",
        json={
            "runtime": "claude-code",
            "session_ref": "second",
            "container_ref": other_container,
        },
    ).status_code == 200
    expected[0] = expected[2] = 0
    assert_counts()
    assert client.post(
        "/relay/turn",
        json={
            "runtime": "claude-code",
            "session_ref": "second",
            "container_ref": other_container,
        },
    ).status_code == 200
    expected[0] = expected[2] = 1
    assert_counts()
    assert first["session"]["endpoint_id"] not in str(_counts(client, refs).json())


def test_batch_counts_unavailable_and_storage_errors_are_not_zero(client, monkeypatch):
    _turn(client, structural_work_refs=[FEATURE])
    store = client.app.state.pallium_service._storage
    with monkeypatch.context() as patch:
        patch.setattr(store, "relay_work_ref_participant_counts", None)
        assert _counts(client, [FEATURE]).status_code == 501

    def fail(**_kwargs):
        raise RuntimeError("database unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(store, "relay_work_ref_participant_counts", fail)
        with pytest.raises(RuntimeError, match="database unavailable"):
            _counts(client, [FEATURE])
    assert _counts(client, [FEATURE]).json()["counts"][0]["participant_count"] == 1

def test_batch_counts_do_not_write_relay_state(client):
    _turn(client, structural_work_refs=[FEATURE])
    store = client.app.state.pallium_service._storage
    engine = store._relay_engine

    def snapshot():
        with engine.connect() as connection:
            return tuple(
                tuple(tuple(row) for row in connection.execute(text(query)))
                for query in (
                    "SELECT * FROM relay_sessions ORDER BY id",
                    "SELECT * FROM relay_session_work_refs ORDER BY endpoint_id, work_ref, origin",
                    "SELECT * FROM relay_messages ORDER BY id",
                    "SELECT * FROM relay_deliveries ORDER BY id",
                )
            )

    before = snapshot()
    writes = []

    def record_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record_write)
    try:
        for _ in range(3):
            response = _counts(client, [FEATURE, BRANCH])
            assert response.status_code == 200, response.text
            assert [row["participant_count"] for row in response.json()["counts"]] == [1, 0]
    finally:
        event.remove(engine, "before_cursor_execute", record_write)
    assert writes == []
    assert snapshot() == before


def test_batch_counts_reflect_attach_detach_before_aggregate_read(client):
    _turn(client)
    assert _attach(client, FEATURE).status_code == 200
    store = client.app.state.pallium_service._storage
    relay = RelayService(store)
    changed = False

    def change_before_aggregate(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal changed
        if changed or "relay_session_work_refs" not in statement or not statement.lstrip().upper().startswith("SELECT"):
            return
        changed = True
        relay.detach_work_ref(runtime="codex", session_ref="worker", container_ref=CONTAINER, **FEATURE)
        relay.attach_work_ref(runtime="codex", session_ref="worker", container_ref=CONTAINER, **BRANCH)

    event.listen(store._relay_engine, "before_cursor_execute", change_before_aggregate)
    try:
        response = _counts(client, [FEATURE, BRANCH])
    finally:
        event.remove(store._relay_engine, "before_cursor_execute", change_before_aggregate)
    assert changed is True
    assert response.status_code == 200, response.text
    assert [row["participant_count"] for row in response.json()["counts"]] == [0, 1]
