from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, text

from core.relay import RelayService
from core.work_ref import readable_work_ref


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


def test_alias_transfer_does_not_transfer_associations_and_reopen_retains_them(client):
    ticket = {
        "scope_ref": "tracker:v1:example.test#relay",
        "local_ref": "ticket:owner",
    }
    first = _turn(client, session="first")
    second = _turn(client, session="second")
    assert _attach(client, ticket, session="first").status_code == 200
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

    assert client.post(
        "/relay/sessions/close",
        json={
            "runtime": "codex",
            "session_ref": "first",
            "container_ref": CONTAINER,
        },
    ).status_code == 200
    reopened = _turn(client, session="first")
    assert reopened["session"]["endpoint_id"] == first["session"]["endpoint_id"]
    assert {row["local_ref"] for row in _list(client, session="first")["work_refs"]} == {
        ticket["local_ref"]
    }

def test_detach_changes_future_history_but_not_captured_snapshot(client, drain_queue):
    _turn(client, session="history")
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

def test_participant_lookup_keeps_page_full_during_concurrent_final_detach(client):
    for index in range(6):
        session = f"worker-{index}"
        _turn(client, session=session)
        assert _attach(client, FEATURE, session=session).status_code == 200
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    detached = False

    def detach_before_participant_projection(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        nonlocal detached
        if detached or "relay_session_work_refs" not in statement:
            return
        detached = True
        relay.detach_work_ref(
            runtime="codex",
            session_ref="worker-5",
            container_ref=CONTAINER,
            **FEATURE,
        )

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

    assert detached is True
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
