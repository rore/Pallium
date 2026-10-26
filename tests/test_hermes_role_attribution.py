"""Fixed-profile Hermes role attribution through public hooks and History."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from tests.test_hermes_history import history_plugin
from tests.test_hermes_relay_plugin import SCOPE, mcp_plugin_context, plugin_context

TEXT = "role history marker café 漢字 🌍"


@pytest.fixture
def role_plugin(client, history_plugin, plugin_context):
    module, ctx, _config, writes = history_plugin
    _, create, _ = plugin_context
    data = {"module": module, "ctx": ctx, "create": create, "writes": writes,
            "scope": {**SCOPE, "actor_ref": "hermes-test"}}

    def pre(turn, text=TEXT, session="role-session"):
        return data["ctx"].hooks["pre_llm_call"](
            session_id=session, turn_id=turn, user_message=text,
            conversation_history=[{"role": "user", "content": text, "message_uid": "user-" + turn}])

    data["pre"] = pre
    assert pre("seed", "seed")
    writes.clear()
    return data


def _name(client, data, alias, session="role-session", replace=False):
    response = client.post("/relay/sessions/name", json={
        "runtime": "hermes", "session_ref": session,
        "container_ref": data["scope"]["container_ref"],
        "alias": alias, "replace_existing": replace,
    })
    assert response.status_code == 200, response.text


def _post(data, turn, text=TEXT, assistant=None, session="role-session",
          user_uid=None, assistant_uid=None):
    assistant = text + " answer" if assistant is None else assistant
    rows = [{"role": "user", "content": text, "message_uid": user_uid or "user-" + turn},
            {"role": "assistant", "content": assistant,
             "message_uid": assistant_uid or "answer-" + turn}]
    data["ctx"].hooks["post_llm_call"](
        session_id=session, turn_id=turn, user_message=text,
        assistant_response=assistant, conversation_history=rows)
    return rows


def _search(client, data, name=None):
    body = {**data["scope"], "text": "role history marker", "source_type": "hermes",
            "visibility": "private", "source_only": True, "limit": 50,
            "trigger_origin": "agent_pull", "active_session_ref": "reader"}
    if name is not None:
        body["relay_name"] = name
    response = client.post("/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _reload(data):
    old = data["ctx"]
    for cleanup in old.cleanups:
        cleanup()
    data["ctx"] = data["create"](old.state)


@pytest.mark.parametrize("alias,expected", [
    ("planner", "named"), ("a" * 32, "named"), ("a" * 33, "unavailable"),
    ("工程師", "unavailable"), (None, "unnamed"), ("missing", "unavailable"),
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
    _post(data, "boundary")
    rows = _search(client, data, alias if expected == "named" else None)
    assert len(rows) == 2 and {row["role"] for row in rows} == {"user", "assistant"}
    assert all(row["relay_attribution_state"] == expected for row in rows)
    assert all(row["relay_name"] == (alias if expected == "named" else None) for row in rows)
    body = data["writes"][-1][0]
    assert body[0]["source_turn_id"] == body[1]["source_turn_id"]
    assert "relay_name" not in body[1]
    assert "relay_attribution_state" not in body[1]


@pytest.mark.parametrize("reload", [False, True])
def test_public_turn_snapshot_survives_rename_retry_and_next_turn(client, role_plugin, reload):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("first")
    _name(client, data, "later-name")
    if reload:
        _reload(data)
    assert data["pre"]("first")
    _post(data, "first")
    assert len(_search(client, data, "planner")) == 2
    assert _search(client, data, "later-name") == []

    data["ctx"].hooks["on_session_end"](session_id="role-session", turn_id="first")
    assert data["pre"]("next", TEXT + " next")
    _post(data, "next", TEXT + " next")
    later = _search(client, data, "later-name")
    assert len(later) == 2 and all(row["relay_name"] == "later-name" for row in later)


def test_same_turn_keeps_distinct_assistant_outputs(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("outputs")
    _post(data, "outputs", assistant=TEXT + " first output", assistant_uid="assistant-1")
    _post(data, "outputs", assistant=TEXT + " second output", assistant_uid="assistant-2")
    rows = _search(client, data, "planner")
    assert len(rows) == 3
    assert {row["role"] for row in rows} == {"user", "assistant"}
    first, second = (entry[0] for entry in data["writes"][-2:])
    assert first[0]["source_turn_id"] == first[1]["source_turn_id"]
    assert first[0]["source_turn_id"] == second[0]["source_turn_id"] == second[1]["source_turn_id"]
    assert {first[1]["content"], second[1]["content"]} == {
        TEXT + " first output", TEXT + " second output"}
    assert first[1]["source_id"] != second[1]["source_id"]


@pytest.mark.parametrize("field,value", [
    ("profile", "other-profile"), ("container_ref", "git:example.test/team/other"),
    ("actor_ref", "other-actor"), ("session_ref", "other-session"),
    ("turn_id", "other-turn"), ("endpoint_id", "relay-session-" + "f" * 32),
    ("user_digest", "0" * 64),
])
def test_foreign_saved_turn_cannot_carry_role_attribution(client, role_plugin, field, value):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("foreign")
    slot, saved = next((key, value) for key, value in data["ctx"].state.values.items()
                       if isinstance(value, dict) and value.get("turn_id") == "foreign"
                       and "capture" in value)
    saved = copy.deepcopy(saved)
    saved[field] = value
    data["ctx"].state.set(slot, saved)
    _post(data, "foreign")
    assert _search(client, data, "planner") == []


def test_missing_saved_snapshot_is_not_refreshed_after_rename(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("missing-capture")
    slot, saved = next((key, value) for key, value in data["ctx"].state.values.items()
                       if isinstance(value, dict) and value.get("turn_id") == "missing-capture"
                       and "capture" in value)
    saved = copy.deepcopy(saved)
    saved.pop("capture")
    data["ctx"].state.set(slot, saved)
    _reload(data)
    _name(client, data, "later-name")
    assert data["pre"]("missing-capture")
    _post(data, "missing-capture")
    assert _search(client, data, "planner") == []
    assert _search(client, data, "later-name") == []


def test_failed_first_registration_cannot_refresh_name_on_same_turn_retry(
        client, role_plugin, monkeypatch):
    data = role_plugin
    http = data["module"]._json_request
    failed = []

    def fail_first_registration(base, method, path, **kwargs):
        if method == "POST" and path == "/relay/turn" and not failed:
            failed.append(True)
            raise OSError("Relay turn response unavailable")
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(data["module"], "_json_request", fail_first_registration)
    assert data["pre"]("retry-after-failure") is None
    marker = next(value for value in data["ctx"].state.values.values()
                  if isinstance(value, dict) and value.get("turn_id") == "retry-after-failure")
    assert marker["state"] == "unavailable"

    _name(client, data, "later-name")
    assert data["pre"]("retry-after-failure") is None
    _post(data, "retry-after-failure")
    rows = data["writes"][-1][0]
    assert all("source_turn_id" not in row and "relay_name" not in row for row in rows)
    assert _search(client, data, "later-name") == []


def test_session_end_fences_late_retry_after_reload(client, role_plugin):
    data = role_plugin
    _name(client, data, "planner")
    assert data["pre"]("ended")
    _post(data, "ended")
    original = {row["source_item_id"] for row in _search(client, data, "planner")}
    data["ctx"].hooks["on_session_end"](session_id="role-session", turn_id="ended")
    _reload(data)
    _name(client, data, "later-name")
    assert data["pre"]("ended") is None
    _post(data, "ended")
    assert {row["source_item_id"] for row in _search(client, data, "planner")} == original
    assert _search(client, data, "later-name") == []


def test_user_source_turn_id_uses_shared_opaque_contract(role_plugin):
    data = role_plugin
    assert data["pre"]("source-id")
    value = next(value for value in data["ctx"].state.values.values()
                 if isinstance(value, dict) and value.get("turn_id") == "source-id")
    encoded = json.dumps(
        [data["ctx"].profile_name, data["scope"]["container_ref"], "role-session", "source-id", "user"],
        ensure_ascii=False)
    expected = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert value["capture"]["source_turn_id"] == expected
