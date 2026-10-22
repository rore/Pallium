"""Hermes session-owned project authority through public hooks, tools and HTTP."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextvars
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import ModuleType
from urllib.error import HTTPError

import pytest

from tests.test_hermes_relay_plugin import _await, _mcp_tool, plugin_context


@pytest.fixture
def project_plugin(plugin_context, monkeypatch):
    module, create, config = plugin_context
    seed = create()
    host_context = contextvars.ContextVar("test_hermes_host_scope")
    accesses, calls = [], []

    def public(name):
        def accessor(self):
            value = host_context.get()  # No background/default process cwd is available.
            accesses.append(name)
            return value[0 if name == "cwd" else 1]
        return accessor

    monkeypatch.setattr(type(seed), "session_cwd", public("cwd"), raising=False)
    monkeypatch.setattr(type(seed), "session_surface", public("surface"), raising=False)
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

    def pre(cwd, session="session", turn="turn", message="hello", surface="tui", context=None, history=None):
        token = host_context.set((cwd, surface))
        try:
            return (context or ctx).hooks["pre_llm_call"](
                session_id=session, turn_id=turn, user_message=message, conversation_history=history)
        finally:
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
def test_finalized_turn_cannot_resume_closed_incarnation(client, project_plugin, tmp_path, reload):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    root = _repo(tmp_path, "a")
    assert pre(str(root), turn="a")
    ctx.hooks["on_session_finalize"](session_id="session")
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


def test_uncertain_wake_stays_in_original_project_across_reload(client, project_plugin, tmp_path):
    _module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    endpoint = _sessions(client, _project("a"))[0]["endpoint_id"]
    assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "peer", "container_ref": _project("a")}).status_code == 200
    message = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "peer",
                          "recipient": endpoint, "payload": "pending original project", "container_ref": _project("a")})
    assert message.status_code == 200, message.text
    marker = _await(lambda: ctx.injections and ctx.injections[-1][0])
    assert pre(str(b), turn="b") is None
    assert pre(str(b), turn="stale-wake", message=marker) is None
    assert _sessions(client, _project("b")) == []
    resumed = create(ctx.state)
    assert pre(str(b), turn="reload", context=resumed) is None
    assert pre(str(b), turn="reload-wake", message=marker, context=resumed) is None
    response = client.get("/relay/messages/" + message.json()["message_id"], params={"container_ref": _project("a")})
    assert response.json()["deliveries"][0]["state"] == "pending"


def test_turn_end_cleans_turn_authority_without_closing_endpoint(client, project_plugin, tmp_path):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert pre(str(a), turn="a")
    ctx.hooks["on_session_end"](session_id="session", turn_id="a")
    assert _sessions(client, _project("a"))[0]["state"] == "recent"
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert pre(str(a), turn="next")


@pytest.mark.parametrize("capability", ["session_cwd", "session_surface"])
def test_automatic_mode_refuses_missing_public_api(project_plugin, monkeypatch, capability):
    _module, ctx, _pre, create, calls, _settings = project_plugin
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
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    original = bridge_type.call
    entered, release = threading.Event(), threading.Event()

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
        finally:
            release.set()
        assert json.loads(tool.result(timeout=5))["scope"]["container_ref"] == _project("a")
        assert transition.result(timeout=5)
    assert _sessions(client, _project("a")) == []
    assert _sessions(client, _project("b"))[0]["scope_generation"] == 1


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


@pytest.mark.parametrize("hook", ["on_session_finalize", "on_session_delete"])
def test_true_disposal_guards_exact_endpoint_and_allows_new_user_resume(client, project_plugin, tmp_path, hook):
    _module, ctx, pre, _create, _calls, _settings = project_plugin
    a = _repo(tmp_path, "a")
    assert pre(str(a), turn="a")
    original = _sessions(client, _project("a"))[0]
    ctx.hooks[hook](session_id="session", profile="foreign-profile")
    assert _sessions(client, _project("a"))[0]["state"] == "recent"
    ctx.hooks[hook](session_id="session")
    closed = _sessions(client, _project("a"))[0]
    assert closed["endpoint_id"] == original["endpoint_id"]
    assert closed["state"] == "closed"
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="session", turn="a"))
    assert pre(str(a), turn="resume")
    resumed = _sessions(client, _project("a"))[0]
    assert resumed["endpoint_id"] == original["endpoint_id"]
    assert resumed["scope_generation"] == original["scope_generation"] + 1
    assert resumed["state"] == "recent"


def test_bulk_delete_is_profile_scoped_and_uncertain_close_survives_reload(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), session="one", turn="a")
    assert pre(str(b), session="two", turn="b")
    http = module._json_request
    attempts = []

    def fail_close(base, method, path, **kwargs):
        if path == "/relay/sessions/close":
            attempts.append(kwargs["body"])
            if kwargs["body"]["session_ref"] == "one":
                raise TimeoutError("close response unknown")
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", fail_close)
    ctx.hooks["on_session_delete"](session_id="one", deleted_ids=["one", "two"], profile=ctx.profile_name)
    assert len(attempts) == 2
    assert all({"expected_endpoint_id", "expected_scope_generation"} <= set(row) for row in attempts)
    assert _sessions(client, _project("a"), "one")[0]["state"] == "recent"
    assert _sessions(client, _project("b"), "two")[0]["state"] == "closed"
    resumed = create(ctx.state)
    assert pre(str(a), session="one", turn="blocked", context=resumed) is None
    assert len(attempts) == 2  # No unguarded close retry or lifecycle reset.


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
        if path == "/relay/sessions/close":
            closes.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(ctx.state, "get", observe_state)
    monkeypatch.setattr(module, "_json_request", delayed_transition)
    with ThreadPoolExecutor(max_workers=1) as pool:
        transition = pool.submit(pre, str(b), turn="b")
        assert entered.wait(5)
        closing = threading.Thread(name="close-callback", target=ctx.hooks["on_session_finalize"], kwargs={"session_id": "session"})
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


def test_inflight_operation_reload_fence_clears_after_exact_completion(client, project_plugin, tmp_path, monkeypatch):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
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
    assert _sessions(client, _project("b"))[0]["scope_generation"] == 1


@pytest.mark.parametrize("mutation", [False, True])
def test_only_uncertain_mutations_retain_project_fence(client, project_plugin, tmp_path, monkeypatch, mutation):
    module, ctx, pre, create, _calls, _settings = project_plugin
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    assert pre(str(a), turn="a")
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    monkeypatch.setattr(bridge_type, "call", lambda *args, **kwargs: json.dumps({"error": "transport failed", "operation_uncertain": True}))
    name = "pallium_relay_send" if mutation else "pallium_relay_address"
    assert "error" in json.loads(_mcp_tool(ctx, name, {}, session="session", turn="a"))
    reloaded = create(ctx.state)
    outcome = pre(str(b), turn="b", context=reloaded)
    assert (outcome is None) is mutation
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


def test_finalize_after_reload_defers_until_inflight_operation_finishes(client, project_plugin, tmp_path, monkeypatch):
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
        if path == "/relay/sessions/close":
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
            reloaded.hooks["on_session_finalize"](session_id="session")
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
