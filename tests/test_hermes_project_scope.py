"""Hermes session-owned project authority through public hooks, tools and HTTP."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import contextvars
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import ModuleType
from urllib.error import HTTPError

import pytest

from tests.test_hermes_relay_plugin import _await, _execute_request, _mcp_tool, _observe_request, plugin_context


@pytest.fixture
def project_plugin(plugin_context, monkeypatch):
    module, create, config = plugin_context
    seed = create()
    host_context = contextvars.ContextVar("test_hermes_host_scope")
    route_context = contextvars.ContextVar("test_hermes_host_route")
    accesses, calls = [], []

    def public(name):
        def accessor(self):
            value = host_context.get()  # No background/default process cwd is available.
            accesses.append(name)
            return value[0 if name == "cwd" else 1]
        return accessor

    monkeypatch.setattr(type(seed), "session_cwd", public("cwd"), raising=False)
    monkeypatch.setattr(type(seed), "session_surface", public("surface"), raising=False)
    gateway_session_context = ModuleType("gateway.session_context")
    gateway_session_context.bound_session_key = lambda: route_context.get(None)
    monkeypatch.setitem(sys.modules, "gateway.session_context", gateway_session_context)
    settings = config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]
    settings.pop("container_ref")
    settings.update(scope_mode="cwd", mcp_python=sys.executable,
                    mcp_repo=str(Path(__file__).resolve().parents[1]), visibility="private")
    bridge_module = ModuleType(module.__name__ + ".mcp_bridge")

    class Bridge:
        def __init__(self, **configuration):
            assert configuration["container_ref"] is configuration["actor_ref"] is None
            self.catalog = [{"name": "pallium_relay_address", "description": "Self",
                             "parameters": {"properties": {}}},
                            {"name": "pallium_relay_send", "description": "Send",
                             "parameters": {"properties": {"recipient": {}, "message": {}}}}]

        def call(self, name, args, identity, reply=None, *, scope):
            calls.append((name, identity, scope))
            return json.dumps({"identity": identity, "scope": scope})

        def close(self):
            pass

    bridge_module.RelayMcpBridge = Bridge
    monkeypatch.setitem(sys.modules, bridge_module.__name__, bridge_module)
    ctx = create()
    assert accesses == []  # Capability checks never invoke task-local accessors.

    default_route = object()

    def pre(cwd, session="session", turn="turn", message="hello", surface="tui", context=None, history=None,
            route_key=default_route):
        route = "local:route:" + session if route_key is default_route else route_key
        token = host_context.set((cwd, surface))
        route_token = route_context.set(route)
        try:
            return (context or ctx).hooks["pre_llm_call"](
                session_id=session, turn_id=turn, user_message=message, conversation_history=history)
        finally:
            route_context.reset(route_token)
            host_context.reset(token)

    return module, ctx, pre, create, calls, settings


def _repo(tmp_path, name, actor=None):
    root = tmp_path / name
    root.mkdir()
    for args in (["init", "-q"], ["remote", "add", "origin", f"https://example.test/team/{name}.git"],
                 ["config", "user.name", actor or "actor-" + name]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def _sessions(client, container, session="session"):
    response = client.get("/relay/sessions", params={
        "runtime": "hermes", "session_ref": session, "container_ref": container, "include_inactive": True})
    assert response.status_code == 200, response.text
    return response.json()


def _project(name):
    return "git:example.test/team/" + name


def _capture(ctx, session, turn, suffix=""):
    rows = [{"role": "user", "content": "history marker café " + suffix, "message_uid": "user" + suffix},
            {"role": "assistant", "content": "answer 漢字 " + suffix, "message_uid": "answer" + suffix}]
    ctx.hooks["post_llm_call"](session_id=session, turn_id=turn, user_message=rows[0]["content"],
                              assistant_response=rows[1]["content"], conversation_history=rows)


def test_one_profile_concurrent_projects_and_actors(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, calls, _settings = project_plugin
    roots = [_repo(tmp_path, name) for name in ("a", "b")]

    def run(index):
        assert pre(str(roots[index]), session=f"s{index}", turn="seed")
        return json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session=f"s{index}", turn="seed"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert {row["scope"]["container_ref"] for row in results} == {_project("a"), _project("b")}
    assert results[0]["scope"]["actor_ref"] != results[1]["scope"]["actor_ref"]
    assert len(calls) == 2
    assert _sessions(client, _project("a"), "s0")[0]["state"] == "recent"
    assert _sessions(client, _project("b"), "s1")[0]["state"] == "recent"
    assert _sessions(client, _project("b"), "s0") == []


@pytest.mark.parametrize("reload", [False, True])
def test_completed_turn_chain_never_readmits_stale_callbacks(client, project_plugin, tmp_path, monkeypatch, reload):
    module, ctx, pre, create, _calls, _settings = project_plugin
    roots = {name: _repo(tmp_path, name) for name in ("a", "b", "c")}
    for name in roots:
        assert pre(str(roots[name]), turn=name)
        ctx.hooks["on_session_end"](session_id="session", turn_id=name)
    owner = create(ctx.state) if reload else ctx
    assert pre(str(roots["c"]), turn="current", context=owner)
    before = _sessions(client, _project("c"))
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if method != "GET":
            writes.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    for name in roots:
        assert pre(str(roots[name]), turn=name, context=owner) is None
        assert "error" in json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session="session", turn=name))
        _capture(owner, "session", name, "stale")
    assert writes == []
    assert _sessions(client, _project("c")) == before
    assert json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session="session", turn="current"))["scope"]["container_ref"] == _project("c")


def test_unfinished_old_turn_cannot_rebind_after_reload(client, project_plugin, tmp_path):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    roots = {name: _repo(tmp_path, name) for name in ("a", "b", "c")}
    for name in roots:
        assert pre(str(roots[name]), turn=name)
    owner = create(ctx.state)
    assert pre(str(roots["a"]), turn="a", context=owner) is None
    assert _sessions(client, _project("a")) == []
    assert _sessions(client, _project("c"))[0]["scope_generation"] == 2


@pytest.mark.parametrize("reload", [False, True])
def test_actor_aba_invalidates_old_turn_without_changing_relay_scope(
    client, project_plugin, tmp_path, monkeypatch, reload,
):
    module, ctx, pre, create, calls, _settings = project_plugin
    root = _repo(tmp_path, "actor-aba", actor="actor-A")
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if method != "GET":
            writes.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    old_message = "history marker café actor A"
    assert pre(str(root), turn="actor-a", message=old_message,
               history=[{"role": "user", "content": old_message}])
    original = _sessions(client, _project("actor-aba"))[0]
    session_key = next(key for key in ctx.state.values if key.startswith("session:"))
    original_incarnation = ctx.state.values[session_key]["authority_incarnation"]
    old_source = json.loads(_mcp_tool(ctx, "pallium_relay_address", {},
                                    session="session", turn="actor-a"))["scope"]["request_source_item_id"]

    subprocess.run(["git", "-C", str(root), "config", "user.name", "actor-B"],
                   check=True, capture_output=True)
    assert pre(str(root), turn="actor-b", message="history marker café actor B")
    middle = _sessions(client, _project("actor-aba"))[0]
    middle_incarnation = ctx.state.values[session_key]["authority_incarnation"]
    assert (middle["endpoint_id"], middle["scope_generation"]) == (
        original["endpoint_id"], original["scope_generation"])

    owner = create(ctx.state) if reload else ctx
    reloaded_incarnation = None
    if reload:
        session_key = next(key for key in owner.state.values if key.startswith("session:"))
        reloaded_incarnation = owner.state.values[session_key]["authority_incarnation"]
    subprocess.run(["git", "-C", str(root), "config", "user.name", "actor-A"],
                   check=True, capture_output=True)
    current_message = "history marker café actor A again"
    assert pre(str(root), turn="actor-c", message=current_message,
               history=[{"role": "user", "content": current_message}], context=owner)
    current = _sessions(client, _project("actor-aba"))[0]
    current_incarnation = owner.state.values[session_key]["authority_incarnation"]
    assert (current["endpoint_id"], current["scope_generation"]) == (
        original["endpoint_id"], original["scope_generation"])

    before_stale = list(writes)
    assert pre(str(root), turn="actor-a", message=old_message,
               history=[{"role": "user", "content": old_message}], context=owner) is None
    calls_before = len(calls)
    assert "error" in json.loads(_mcp_tool(owner, "pallium_relay_send", {
        "recipient": "@nobody", "message": "stale mutation"}, session="session", turn="actor-a"))
    assert len(calls) == calls_before
    owner.hooks["post_llm_call"](
        session_id="session", turn_id="actor-a", user_message=old_message,
        assistant_response="stale answer", conversation_history=[
            {"role": "user", "content": old_message, "message_uid": "actor-a-user"},
            {"role": "assistant", "content": "stale answer", "message_uid": "actor-a-answer"},
        ])
    assert writes == before_stale
    old_context = client.get(f"/source/{old_source}/context", params={
        "container_ref": _project("actor-aba"), "query_actor_ref": "actor-A",
        "query_visibility": "private", "before": 0, "after": 0})
    assert old_context.status_code == 200, old_context.text
    assert "stale answer" not in old_context.text
    assert old_message in [row["content"] for row in old_context.json()["items"]]

    address = json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session="session", turn="actor-c"))
    assert address["scope"]["container_ref"] == _project("actor-aba")
    assert address["scope"]["actor_ref"] == "actor-A"
    owner.hooks["post_llm_call"](
        session_id="session", turn_id="actor-c", user_message=current_message,
        assistant_response="current answer", conversation_history=[
            {"role": "user", "content": current_message, "message_uid": "actor-c-user"},
            {"role": "assistant", "content": "current answer", "message_uid": "actor-c-answer"},
        ])
    assert writes[-1] == "/items"
    current_source = address["scope"]["request_source_item_id"]
    current_context = client.get(f"/source/{current_source}/context", params={
        "container_ref": _project("actor-aba"), "query_actor_ref": "actor-A",
        "query_visibility": "private", "before": 0, "after": 1})
    assert current_context.status_code == 200, current_context.text
    assert "current answer" in [row["content"] for row in current_context.json()["items"]]
    assert middle_incarnation != original_incarnation
    assert current_incarnation != middle_incarnation
    if reload:
        assert reloaded_incarnation == middle_incarnation


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
@pytest.mark.parametrize("target", ["session", "turn"])
@pytest.mark.parametrize("incarnation", [None, {}, "", " " * 32, "x" * 33, "漢" * 32])
def test_missing_or_malformed_automatic_incarnation_refuses_callbacks(
    client, project_plugin, tmp_path, monkeypatch, target, incarnation, relay_admission_clock,
):
    module, ctx, pre, _create, calls, _settings = project_plugin
    root = _repo(tmp_path, "bad-incarnation-" + target)
    # One CWD registration also refreshes its structural work references, even an empty list.
    with relay_admission_clock(client.app.state.pallium_service._storage, expected_admissions=2):
        assert pre(str(root), turn="a", message="history marker café",
                   history=[{"role": "user", "content": "history marker café"}])
    state_key = next(key for key in ctx.state.values if key.startswith(target + ":"))
    if incarnation is None:
        ctx.state.values[state_key].pop("authority_incarnation")
    else:
        ctx.state.values[state_key]["authority_incarnation"] = incarnation
    saved = json.loads(json.dumps(ctx.state.values))
    writes, http = [], module._json_request

    def observe(base, method, path, **kwargs):
        if method != "GET":
            writes.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(root), turn="a", message="history marker café",
               history=[{"role": "user", "content": "history marker café"}]) is None
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_send", {
        "recipient": "@nobody", "message": "must not dispatch"}, session="session", turn="a"))
    assert writes == []
    assert calls == []
    assert ctx.state.values == saved


def test_reload_transition_before_publication_retains_original_turn_reservation(client, project_plugin, tmp_path, monkeypatch):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    get, put = ctx.state.get, ctx.state.set
    successors = []

    def interleave(key, value):
        previous = get(key)
        put(key, value)
        if (key.startswith("operation:") and value is None and isinstance(previous, dict)
                and previous.get("operation") == "capture_user" and not successors):
            successor = create(ctx.state)
            successors.append(successor)
            assert pre(str(b), turn="b", context=successor)

    monkeypatch.setattr(ctx.state, "set", interleave)
    assert pre(str(a), turn="a", history=[{"role": "user", "content": "hello"}]) is None
    assert successors
    assert pre(str(a), turn="a", context=successors[0]) is None
    assert _sessions(client, _project("a")) == []
    assert _sessions(client, _project("b"))[0]["scope_generation"] == 1


def test_reload_end_during_active_stamp_write_cannot_revive_turn(client, project_plugin, tmp_path, monkeypatch):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a")
    put, successors = ctx.state.set, []

    def interleave(key, value):
        if key.startswith("turn:") and isinstance(value, dict) and value.get("state") == "active" and not successors:
            successor = create(ctx.state)
            successors.append(successor)
            successor.hooks["on_session_end"](session_id="session", turn_id="a")
        put(key, value)

    monkeypatch.setattr(ctx.state, "set", interleave)
    pre(str(root), turn="a")
    assert successors
    assert pre(str(root), turn="a", context=successors[0]) is None
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert "error" in json.loads(_mcp_tool(successors[0], "pallium_relay_address", {}, session="session", turn="a"))


def test_active_turn_reload_preserves_authority_but_malformed_stamp_refuses(client, project_plugin, tmp_path):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a")
    assert pre(str(root), turn="a")
    original = _sessions(client, _project("a"))
    owner = create(ctx.state)
    assert pre(str(root), turn="a", context=owner)
    resumed = _sessions(client, _project("a"))[0]
    assert (resumed["endpoint_id"], resumed["scope_generation"]) == (
        original[0]["endpoint_id"], original[0]["scope_generation"])
    stamp_key = next(key for key in ctx.state.values if key.startswith("turn:"))
    ctx.state.set(stamp_key, {"version": 1, "state": "active"})
    assert pre(str(root), turn="a", context=owner) is None
    assert "error" in json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session="session", turn="a"))


@pytest.mark.parametrize("reload", [False, True])
def test_permanently_deleted_turn_cannot_resume_closed_incarnation(client, project_plugin, tmp_path, reload):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a")
    assert pre(str(root), turn="a")
    ctx.hooks["on_session_delete"](session_id="session", profile=ctx.profile_name, reason="delete")
    owner = create(ctx.state) if reload else ctx
    assert pre(str(root), turn="a", context=owner) is None
    assert _sessions(client, _project("a"))[0]["state"] == "closed"
    assert pre(str(root), turn="new", context=owner)
    assert _sessions(client, _project("a"))[0]["scope_generation"] == 1
    assert pre(str(root), turn="a", context=owner) is None


@pytest.mark.parametrize("actor", ["x" * 256, "unsafe\nactor", "unsafe\tactor"])
def test_invalid_actor_never_reaches_admission_or_capture(client, project_plugin, tmp_path, monkeypatch, actor):
    module, _ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a", actor=actor)
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if method != "GET":
            writes.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(root), history=[{"role": "user", "content": "hello"}]) is None
    assert writes == []
    assert _sessions(client, _project("a")) == []


def test_project_chain_and_frozen_callbacks_do_not_borrow_new_authority(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, calls, _settings = project_plugin
    roots = {name: _repo(tmp_path, name) for name in ("a", "b", "c")}
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if path == "/items":
            writes.append((kwargs["body"], result))
        return result

    monkeypatch.setattr(module, "_json_request", observe)
    endpoints = []
    for generation, name in enumerate(("a", "b", "c", "a")):
        assert pre(str(roots[name]), turn=f"turn{generation}", message="history marker café " + str(generation))
        session = _sessions(client, _project(name))[0]
        endpoints.append(session["endpoint_id"])
        assert session["scope_generation"] == generation
        result = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn=f"turn{generation}"))
        assert result["scope"]["container_ref"] == _project(name)
        _capture(ctx, "session", f"turn{generation}", str(generation))
        assert writes[-1][0][0]["container_ref"] == _project(name)
        if generation:
            before = len(writes)
            _capture(ctx, "session", "turn0", "stale")
            assert len(writes) == before
            assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="turn0"))
    assert len(set(endpoints)) == 1
    assert len(calls) == 4
    source = writes[0][1][0]["source_item_id"]
    for name, code in (("a", 200), ("b", 404)):
        response = client.get(f"/source/{source}/context", params={"container_ref": _project(name),
                              "query_visibility": "private", "active_session_ref": "reader"})
        assert response.status_code == code, response.text


def test_transient_non_git_pins_project_but_invalid_cwd_never_binds(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assert pre(str(root), turn="a")
    assert pre(str(scratch), turn="scratch")
    assert json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="scratch"))["scope"]["container_ref"] == _project("a")
    for index, cwd in enumerate((None, "", "relative", str(tmp_path / "missing"))):
        assert pre(cwd, turn=f"bad{index}") is None
        assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn=f"bad{index}"))
    assert pre(str(root), turn="remote", surface="telegram") is None
    assert len(_sessions(client, _project("a"))) == 1


def test_transient_actor_change_keeps_project_but_separates_private_turns(
    client, project_plugin, tmp_path, monkeypatch,
):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    private_home = tmp_path / "private-home"
    private_home.mkdir()
    (private_home / ".gitconfig").write_text("[user]\n name = Global Bob\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.setenv("USERPROFILE", str(private_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(private_home / "xdg"))
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    for key in tuple(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(private_home / ".gitconfig"))
    packaged_scope = importlib.import_module(module.__name__ + ".scope")
    isolated_git = ModuleType("isolated_git")
    isolated_git.run = lambda *args, **kwargs: subprocess.run(*args, **{
        **kwargs, "env": {**kwargs["env"], "GIT_CONFIG_NOSYSTEM": "1",
                         "GIT_CONFIG_GLOBAL": str(private_home / ".gitconfig")}})
    monkeypatch.setattr(packaged_scope, "subprocess", isolated_git)
    project = _repo(tmp_path, "transient-actor", actor="Alice")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    writes = []
    original_http = module._json_request

    def observe(base, method, path, **kwargs):
        if path in {"/item-and-query", "/items"}:
            writes.append((path, kwargs.get("body")))
        return original_http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    private_text = "Alice private context café"
    assert pre(str(project), turn="alice", message=private_text,
               history=[{"role": "user", "content": private_text}])
    first = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="alice"))
    assert first["scope"]["actor_ref"] == "Alice"
    private_memory = "opal lantern belongs to Alice alone"
    remembered = client.post("/memory/remember", json={
        "container_ref": first["scope"]["container_ref"], "actor_ref": first["scope"]["actor_ref"],
        "thread_ref": "session", "agent_ref": "hermes", "visibility": "private",
        "evidence": [first["scope"]["request_source_item_id"]],
        "text": private_memory, "type": "decision"})
    assert remembered.status_code == 200, remembered.text
    memory_id = remembered.json()["memory_object_id"]

    def memory_hits(actor):
        response = client.post("/query", json={
            "container_ref": _project("transient-actor"), "actor_ref": actor,
            "visibility": "private", "text": "opal lantern", "limit": 20,
            "thread_ref": "later-session", "active_session_ref": "later-session"})
        assert response.status_code == 200, response.text
        return [row.get("memory_object_id") for row in response.json()["results"]]

    assert memory_id in memory_hits("Alice")
    session = _sessions(client, _project("transient-actor"))[0]
    bob = pre(str(scratch), turn="bob", message="Bob asks about another task",
              history=[{"role": "user", "content": "Bob asks about another task"}])
    assert bob and private_text not in json.dumps(bob, ensure_ascii=False)
    current = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="bob"))
    assert current["scope"]["container_ref"] == _project("transient-actor")
    assert current["scope"]["actor_ref"] == "Global Bob"
    assert current["scope"]["request_source_item_id"] != first["scope"]["request_source_item_id"]
    assert memory_id not in memory_hits("Global Bob")
    private_history = client.get("/source/" + first["scope"]["request_source_item_id"] + "/context", params={
        "container_ref": _project("transient-actor"), "query_actor_ref": "Global Bob",
        "query_visibility": "private", "before": 0, "after": 0,
        "include_supported_memories": True})
    assert private_history.status_code == 404 or (
        private_history.status_code == 200
        and private_text not in private_history.text and memory_id not in private_history.text)
    assert (_sessions(client, _project("transient-actor"))[0]["endpoint_id"],
            _sessions(client, _project("transient-actor"))[0]["scope_generation"]) == (
                session["endpoint_id"], session["scope_generation"])
    assert writes[-1][0] == "/item-and-query" and writes[-1][1]["actor_ref"] == "Global Bob"
    before = len(writes)
    assert pre(str(project), turn="alice", message=private_text) is None
    ctx.hooks["post_llm_call"](session_id="session", turn_id="alice", user_message=private_text,
                               assistant_response="stale answer", conversation_history=[
                                   {"role": "user", "content": private_text, "message_uid": "old-user"},
                                   {"role": "assistant", "content": "stale answer", "message_uid": "old-answer"}])
    assert len(writes) == before
    old = client.get("/source/" + first["scope"]["request_source_item_id"] + "/context", params={
        "container_ref": _project("transient-actor"), "query_actor_ref": "Alice",
        "query_visibility": "private", "before": 0, "after": 1,
        "include_supported_memories": True})
    assert old.status_code == 200 and "stale answer" not in old.text
    assert pre(str(project), turn="alice-return", message="Alice returns")
    returned = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="alice-return"))
    assert returned["scope"]["actor_ref"] == "Alice"
    assert returned["scope"]["container_ref"] == first["scope"]["container_ref"]
    assert memory_id in memory_hits("Alice")


def test_moved_project_poll_does_not_take_old_recipient_snapshot(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    a, b = _repo(tmp_path, "snapshot-a"), _repo(tmp_path, "snapshot-b")
    original_http = module._json_request
    reads = []

    def observe(base, method, path, **kwargs):
        query = kwargs.get("query") or {}
        if method == "GET" and path == "/relay/pending-candidate" and query.get("session_ref") == "session":
            reads.append(query["container_ref"])
            if query["container_ref"] == _project("snapshot-a") and not returned_to_a[0]:
                return None  # Hold the old project's poll until after the visible project move.
        return original_http(base, method, path, **kwargs)

    returned_to_a = [False]
    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(a), turn="a")
    endpoint = _sessions(client, _project("snapshot-a"))[0]["endpoint_id"]
    assert client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "peer", "container_ref": _project("snapshot-a")}).status_code == 200
    old = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "peer", "recipient": endpoint,
        "payload": "old project only", "container_ref": _project("snapshot-a")})
    assert old.status_code == 200, old.text
    assert pre(str(b), turn="b")
    _await(lambda: reads.count(_project("snapshot-b")) >= 2)
    assert ctx.injections == []
    delivery = client.get("/relay/messages/" + old.json()["message_id"],
                          params={"container_ref": _project("snapshot-a")}).json()["deliveries"][0]
    assert (delivery["state"], delivery["attempts"], delivery["claim_token"]) == ("pending", 0, None)
    returned_to_a[0] = True
    assert pre(str(a), turn="a-return")
    _await(lambda: len(ctx.injections) == 1)
    marker, target = ctx.injections[0]
    assert marker.startswith("[[PALLIUM_RELAY_WAKE:")
    assert target["session_key"] == "local:route:session"
    wake = pre(str(a), turn="wake", message=marker)
    assert wake and wake["context"].startswith("[[PALLIUM_RELAY_CONTEXT:")
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + wake["context"]}]}
    observed = []

    def provider(actual):
        content = actual["messages"][0]["content"]
        assert marker in content and "[Untrusted Pallium Relay delivery;" in content
        assert "old project only" in content
        observed.append(content)
        return "provider observed scoped wake"

    assert _execute_request(ctx, request, provider, session_id="session", turn_id="wake",
                            api_request_id="api-snapshot-wake") == "provider observed scoped wake"
    assert len(observed) == 1
    delivered = client.get("/relay/messages/" + old.json()["message_id"],
                           params={"container_ref": _project("snapshot-a")}).json()["deliveries"][0]
    assert delivered["state"] == "delivered" and delivered["attempts"] == 1
    assert len(ctx.injections) == 1


@pytest.mark.parametrize("lost_response", [False, True])
def test_failed_transition_does_not_publish_and_reload_keeps_uncertainty(client, project_plugin, tmp_path, monkeypatch, lost_response):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    http = module._json_request

    def failure(base, method, path, **kwargs):
        if path == "/relay/turn" and kwargs.get("body", {}).get("container_ref") == _project("b"):
            if lost_response:
                http(base, method, path, **kwargs)
            raise TimeoutError("transition outcome uncertain")
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", failure)
    assert pre(str(b), turn="b") is None
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="b"))
    saved = [value for key, value in ctx.state.values.items() if key.startswith("session:")]
    assert saved[0]["container_ref"] == _project("a")
    old = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert ("error" in old) is lost_response
    monkeypatch.setattr(module, "_json_request", http)
    resumed = create(ctx.state)
    assert pre(str(b), turn="retry", context=resumed) is None
    assert "error" in json.loads(_mcp_tool(resumed, "pallium_relay_address", {}, session="session", turn="retry"))


@pytest.mark.parametrize("actor_only", [False, True])
def test_uncertain_wake_stays_in_original_project_across_reload(client, project_plugin, tmp_path, actor_only):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    route_a, route_b = "gateway-route:A", "gateway-route:B"
    assert pre(str(a), turn="a", route_key=route_a)
    endpoint = _sessions(client, _project("a"))[0]["endpoint_id"]
    assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "peer", "container_ref": _project("a")}).status_code == 200
    message = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "peer",
                          "recipient": endpoint, "payload": "pending original project", "container_ref": _project("a")})
    assert message.status_code == 200, message.text
    marker = _await(lambda: ctx.injections and ctx.injections[-1][0])
    assert ctx.injections[-1][1]["session_key"] == route_a
    original_scope = next(value.copy() for key, value in ctx.state.values.items() if key.startswith("session:"))
    if actor_only:
        b = a
        subprocess.run(["git", "-C", str(a), "config", "user.name", "actor-new"],
                       check=True, capture_output=True)
    assert pre(str(b), turn="b", route_key=route_b) is None
    assert pre(str(b), turn="stale-wake", message=marker, route_key=route_b) is None
    assert _sessions(client, _project("b")) == []
    resumed = create(ctx.state)
    assert pre(str(b), turn="reload", context=resumed, route_key=route_b) is None
    assert pre(str(b), turn="reload-wake", message=marker, context=resumed, route_key=route_b) is None
    assert next(value for key, value in ctx.state.values.items() if key.startswith("session:")) == original_scope
    response = client.get("/relay/messages/" + message.json()["message_id"], params={"container_ref": _project("a")})
    assert response.json()["deliveries"][0]["state"] == "pending"


@pytest.mark.parametrize("reload", [False, True])
def test_pending_wake_blocks_route_only_change_in_same_project(client, project_plugin, tmp_path, reload):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "route-only-pending")
    route_a, route_b = "gateway-route:A", "gateway-route:B"
    assert pre(str(root), turn="route-a", route_key=route_a)
    original_session = _sessions(client, _project("route-only-pending"))[0]
    endpoint = original_session["endpoint_id"]
    sent = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "peer", "container_ref": _project("route-only-pending")})
    assert sent.status_code == 200, sent.text
    payload = "pending route transition"
    message = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "peer", "recipient": endpoint,
        "payload": payload, "container_ref": _project("route-only-pending")})
    assert message.status_code == 200, message.text
    marker = _await(lambda: ctx.injections and ctx.injections[-1][0])
    assert ctx.injections[-1][1]["session_key"] == route_a
    assert isinstance(marker, str) and marker.startswith("[[PALLIUM_RELAY_WAKE:")
    before_state = copy.deepcopy(ctx.state.values)
    before_injections = len(ctx.injections)
    protected_prefixes = ("session:", "wake:", "transition:", "operation:", "lifecycle:")
    before_protected = {key: value for key, value in before_state.items()
                        if key.startswith(protected_prefixes)}
    before_turns = {key: value for key, value in before_state.items() if key.startswith("turn:")}

    owner = create(ctx.state) if reload else ctx
    assert pre(str(root), turn="route-b", route_key=route_b, context=owner) is None
    after_state = owner.state.values
    assert {key: value for key, value in after_state.items()
            if key.startswith(protected_prefixes)} == before_protected
    assert all(after_state.get(key) == value for key, value in before_turns.items())
    added_turns = {key: value for key, value in after_state.items()
                   if key.startswith("turn:") and key not in before_turns}
    assert len(added_turns) == 1
    reserved_turn, = added_turns.values()
    assert reserved_turn["state"] == "pending"
    assert reserved_turn["container_ref"] == _project("route-only-pending")
    assert reserved_turn["native_session_key"] == route_b
    assert ctx.injections[before_injections:] == []
    assert _sessions(client, _project("route-only-pending"))[0] == original_session
    status = client.get("/relay/messages/" + message.json()["message_id"],
                        params={"container_ref": _project("route-only-pending")})
    assert status.status_code == 200, status.text
    assert status.json()["payload"] == payload
    delivery = status.json()["deliveries"][0]
    assert (delivery["state"], delivery["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("reload", [False, True])
def test_route_a_b_a_rotates_only_adapter_authority_and_rejects_old_turn(
    client, project_plugin, tmp_path, reload,
):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "route-aba")
    session_id = "hook-id-漢"
    route_a, route_b = "native-route:A", "native-route:B"
    marker_a = "route A history café"
    first = pre(str(root), session=session_id, turn="turn-A", route_key=route_a,
                message=marker_a, history=[{"role": "user", "content": marker_a}])
    assert first
    endpoint_a = _sessions(client, _project("route-aba"), session_id)[0]
    address_a = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session=session_id, turn="turn-A"))
    actor_a = address_a["scope"]["actor_ref"]
    source_a = address_a["scope"]["request_source_item_id"]
    session_record = next(value for key, value in ctx.state.values.items()
                          if key.startswith("session:") and value.get("session_ref") == session_id)
    incarnation_a = session_record["authority_incarnation"]
    assert session_record["native_session_key"] == route_a

    marker_b = "route B history שלום"
    assert pre(str(root), session=session_id, turn="turn-B", route_key=route_b,
               message=marker_b, history=[{"role": "user", "content": marker_b}])
    endpoint_b = _sessions(client, _project("route-aba"), session_id)[0]
    owner = create(ctx.state) if reload else ctx
    if reload:
        assert pre(str(root), session=session_id, turn="turn-B", route_key=route_b,
                   message=marker_b, history=[{"role": "user", "content": marker_b}], context=owner)
    assert pre(str(root), session=session_id, turn="turn-A", route_key=route_a, context=owner) is None
    current_b = json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session=session_id, turn="turn-B"))
    assert current_b["scope"]["request_source_item_id"]
    record_b = next(value for key, value in owner.state.values.items()
                    if key.startswith("session:") and value.get("session_ref") == session_id)
    assert record_b["native_session_key"] == route_b
    assert record_b["authority_incarnation"] != incarnation_a

    assert pre(str(root), session=session_id, turn="turn-A2", route_key=route_a, context=owner)
    endpoint_a2 = _sessions(client, _project("route-aba"), session_id)[0]
    address_a2 = json.loads(_mcp_tool(owner, "pallium_relay_address", {}, session=session_id, turn="turn-A2"))
    record_a2 = next(value for key, value in owner.state.values.items()
                     if key.startswith("session:") and value.get("session_ref") == session_id)
    assert record_a2["native_session_key"] == route_a
    assert record_a2["authority_incarnation"] != record_b["authority_incarnation"]
    assert (endpoint_a["endpoint_id"], endpoint_a["scope_generation"]) == (
        endpoint_b["endpoint_id"], endpoint_b["scope_generation"])
    assert (endpoint_a["endpoint_id"], endpoint_a["scope_generation"]) == (
        endpoint_a2["endpoint_id"], endpoint_a2["scope_generation"])
    assert current_b["scope"]["actor_ref"] == address_a2["scope"]["actor_ref"] == actor_a
    old_history = client.get(f"/source/{source_a}/context", params={
        "container_ref": _project("route-aba"), "query_actor_ref": actor_a,
        "query_visibility": "private", "before": 0, "after": 0,
    })
    assert old_history.status_code == 200, old_history.text
    assert marker_a in [row["content"] for row in old_history.json()["items"]]


@pytest.mark.parametrize("route_key", [None, "", " ", "route\nkey", 7, "r" * 4097],
                         ids=["missing", "empty", "blank", "control", "non-string", "over-max"])
def test_missing_or_invalid_bound_route_refuses_without_environment_fallback(
    client, project_plugin, tmp_path, monkeypatch, route_key,
):
    _module, ctx, pre, _create, calls, _settings = project_plugin
    root = _repo(tmp_path, "invalid-native-route")
    monkeypatch.setenv("HERMES_SESSION_KEY", "must-not-be-used-as-fallback")
    assert pre(str(root), turn="invalid-route", route_key=route_key) is None
    assert _sessions(client, _project("invalid-native-route")) == []
    assert calls == []


def test_maximum_native_route_key_is_accepted_and_recorded(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "maximum-native-route")
    route_key = "r" * 4096
    assert pre(str(root), turn="max-route", route_key=route_key)
    saved = next(value for key, value in ctx.state.values.items()
                 if key.startswith("session:") and value.get("session_ref") == "session")
    assert saved["native_session_key"] == route_key
    assert _sessions(client, _project("maximum-native-route"))[0]["session_ref"] == "session"


def test_legacy_saved_scope_without_native_route_refuses_without_overwrite(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "legacy-without-native-route")
    route_key = "native-route:legacy"
    assert pre(str(root), turn="before-legacy", route_key=route_key)
    saved_key = next(key for key, value in ctx.state.values.items()
                     if key.startswith("session:") and value.get("session_ref") == "session")
    saved = dict(ctx.state.values[saved_key])
    saved.pop("native_session_key")
    ctx.state.values[saved_key] = saved
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if method != "GET":
            writes.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(root), turn="after-legacy", route_key=route_key) is None
    assert writes == []
    assert ctx.state.values[saved_key] == saved
    assert _sessions(client, _project("legacy-without-native-route"))[0]["state"] == "recent"


def test_turn_end_cleans_turn_authority_without_closing_endpoint(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert pre(str(a), turn="a")
    ctx.hooks["on_session_end"](session_id="session", turn_id="a")
    assert _sessions(client, _project("a"))[0]["state"] == "recent"
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert pre(str(a), turn="next")


@pytest.mark.parametrize("capability", ["session_cwd", "session_surface", "bound_session_key"])
def test_automatic_mode_refuses_missing_public_api(project_plugin, monkeypatch, capability):
    _module, ctx, _pre, create, calls, _settings = project_plugin
    if capability == "bound_session_key":
        monkeypatch.setattr(sys.modules["gateway.session_context"], capability, None)
    else:
        monkeypatch.setattr(type(ctx), capability, None)
    with pytest.raises(ValueError, match=capability):
        create()
    assert calls == []


def test_model_cwd_and_stale_marker_never_grant_authority(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert ctx.hooks["pre_llm_call"](session_id="unknown", turn_id="no-host", user_message="hello", cwd=str(a)) is None
    assert pre(str(a), turn="stale", message="[[PALLIUM_RELAY_WAKE:v1:old:nonce]]") is None
    assert _sessions(client, _project("a")) == []


def test_inflight_tool_keeps_exact_project_until_completed(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    assert pre(str(b), session="second-session", turn="second-seed")
    second_endpoint = _sessions(client, _project("b"), "second-session")[0]["endpoint_id"]
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    original = bridge_type.call
    entered, release = threading.Event(), threading.Event()
    second_candidate_reads = []
    original_http = module._json_request

    def observe_candidate(base, method, path, **kwargs):
        result = original_http(base, method, path, **kwargs)
        query = kwargs.get("query") or {}
        if (method == "GET" and path == "/relay/pending-candidate"
                and query == {"runtime": "hermes", "session_ref": "second-session",
                              "container_ref": _project("b")}
                and isinstance(result, dict) and result.get("state") == "pending"):
            second_candidate_reads.append(result)
        return result

    monkeypatch.setattr(module, "_json_request", observe_candidate)

    def delayed(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(bridge_type, "call", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tool = pool.submit(_mcp_tool, ctx, "pallium_relay_address", {}, "session", "a")
        assert entered.wait(5)
        transition = pool.submit(pre, str(b), turn="b")
        try:
            assert not transition.done()
            peer = client.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "poll-peer", "container_ref": _project("b")})
            assert peer.status_code == 200, peer.text
            second_message = client.post("/relay/messages", json={
                "sender_runtime": "codex", "sender_session_ref": "poll-peer", "recipient": second_endpoint,
                "payload": "independent session poll ✓", "container_ref": _project("b")})
            assert second_message.status_code == 200, second_message.text
            _await(lambda: len(second_candidate_reads) >= 2)
            _await(lambda: ctx.injections)
            assert all(row == {"state": "pending", "recipient_endpoint_id": second_endpoint,
                               "delivery_id": second_message.json()["deliveries"][0]["delivery_id"]}
                       for row in second_candidate_reads)
            assert len(ctx.injections) == 1
            marker, target = ctx.injections[0]
            assert target == {"role": "user", "session_key": "local:route:second-session"}
            assert second_message.json()["payload"] not in marker
            observed = client.get("/relay/messages/" + second_message.json()["message_id"],
                                  params={"container_ref": _project("b")})
            assert observed.status_code == 200, observed.text
            delivery = observed.json()["deliveries"][0]
            assert (delivery["state"], delivery["attempts"], delivery["claim_token"]) == ("pending", 0, None)
        finally:
            release.set()
        assert json.loads(tool.result(timeout=5))["scope"]["container_ref"] == _project("a")
        assert transition.result(timeout=5)
    assert _sessions(client, _project("a")) == []
    assert _sessions(client, _project("b"))[0]["scope_generation"] == 1


@pytest.mark.parametrize("gate_kind", ["provider", "external_tool"], ids=["provider", "unknown-tool"])
def test_provider_and_unknown_tool_continuations_do_not_block_delivery_polling(
    client, project_plugin, tmp_path, monkeypatch, gate_kind,
):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    root = _repo(tmp_path, "unlocked-continuation-" + gate_kind)
    session_id, route_key = "session", "gateway-route:busy"
    assert pre(str(root), turn="seed", route_key=route_key, message="register before the gate")
    address = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session=session_id, turn="seed"))
    endpoint = _sessions(client, _project("unlocked-continuation-" + gate_kind), session_id)[0]["endpoint_id"]
    ctx.hooks["on_session_end"](session_id=session_id, turn_id="seed")
    assert pre(str(root), turn="held", route_key=route_key, message="hold ordinary work")

    original_http = module._json_request
    positive_reads, ack_bodies, history_writes = [], [], []
    continuation_args = []
    observed_lock = threading.Lock()
    positive_ready, entered, release = threading.Event(), threading.Event(), threading.Event()
    continuation_result = object()

    def observed_http(base, method, path, **kwargs):
        result = original_http(base, method, path, **kwargs)
        query = kwargs.get("query") or {}
        with observed_lock:
            if (method == "GET" and path == "/relay/pending-candidate"
                    and query == {"runtime": "hermes", "session_ref": session_id,
                                  "container_ref": _project("unlocked-continuation-" + gate_kind)}
                    and isinstance(result, dict) and result.get("state") == "pending"):
                positive_reads.append(result)
                if len(positive_reads) >= 2:
                    positive_ready.set()
            if method == "POST" and path == "/relay/deliveries/ack":
                ack_bodies.append(dict(kwargs["body"]))
            if method == "POST" and path == "/items":
                history_writes.append((kwargs.get("body"), result))
        return result

    monkeypatch.setattr(module, "_json_request", observed_http)
    request = {"messages": [{"role": "user", "content": "ordinary provider request"}]}

    def blocked(actual):
        continuation_args.append(actual)
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release the in-flight continuation")
        return continuation_result

    def invoke_gate():
        if gate_kind == "provider":
            staged = ctx.middleware["llm_request"](
                request=request, session_id=session_id, turn_id="held", api_request_id="api-held")
            actual = staged["request"] if staged else request
            return ctx.middleware["llm_execution"](
                actual, blocked, session_id=session_id, turn_id="held", api_request_id="api-held")
        external_args = {"ordinary": True}
        expected_args.append(external_args)
        return ctx.middleware["tool_execution"](
            tool_name="user_plugin_external_tool", args=external_args, next_call=blocked,
            session_id=session_id, turn_id="held")

    expected_args = []

    with ThreadPoolExecutor(max_workers=1) as pool:
        gate = pool.submit(invoke_gate)
        try:
            assert entered.wait(3), "continuation did not reach its deterministic gate"
            peer = client.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "busy-peer",
                "container_ref": _project("unlocked-continuation-" + gate_kind),
            })
            assert peer.status_code == 200, peer.text
            sent = client.post("/relay/messages", json={
                "sender_runtime": "codex", "sender_session_ref": "busy-peer", "recipient": endpoint,
                "payload": "queued while external work is held ✓",
                "container_ref": _project("unlocked-continuation-" + gate_kind),
            })
            assert sent.status_code == 200, sent.text
            message = sent.json()
            delivery_id = message["deliveries"][0]["delivery_id"]
            assert positive_ready.wait(3), "same-session candidate polling stopped behind the continuation"
            assert len(positive_reads) >= 2
            assert all(row == {"delivery_id": delivery_id, "recipient_endpoint_id": endpoint,
                               "state": "pending"} for row in positive_reads)
            current = client.get("/relay/messages/" + message["message_id"],
                                 params={"container_ref": _project("unlocked-continuation-" + gate_kind)})
            assert current.status_code == 200, current.text
            delivery = current.json()["deliveries"][0]
            assert (delivery["state"], delivery["attempts"], delivery["claim_token"]) == ("pending", 0, None)
            assert not ack_bodies
            _await(lambda: ctx.injections)
            assert len(ctx.injections) == 1
            marker, target = ctx.injections[0]
            assert target == {"role": "user", "session_key": route_key}
            assert message["payload"] not in marker
        finally:
            release.set()
        assert gate.result(timeout=5) is continuation_result
    assert len(continuation_args) == 1
    if gate_kind == "provider":
        assert continuation_args[0] is request
    else:
        assert len(expected_args) == 1 and continuation_args[0] is expected_args[0]

    ctx.hooks["on_session_end"](session_id=session_id, turn_id="held")
    wake = pre(str(root), turn="wake", route_key=route_key, message=marker)
    assert wake and isinstance(wake.get("context"), str)
    wake_request = {"messages": [{"role": "user", "content": marker + "\n\n" + wake["context"]}]}
    _observe_request(ctx, wake_request, session=session_id, turn="wake", api_request_id="api-wake")
    assert len(ack_bodies) == 1 and ack_bodies[0]["delivery_id"] == delivery_id
    delivered = client.get("/relay/messages/" + message["message_id"],
                           params={"container_ref": _project("unlocked-continuation-" + gate_kind)})
    assert delivered.status_code == 200 and delivered.json()["deliveries"][0]["state"] == "delivered"

    answer = "ordinary wake completed ✓ " + gate_kind
    rows = [{"role": "user", "content": marker, "message_uid": "busy-wake-user"},
            {"role": "assistant", "content": answer, "message_uid": "busy-wake-answer"}]
    ctx.hooks["post_llm_call"](session_id=session_id, turn_id="wake", user_message=marker,
                               assistant_response=answer, conversation_history=rows)
    assert history_writes
    stored = next(response[index] for body, response in history_writes for index, item in enumerate(body)
                  if item.get("role") == "assistant" and item.get("content") == answer)
    history = client.get(f"/source/{stored['source_item_id']}/context", params={
        "container_ref": _project("unlocked-continuation-" + gate_kind),
        "query_actor_ref": address["scope"]["actor_ref"], "query_visibility": "private",
        "before": 1, "after": 0,
    })
    assert history.status_code == 200, history.text
    assert answer in [item["content"] for item in history.json()["items"]]
    ctx.hooks["on_session_end"](session_id=session_id, turn_id="wake")
    assert _sessions(client, _project("unlocked-continuation-" + gate_kind), session_id)[0]["state"] == "recent"


@pytest.mark.parametrize("outcome", ["return", "raise"], ids=["return", "provider-error"])
def test_late_provider_continuation_preserves_result_but_cannot_capture_after_project_change(
    client, project_plugin, tmp_path, monkeypatch, outcome,
):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "late-provider-a"), _repo(tmp_path, "late-provider-b")
    session_id, route_a, route_b = "session", "gateway-route:A", "gateway-route:B"
    old_message = "late provider history must stay in A"
    assert pre(str(a), turn="old", route_key=route_a, message=old_message,
               history=[{"role": "user", "content": old_message}])
    old_address = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session=session_id, turn="old"))
    old_source = old_address["scope"]["request_source_item_id"]
    old_actor = old_address["scope"]["actor_ref"]
    original_http = module._json_request
    history_writes = []
    module_lock = threading.Lock()

    def observe(base, method, path, **kwargs):
        result = original_http(base, method, path, **kwargs)
        if method == "POST" and path == "/items":
            with module_lock:
                history_writes.append((kwargs.get("body"), result))
        return result

    monkeypatch.setattr(module, "_json_request", observe)
    request = {"messages": [{"role": "user", "content": old_message}]}
    entered, release = threading.Event(), threading.Event()
    continuation_args = []
    provider_result = object()
    provider_error = RuntimeError("provider failure sentinel")

    def continuation(actual):
        continuation_args.append(actual)
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release the provider continuation")
        if outcome == "raise":
            raise provider_error
        return provider_result

    def invoke_provider():
        staged = ctx.middleware["llm_request"](
            request=request, session_id=session_id, turn_id="old", api_request_id="api-old")
        actual = staged["request"] if staged else request
        try:
            value = ctx.middleware["llm_execution"](
                actual, continuation, session_id=session_id, turn_id="old", api_request_id="api-old")
            return "return", value
        except RuntimeError as error:
            return "raise", error

    with ThreadPoolExecutor(max_workers=2) as pool:
        provider = pool.submit(invoke_provider)
        transition = None
        transition_before_release = False
        try:
            assert entered.wait(3), "provider continuation did not reach its gate"
            transition = pool.submit(pre, str(b), turn="new", route_key=route_b,
                                     message="new project turn")
            try:
                transition_result = transition.result(timeout=3)
                transition_before_release = True
            except TimeoutError:
                transition_result = None
        finally:
            release.set()
        provider_outcome, observed = provider.result(timeout=5)
        assert len(continuation_args) == 1 and continuation_args[0] is request
        assert transition is not None
        if not transition_before_release:
            transition_result = transition.result(timeout=5)
        assert transition_before_release and transition_result

    if outcome == "return":
        assert provider_outcome == "return" and observed is provider_result
        late_rows = [{"role": "user", "content": old_message, "message_uid": "late-user"},
                     {"role": "assistant", "content": "late answer must not enter History",
                      "message_uid": "late-answer"}]
        ctx.hooks["post_llm_call"](session_id=session_id, turn_id="old", user_message=old_message,
                                   assistant_response=late_rows[-1]["content"], conversation_history=late_rows)
    else:
        assert provider_outcome == "raise" and observed is provider_error

    ctx.hooks["on_session_end"](session_id=session_id, turn_id="old")
    assert history_writes == []
    old_history = client.get(f"/source/{old_source}/context", params={
        "container_ref": _project("late-provider-a"), "query_actor_ref": old_actor,
        "query_visibility": "private", "before": 0, "after": 1,
    })
    assert old_history.status_code == 200, old_history.text
    old_contents = [item["content"] for item in old_history.json()["items"]]
    assert old_message in old_contents
    assert "late answer must not enter History" not in old_contents
    current = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session=session_id, turn="new"))
    assert current["scope"]["container_ref"] == _project("late-provider-b")
    saved = next(value for key, value in ctx.state.values.items()
                 if key.startswith("session:") and value.get("session_ref") == session_id)
    assert saved["native_session_key"] == route_b
    assert _sessions(client, _project("late-provider-b"), session_id)[0]["state"] == "recent"


def test_pre_inference_capture_provenance_and_completion_dedup(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    message = "history marker café 0"
    observed = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if path in {"/item-and-query", "/items"}:
            observed.append((path, kwargs["body"], result))
        return result

    monkeypatch.setattr(module, "_json_request", observe)
    orientation = pre(str(a), turn="a", message=message, history=[{"role": "user", "content": message}])
    assert observed[0][0] == "/item-and-query"
    source = observed[0][2]["source_item_id"]
    assert source in orientation["context"]
    tool = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert tool["scope"]["request_source_item_id"] == source
    _capture(ctx, "session", "a", "0")
    assert observed[-1][0] == "/items"
    assert observed[-1][2][0]["source_item_id"] == source
    assert pre(str(a), turn="a", message=message, history=[{"role": "user", "content": message}])
    assert [path for path, _body, _result in observed].count("/item-and-query") == 1


def test_distinct_native_route_drives_wake_ack_and_history_through_public_surfaces(
    client, project_plugin, tmp_path, monkeypatch,
):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    root = _repo(tmp_path, "native-route-e2e")
    captured = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if path == "/items":
            captured.append((kwargs["body"], result))
        return result

    monkeypatch.setattr(module, "_json_request", observe)
    session_id, route_key = "hook-session-漢", "gateway-route:α-session"
    ordinary = pre(str(root), session=session_id, turn="ordinary", route_key=route_key,
                   message="ordinary request café")
    assert ordinary and _sessions(client, _project("native-route-e2e"), session_id)[0]["session_ref"] == session_id
    ordinary_address = json.loads(_mcp_tool(ctx, "pallium_relay_address", {},
                                            session=session_id, turn="ordinary"))
    saved = next(value for key, value in ctx.state.values.items()
                 if key.startswith("session:") and value.get("session_ref") == session_id)
    assert saved["native_session_key"] == route_key
    endpoint = _sessions(client, _project("native-route-e2e"), session_id)[0]["endpoint_id"]
    assert client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "wake-sender", "container_ref": _project("native-route-e2e"),
    }).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "wake-sender", "recipient": endpoint,
        "payload": "route-keyed wake payload ✓", "container_ref": _project("native-route-e2e"),
    })
    assert sent.status_code == 200, sent.text
    message = sent.json()
    _await(lambda: ctx.injections)
    marker, target = ctx.injections[-1]
    assert target == {"role": "user", "session_key": route_key}

    wake = pre(str(root), session=session_id, turn="wake-turn", message=marker,
               route_key=route_key)
    assert wake and isinstance(wake.get("context"), str)
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + wake["context"]}]}
    _observe_request(ctx, request, session=session_id, turn="wake-turn", api_request_id="api-native-route-wake")
    status = client.get("/relay/messages/" + message["message_id"],
                        params={"container_ref": _project("native-route-e2e")})
    assert status.status_code == 200, status.text
    assert status.json()["deliveries"][0]["state"] == "delivered"

    answer = "route-keyed wake answer ✓"
    history = [{"role": "user", "content": marker, "message_uid": "wake-user"},
               {"role": "assistant", "content": answer, "message_uid": "wake-answer"}]
    ctx.hooks["post_llm_call"](session_id=session_id, turn_id="wake-turn", user_message=marker,
                               assistant_response=answer, conversation_history=history)
    source = next(response[0]["source_item_id"] for body, response in captured
                  if any(row.get("content") == answer and row.get("role") == "assistant" for row in body))
    history_response = client.get(f"/source/{source}/context", params={
        "container_ref": _project("native-route-e2e"),
        "query_actor_ref": ordinary_address["scope"]["actor_ref"],
        "query_visibility": "private", "before": 0, "after": 0,
    })
    assert history_response.status_code == 200, history_response.text
    assert answer in [row["content"] for row in history_response.json()["items"]]
    assert _sessions(client, _project("native-route-e2e"), session_id)[0]["session_ref"] == session_id


def test_structural_branch_work_is_admitted_and_used_for_capture(client, project_plugin, tmp_path, monkeypatch):
    module, _ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    subprocess.run(["git", "-C", str(a), "symbolic-ref", "HEAD", "refs/heads/feat/generic"],
                   check=True, capture_output=True)
    writes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if path == "/item-and-query":
            writes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(a), turn="a", history=[{"role": "user", "content": "hello"}])
    response = client.get("/relay/sessions/work-refs", params={"runtime": "hermes", "session_ref": "session",
                           "container_ref": _project("a")})
    assert response.status_code == 200, response.text
    refs = response.json()["work_refs"]
    assert [row["local_ref"] for row in refs] == ["git-branch:feat/generic"]
    assert writes[0]["metadata"]["pallium_work_refs"] == [row["work_ref"] for row in refs]


def test_qualified_delete_closes_exact_endpoint_and_rebinds_synthetic_session(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert pre(str(a), turn="a")
    original = _sessions(client, _project("a"))[0]
    ctx.hooks["on_session_delete"](session_id="session", profile="foreign-profile", reason="delete")
    assert _sessions(client, _project("a"))[0]["state"] == "recent"
    ctx.hooks["on_session_delete"](session_id="session", profile=ctx.profile_name, reason="delete")
    closed = _sessions(client, _project("a"))[0]
    assert closed["endpoint_id"] == original["endpoint_id"]
    assert closed["state"] == "closed"
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert pre(str(a), turn="resume")
    resumed = _sessions(client, _project("a"))[0]
    assert resumed["endpoint_id"] == original["endpoint_id"]
    assert resumed["scope_generation"] == original["scope_generation"] + 1
    assert resumed["state"] == "recent"


@pytest.mark.parametrize("reload", [False, True])
def test_finalize_is_advisory_across_resume_and_reload(client, project_plugin, tmp_path, monkeypatch, reload):
    module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "finalize-advisory")
    assert pre(str(root), turn="first")
    if reload:
        ctx = create(ctx.state)
        assert pre(str(root), turn="first", context=ctx)
    session = _sessions(client, _project("finalize-advisory"))[0]
    saved = copy.deepcopy(ctx.state.values)
    closes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    ctx.hooks["on_session_finalize"](session_id="session", profile=ctx.profile_name)
    assert closes == [] and ctx.state.values == saved
    assert _sessions(client, _project("finalize-advisory"))[0] == session
    assert "error" not in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="first"))
    ctx.hooks["on_session_end"](session_id="session", turn_id="first")
    assert pre(str(root), turn="after-archive", context=ctx)
    resumed = _sessions(client, _project("finalize-advisory"))[0]
    assert (resumed["endpoint_id"], resumed["scope_generation"]) == (
        session["endpoint_id"], session["scope_generation"])
    ctx.hooks["on_session_finalize"](session_id="session", profile=ctx.profile_name)
    assert closes == [] and _sessions(client, _project("finalize-advisory"))[0] == resumed


def test_finalize_preserves_pending_wake_and_reloaded_authority(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    root = _repo(tmp_path, "finalize-wake")
    assert pre(str(root), turn="seed")
    session = _sessions(client, _project("finalize-wake"))[0]
    assert client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "peer", "container_ref": _project("finalize-wake")}).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "peer", "recipient": session["endpoint_id"],
        "payload": "pending across advisory finalize", "container_ref": _project("finalize-wake")})
    assert sent.status_code == 200, sent.text
    marker = _await(lambda: ctx.injections and ctx.injections[-1][0])
    saved = copy.deepcopy(ctx.state.values)
    closes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    ctx.hooks["on_session_finalize"](session_id="session")
    assert ctx.state.values == saved and closes == []
    owner = create(ctx.state)
    reloaded = copy.deepcopy(owner.state.values)
    owner.hooks["on_session_finalize"](session_id="session", profile=owner.profile_name)
    assert owner.state.values == reloaded and closes == []
    assert _sessions(client, _project("finalize-wake"))[0] == session
    wake = pre(str(root), turn="wake", message=marker, context=owner)
    assert wake and wake["context"].startswith("[[PALLIUM_RELAY_CONTEXT:")
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + wake["context"]}]}
    observed = []

    def provider(actual):
        content = actual["messages"][0]["content"]
        assert marker in content and "[Untrusted Pallium Relay delivery;" in content
        assert "pending across advisory finalize" in content
        observed.append(content)
        return "provider observed resumed wake"

    assert _execute_request(owner, request, provider, session_id="session", turn_id="wake",
                            api_request_id="api-finalize-wake") == "provider observed resumed wake"
    assert len(observed) == 1
    delivery = client.get("/relay/messages/" + sent.json()["message_id"],
                          params={"container_ref": _project("finalize-wake")}).json()["deliveries"][0]
    assert delivery["state"] == "delivered" and delivery["attempts"] == 1
    assert len(ctx.injections) == 1


@pytest.mark.parametrize("event", [
    {}, {"profile": "foreign", "reason": "delete"}, {"reason": "delete"},
    {"profile": 7, "reason": "delete"},
    {"profile": "own"},
    *({"profile": "own", "reason": reason} for reason in
      ("archive", "prune", "sweep", "profile_repair", "unknown", None)),
    {"profile": "own", "reason": "delete", "session_id": ""},
    {"profile": "own", "reason": "delete", "session_id": " bad"},
    {"profile": "own", "reason": "delete", "session_id": "x" * 256},
    {"profile": "own", "reason": "delete", "session_id": 7},
    {"profile": "own", "reason": "delete", "deleted_ids": []},
    {"profile": "own", "reason": "delete", "deleted_ids": None},
    {"profile": "own", "reason": "delete", "deleted_ids": "one"},
    {"profile": "own", "reason": "delete", "deleted_ids": ["one", ""]},
    {"profile": "own", "reason": "delete", "deleted_ids": ["one", "missing\n"]},
    {"profile": "own", "reason": "delete", "deleted_ids": ["one", "x" * 256]},
    {"profile": "own", "reason": "delete", "deleted_ids": ["two"]},
], ids=lambda value: str(value))
def test_unqualified_delete_refuses_whole_event_before_close(client, project_plugin, tmp_path, monkeypatch, event):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    one, two = _repo(tmp_path, "one"), _repo(tmp_path, "two")
    assert pre(str(one), session="one", turn="seed")
    assert pre(str(two), session="two", turn="seed")
    before = (_sessions(client, _project("one"), "one"), _sessions(client, _project("two"), "two"))
    saved = copy.deepcopy(ctx.state.values)
    closes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    fields = {"session_id": "one", **event}
    if fields.get("profile") == "own":
        fields["profile"] = ctx.profile_name
    ctx.hooks["on_session_delete"](**fields)
    assert closes == [] and ctx.state.values == saved
    assert (_sessions(client, _project("one"), "one"),
            _sessions(client, _project("two"), "two")) == before


def test_qualified_delete_list_closes_exact_sessions_once(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    for name in ("one", "two", "unrelated"):
        assert pre(str(_repo(tmp_path, name)), session=name, turn="seed")
    unrelated = _sessions(client, _project("unrelated"), "unrelated")[0]
    closes = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe)
    event = {"session_id": "one", "deleted_ids": ["one", "two", "one"],
             "profile": ctx.profile_name, "reason": "delete"}
    ctx.hooks["on_session_delete"](**event)
    assert [row["session_ref"] for row in closes] == ["one", "two"]
    assert all({"expected_endpoint_id", "expected_scope_generation"} <= set(row) for row in closes)
    assert _sessions(client, _project("one"), "one")[0]["state"] == "closed"
    assert _sessions(client, _project("two"), "two")[0]["state"] == "closed"
    assert _sessions(client, _project("unrelated"), "unrelated")[0] == unrelated
    ctx.hooks["on_session_delete"](**event)
    assert [row["session_ref"] for row in closes] == ["one", "two"]


@pytest.mark.parametrize("native_id", ["session-שלום", "s" * 255])
def test_qualified_delete_accepts_native_id_boundaries(client, project_plugin, tmp_path, native_id):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "boundary")
    assert pre(str(root), session=native_id, turn="seed")
    ctx.hooks["on_session_delete"](session_id=native_id, profile=ctx.profile_name, reason="delete")
    assert _sessions(client, _project("boundary"), native_id)[0]["state"] == "closed"


def test_bulk_delete_is_profile_scoped_and_uncertain_close_survives_reload(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), session="one", turn="a")
    assert pre(str(b), session="two", turn="b")
    http = module._json_request
    attempts = []

    def fail_close(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            attempts.append(kwargs["body"])
            if kwargs["body"]["session_ref"] == "one":
                raise TimeoutError("close response unknown")
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", fail_close)
    ctx.hooks["on_session_delete"](session_id="one", deleted_ids=["one", "two"],
                                   profile=ctx.profile_name, reason="delete")
    assert len(attempts) == 2
    assert all({"expected_endpoint_id", "expected_scope_generation"} <= set(row) for row in attempts)
    assert _sessions(client, _project("a"), "one")[0]["state"] == "recent"
    assert _sessions(client, _project("b"), "two")[0]["state"] == "closed"
    resumed = create(ctx.state)
    assert pre(str(a), session="one", turn="blocked", context=resumed) is None
    assert len(attempts) == 2  # No unguarded close retry or lifecycle reset.




def test_missing_persisted_opt_in_witness_refuses_before_capture(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "old-service")
    http = module._json_request
    turns, captures = [], []

    def omit_witness(base, method, path, **kwargs):
        if path == "/relay/turn":
            turns.append(kwargs["body"])
            result = http(base, method, path, **kwargs)
            result["session"].pop("guarded_lifecycle", None)
            return result
        if path in {"/item-and-query", "/items"}:
            captures.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", omit_witness)
    assert pre(str(a), turn="old-service", message="must not capture") is None
    assert len(turns) == 1 and turns[0]["guarded_lifecycle"] is True
    assert captures == []


def test_missing_conditional_close_route_keeps_reload_fence_without_legacy_fallback(
    client, project_plugin, tmp_path, monkeypatch,
):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "missing-close-route")
    assert pre(str(a), turn="before-close")
    attempts = []
    http = module._json_request

    def old_service(base, method, path, **kwargs):
        if path in {"/relay/sessions/close-if-current", "/relay/sessions/close"}:
            attempts.append(path)
            if path == "/relay/sessions/close-if-current":
                raise HTTPError(base + path, 404, "route missing", {}, None)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", old_service)
    ctx.hooks["on_session_delete"](session_id="session", profile=ctx.profile_name, reason="delete")
    assert attempts == ["/relay/sessions/close-if-current"]
    assert _sessions(client, _project("missing-close-route"))[0]["state"] == "recent"
    reloaded = create(ctx.state)
    assert pre(str(a), turn="after-reload", context=reloaded) is None
    assert attempts == ["/relay/sessions/close-if-current"]
def test_close_callback_started_during_transition_cannot_close_successor(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    entered, release, snapshot = threading.Event(), threading.Event(), threading.Event()
    http, get_state = module._json_request, ctx.state.get
    closes = []

    def observe_state(key, default=None):
        result = get_state(key, default)
        if key.startswith("session:") and threading.current_thread().name == "close-callback":
            snapshot.set()
        return result

    def delayed_transition(base, method, path, **kwargs):
        if path == "/relay/turn" and kwargs.get("body", {}).get("container_ref") == _project("b"):
            entered.set()
            assert release.wait(5)
        if path == "/relay/sessions/close-if-current":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(ctx.state, "get", observe_state)
    monkeypatch.setattr(module, "_json_request", delayed_transition)
    with ThreadPoolExecutor(max_workers=1) as pool:
        transition = pool.submit(pre, str(b), turn="b")
        assert entered.wait(5)
        closing = threading.Thread(name="close-callback", target=ctx.hooks["on_session_delete"],
                                   kwargs={"session_id": "session", "profile": ctx.profile_name, "reason": "delete"})
        closing.start()
        try:
            assert snapshot.wait(5)
        finally:
            release.set()
        assert transition.result(timeout=5)
        closing.join(timeout=5)
        assert not closing.is_alive()
    assert closes == []
    assert _sessions(client, _project("b"))[0]["state"] == "recent"


@pytest.mark.parametrize("actor_only", [False, True])
def test_inflight_operation_reload_fence_clears_after_exact_completion(client, project_plugin, tmp_path, monkeypatch, actor_only):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    if actor_only:
        b = a
        subprocess.run(["git", "-C", str(a), "config", "user.name", "actor-new"],
                       check=True, capture_output=True)
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    original = bridge_type.call
    entered, release = threading.Event(), threading.Event()

    def delayed(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(bridge_type, "call", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        tool = pool.submit(_mcp_tool, ctx, "pallium_relay_address", {}, "session", "a")
        assert entered.wait(5)
        reloaded = create(ctx.state)
        try:
            assert pre(str(b), turn="while-inflight", context=reloaded) is None
        finally:
            release.set()
        assert "error" not in json.loads(tool.result(timeout=5))
    assert pre(str(b), turn="after-completion", context=reloaded)
    assert _sessions(client, _project("a" if actor_only else "b"))[0]["scope_generation"] == (0 if actor_only else 1)
    assert json.loads(_mcp_tool(reloaded, "pallium_relay_address", {}, "session", "after-completion"))["scope"]["actor_ref"] == ("actor-new" if actor_only else "actor-b")


@pytest.mark.parametrize("mutation", [False, True])
@pytest.mark.parametrize("actor_only", [False, True])
def test_only_uncertain_mutations_retain_project_fence(client, project_plugin, tmp_path, monkeypatch, mutation, actor_only):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    original_scope = next(value.copy() for key, value in ctx.state.values.items() if key.startswith("session:"))
    if actor_only:
        b = a
        subprocess.run(["git", "-C", str(a), "config", "user.name", "actor-new"],
                       check=True, capture_output=True)
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    monkeypatch.setattr(bridge_type, "call", lambda *args, **kwargs: json.dumps({"error": "transport failed", "operation_uncertain": True}))
    name = "pallium_relay_send" if mutation else "pallium_relay_address"
    assert "error" in json.loads(_mcp_tool(ctx, name, {}, session="session", turn="a"))
    reloaded = create(ctx.state)
    outcome = pre(str(b), turn="b", context=reloaded)
    assert (outcome is None) is mutation
    if actor_only:
        current_scope = next(value for key, value in ctx.state.values.items() if key.startswith("session:"))
        assert (current_scope == original_scope) is mutation
        assert current_scope["actor_ref"] == ("actor-a" if mutation else "actor-new")
    else:
        assert bool(_sessions(client, _project("b"))) is not mutation


def test_unsafe_origin_never_registers_or_logs_secret(client, project_plugin, tmp_path, caplog):
    _module, _ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    secret = "private-value-do-not-print"
    subprocess.run(["git", "-C", str(a), "remote", "set-url", "origin",
                    "https://example.test/team/a.git?token=" + secret], check=True, capture_output=True)
    assert pre(str(a), turn="unsafe") is None
    assert _sessions(client, _project("a")) == []
    assert secret not in caplog.text


def test_delete_after_reload_defers_until_inflight_operation_finishes(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert pre(str(a), turn="a")
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    original, http = bridge_type.call, module._json_request
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    closes = []

    def delayed(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        result = original(self, *args, **kwargs)
        completed.set()
        return result

    def observe(base, method, path, **kwargs):
        if path == "/relay/sessions/close-if-current":
            assert completed.is_set()
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(bridge_type, "call", delayed)
    monkeypatch.setattr(module, "_json_request", observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        tool = pool.submit(_mcp_tool, ctx, "pallium_relay_address", {}, "session", "a")
        assert entered.wait(5)
        reloaded = create(ctx.state)
        try:
            reloaded.hooks["on_session_delete"](session_id="session", profile=ctx.profile_name,
                                                reason="delete")
            assert closes == []
            assert _sessions(client, _project("a"))[0]["state"] == "recent"
        finally:
            release.set()
        assert "error" not in json.loads(tool.result(timeout=5))
    assert len(closes) == 1
    assert _sessions(client, _project("a"))[0]["state"] == "closed"
    assert pre(str(a), turn="resume", context=reloaded)


def test_malformed_mutation_result_keeps_project_fence(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    monkeypatch.setattr(bridge_type, "call", lambda *args, **kwargs: "malformed result")
    assert _mcp_tool(ctx, "pallium_relay_send", {}, session="session", turn="a") == "malformed result"
    assert pre(str(b), turn="b") is None
    assert _sessions(client, _project("b")) == []


def test_missing_post_user_uid_keeps_valid_assistant_and_deduplicates_user(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    message = "current user café"
    captures = []
    http = module._json_request

    def observe(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if path in {"/item-and-query", "/items"}:
            captures.append((path, result))
        return result

    monkeypatch.setattr(module, "_json_request", observe)
    assert pre(str(a), turn="a", message=message, history=[{"role": "user", "content": message}])
    rows = [{"role": "user", "content": message},
            {"role": "assistant", "content": "answer 漢字", "message_uid": "assistant-stable-uid"}]
    ctx.hooks["post_llm_call"](session_id="session", turn_id="a", user_message=message,
                              assistant_response=rows[1]["content"], conversation_history=rows)
    assert [row[0] for row in captures] == ["/item-and-query", "/items"]
    assert captures[1][1][0]["source_item_id"] == captures[0][1]["source_item_id"]
    assert len(captures[1][1]) == 2


def test_unicode_cwd_actor_and_session_keep_exact_http_identity(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a", actor="Actor שלום")
    root = a.rename(tmp_path / "פרויקט café")
    assert pre(str(root), session="session_世界", turn="turn_שלום")
    result = json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session_世界", turn="turn_שלום"))
    assert result["scope"]["actor_ref"] == "Actor שלום"
    assert result["identity"] == ["session_世界", "turn_שלום"]
    assert _sessions(client, _project("a"), "session_世界")[0]["state"] == "recent"


def test_known_atomic_admission_refusal_preserves_old_project_and_can_retry(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    http = module._json_request
    refuse = True

    def conflict(base, method, path, **kwargs):
        if refuse and path == "/relay/turn" and kwargs.get("body", {}).get("container_ref") == _project("b"):
            body = {**kwargs["body"], "previous_scope_generation": 999}
            response = client.post(path, json=body)
            assert response.status_code == 409, response.text
            raise HTTPError(base + path, response.status_code, "scope conflict", {}, None)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", conflict)
    assert pre(str(b), turn="refused") is None
    assert _sessions(client, _project("b")) == []
    assert "error" not in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    refuse = False
    assert pre(str(b), turn="retry")
    assert _sessions(client, _project("b"))[0]["scope_generation"] == 1


def _send_cwd_message(client, container, endpoint):
    response = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "peer", "container_ref": container})
    assert response.status_code == 200, response.text
    response = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "peer", "recipient": endpoint,
        "payload": "current route payload", "container_ref": container})
    assert response.status_code == 200, response.text
    return response.json()["message_id"]


def _observe_cwd_poller(monkeypatch, changed):
    accessor = sys.modules["hermes_cli.config"].load_config_readonly
    revisited, reads = threading.Event(), []

    def config():
        value = accessor()
        if changed.is_set() and threading.current_thread().name == "pallium-hermes-relay":
            reads.append(True)
            if len(reads) >= 8:
                revisited.set()
        return value

    monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", config)
    return revisited


@pytest.mark.parametrize("new_route", [None, "native:replacement"])
def test_cwd_route_invalidated_at_dispatch_boundary_retains_pending_delivery(
        client, project_plugin, tmp_path, monkeypatch, new_route):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "dispatch")
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    assert pre(str(root), turn="seed", route_key="native:original")
    ctx.hooks["on_session_end"](session_id="session", turn_id="seed")
    changed = threading.Event()
    revisited = _observe_cwd_poller(monkeypatch, changed)
    write = ctx.state.set

    def invalidate(key, value):
        write(key, value)
        if key.startswith("wake:") and not changed.is_set():
            assert pre(str(root), turn="new-route", route_key=new_route) is None
            changed.set()

    monkeypatch.setattr(ctx.state, "set", invalidate)
    endpoint = _sessions(client, _project("dispatch"))[0]["endpoint_id"]
    message = _send_cwd_message(client, _project("dispatch"), endpoint)
    assert changed.wait(3) and revisited.wait(3)
    assert not ctx.injections
    wake, = (v for k, v in ctx.state.values.items() if k.startswith("wake:"))
    assert wake["state"] == "injection_attempted" and wake["native_session_key"] == "native:original"
    delivery = client.get("/relay/messages/" + message,
                          params={"container_ref": _project("dispatch")}).json()["deliveries"][0]
    assert (delivery["state"], delivery["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("phase", ["surface", "accessor", "response", "publication"])
def test_cwd_stale_registration_cannot_restore_invalidated_native_route(
        client, project_plugin, tmp_path, monkeypatch, phase):
    module, ctx, pre, _create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "registration")
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    assert pre(str(root), turn="seed", route_key="native:original")
    ctx.hooks["on_session_end"](session_id="session", turn_id="seed")
    changed = threading.Event()
    revisited = _observe_cwd_poller(monkeypatch, changed)

    def invalidate():
        changed.set()
        assert pre(str(root), turn="newer", route_key=None) is None

    if phase in {"surface", "accessor"}:
        accessor = "session_surface" if phase == "surface" else "session_cwd"
        original = getattr(type(ctx), accessor)
        def cwd(self):
            value = original(self)
            if not changed.is_set():
                invalidate()
            return value
        monkeypatch.setattr(type(ctx), accessor, cwd)
    elif phase == "response":
        original = module._json_request
        def http(base, method, path, **kwargs):
            value = original(base, method, path, **kwargs)
            if method == "POST" and path == "/relay/turn" and not changed.is_set():
                invalidate()
            return value
        monkeypatch.setattr(module, "_json_request", http)
    else:
        original = ctx.state.set
        def write(key, value):
            original(key, value)
            if key.startswith("session:") and not changed.is_set():
                invalidate()
        monkeypatch.setattr(ctx.state, "set", write)
    assert pre(str(root), turn="older", route_key="native:original") is None
    assert changed.is_set()
    endpoint = _sessions(client, _project("registration"))[0]["endpoint_id"]
    message = _send_cwd_message(client, _project("registration"), endpoint)
    assert revisited.wait(3)
    assert not ctx.injections
    delivery = client.get("/relay/messages/" + message,
                          params={"container_ref": _project("registration")}).json()["deliveries"][0]
    assert (delivery["state"], delivery["attempts"]) == ("pending", 0)


def _cwd_role_history(client, name=None):
    body = {"container_ref": _project("role-history"), "actor_ref": "actor-role-history",
            "visibility": "private", "source_type": "hermes", "source_only": True,
            "text": "project role marker café", "trigger_origin": "agent_pull", "limit": 30}
    if name is not None:
        body["relay_name"] = name
    response = client.post("/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()["results"]


@pytest.mark.parametrize("reload", [False, True])
def test_cwd_role_snapshot_survives_rename_reload_and_completion_dedup(
        client, project_plugin, tmp_path, reload):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "role-history")
    assert pre(str(root), turn="seed")
    def name(value):
        response = client.post("/relay/sessions/name", json={
            "runtime": "hermes", "session_ref": "session", "container_ref": _project("role-history"),
            "alias": value})
        assert response.status_code == 200, response.text
    name("planner")
    text = "project role marker café"
    history = [{"role": "user", "content": text, "message_uid": "user-first"}]
    assert pre(str(root), turn="first", message=text, history=history)
    name("later")
    if reload:
        for cleanup in ctx.cleanups:
            cleanup()
        ctx = create(ctx.state)
    assert pre(str(root), turn="first", message=text, history=history, context=ctx)
    rows = [*history, {"role": "assistant", "content": text + " answer", "message_uid": "assistant-first"}]
    for _ in range(2):
        ctx.hooks["post_llm_call"](session_id="session", turn_id="first", user_message=text,
                                  assistant_response=text + " answer", conversation_history=rows)
    found = _cwd_role_history(client, "planner")
    assert len(found) == 2 and {row["role"] for row in found} == {"user", "assistant"}
    assert all(row["relay_name"] == "planner" and row["relay_attribution_state"] == "named" for row in found)
    assert not _cwd_role_history(client, "later")
    ctx.hooks["on_session_end"](session_id="session", turn_id="first")
    next_history = [{"role": "user", "content": text + " next", "message_uid": "user-next"}]
    assert pre(str(root), turn="next", message=text + " next", history=next_history, context=ctx)
    assert len(_cwd_role_history(client, "later")) == 1


def test_cwd_legacy_active_turn_does_not_backfill_role_provenance(
        client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "role-history")
    text = "project role marker café legacy"
    history = [{"role": "user", "content": text, "message_uid": "legacy-user"}]
    http = module._json_request
    def legacy(base, method, path, **kwargs):
        if path == "/item-and-query":
            kwargs["body"] = {k: v for k, v in kwargs["body"].items()
                              if k not in {"source_turn_id", "relay_name", "relay_attribution_state"}}
        return http(base, method, path, **kwargs)
    monkeypatch.setattr(module, "_json_request", legacy)
    assert pre(str(root), turn="legacy", message=text, history=history)
    for key, value in list(ctx.state.values.items()):
        if key.startswith("turn:"):
            ctx.state.set(key, {k: v for k, v in value.items() if k != "capture"})
    for cleanup in ctx.cleanups:
        cleanup()
    ctx = create(ctx.state)
    monkeypatch.setattr(module, "_json_request", http)
    assert pre(str(root), turn="legacy", message=text, history=history, context=ctx)
    ctx.hooks["post_llm_call"](session_id="session", turn_id="legacy", user_message=text,
        assistant_response=text + " answer", conversation_history=[*history,
        {"role": "assistant", "content": text + " answer", "message_uid": "legacy-assistant"}])
    found = _cwd_role_history(client)
    assert len(found) == 2 and all(row["relay_name"] is None for row in found)
    assert all(row["relay_attribution_state"] == "unavailable" for row in found)


@pytest.mark.parametrize("failure", ["before-write", "lost-response"])
def test_cwd_partial_capture_keeps_first_role_after_rename_reload_and_completion(
        client, project_plugin, tmp_path, monkeypatch, failure):
    module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "role-history")
    assert pre(str(root), turn="seed")
    def name(alias):
        response = client.post("/relay/sessions/name", json={
            "runtime": "hermes", "session_ref": "session", "container_ref": _project("role-history"),
            "alias": alias})
        assert response.status_code == 200, response.text
    name("planner")
    text = "project role marker café partial"
    history = [{"role": "user", "content": text, "message_uid": "partial-user"}]
    http = module._json_request
    attempted = []
    def uncertain(base, method, path, **kwargs):
        if path == "/item-and-query" and not attempted:
            attempted.append(copy.deepcopy(kwargs["body"]))
            if failure == "lost-response":
                http(base, method, path, **kwargs)
            raise TimeoutError("controlled capture uncertainty")
        return http(base, method, path, **kwargs)
    monkeypatch.setattr(module, "_json_request", uncertain)
    assert pre(str(root), turn="partial", message=text, history=history)
    assert len(attempted) == 1 and attempted[0]["relay_name"] == "planner"
    name("later")
    for cleanup in ctx.cleanups:
        cleanup()
    ctx = create(ctx.state)
    monkeypatch.setattr(module, "_json_request", http)
    assert pre(str(root), turn="partial", message=text, history=history, context=ctx)
    for _ in range(2):
        ctx.hooks["post_llm_call"](session_id="session", turn_id="partial", user_message=text,
            assistant_response=text + " answer", conversation_history=[*history,
            {"role": "assistant", "content": text + " answer", "message_uid": "partial-assistant"}])
    found = _cwd_role_history(client, "planner")
    assert len(found) == 2 and {row["role"] for row in found} == {"user", "assistant"}
    assert all(row["relay_name"] == "planner" and row["relay_attribution_state"] == "named" for row in found)
    assert not _cwd_role_history(client, "later")
