"""Hermes public completion hook to governed History HTTP caller contracts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy

import pytest

from tests.test_hermes_relay_plugin import SCOPE, _plugin_wake, mcp_plugin_context, plugin_context


@pytest.fixture
def history_plugin(client, plugin_context, mcp_plugin_context, monkeypatch):
    module, _create, _config = plugin_context
    create, config, _calls = mcp_plugin_context
    writes = []
    request = module._json_request

    def http(base, method, path, **kwargs):
        result = request(base, method, path, **kwargs)
        if method == "POST" and path == "/items":
            writes.append((copy.deepcopy(kwargs["body"]), result))
        return result

    monkeypatch.setattr(module, "_json_request", http)
    return module, create(), config, writes


def _pair(user="history marker: café 漢字 🌍", assistant="history answer: café 漢字 🌍"):
    return [
        {"role": "user", "content": user, "message_uid": "a" * 32},
        {"role": "assistant", "content": assistant, "message_uid": "b" * 32},
    ]


def _capture(ctx, rows=None, session="session_שלום", turn="turn_1", **overrides):
    rows = _pair() if rows is None else rows
    args = {"session_id": session, "turn_id": turn, "user_message": rows[0]["content"],
            "assistant_response": rows[-1]["content"], "conversation_history": rows}
    args.update(overrides)
    return ctx.hooks["post_llm_call"](**args)


def _register(ctx, session="session_שלום"):
    ctx.hooks["pre_llm_call"](session_id=session, turn_id="register", user_message="hello")


def _context(client, source_id, **overrides):
    params = {**SCOPE, "query_visibility": "private", "active_session_ref": "later-session"}
    params.update(overrides)
    return client.get(f"/source/{source_id}/context", params=params)


def _query(client, **overrides):
    body = {**SCOPE, "visibility": "private", "active_session_ref": "later-session",
            "source_only": True, "trigger_origin": "agent_pull", "text": "history marker",
            "limit": 20}
    body.update(overrides)
    response = client.post("/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_completion_capture_scope_redaction_and_forget_non_resurrection(client, history_plugin):
    _module, ctx, _config, writes = history_plugin
    _register(ctx)
    rows = _pair(user="history marker café Bearer sk-private-value", assistant="history answer 漢字 🌍")
    _capture(ctx, rows)
    _capture(ctx, rows)
    assert len(writes) == 2
    ids = [row["source_item_id"] for row in writes[0][1]]
    assert ids == [row["source_item_id"] for row in writes[1][1]]
    assert len(set(ids)) == 2
    for row in writes[0][0]:
        assert row["container_ref"] == SCOPE["container_ref"]
        assert row["thread_ref"] == "session_שלום"
        assert row["actor_ref"] == "hermes-test"
        assert row["agent_ref"] == row["source_type"] == "hermes"
        assert row["visibility"] == "private"
        assert row["metadata"]["capture_stage"] == "post_llm_call"
        assert row["metadata"]["hermes_turn_id"] == "turn_1"
    expanded = _context(client, ids[0])
    assert expanded.status_code == 200, expanded.text
    assert "sk-private-value" not in expanded.text
    assert "[REDACTED]" in expanded.text
    assert "漢字" in expanded.text
    assert _context(client, ids[0], container_ref="git:example.test/team/other").status_code == 404
    assert ids[0] in {row["source_item_id"] for row in _query(client)["results"]}
    forgotten = client.post("/source/forget", json={"source_item_id": ids[0], "reason": "test"})
    assert forgotten.status_code == 200, forgotten.text
    _capture(ctx, rows)
    assert [row["source_item_id"] for row in writes[-1][1]] == ids
    assert _context(client, ids[0]).status_code == 404
    assert ids[0] not in {row["source_item_id"] for row in _query(client)["results"]}


def test_capture_only_current_pair_and_hook_observation_not_host_commit(client, history_plugin):
    _module, ctx, _config, writes = history_plugin
    rows = _pair()
    # Hermes can emit this public callback after a failed native transcript flush.
    # Its private marker is neither a prerequisite nor evidence in Pallium's source.
    for row in rows:
        row["_db_persisted"] = False
    old = [{"role": "user", "content": "old untracked text", "message_uid": "c" * 32},
           {"role": "assistant", "content": "old untracked answer", "message_uid": "d" * 32}]
    _capture(ctx, rows, conversation_history=old + rows)
    assert len(writes) == 1
    assert len(writes[0][0]) == 2
    assert {row["metadata"]["hermes_message_uid"] for row in writes[0][0]} == {"a" * 32, "b" * 32}
    assert all("_db_persisted" not in row["metadata"] for row in writes[0][0])
    assert all(row["metadata"]["capture_stage"] == "post_llm_call" for row in writes[0][0])
    assert _context(client, writes[0][1][0]["source_item_id"]).status_code == 200


@pytest.mark.parametrize("size,accepted", [(0, False), (1, True), (20_000, True), (20_001, False)])
def test_capture_text_boundaries(history_plugin, size, accepted):
    _module, ctx, _config, writes = history_plugin
    _capture(ctx, _pair(user="é" * size))
    assert bool(writes) is accepted
    if accepted:
        assert writes[0][0][0]["content"] == "é" * size


@pytest.mark.parametrize("field,value", [
    ("session_id", ""), ("session_id", "wrong\n"), ("session_id", "x" * 256),
    ("turn_id", ""), ("turn_id", "x" * 256), ("conversation_history", None),
    ("conversation_history", []), ("user_message", "different user"),
    ("assistant_response", "different answer"),
])
def test_capture_rejects_missing_or_conflicting_callback_identity(history_plugin, field, value):
    _module, ctx, _config, writes = history_plugin
    _capture(ctx, **{field: value})
    assert writes == []


@pytest.mark.parametrize("field,value", [
    ("message_uid", None), ("message_uid", ""), ("message_uid", "x" * 256),
    ("content", [{"type": "text", "text": "multimodal"}]),
    ("content", "  "), ("tool_calls", [{"id": "tool-1"}]),
    ("display_kind", "hidden"), ("_merged_turn_prefix", "earlier"),
    ("_absorbed_message_uids", ["earlier"]), ("_verification_continuation", True),
])
def test_capture_rejects_unsupported_or_ambiguous_rows(history_plugin, field, value):
    _module, ctx, _config, writes = history_plugin
    rows = _pair()
    rows[0][field] = value
    _capture(ctx, rows)
    assert writes == []


def test_capture_distinguishes_same_uid_in_concurrent_sessions(client, history_plugin):
    _module, ctx, _config, writes = history_plugin
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda session: _capture(ctx, session=session), ("session-a", "session-b")))
    assert len(writes) == 2
    ids = [row["source_item_id"] for _body, result in writes for row in result]
    assert len(set(ids)) == 4
    assert {row["thread_ref"] for body, _result in writes for row in body} == {"session-a", "session-b"}
    assert all(_context(client, source_id).status_code == 200 for source_id in ids)


def test_capture_exact_work_association_is_searchable_later(client, history_plugin):
    _module, ctx, _config, writes = history_plugin
    _register(ctx)
    attached = client.post("/relay/sessions/work-refs/attach", json={
        **SCOPE, "runtime": "hermes", "session_ref": "session_שלום",
        "scope_ref": "roadmap:test/history", "local_ref": "item:history",
    })
    assert attached.status_code == 200, attached.text
    exact = attached.json()["attached"]["work_ref"]
    _capture(ctx)
    assert writes[0][0][0]["metadata"]["pallium_work_refs"] == [exact]
    result = _query(client, text="", trigger_origin="agent_pull_work", work_refs=[exact])
    assert {row["source_item_id"] for row in result["results"]} == {
        row["source_item_id"] for row in writes[0][1]}


@pytest.mark.parametrize("problem", ["unavailable", "wrong-session"])
def test_capture_never_infers_work_associations(client, history_plugin, monkeypatch, problem):
    module, ctx, _config, writes = history_plugin
    _register(ctx)
    request = module._json_request

    def http(base, method, path, **kwargs):
        if path == "/relay/sessions/work-refs":
            if problem == "unavailable":
                raise OSError("unavailable")
            return {"session": {"runtime": "hermes", "session_ref": "someone-else",
                                **SCOPE, "state": "recent", "destination_health": "active"},
                    "work_refs": [{"work_ref": "foreign-work"}]}
        return request(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", http)
    _capture(ctx)
    assert len(writes) == 1
    assert all("pallium_work_refs" not in row["metadata"] for row in writes[0][0])
    assert _context(client, writes[0][1][0]["source_item_id"]).status_code == 200


def test_capture_failure_is_bounded_and_does_not_break_host(history_plugin, monkeypatch, caplog):
    module, ctx, _config, writes = history_plugin
    request = module._json_request

    def fail(base, method, path, **kwargs):
        if path == "/items":
            raise TimeoutError("private content must not leak")
        return request(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", fail)
    assert _capture(ctx) is None
    assert writes == []
    assert "snapshot was not confirmed" in caplog.text
    assert "private content must not leak" not in caplog.text


def test_capture_excludes_synthetic_wake_user_and_labels_observed_assistant(client, history_plugin):
    _module, ctx, _config, writes = history_plugin
    ctx, marker, _message = _plugin_wake(client, lambda: ctx)
    _capture(ctx, _pair(user=marker), session="ses_שלום")
    assert len(writes) == 1
    assert len(writes[0][0]) == 1
    row = writes[0][0][0]
    assert row["role"] == "assistant"
    assert row["metadata"]["capture_origin"] == "relay_wake"
    assert marker not in str(row)
    _capture(ctx, _pair(user=marker + "stale"), session="ses_שלום")
    assert len(writes) == 1


def test_capture_rejects_changed_profile_and_duplicate_row_identity(history_plugin):
    _module, ctx, config, writes = history_plugin
    rows = _pair()
    rows[1]["message_uid"] = rows[0]["message_uid"]
    _capture(ctx, rows)
    assert writes == []
    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["actor_ref"] = "changed"
    _capture(ctx)
    assert writes == []
