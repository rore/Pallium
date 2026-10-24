"""Public Hermes hooks + real HTTP; requires composed f24 role-history schema.

These assertions deliberately do not skip on the older service: authoring them on
1bc is not evidence of role readback until the owner composes the shared change.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib

import pytest

from integrations.hermes.turn_capture import user_source_id
from tests.test_hermes_history import history_plugin
from tests.test_hermes_project_scope import _project, _repo, project_plugin
from tests.test_hermes_relay_plugin import (
    SCOPE, _observe_request, _plugin_wake, mcp_plugin_context, plugin_context,
)

TEXT = "role history marker café 漢字 🌍"


@pytest.fixture(params=["cwd", "fixed"])
def role_plugin(request, client, tmp_path, monkeypatch):
    if request.param == "cwd":
        module, ctx, native_pre, create, _calls, _settings = request.getfixturevalue("project_plugin")
        root = _repo(tmp_path, "roles", actor="role-actor")
        scope = {"container_ref": _project("roles"), "actor_ref": "role-actor"}
    else:
        module, ctx, _config, _writes = request.getfixturevalue("history_plugin")
        _, create, _ = request.getfixturevalue("plugin_context")
        scope = {**SCOPE, "actor_ref": "hermes-test"}
    data = {"mode": request.param, "module": module, "ctx": ctx, "create": create,
            "scope": scope, "calls": [], "attempts": []}
    http = module._json_request

    def observe(base, method, path, **kwargs):
        data["attempts"].append((method, path, copy.deepcopy(kwargs)))
        result = http(base, method, path, **kwargs)
        data["calls"].append((method, path, copy.deepcopy(kwargs), copy.deepcopy(result)))
        return result

    monkeypatch.setattr(module, "_json_request", observe)

    def pre(turn, text=TEXT, session="role-session"):
        rows = [{"role": "user", "content": text, "message_uid": "user-" + turn}]
        if data["mode"] == "cwd":
            return native_pre(str(root), session=session, turn=turn, message=text,
                              history=rows, context=data["ctx"])
        return data["ctx"].hooks["pre_llm_call"](
            session_id=session, turn_id=turn, user_message=text, conversation_history=rows)

    data["pre"] = pre
    assert pre("seed", "seed")
    data["calls"].clear()
    data["attempts"].clear()
    return data


def _name(client, data, alias, session="role-session", replace=False):
    response = client.post("/relay/sessions/name", json={
        "runtime": "hermes", "session_ref": session, "container_ref": data["scope"]["container_ref"],
        "alias": alias, "replace_existing": replace,
    })
    assert response.status_code == 200, response.text


def _post(data, turn, text=TEXT, session="role-session"):
    rows = [{"role": "user", "content": text, "message_uid": "user-" + turn},
            {"role": "assistant", "content": text + " answer", "message_uid": "answer-" + turn}]
    data["ctx"].hooks["post_llm_call"](
        session_id=session, turn_id=turn, user_message=text,
        assistant_response=rows[-1]["content"], conversation_history=rows)


def _search(client, data, name=None, **overrides):
    body = {**data["scope"], "text": "role history marker", "source_type": "hermes",
            "visibility": "private", "source_only": True, "limit": 50,
            "trigger_origin": "agent_pull", "active_session_ref": "reader"}
    if name is not None:
        body["relay_name"] = name
    body.update(overrides)
    response = client.post("/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _writes(data, path="/items"):
    return [row for row in data["calls"] if row[0:2] == ("POST", path)]


def _attempts(data):
    return [row for row in data["attempts"] if row[0:2] == ("POST", "/items")]


def _unkeyed_legacy_pair(data, turn):
    body = _attempts(data)[-1][2]["body"]
    assert [row["role"] for row in body] == ["user", "assistant"]
    assert all("source_turn_id" not in row and "relay_name" not in row for row in body)
    assert [row["source_id"] for row in body] == [
        hashlib.sha256((data["scope"]["container_ref"] + "\0role-session\0" + uid).encode()).hexdigest()
        for uid in ("user-" + turn, "answer-" + turn)]
    return body


def _reload(data):
    old = data["ctx"]
    for cleanup in old.cleanups:
        cleanup()
    data["ctx"] = data["create"](old.state)


@pytest.mark.parametrize("alias,expected", [
    ("a", "named"), ("a" * 32, "named"), ("a" * 33, "unavailable"),
    ("工程師", "unavailable"), ("Bad Name", "unavailable"), (None, "unnamed"),
    ("missing", "unavailable"),
])
def test_public_hook_role_snapshot_boundaries(client, role_plugin, monkeypatch, alias, expected):
    data = role_plugin
    http = data["module"]._json_request

    def response_fault(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if method == "POST" and path == "/relay/turn":
            if alias == "missing":
                result["session"].pop("alias", None)
            else:
                result["session"]["alias"] = alias
        return result

    monkeypatch.setattr(data["module"], "_json_request", response_fault)
    assert data["pre"]("boundary")
    if data["mode"] == "fixed":
        assert not _writes(data, "/item-and-query") and not _writes(data)
    _post(data, "boundary")
    rows = _search(client, data)["results"]
    assert {row["role"] for row in rows} == {"user", "assistant"}
    assert all(row["relay_attribution_state"] == expected for row in rows)
    assert all(row["relay_name"] == (alias if expected == "named" else None) for row in rows)
    correlation = user_source_id(data["ctx"].profile_name, data["scope"]["container_ref"],
                                 "role-session", "boundary")
    bodies = _writes(data)[-1][2]["body"]
    assert all(row["source_turn_id"] == correlation for row in bodies)
    assert "relay_name" not in bodies[1] and "relay_attribution_state" not in bodies[1]
    if data["mode"] == "fixed":
        assert [row["source_id"] for row in bodies] == [
            hashlib.sha256((data["scope"]["container_ref"] + "\0role-session\0" + uid).encode()).hexdigest()
            for uid in ("user-boundary", "answer-boundary")]
    else:
        assert bodies[0]["source_id"] == correlation


@pytest.mark.parametrize("reload", [False, True])
def test_public_turn_snapshot_survives_takeover_repeat_and_next_turn(client, role_plugin, reload):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("first")
    if data["mode"] == "cwd":
        before = _search(client, data, "planner")["results"]
        assert len(before) == 1 and before[0]["role"] == "user"
    else:
        assert not _writes(data, "/item-and-query") and not _writes(data)
    assert data["pre"]("peer-seed", "peer", session="peer-session")
    _name(client, data, "planner", session="peer-session", replace=True)
    if reload:
        _reload(data)
    assert data["pre"]("first")
    _post(data, "first")
    _post(data, "first")
    result = _search(client, data, "planner")
    rows = result["results"]
    assert len(rows) == 2 and {row["role"] for row in rows} == {"user", "assistant"}
    assert all(row["thread_ref"] == "role-session" and row["relay_name"] == "planner" for row in rows)
    for row in rows:
        expanded = client.get(f"/source/{row['source_item_id']}/context", params={
            "container_ref": data["scope"]["container_ref"], "query_actor_ref": data["scope"]["actor_ref"],
            "query_visibility": "private", "active_session_ref": "reader",
            "parent_lookup_id": result["lookup_event_id"],
        })
        assert expanded.status_code == 200, expanded.text
        assert "漢字" in expanded.text
        assert client.get(f"/source/{row['source_item_id']}/context", params={
            "container_ref": "git:example.test/team/other", "query_visibility": "private",
        }).status_code == 404
    data["ctx"].hooks["on_session_end"](session_id="role-session", turn_id="first")
    assert data["pre"]("next", TEXT + " next")
    _post(data, "next", TEXT + " next")
    assert len(_search(client, data, "planner")["results"]) == 2
    assert any(row["relay_attribution_state"] == "unnamed" for row in _search(client, data)["results"])


@pytest.mark.parametrize("uncertain", [False, True])
def test_capture_failure_retry_never_replaces_start_snapshot(client, role_plugin, monkeypatch, uncertain):
    data = role_plugin
    _name(client, data, "first-name")
    http = data["module"]._json_request
    target = "/item-and-query" if data["mode"] == "cwd" else "/items"
    failed = []

    def fail_once(base, method, path, **kwargs):
        if method == "POST" and path == target and not failed:
            failed.append(True)
            if uncertain:
                http(base, method, path, **kwargs)
            raise OSError("isolated capture response unavailable")
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(data["module"], "_json_request", fail_once)
    assert data["pre"]("failure")
    if data["mode"] == "fixed":
        _post(data, "failure")
    _name(client, data, "later-name")
    _reload(data)
    assert data["pre"]("failure")
    _post(data, "failure")
    rows = _search(client, data, "first-name")["results"]
    assert len(rows) == 2 and all(row["relay_name"] == "first-name" for row in rows)
    assert _search(client, data, "later-name")["results"] == []


def test_durable_end_evidence_rejects_late_a_after_b_end(client, role_plugin):
    data = role_plugin
    _name(client, data, "first-name")
    for turn in ("a", "b"):
        assert data["pre"](turn, TEXT + turn)
        _post(data, turn, TEXT + turn)
        data["ctx"].hooks["on_session_end"](session_id="role-session", turn_id=turn)
    _reload(data)
    _name(client, data, "later-name")
    original = {row["source_item_id"] for row in _search(client, data, "first-name")["results"]}
    count, attempts = len(_writes(data)), len(_attempts(data))
    assert data["pre"]("a", TEXT + "a") is None
    _post(data, "a", TEXT + "a")
    assert len(_writes(data)) == count
    if data["mode"] == "fixed":
        assert len(_attempts(data)) == attempts + 1
        body = _unkeyed_legacy_pair(data, "a")
        # The producer preserves raw capture; the shared immutable keyed-row
        # contract correctly refuses its unkeyed retry, without overwriting it.
        response = client.post("/items", json=body)
        assert response.status_code == 409, response.text
    else:
        assert len(_attempts(data)) == attempts
    assert {row["source_item_id"] for row in _search(client, data, "first-name")["results"]} == original
    assert _search(client, data, "later-name")["results"] == []


def test_concurrent_repeated_start_uses_one_capture_snapshot(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: data["pre"]("concurrent"), range(2)))
    assert all(outcomes)
    _name(client, data, "renamed")
    _post(data, "concurrent")
    rows = _search(client, data, "planner")["results"]
    assert len(rows) == 2 and all(row["relay_name"] == "planner" for row in rows)
    if data["mode"] == "cwd":
        assert len(_writes(data, "/item-and-query")) == 1
    else:
        assert not _writes(data, "/item-and-query")


def test_reload_at_capture_boundary_keeps_original_snapshot(client, role_plugin, monkeypatch):
    data = role_plugin
    _name(client, data, "planner")
    if data["mode"] == "cwd":
        http = data["module"]._json_request
        boundary = []

        def reload_before_http(base, method, path, **kwargs):
            if method == "POST" and path == "/item-and-query" and not boundary:
                boundary.append(copy.deepcopy(kwargs["body"]))
                _reload(data)
                assert data["pre"]("boundary") is None  # Existing pending-authority fence.
                _name(client, data, "renamed")
            return http(base, method, path, **kwargs)

        monkeypatch.setattr(data["module"], "_json_request", reload_before_http)
        assert data["pre"]("boundary") is None  # Old plugin was actually unloaded.
        assert boundary[0]["relay_name"] == "planner"
        assert data["pre"]("boundary") is None
        pending = [value for value in data["ctx"].state.values.values()
                   if isinstance(value, dict) and value.get("state") == "pending" and "capture" in value]
        assert len(pending) == 1 and pending[0]["capture"]["snapshot"] == ["named", "planner"]
        assert pending[0]["capture"]["source_turn_id"] == boundary[0]["source_turn_id"]
    else:
        assert data["pre"]("boundary")
        assert not _writes(data, "/item-and-query") and not _writes(data)
        _reload(data)
        _name(client, data, "renamed")
        assert data["pre"]("boundary")
    count = len(_attempts(data))
    _post(data, "boundary")
    rows = _search(client, data, "planner")["results"]
    if data["mode"] == "cwd":
        assert len(_attempts(data)) == count and len(rows) == 1 and rows[0]["role"] == "user"
    else:
        assert len(rows) == 2
    assert _search(client, data, "renamed")["results"] == []


@pytest.mark.parametrize("damage", ["missing", "key", "snapshot", "list_state", "dict_state"])
def test_missing_or_invalid_old_snapshot_is_never_refreshed(client, role_plugin, damage):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("old")
    for key, value in list(data["ctx"].state.values.items()):
        if isinstance(value, dict) and "capture" in value:
            updated = copy.deepcopy(value)
            if damage == "missing":
                updated.pop("capture")
            elif damage == "key":
                updated["capture"]["source_turn_id"] = "foreign-key"
            elif damage in {"list_state", "dict_state"}:
                updated["capture"]["snapshot"] = [[] if damage == "list_state" else {}, None]
            else:
                updated["capture"]["snapshot"] = ["named", "工程師"]
            data["ctx"].state.set(key, updated)
    _reload(data)
    _name(client, data, "renamed")
    data["pre"]("old")
    _post(data, "old")
    assert _search(client, data, "renamed")["results"] == []
    assert all(row["relay_name"] != "renamed" for row in _search(client, data)["results"])


def test_fixed_missing_start_and_synthetic_wake_omit_key(client, history_plugin, plugin_context):
    _module, ctx, _config, writes = history_plugin
    data = {"ctx": ctx}
    ctx.hooks["pre_llm_call"](session_id="role-session", turn_id="seed", user_message="seed")
    _post(data, "missing")
    assert all("source_turn_id" not in row for row in writes[-1][0])
    _, create, _ = plugin_context
    wake_ctx, marker, _message = _plugin_wake(client, create)
    placeholder = wake_ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)
    _observe_request(wake_ctx, {"messages": [{"role": "user", "content": marker + "\n" + placeholder["context"]}]})
    _post({"ctx": wake_ctx}, "wake", marker, "ses_שלום")
    rows = writes[-1][0]
    assert len(rows) == 1 and rows[0]["role"] == "assistant"
    assert "source_turn_id" not in rows[0]

@pytest.mark.parametrize("field,value", [
    ("container_ref", "git:example.test/team/other"),
    ("endpoint_id", "relay-session-" + "f" * 32),
    ("actor_ref", "other-actor"), ("user_digest", "0" * 64),
])
def test_foreign_saved_turn_cannot_carry_role_attribution(client, role_plugin, field, value):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("guarded")
    for key, saved in list(data["ctx"].state.values.items()):
        if isinstance(saved, dict) and "capture" in saved:
            data["ctx"].state.set(key, {**saved, field: value})
    _reload(data)
    count, attempts = len(_writes(data)), len(_attempts(data))
    assert data["pre"]("guarded") is None
    _post(data, "guarded")
    if data["mode"] == "fixed":
        assert len(_attempts(data)) == attempts + 1 and len(_writes(data)) == count + 1
        _unkeyed_legacy_pair(data, "guarded")
        rows = _search(client, data)["results"]
        assert len(rows) == 2 and all(row["relay_attribution_state"] == "unavailable" for row in rows)
        assert all(row["relay_name"] is None for row in rows)
    else:
        assert len(_attempts(data)) == attempts and len(_writes(data)) == count


def test_other_session_cannot_reuse_original_turn_snapshot(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("same-turn")
    assert data["pre"]("seed", "peer", session="peer-session")
    _name(client, data, "peer", session="peer-session")
    assert data["pre"]("same-turn", session="peer-session")
    _post(data, "same-turn", session="peer-session")
    _post(data, "same-turn")
    planner = _search(client, data, "planner")["results"]
    peer = _search(client, data, "peer")["results"]
    assert len(planner) == len(peer) == 2
    assert all(row["thread_ref"] == "role-session" for row in planner)
    assert all(row["thread_ref"] == "peer-session" for row in peer)
    assert {row["source_item_id"] for row in planner}.isdisjoint(row["source_item_id"] for row in peer)


def test_unloaded_callbacks_cannot_activate_saved_role_snapshot(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("unload")
    old = data["ctx"]
    for cleanup in old.cleanups:
        cleanup()
    count = len(_writes(data))
    assert data["pre"]("unload") is None
    _post(data, "unload")
    assert len(_writes(data)) == count
    data["ctx"] = data["create"](old.state)
    assert data["pre"]("unload")
    _post(data, "unload")
    assert len(_search(client, data, "planner")["results"]) == 2

@pytest.mark.parametrize("field,value", [
    ("session_id", []), ("session_id", {}), ("turn_id", []), ("turn_id", {}),
])
def test_public_hook_rejects_unhashable_identity_before_lock(role_plugin, field, value):
    data = role_plugin
    identity = {"session_id": "role-session", "turn_id": "invalid", field: value}
    count = len(data["calls"])
    assert data["ctx"].hooks["pre_llm_call"](**identity, user_message=TEXT) is None
    data["ctx"].hooks["post_llm_call"](
        **identity, user_message=TEXT, assistant_response=TEXT + " answer",
        conversation_history=[{"role": "user", "content": TEXT, "message_uid": "invalid-user"},
                              {"role": "assistant", "content": TEXT + " answer", "message_uid": "invalid-answer"}])
    assert len(data["calls"]) == count


def _reject_accepted_turn_response(client, data, monkeypatch, field, value):
    _name(client, data, "planner")
    before = copy.deepcopy(data["ctx"].state.values)
    snapshots = {key: row for key, row in before.items() if isinstance(row, dict) and "capture" in row}
    authorities = {key: row for key, row in before.items() if key.startswith("session:")}
    http = data["module"]._json_request
    responses = []

    def malformed_response(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if method == "POST" and path == "/relay/turn":
            result["session"]["alias"] = "forged-role"
            if field == "session":
                result["session"] = value
            elif field == "missing:session":
                result.pop("session")
            elif field.startswith("missing:"):
                result["session"].pop(field.split(":", 1)[1], None)
            else:
                result["session"][field] = value
            responses.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(data["module"], "_json_request", malformed_response)
    assert data["pre"]("refused-response") is None
    assert len(responses) == 1  # Direct ordinary POST response, never cached GET.
    saved = data["ctx"].state.values
    assert {key: row for key, row in saved.items() if isinstance(row, dict) and "capture" in row} == snapshots
    assert {key: row for key, row in saved.items() if key.startswith("session:")} == authorities
    assert not [row for row in data["attempts"] if row[0:2] == ("POST", "/item-and-query")]
    if data["mode"] == "cwd":
        assert any(key.startswith("transition:") and row is not None for key, row in saved.items())
        assert data["pre"]("refused-response") is None
        assert len(responses) == 1  # Pending/uncertain admission cannot repair the old turn.
    attempts = len(_attempts(data))
    _post(data, "refused-response")
    rows = _search(client, data)["results"]
    if data["mode"] == "fixed":
        assert len(_attempts(data)) == attempts + 1
        _unkeyed_legacy_pair(data, "refused-response")
        assert len(rows) == 2 and {row["role"] for row in rows} == {"user", "assistant"}
        assert all(row["relay_name"] is None and row["relay_attribution_state"] == "unavailable" for row in rows)
    else:
        assert len(_attempts(data)) == attempts and rows == []
    assert _search(client, data, "forged-role")["results"] == []
    assert _search(client, data, "planner")["results"] == []


@pytest.mark.parametrize("field,value", [
    ("runtime", "codex"), ("session_ref", "foreign-session"),
    ("container_ref", "git:example.test/team/foreign"),
    ("missing:endpoint_id", None), ("endpoint_id", ""),
    ("state", "closed"), ("destination_health", "unreachable"),
    ("missing:session", None), ("session", None), ("session", []),
])
def test_direct_turn_response_identity_fault_never_freezes_role(client, role_plugin, monkeypatch, field, value):
    _reject_accepted_turn_response(client, role_plugin, monkeypatch, field, value)


@pytest.mark.parametrize("role_plugin", ["cwd"], indirect=True)
@pytest.mark.parametrize("field,value", [
    ("missing:guarded_lifecycle", None), ("guarded_lifecycle", False),
    ("missing:scope_generation", None), ("scope_generation", True),
    ("scope_generation", -1), ("scope_generation", 1.5),
])
def test_direct_automatic_turn_response_requires_guarded_generation(client, role_plugin, monkeypatch, field, value):
    _reject_accepted_turn_response(client, role_plugin, monkeypatch, field, value)
