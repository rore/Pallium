"""Caller-visible Relay contracts for the experimental Hermes integration."""
from __future__ import annotations

import importlib.util
import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import create_router
from core.relay import RelayService


SCOPE = {"container_ref": "git:example.test/team/relay"}
HOST_EXECUTION = {
    "provider": "anthropic", "model": "ordinary-model", "api_mode": "anthropic_messages",
    "base_url": "https://api.example.test/v1",
}


def turn(client, session="ses_שלום", **extra):
    response = client.post("/relay/turn", json={
        "runtime": "hermes", "session_ref": session, **SCOPE, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def pending(client, **extra):
    return client.get("/relay/pending-candidate", params={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE, **extra,
    })


def send(client, endpoint, payload="Hello שלום 🌍"):
    registered = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    })
    assert registered.status_code == 200, registered.text
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": endpoint, "payload": payload, **SCOPE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def status(client, message):
    response = client.get("/relay/messages/" + message["message_id"], params=SCOPE)
    assert response.status_code == 200, response.text
    return response.json()


def test_hermes_pending_read_and_reply_lifecycle(client):
    assert pending(client).json() is None
    session = turn(client)["session"]
    activation = session["activation"]
    assert activation["runtime"] == "hermes"
    assert activation["behavior"] == "passive"
    assert activation["qualification"] == "unqualified"
    assert activation["qualification_source"] == "none"
    assert activation["supported_evidence"] == []
    assert activation["fallback"] == "unknown"
    message = send(client, session["endpoint_id"])
    before = status(client, message)
    for _ in range(2):
        assert pending(client).json() == {
            "delivery_id": message["deliveries"][0]["delivery_id"],
            "recipient_endpoint_id": session["endpoint_id"], "state": "pending",
        }
    assert status(client, message) == before
    assert pending(client, session_ref="other").json() is None
    assert pending(client, runtime="codex").json() is None
    assert pending(client, container_ref="git:example.test/team/other").json() is None
    claim = turn(client, max_chars=2400, max_messages=1)["deliveries"][0]
    assert claim["payload"] == message["payload"]
    assert claim["recipient_session_ref"] == "ses_שלום"
    assert not claim["content_truncated"]
    assert pending(client).json() is None
    ack_body = {"delivery_id": claim["delivery_id"], "claim_token": claim["claim_token"], **SCOPE}
    assert client.post("/relay/deliveries/ack", json={**ack_body, "claim_token": "wrong"}).status_code == 409
    assert client.post("/relay/deliveries/ack", json=ack_body).status_code == 200
    assert client.post("/relay/deliveries/ack", json=ack_body).status_code == 200
    reply = client.post("/relay/replies", json={
        "delivery_id": claim["delivery_id"], "receipt": claim["receipt"],
        "payload": "reply ✓", **SCOPE,
    })
    assert reply.status_code == 200, reply.text
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", "max_chars": 2400, **SCOPE,
    }).json()["deliveries"][0]
    assert received["payload"] == "reply ✓"
    assert received["sender_runtime"] == "hermes"
    assert received["in_reply_to"] == message["message_id"]
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    assert pending(client).json() is None
    closed = client.post("/relay/sessions/close", json={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
    })
    assert closed.status_code == 200
    assert closed.json()["state"] == "closed"


@pytest.mark.parametrize("field,value", [
    ("runtime", "unknown"), ("runtime", "Hermes"), ("runtime", ""),
    ("session_ref", ""), ("session_ref", " "), ("session_ref", "s\n"),
    ("session_ref", "s" * 256), ("container_ref", ""),
    ("container_ref", "c" * 513),
])
def test_pending_rejects_invalid_scope(client, field, value):
    assert pending(client, **{field: value}).status_code == 422


def test_pending_boundaries_and_unsupported_backend(client):
    assert pending(client, session_ref="s" * 255).status_code == 200
    assert pending(client, container_ref="c" * 512).status_code == 200
    assert client.get("/relay/pending-candidate", params=SCOPE).status_code == 422
    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service))
    with TestClient(app) as unsupported:
        assert pending(unsupported).status_code == 501


def test_stale_hermes_wake_cannot_reopen_closed_endpoint(client):
    endpoint = turn(client)["session"]["endpoint_id"]
    message = send(client, endpoint)
    response = client.post("/relay/sessions/close", json={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
    })
    assert response.status_code == 200
    assert pending(client).json()["recipient_endpoint_id"] == endpoint
    wake = turn(client, register_session=False, max_chars=2400, max_messages=1)
    assert wake["session"]["state"] == "closed"
    assert wake["deliveries"] == []
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending"
    assert delivery["attempts"] == 0
    assert delivery["claim_token"] is None


def test_hermes_callbacks_do_not_use_codex_executor(client):
    callbacks = []

    async def general(operation):
        return operation()

    async def codex(operation):
        pytest.fail("Hermes operation reached the Codex executor")

    service = client.app.state.pallium_service
    app = FastAPI()
    app.include_router(create_router(
        service, relay_service=RelayService(service._storage),
        relay_runner=general, relay_codex_runner=codex,
        relay_ack_callback=lambda result, scope: callbacks.append(result),
    ))
    with TestClient(app) as isolated:
        endpoint = turn(isolated)["session"]["endpoint_id"]
        send(isolated, endpoint)
        claim = turn(isolated, max_chars=2400)["deliveries"][0]
        assert isolated.post("/relay/deliveries/ack", json={
            "delivery_id": claim["delivery_id"], "claim_token": claim["claim_token"], **SCOPE,
        }).status_code == 200
        assert isolated.post("/relay/replies", json={
            "delivery_id": claim["delivery_id"], "receipt": claim["receipt"],
            "payload": "reply", **SCOPE,
        }).status_code == 200
    assert len(callbacks) == 2
    assert all(row["recipient_runtime"] == "hermes" for row in callbacks)


@pytest.fixture
def plugin_context(client, monkeypatch):
    """Exercise public plugin callbacks against the real Relay caller surface."""
    config = {
        "model": {"provider": "anthropic", "default": "ordinary-model",
                  "base_url": "https://api.example.test/v1", "api_mode": "anthropic_messages"},
        "fallback_providers": ["backup-provider"],
        "platform_toolsets": {"cli": ["hermes-cli", "custom-tools"]},
        "tools": {"tool_search": {"enabled": "auto"}},
        "plugins": {"enabled": ["user-plugin", "pallium-hermes-relay"], "entries": {
            "user-plugin": {"settings": {"keep": "value"}},
            "pallium-hermes-relay": {"allow_gateway_injection": True, "settings": {
                "service_url": "http://127.0.0.1:29999", **SCOPE,
            }},
        }},
    }
    host = ModuleType("hermes_cli")
    host.__path__ = []
    host_config = ModuleType("hermes_cli.config")
    host_config.load_config_readonly = lambda: config
    monkeypatch.setitem(sys.modules, "hermes_cli", host)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", host_config)
    monkeypatch.delitem(sys.modules, "hermes_cli.plugin_session", raising=False)
    path = Path(__file__).resolve().parents[1] / "integrations/hermes/__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_test_plugin", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def http(base, method, path, *, body=None, query=None):
        response = client.request(method, path, json=body, params=query)
        if response.status_code >= 400:
            raise RuntimeError(f"Relay HTTP {response.status_code}")
        return response.json()

    module._real_json_request = module._json_request
    monkeypatch.setattr(module, "_json_request", http)

    class State:
        def __init__(self):
            self.values = {}

        def get(self, key, default=None):
            return json.loads(json.dumps(self.values.get(key, default)))

        def set(self, key, value):
            self.values[key] = json.loads(json.dumps(value))

    class Context:
        profile_name = "disposable-profile"
        plugin_id = "pallium-hermes-relay"

        def __init__(self, state):
            self.state, self.hooks, self.middleware = state, {}, {}
            self.tools, self.cleanups, self.injections = {}, [], []

        def get_config(self, key, default=None):
            return config["plugins"]["entries"][self.plugin_id]["settings"].get(key, default)

        def has_capability(self, _name):
            return True

        def register_hook(self, name, callback):
            self.hooks[name] = callback

        def register_middleware(self, kind, callback):
            self.middleware[kind] = callback

        def register_tool(self, **kwargs):
            self.tools[kwargs["name"]] = kwargs["handler"]

        def on_unload(self, callback):
            self.cleanups.append(callback)

        def inject_message(self, text, **kwargs):
            self.injections.append((text, kwargs))
            return True

    contexts = []

    def create(state=None):
        ctx = Context(state or State())
        module.register(ctx)
        contexts.append(ctx)
        return ctx

    yield module, create, config
    for ctx in reversed(contexts):
        for callback in ctx.cleanups:
            callback()


def _await(check):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.02)
    pytest.fail("plugin did not reach the expected observable state")


@pytest.mark.parametrize("capability", [
    "get_config", "register_hook", "register_middleware", "register_tool",
    "inject_message", "on_unload", "state.get", "state.set",
])
@pytest.mark.parametrize("missing", [True, False])
def test_plugin_refuses_missing_public_capability_before_side_effects(plugin_context, capability, missing):
    module, _, _ = plugin_context

    def unexpected(*_args, **_kwargs):
        pytest.fail("unsupported host started configuration, registration or runtime work")

    ctx = SimpleNamespace(
        profile_name="profile_שלום", state=SimpleNamespace(get=unexpected, set=unexpected),
        **{name: unexpected for name in (
            "get_config", "register_hook", "register_middleware", "register_tool",
            "inject_message", "on_unload")},
    )
    target, name = (ctx.state, capability[6:]) if capability.startswith("state.") else (ctx, capability)
    if missing:
        delattr(target, name)
    else:
        setattr(target, name, 42)
    with pytest.raises(ValueError, match="Unsupported Hermes plugin capability: " + capability):
        module.register(ctx)


@pytest.mark.parametrize("capability,value", [
    ("profile_name", None), ("profile_name", ""), ("profile_name", "   "),
    ("profile_name", 123), ("state", None),
])
def test_plugin_refuses_invalid_public_state_before_config(plugin_context, capability, value):
    module, _, _ = plugin_context

    def unexpected(*_args, **_kwargs):
        pytest.fail("unsupported host started configuration or runtime work")

    ctx = SimpleNamespace(
        profile_name="disposable-profile", state=SimpleNamespace(get=unexpected, set=unexpected),
        **{name: unexpected for name in (
            "get_config", "register_hook", "register_middleware", "register_tool",
            "inject_message", "on_unload")},
    )
    setattr(ctx, capability, value)
    with pytest.raises(ValueError, match="Unsupported Hermes plugin capability: " + capability):
        module.register(ctx)


@pytest.mark.parametrize("capability", ["get_config", "profile_name", "state"])
def test_plugin_sanitizes_inaccessible_public_capability(plugin_context, capability):
    module, _, _ = plugin_context

    class Context:
        def __getattr__(self, name):
            if name == capability:
                raise RuntimeError("private context details")
            if name == "profile_name":
                return "disposable-profile"
            if name == "state":
                return SimpleNamespace(get=lambda *_: None, set=lambda *_: None)
            return lambda *_args, **_kwargs: pytest.fail("unsupported host started work")

    with pytest.raises(ValueError) as error:
        module.register(Context())
    assert str(error.value) == "Unsupported Hermes plugin capability: " + capability


def _plugin_wake(client, create, payload="Hello שלום 🌍", *, preparation=None):
    ctx = create()
    with preparation or nullcontext():
        ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום")
    response = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE})
    response.raise_for_status()
    rows = response.json()
    assert len(rows) == 1
    message = send(client, rows[0]["endpoint_id"], payload=payload)
    _await(lambda: ctx.injections)
    marker, target = ctx.injections[0]
    assert target == {"role": "user", "session_key": "ses_שלום"}
    assert message["payload"] not in marker
    assert status(client, message)["deliveries"][0]["attempts"] == 0
    return ctx, marker, message


def _plugin_reply(ctx, args, **trusted):
    calls = []

    def authorized_dispatch(actual):
        assert actual is args
        calls.append(actual)
        # The released registry forwards session_id but drops turn_id.
        return ctx.tools["pallium_relay_reply"](actual, session_id=trusted.get("session_id", ""))

    result = ctx.middleware["tool_execution"](
        tool_name="pallium_relay_reply", args=args, next_call=authorized_dispatch, **trusted,
    )
    assert len(calls) == 1
    return result


@pytest.mark.parametrize("outcome", ["deny", "raise"])
def test_packaged_mcp_preserves_authorization_and_clears_binding(client, mcp_plugin_context, outcome):
    create, _, calls = mcp_plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="session_שלום", turn_id="seed", user_message="hello")
    args = {"recipient": "@peer", "message": "hello"}

    def authorized_dispatch(actual):
        assert actual is args
        if outcome == "raise":
            raise PermissionError("host refusal")
        return "denied by host"

    def invoke():
        return ctx.middleware["tool_execution"](
            tool_name="pallium_relay_send", args=args, session_id="session_שלום", turn_id="send",
            next_call=authorized_dispatch,
        )

    if outcome == "raise":
        with pytest.raises(PermissionError):
            invoke()
    else:
        assert invoke() == "denied by host"
    assert not calls
    assert "error" in json.loads(ctx.tools["pallium_relay_send"](args, session_id="session_שלום"))
    assert not calls


def _request_stage(ctx, request, *, session="ses_שלום", turn="wake", api_request_id="api-wake-1"):
    middleware = ctx.middleware.get("llm_request")
    result = middleware(request=request, session_id=session, turn_id=turn, api_request_id=api_request_id) if middleware else None
    return result["request"] if result else request


def _execute_request(ctx, request, next_call, *, session_id="ses_שלום", turn_id="wake",
                     api_request_id="api-wake-1", **context):
    request = _request_stage(ctx, request, session=session_id, turn=turn_id, api_request_id=api_request_id)
    return ctx.middleware["llm_execution"](request, next_call, session_id=session_id,
        turn_id=turn_id, api_request_id=api_request_id, **context)


def _observe_request(ctx, request, *, session="ses_שלום", turn="wake", api_request_id="api-wake-1"):
    return _execute_request(ctx, request, lambda _actual: "host context observed", api_request_id=api_request_id,
                            session_id=session, turn_id=turn)


def _admit_plugin_wake(ctx, marker, turn, session="ses_שלום"):
    context = ctx.hooks["pre_llm_call"](
        session_id=session, turn_id=turn, user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    _observe_request(ctx, request, session=session, turn=turn, api_request_id="api-" + turn)
    return request


def _persisted_wake(ctx, session="ses_שלום"):
    return next(value for key, value in ctx.state.values.items()
                if key.startswith("wake:") and value.get("session_ref") == session)


def test_native_wake_routes_are_captured_per_conversation(client, plugin_context, monkeypatch):
    import contextvars

    module, create, _ = plugin_context
    current_route = contextvars.ContextVar("native_route", default="")
    native = ModuleType("hermes_cli.plugin_session")
    native.session_key = current_route.get
    monkeypatch.setitem(sys.modules, native.__name__, native)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    ctx = create()
    routes = {"conversation_שלום": "opaque-host-route-a", "conversation_世界": "opaque-host-route-b"}
    for session, route in routes.items():
        token = current_route.set(route)
        try:
            ctx.hooks["pre_llm_call"](session_id=session, turn_id="seed", user_message="seed")
            ctx.hooks["on_session_end"](session_id=session, turn_id="seed")
        finally:
            current_route.reset(token)

    routed = []

    def native_inject(marker, *, role, session_key):
        if session_key in routes.values():
            routed.append((marker, role, session_key))
        return True  # Like the native host, scheduling can succeed before routing.

    monkeypatch.setattr(ctx, "inject_message", native_inject)
    rows = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()
    for session in reversed(routes):
        endpoint = next(row["endpoint_id"] for row in rows if row["session_ref"] == session)
        message = send(client, endpoint, payload="Payload for " + session)
        _await(lambda: any(route == routes[session] for _, _, route in routed))
        marker, role, route = next(item for item in routed if item[2] == routes[session])
        assert role == "user" and route != session
        token = current_route.set(route)
        try:
            request = _admit_plugin_wake(ctx, marker, "wake", session=session)
            observed = []
            _execute_request(ctx, request, lambda actual: observed.append(actual),
                             session_id=session, **HOST_EXECUTION)
            assert message["payload"] in observed[0]["messages"][0]["content"]
            assert all(target not in json.dumps(observed) for target in routes.values())
            delivery = status(client, message)["deliveries"][0]
            assert delivery["recipient_session_ref"] == session and delivery["state"] == "delivered"
            ctx.hooks["on_session_end"](session_id=session, turn_id="wake")
        finally:
            current_route.reset(token)
    assert len(routed) == 2 and current_route.get() == ""


@pytest.mark.parametrize("failure", ["empty", "invalid", "overlong", "accessor-error",
                                     "missing-accessor", "nested-dependency"])
def test_invalid_native_route_retires_old_target_without_claim(
        client, plugin_context, monkeypatch, failure):
    module, create, config = plugin_context
    native = ModuleType("hermes_cli.plugin_session")
    native.session_key = lambda: "opaque-native-route"
    monkeypatch.setitem(sys.modules, native.__name__, native)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="seed")
    if failure == "missing-accessor":
        del native.session_key
    elif failure in {"accessor-error", "nested-dependency"}:
        def unavailable():
            if failure == "nested-dependency":
                raise ModuleNotFoundError("missing dependency", name="host_dependency")
            raise RuntimeError("route unavailable")
        native.session_key = unavailable
    else:
        native.session_key = lambda: {"empty": "", "invalid": "bad\nroute", "overlong": "x" * 1025}[failure]
    assert ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="invalid", user_message="seed") is None
    endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
    progress = threading.Event()
    reads = []

    def current_config():
        if threading.current_thread().name == "pallium-hermes-relay":
            reads.append(True)
            if len(reads) >= 8:
                progress.set()
        return config

    monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", current_config)
    message = send(client, endpoint)
    assert progress.wait(2), "poller did not revisit the session after route invalidation"
    assert not ctx.injections
    assert status(client, message)["deliveries"][0]["attempts"] == 0
    assert not any(key.startswith("wake:") for key in ctx.state.values)


@pytest.mark.parametrize("new_route", ["opaque-replacement-route", ""])
def test_native_route_change_preserves_attempted_wake(client, plugin_context, monkeypatch, new_route):
    module, create, config = plugin_context
    native = ModuleType("hermes_cli.plugin_session")
    native.session_key = lambda: "opaque-original-route"
    monkeypatch.setitem(sys.modules, native.__name__, native)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="seed")
    endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
    message = send(client, endpoint)
    _await(lambda: ctx.injections)
    before = dict(_persisted_wake(ctx))
    assert before["state"] == "injection_attempted"
    assert ctx.injections[0][1]["session_key"] == "opaque-original-route"

    native.session_key = lambda: new_route
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="route-change", user_message="seed")
    progress = threading.Event()
    reads = []

    def current_config():
        if threading.current_thread().name == "pallium-hermes-relay":
            reads.append(True)
            if len(reads) >= 8:
                progress.set()
        return config

    monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", current_config)
    assert progress.wait(2), "poller did not revisit the session after the native route changed"
    assert len(ctx.injections) == 1
    assert _persisted_wake(ctx) == before
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0


@pytest.mark.parametrize("new_route", ["opaque-replacement-route", ""])
def test_native_route_invalidated_at_dispatch_boundary_is_not_used(
        client, plugin_context, monkeypatch, new_route):
    module, create, config = plugin_context
    native = ModuleType("hermes_cli.plugin_session")
    native.session_key = lambda: "opaque-original-route"
    monkeypatch.setitem(sys.modules, native.__name__, native)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="seed")
    set_state = ctx.state.set
    invalidated, revisited = threading.Event(), threading.Event()

    def invalidate_after_fence(key, value):
        set_state(key, value)
        if key.startswith("wake:") and not invalidated.is_set():
            # Synchronous host callbacks can reenter even while the RLock is held.
            native.session_key = lambda: new_route
            ctx.hooks["pre_llm_call"](
                session_id="ses_שלום", turn_id="route-change", user_message="seed")
            invalidated.set()

    reads = []

    def current_config():
        if invalidated.is_set() and threading.current_thread().name == "pallium-hermes-relay":
            reads.append(True)
            if len(reads) >= 8:
                revisited.set()
        return config

    monkeypatch.setattr(ctx.state, "set", invalidate_after_fence)
    monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", current_config)
    endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
    message = send(client, endpoint)
    assert invalidated.wait(2) and revisited.wait(2)
    assert not ctx.injections
    assert _persisted_wake(ctx)["state"] == "injection_attempted"
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0


@pytest.mark.parametrize("phase", ["accessor", "response", "publication"])
@pytest.mark.parametrize("new_route", ["opaque-new-route", ""])
def test_older_registration_cannot_restore_a_superseded_native_route(
        client, plugin_context, monkeypatch, phase, new_route):
    import contextvars

    module, create, config = plugin_context
    route = contextvars.ContextVar("native_registration_route", default="opaque-old-route")
    paused, resume, newer_done = threading.Event(), threading.Event(), threading.Event()
    native = ModuleType("hermes_cli.plugin_session")

    def native_key():
        value = route.get()
        if phase == "accessor" and threading.current_thread().name == "older-registration":
            paused.set()
            assert resume.wait(5)
        return value

    native.session_key = native_key
    monkeypatch.setitem(sys.modules, native.__name__, native)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    ctx = create()
    hook = ctx.hooks["pre_llm_call"]
    hook(session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="seed")
    http, write_state = module._json_request, ctx.state.set
    reentered = []

    def request(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if (phase == "response" and threading.current_thread().name == "older-registration"
                and method == "POST" and path == "/relay/turn"):
            paused.set()
            assert resume.wait(5)
        return result

    def publish(key, value):
        write_state(key, value)
        if (phase == "publication" and key.startswith("session:") and not reentered
                and threading.current_thread().name == "older-registration"):
            reentered.append(True)
            token = route.set(new_route)
            try:
                hook(session_id="ses_שלום", turn_id="newer", user_message="seed")
                newer_done.set()
            finally:
                route.reset(token)

    monkeypatch.setattr(module, "_json_request", request)
    monkeypatch.setattr(ctx.state, "set", publish)
    errors = []

    def register_older():
        try:
            hook(session_id="ses_שלום", turn_id="older", user_message="seed")
        except Exception as error:
            errors.append(error)

    older = threading.Thread(target=register_older, name="older-registration")
    older.start()
    token = route.set(new_route)
    try:
        try:
            if phase == "publication":
                assert newer_done.wait(5)
            else:
                assert paused.wait(5)
                hook(session_id="ses_שלום", turn_id="newer", user_message="seed")
        finally:
            resume.set()
            older.join(5)
        assert not older.is_alive() and not errors
        endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
        message = send(client, endpoint, payload="Payload for the latest registration שלום")
        revisited, reads = threading.Event(), []

        def current_config():
            if threading.current_thread().name == "pallium-hermes-relay":
                reads.append(True)
                if len(reads) >= 8:
                    revisited.set()
            return config

        monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", current_config)
        assert revisited.wait(3)
        if new_route:
            _await(lambda: ctx.injections)
            assert ctx.injections[0][1]["session_key"] == new_route
            request_body = _admit_plugin_wake(ctx, ctx.injections[0][0], "wake")
            observed = []
            _execute_request(ctx, request_body, lambda actual: observed.append(actual), **HOST_EXECUTION)
            assert message["payload"] in observed[0]["messages"][0]["content"]
            assert status(client, message)["deliveries"][0]["state"] == "delivered"
            ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
        else:
            assert not ctx.injections
            assert status(client, message)["deliveries"][0]["attempts"] == 0
            assert not any(key.startswith("wake:") for key in ctx.state.values)
    finally:
        route.reset(token)


@pytest.mark.parametrize("ambient_profile", ["default", "sibling"])
def test_poller_keeps_named_profile_after_foreground_context_ends(
        client, plugin_context, monkeypatch, ambient_profile):
    import contextvars
    from copy import deepcopy

    module, create, config = plugin_context
    profile = contextvars.ContextVar("hermes_profile", default=ambient_profile)
    other = deepcopy(config)
    if ambient_profile == "default":
        other["plugins"]["enabled"].remove("pallium-hermes-relay")
    else:
        other["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["container_ref"] = "sibling-scope"
    changed_read = threading.Event()

    def current_config():
        if profile.get() != "named-profile":
            return other
        if config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["container_ref"] != SCOPE["container_ref"]:
            changed_read.set()
        return config

    monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config_readonly", current_config)
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    token = profile.set("named-profile")
    try:
        ctx = create()
        ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="seed")
    finally:
        profile.reset(token)

    endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
    message = send(client, endpoint, payload="Profile-scoped reply שלום 🌍")
    _await(lambda: ctx.injections)
    assert profile.get() == ambient_profile
    assert len(ctx.injections) == 1
    marker, target = ctx.injections[0]
    assert target == {"role": "user", "session_key": "ses_שלום"}
    unclaimed = status(client, message)["deliveries"][0]
    assert unclaimed["attempts"] == 0
    assert ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wrong-profile", user_message=marker) is None
    assert status(client, message)["deliveries"][0] == unclaimed
    token = profile.set("named-profile")
    try:
        request = _admit_plugin_wake(ctx, marker, "wake")
        observed = []
        _execute_request(ctx, request, lambda actual: observed.append(actual), **HOST_EXECUTION)
        assert message["payload"] in observed[0]["messages"][0]["content"]
        assert status(client, message)["deliveries"][0]["state"] == "delivered"
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    finally:
        profile.reset(token)

    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["container_ref"] = "changed-scope"
    later = send(client, endpoint, payload="Must remain fenced")
    assert changed_read.wait(1), "poller must reread current profile configuration"
    assert len(ctx.injections) == 1
    assert status(client, later)["deliveries"][0]["attempts"] == 0
    assert other["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["container_ref"] != "changed-scope"


@pytest.mark.parametrize("host_accepted", [True, False], ids=["scheduled", "refused"])
def test_host_boundary_keeps_unobserved_delivery_unclaimed(
        client, plugin_context, monkeypatch, host_accepted):
    """Host acceptance is scheduling evidence, not proof of either Hermes topology."""
    module, create, _ = plugin_context
    monkeypatch.setattr(module, "POLL_SECONDS", .01)
    original_http = module._json_request
    positive_reads, ack_bodies = [], []
    third_candidate, release_candidate, injected = (
        threading.Event(), threading.Event(), threading.Event())

    def observed_http(base, method, path, **kwargs):
        result = original_http(base, method, path, **kwargs)
        if path == "/relay/deliveries/ack":
            ack_bodies.append(kwargs["body"])
        if (path == "/relay/pending-candidate" and result
                and kwargs["query"]["session_ref"] == "ses_שלום"):
            positive_reads.append(result)
            if len(positive_reads) == 3:
                # Two positive poll iterations have completed before this barrier.
                third_candidate.set()
                if not release_candidate.wait(5):
                    raise TimeoutError("test did not release the observed candidate")
        return result

    monkeypatch.setattr(module, "_json_request", observed_http)
    ctx = create()

    def schedule_marker(text, **kwargs):
        ctx.injections.append((text, kwargs))
        injected.set()
        return host_accepted

    monkeypatch.setattr(ctx, "inject_message", schedule_marker)
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום")
    endpoint = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()[0]["endpoint_id"]
    message = send(client, endpoint, payload="Queued context שלום 🌍 — original delivery")
    delivery_id = message["deliveries"][0]["delivery_id"]
    try:
        assert third_candidate.wait(3), "poller did not revisit the positive candidate"
        assert injected.is_set()
        assert positive_reads == [{
            "delivery_id": delivery_id, "recipient_endpoint_id": endpoint, "state": "pending",
        }] * 3
        assert len(ctx.injections) == 1
        marker, target = ctx.injections[0]
        assert target == {"role": "user", "session_key": "ses_שלום"}
        assert message["payload"] not in marker
        wake = _persisted_wake(ctx)
        assert wake["delivery_id"] == delivery_id and wake["endpoint_id"] == endpoint
        assert wake["state"] == ("injection_attempted" if host_accepted else "injection_refused")
        before = status(client, message)["deliveries"][0]
        assert before["delivery_id"] == delivery_id
        assert before["recipient_session_ref"] == "ses_שלום"
        assert before["state"] == "pending" and before["attempts"] == 0
        assert before["claim_token"] is None and before["receipt"] is None
        assert before["delivered_at"] is None and ack_bodies == []

        # A different host session cannot consume the original queued marker.
        assert ctx.hooks["pre_llm_call"](
            session_id="ses_other", turn_id="foreign", user_message=marker) is None
        assert status(client, message)["deliveries"][0] == before
        assert ack_bodies == []
    finally:
        release_candidate.set()

    if not host_accepted:
        return

    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="delayed", user_message=marker)["context"]
    claimed = status(client, message)["deliveries"][0]
    assert claimed["state"] == "claimed" and claimed["attempts"] == 1
    assert claimed["delivered_at"] is None and ack_bodies == []
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    expanded = _request_stage(ctx, request, turn="delayed")
    assert message["payload"] in expanded["messages"][0]["content"]
    assert status(client, message)["deliveries"][0]["state"] == "claimed"
    _observe_request(ctx, expanded, turn="delayed")
    _observe_request(ctx, expanded, turn="delayed", api_request_id="retry")
    assert len(ack_bodies) == 1 and ack_bodies[0]["delivery_id"] == delivery_id
    delivered = status(client, message)["deliveries"][0]
    assert delivered["state"] == "delivered" and delivered["attempts"] == 1
    assert delivered["delivered_at"] is not None
    assert len(ctx.injections) == 1

    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="delayed")
    injected.clear()
    next_message = send(client, endpoint, payload="Next delivery ✓")
    assert injected.wait(3), "turn end did not permit the next delivery"
    assert len(ctx.injections) == 2
    next_marker, next_target = ctx.injections[1]
    assert next_marker != marker and next_target == target
    assert _persisted_wake(ctx)["delivery_id"] == next_message["deliveries"][0]["delivery_id"]
    assert status(client, next_message)["deliveries"][0]["attempts"] == 0
    _admit_plugin_wake(ctx, next_marker, "next")
    assert [body["delivery_id"] for body in ack_bodies] == [
        delivery_id, next_message["deliveries"][0]["delivery_id"],
    ]
    assert status(client, next_message)["deliveries"][0]["state"] == "delivered"


def test_turn_end_retires_admitted_no_reply_wakes_for_successive_deliveries(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    endpoint = message["deliveries"][0]["recipient_endpoint_id"]
    for index in range(3):
        turn_id = f"wake-{index}"
        if index:
            marker = ctx.injections[index][0]
        _admit_plugin_wake(ctx, marker, turn_id)
        if index:
            ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id=f"wake-{index - 1}")
            assert _persisted_wake(ctx)["state"] == "admitted"
        assert status(client, message)["deliveries"][0]["state"] == "delivered"
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id=turn_id)
        assert _persisted_wake(ctx)["state"] == "complete"
        assert status(client, message)["deliveries"][0]["state"] == "delivered"
        if index < 2:
            message = send(client, endpoint, payload=f"next {index}")
            _await(lambda: len(ctx.injections) == index + 2)


@pytest.mark.parametrize("session,turn", [("ses_שלום", ""), ("other", "wake"), ("ses_שלום", "old")])
def test_inexact_turn_end_keeps_the_admitted_wake(client, plugin_context, session, turn):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    _admit_plugin_wake(ctx, marker, "wake")
    ctx.hooks["on_session_end"](session_id=session, turn_id=turn)
    assert _persisted_wake(ctx)["state"] == "admitted"
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    assert _persisted_wake(ctx)["state"] == "complete"


def test_turn_end_is_scoped_to_one_of_two_hermes_sessions(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker_a, message_a = _plugin_wake(client, create)
    ctx.hooks["pre_llm_call"](session_id="ses_two", turn_id="seed", user_message="seed")
    sessions = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()
    endpoint_b = next(row["endpoint_id"] for row in sessions if row["session_ref"] == "ses_two")
    message_b = send(client, endpoint_b, payload="second session")
    _await(lambda: len(ctx.injections) == 2)
    marker_b = ctx.injections[1][0]
    _admit_plugin_wake(ctx, marker_a, "turn-a")
    _admit_plugin_wake(ctx, marker_b, "turn-b", session="ses_two")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-a")
    assert _persisted_wake(ctx)["state"] == "complete"
    assert _persisted_wake(ctx, "ses_two")["state"] == "admitted"
    assert status(client, message_a)["deliveries"][0]["state"] == "delivered"
    assert status(client, message_b)["deliveries"][0]["state"] == "delivered"
    ctx.hooks["on_session_end"](session_id="ses_two", turn_id="turn-b")
    assert _persisted_wake(ctx, "ses_two")["state"] == "complete"


def test_late_direct_reply_cannot_replace_a_new_admitted_wake(client, plugin_context, monkeypatch):
    module, create, _ = plugin_context
    ctx, marker, first = _plugin_wake(client, create)
    _admit_plugin_wake(ctx, marker, "turn-a")
    entered, release = threading.Event(), threading.Event()
    original = module._json_request

    def delayed_reply(base, method, path, **kwargs):
        result = original(base, method, path, **kwargs)
        if path == "/relay/replies":
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(module, "_json_request", delayed_reply)
    args = {"delivery_id": first["deliveries"][0]["delivery_id"], "payload": "late reply"}
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(
        _plugin_reply(ctx, args, session_id="ses_שלום", turn_id="turn-a")))
    worker.start()
    assert entered.wait(3)
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-a")
    endpoint = first["deliveries"][0]["recipient_endpoint_id"]
    second = send(client, endpoint, payload="second delivery")
    _await(lambda: len(ctx.injections) == 2)
    second_marker = ctx.injections[1][0]
    _admit_plugin_wake(ctx, second_marker, "turn-b")
    assert _persisted_wake(ctx)["state"] == "admitted"
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert "turn changed" in outcome[0]
    assert _persisted_wake(ctx)["delivery_id"] == second["deliveries"][0]["delivery_id"]
    assert _persisted_wake(ctx)["state"] == "admitted"
    assert status(client, second)["deliveries"][0]["state"] == "delivered"


def test_late_mcp_reply_cannot_replace_a_new_admitted_wake(client, plugin_context, mcp_plugin_context, monkeypatch):
    module = plugin_context[0]
    create, _, _ = mcp_plugin_context
    bridge_type = sys.modules[module.__name__ + ".mcp_bridge"].RelayMcpBridge
    original = bridge_type.call
    entered, release = threading.Event(), threading.Event()

    def delayed_reply(self, name, arguments, identity, reply=None):
        result = original(self, name, arguments, identity, reply)
        if name == "pallium_relay_reply":
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(bridge_type, "call", delayed_reply)
    ctx, marker, first = _plugin_wake(client, create)
    _admit_plugin_wake(ctx, marker, "turn-a")
    args = {"delivery_id": first["deliveries"][0]["delivery_id"], "message": "late MCP reply"}
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(
        _mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="turn-a")))
    worker.start()
    assert entered.wait(3)
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-a")
    endpoint = first["deliveries"][0]["recipient_endpoint_id"]
    second = send(client, endpoint, payload="second MCP delivery")
    _await(lambda: len(ctx.injections) == 2)
    _admit_plugin_wake(ctx, ctx.injections[1][0], "turn-b")
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert json.loads(outcome[0])["message_id"] == "relay-msg-test"
    assert _persisted_wake(ctx)["delivery_id"] == second["deliveries"][0]["delivery_id"]
    assert _persisted_wake(ctx)["state"] == "admitted"


def test_late_ack_after_turn_end_keeps_the_uncertain_persisted_fence(client, plugin_context, monkeypatch):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="turn-a", user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    entered, release = threading.Event(), threading.Event()
    original = module._json_request

    def delayed_ack(base, method, path, **kwargs):
        result = original(base, method, path, **kwargs)
        if path == "/relay/deliveries/ack":
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(module, "_json_request", delayed_ack)
    worker = threading.Thread(target=lambda: _observe_request(
        ctx, request, turn="turn-a", api_request_id="api-turn-a"))
    worker.start()
    assert entered.wait(3)
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-a")
    assert _persisted_wake(ctx)["state"] == "claimed"
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    assert _persisted_wake(ctx)["state"] == "claimed"
    assert ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="turn-b", user_message=marker,
    ) is None


def test_stale_end_cannot_unfence_a_late_claim_for_the_current_turn(client, plugin_context, monkeypatch):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    entered, release = threading.Event(), threading.Event()
    original = module._json_request

    def delayed_claim(base, method, path, **kwargs):
        result = original(base, method, path, **kwargs)
        if path == "/relay/turn" and method == "POST" and kwargs.get("body", {}).get("register_session") is False:
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(module, "_json_request", delayed_claim)
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="turn-b", user_message=marker)))
    worker.start()
    assert entered.wait(3)
    assert _persisted_wake(ctx)["state"] == "claim_attempted"
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-b")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="turn-a")
    assert _persisted_wake(ctx)["state"] == "claim_attempted"
    assert _persisted_wake(ctx)["turn_id"] == "turn-b"
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert outcome == [None]
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "claimed"
    assert delivery["delivered_at"] is None


@pytest.mark.parametrize("surface", ["direct", "mcp"])
def test_turn_end_persist_failure_does_not_clear_admitted_state(client, plugin_context, monkeypatch, request, surface):
    module, create, _ = plugin_context
    bridge_calls = []
    if surface == "mcp":
        create, _, bridge_calls = request.getfixturevalue("mcp_plugin_context")
    ctx, marker, message = _plugin_wake(client, create)
    _admit_plugin_wake(ctx, marker, "wake")
    original = ctx.state.set
    original_http = module._json_request
    reply_requests = []

    def observe_reply(base, method, path, **kwargs):
        if path == "/relay/replies":
            reply_requests.append(kwargs)
        return original_http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", observe_reply)

    def fail_completion(key, value):
        if key.startswith("wake:") and value.get("state") == "complete":
            raise OSError("state unavailable")
        original(key, value)

    monkeypatch.setattr(ctx.state, "set", fail_completion)
    with pytest.raises(OSError, match="state unavailable"):
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    assert _persisted_wake(ctx)["state"] == "admitted"
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    delivery_id = message["deliveries"][0]["delivery_id"]
    if surface == "mcp":
        result = _mcp_tool(ctx, "pallium_relay_reply", {"delivery_id": delivery_id, "message": "ended reply"},
                           session="ses_שלום", turn="wake")
        assert "error" in json.loads(result)
    else:
        result = _plugin_reply(ctx, {"delivery_id": delivery_id, "payload": "ended reply"},
                               session_id="ses_שלום", turn_id="wake")
        assert "refused" in result
    assert not reply_requests and not bridge_calls
    monkeypatch.setattr(ctx.state, "set", original)
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    assert _persisted_wake(ctx)["state"] == "complete"


def test_late_refused_injection_cannot_rewrite_a_replaced_wake(client, plugin_context):
    _, create, _ = plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    endpoint = next(value["endpoint_id"] for key, value in ctx.state.values.items()
                    if key.startswith("session:") and value["session_ref"] == "ses_שלום")
    replaced = threading.Event()

    def refuse_after_replacement(_text, **_kwargs):
        key, wake = next((key, value) for key, value in ctx.state.values.items()
                         if key.startswith("wake:") and value.get("session_ref") == "ses_שלום")
        replacement = dict(wake, delivery_id="replacement-delivery", nonce="replacement-nonce")
        ctx.state.set(key, replacement)
        replaced.set()
        return False

    ctx.inject_message = refuse_after_replacement
    send(client, endpoint)
    assert replaced.wait(3)
    assert _persisted_wake(ctx)["delivery_id"] == "replacement-delivery"
    assert _persisted_wake(ctx)["state"] == "injection_attempted"


@pytest.mark.parametrize("failure", [
    "stripped", "partial", "wrong_session", "wrong_turn", "historical",
    "profile_changed", "owned_config_changed", "missing_request_id",
])
def test_plugin_never_acks_unobserved_context(client, plugin_context, failure):
    _, create, config = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    hook = ctx.hooks["pre_llm_call"]
    assert hook(session_id="ses_other", turn_id="wake", user_message=marker) is None
    assert status(client, message)["deliveries"][0]["attempts"] == 0
    assert hook(session_id="ses_שלום", turn_id="wake", user_message="quoted " + marker) is None
    assert status(client, message)["deliveries"][0]["attempts"] == 0
    context = hook(session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    assert hook(session_id="ses_שלום", turn_id="wake", user_message=marker)["context"] == context
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "claimed"
    assert delivery["claim_token"] not in context
    assert delivery["receipt"] not in context
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    if failure == "stripped":
        request["messages"][0]["content"] = marker
    if failure == "partial":
        request["messages"][0]["content"] = marker + "\n" + context[:-1]
    if failure == "historical":
        request["messages"].append({"role": "user", "content": "a later input"})
    if failure == "profile_changed":
        ctx.profile_name = "other-profile"
    if failure == "owned_config_changed":
        config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["service_url"] = "http://127.0.0.1:29998"
    _observe_request(
        ctx, request,
        session="ses_other" if failure == "wrong_session" else "ses_שלום",
        turn="other" if failure == "wrong_turn" else "wake",
        api_request_id="" if failure == "missing_request_id" else "api-wake-1",
    )
    after = status(client, message)["deliveries"][0]
    assert after["state"] == "claimed"
    assert after["delivered_at"] is None


def test_execution_without_request_identity_does_not_ack(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    assert ctx.middleware["llm_execution"](
        request, lambda _actual: "synthetic result", session_id="ses_שלום",
        turn_id="wake", **HOST_EXECUTION,
    ) == "synthetic result"
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


def test_plugin_retains_uncertain_fence_on_reload(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    for callback in ctx.cleanups:
        callback()
    reloaded = create(ctx.state)
    reloaded.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="after-reload", user_message="seed")
    time.sleep(.6)
    assert reloaded.injections == []
    assert status(client, message)["deliveries"][0]["attempts"] == 0


def test_plugin_admission_then_host_bound_reply(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    calls = []

    _observe_request(ctx, request)
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    _observe_request(ctx, request)

    def provider(actual):
        assert actual is not request
        assert message["payload"] in actual["messages"][0]["content"]
        assert status(client, message)["deliveries"][0]["state"] == "delivered"
        calls.append(actual)
        return "provider accepted"

    for _ in range(2):
        assert _execute_request(ctx,
            request, provider, session_id="ses_שלום", turn_id="wake", **HOST_EXECUTION,
        ) == "provider accepted"
    assert len(calls) == 2
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    delivery_id = message["deliveries"][0]["delivery_id"]
    forged = {"delivery_id": delivery_id, "payload": "reply ✓",
              "session_id": "ses_שלום", "turn_id": "wake"}
    assert "refused" in _plugin_reply(ctx, forged, session_id="other", turn_id="other")
    assert "refused" in _plugin_reply(ctx, forged)
    assert "refused" in ctx.tools["pallium_relay_reply"](forged, session_id="ses_שלום")
    assert "refused" in ctx.tools["pallium_relay_reply"](forged, session_id="ses_שלום", turn_id="wake")
    assert "sent" in _plugin_reply(ctx, forged, session_id="ses_שלום", turn_id="wake")
    assert "refused" in _plugin_reply(ctx, forged, session_id="ses_שלום", turn_id="wake")
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    }).json()["deliveries"]
    assert len(received) == 1
    assert received[0]["payload"] == "reply ✓"
    assert received[0]["sender_session_ref"] == "ses_שלום"


def test_provider_failure_after_host_context_observation_keeps_admission(client, plugin_context):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    def provider(_actual):
        raise OSError("provider failed after admission")

    with pytest.raises(OSError, match="provider failed after admission"):
        _execute_request(ctx,
            request, provider, session_id="ses_שלום", turn_id="wake", api_request_id="api-wake-1",
        )
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("failure", ["before-ack", "lost-ack-response", "admission-persistence"])
def test_ack_failure_can_retry_and_duplicate_observation_is_idempotent(client, plugin_context, monkeypatch, failure):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    original = module._json_request
    set_state = ctx.state.set
    ack_calls = []
    fail = True

    def fail_ack(base, method, path, **kwargs):
        nonlocal fail
        if path == "/relay/deliveries/ack":
            ack_calls.append(path)
            if fail and failure == "before-ack":
                raise OSError("ack unavailable")
        result = original(base, method, path, **kwargs)
        if path == "/relay/deliveries/ack" and fail and failure == "lost-ack-response":
            raise OSError("ack response lost")
        return result

    def fail_admission(key, value):
        if fail and failure == "admission-persistence" and key.startswith("wake:") and value.get("state") == "admitted":
            raise OSError("admission persistence failed")
        set_state(key, value)

    monkeypatch.setattr(module, "_json_request", fail_ack)
    monkeypatch.setattr(ctx.state, "set", fail_admission)
    if failure == "admission-persistence":
        with pytest.raises(OSError, match="admission persistence failed"):
            _observe_request(ctx, request)
    else:
        _observe_request(ctx, request)
    assert status(client, message)["deliveries"][0]["state"] == ("claimed" if failure == "before-ack" else "delivered")
    assert "refused" in _plugin_reply(ctx, {
        "delivery_id": message["deliveries"][0]["delivery_id"], "payload": "not admitted",
    }, session_id="ses_שלום", turn_id="wake")
    fail = False
    _observe_request(ctx, request, api_request_id="api-retry-2")
    _observe_request(ctx, request, api_request_id="api-retry-2")
    assert ack_calls == ["/relay/deliveries/ack", "/relay/deliveries/ack"]
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    with pytest.raises(OSError, match="provider failed"):
        _execute_request(ctx,
            request, lambda _actual: (_ for _ in ()).throw(OSError("provider failed")),
            session_id="ses_שלום", turn_id="wake", **HOST_EXECUTION,
        )
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


def test_plugin_accepts_coexisting_plugins_and_provider_configuration(plugin_context):
    _, create, config = plugin_context
    config["plugins"]["enabled"].append("another-user-plugin")
    config["model"] = {"provider": "openai", "default": "different-model",
                        "base_url": "https://api.example.test/v1", "api_mode": "responses"}
    config["fallback_providers"] = ["provider-two"]
    config["tools"]["tool_search"]["enabled"] = "auto"
    config["platform_toolsets"]["cli"].append("other-tools")
    assert create()


def test_plugin_still_refuses_changed_owned_scope(plugin_context):
    _, create, config = plugin_context
    ctx = create()
    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["service_url"] = "http://127.0.0.1:29998"
    assert ctx.hooks["pre_llm_call"](session_id="scope-change", turn_id="seed", user_message="hello") is None
    assert ctx.state.values == {}


@pytest.mark.parametrize("request_kind", ["messages", "text_parts", "string_parts", "input", "input_text", "input_string"])
def test_raw_execution_admits_public_request_formats(client, plugin_context, request_kind):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    text = marker + "\n\n" + context
    content = text
    if request_kind in {"input_text", "text_parts"}:
        content = [{"type": "input_text" if request_kind == "input_text" else "text", "text": text},
                   {"type": "image", "url": "data:unchanged"}]
    elif request_kind == "string_parts":
        content = [text, {"type": "image", "url": "data:unchanged"}]
    key = "messages" if request_kind in {"messages", "text_parts", "string_parts"} else "input"
    request = {key: text if request_kind == "input_string" else [{"role": "user", "content": content}]}
    request["metadata"] = {"keep": ["unrelated", 2]}
    original = json.loads(json.dumps(request))
    downstream = []
    assert _execute_request(ctx,
        request, lambda actual: downstream.append(actual) or "response", session_id="ses_שלום",
        turn_id="wake", api_request_id="request-current",
    ) == "response"
    assert len(downstream) == 1 and downstream[0] is not request
    assert message["payload"] in module._current_user_text(downstream[0])
    assert request == original
    assert downstream[0]["metadata"] is request["metadata"]
    if isinstance(content, list):
        assert downstream[0][key][0]["content"][-1] is content[-1]
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    assert "pre_api_request" not in ctx.hooks


@pytest.mark.parametrize("effective", ["absent", "rewritten", "malformed_latest", "nontext_latest"])
def test_raw_execution_never_admits_historical_or_rewritten_context(client, plugin_context, effective):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    previous = {"role": "user", "content": marker + "\n\n" + context}
    request = {} if effective == "absent" else {"input": [previous]}
    if effective == "rewritten":
        request = {"input": [{"role": "user", "content": "rewritten request"}]}
    elif effective == "malformed_latest":
        request["input"].append({"role": "user", "content": {"text": "unsupported"}})
    elif effective == "nontext_latest":
        request["input"].append({"role": "user", "content": [{"type": "image", "text": previous["content"]}]})
    _observe_request(ctx, request)
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


@pytest.mark.parametrize("size", [1, 1600, 1601, 2400, 16000])
def test_plugin_payload_boundaries_never_ack_a_preview(client, plugin_context, size):
    _, create, _ = plugin_context
    payload = "é" * size
    ctx, marker, message = _plugin_wake(client, create, payload)
    result = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )
    assert len(result["context"]) < 10000
    request = {"messages": [{
        "role": "user", "content": marker + "\n\n" + result["context"],
    }]}
    _observe_request(ctx, request)
    _execute_request(ctx,
        request, lambda actual: "provider accepted", session_id="ses_שלום",
        turn_id="wake", **HOST_EXECUTION,
    )
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "delivered"
    assert delivery["delivered_at"] is not None


@pytest.mark.parametrize("payload,accepted,relay_admission_clock", [
    ("", False, "native"), ("  ", False, "native"), (None, False, "native"),
    ("é" * 2400, True, "native"), ("é" * 2401, False, "native"),
    (None, False, "semantic"),
], indirect=["relay_admission_clock"])
def test_plugin_reply_boundaries(client, plugin_context, payload, accepted, relay_admission_clock):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(
        client, create, preparation=relay_admission_clock(client.app.state.pallium_service._storage),
    )
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{
        "role": "user", "content": marker + "\n\n" + context,
    }]}
    _observe_request(ctx, request)
    _execute_request(ctx,
        request, lambda actual: "provider accepted", session_id="ses_שלום",
        turn_id="wake", **HOST_EXECUTION,
    )
    result = _plugin_reply(ctx, {
        "delivery_id": message["deliveries"][0]["delivery_id"], "payload": payload,
    }, session_id="ses_שלום", turn_id="wake")
    assert ("sent" in result) == accepted
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    }).json()["deliveries"]
    assert len(received) == int(accepted)
    if accepted:
        assert received[0]["payload"] == payload


def test_plugin_preserves_other_tool_execution(plugin_context):
    _, create, _ = plugin_context
    ctx = create()
    args = {"input": "value"}
    response = {"result": "unchanged"}
    calls = []

    def downstream(actual):
        assert actual is args
        calls.append(actual)
        return response

    assert ctx.middleware["tool_execution"](
        tool_name="other_tool", args=args, next_call=downstream,
    ) is response
    assert len(calls) == 1

    def failing(_args):
        raise OSError("tool failed")

    with pytest.raises(OSError):
        ctx.middleware["tool_execution"](tool_name="other_tool", args=args, next_call=failing)


@pytest.mark.parametrize("outcome", ["denied", "error"])
def test_reply_context_preserves_host_authorization_and_resets(client, plugin_context, outcome):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"messages": [{
        "role": "user", "content": marker + "\n\n" + context,
    }]}
    _observe_request(ctx, request)
    _execute_request(ctx,
        request, lambda actual: "provider accepted", session_id="ses_שלום",
        turn_id="wake", **HOST_EXECUTION,
    )
    args = {"delivery_id": message["deliveries"][0]["delivery_id"], "payload": "reply"}

    def authorization(actual):
        assert actual is args
        if outcome == "error":
            raise OSError("authorization failed")
        return {"error": "host denied tool"}

    def invoke():
        return ctx.middleware["tool_execution"](
            tool_name="pallium_relay_reply", args=args, next_call=authorization,
            session_id="ses_שלום", turn_id="wake",
        )

    if outcome == "error":
        with pytest.raises(OSError):
            invoke()
    else:
        assert invoke() == {"error": "host denied tool"}
    assert "refused" in ctx.tools["pallium_relay_reply"](args, session_id="ses_שלום")
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    }).json()["deliveries"]
    assert received == []
    assert "sent" in _plugin_reply(ctx, args, session_id="ses_שלום", turn_id="wake")

@pytest.fixture
def mcp_plugin_context(plugin_context, monkeypatch):
    module, create, config = plugin_context
    settings = config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]
    settings.update(mcp_python=sys.executable, mcp_repo=str(Path(__file__).resolve().parents[1]),
                    actor_ref="hermes-test", visibility="private")
    calls = []
    bridge_module = ModuleType(module.__name__ + ".mcp_bridge")

    class Bridge:
        def __init__(self, **_config):
            self.catalog = [
                {"name": "pallium_relay_send", "description": "Send", "parameters": {
                    "properties": {"message": {}, "recipient": {}},
                }},
                {"name": "pallium_relay_reply", "description": "Reply", "parameters": {
                    "properties": {"delivery_id": {}, "message": {}},
                }},
                {"name": "pallium_relay_address", "description": "Self", "parameters": {"properties": {}}},
            ]
            if _config.get("memory_enabled", False):
                self.catalog.append({"name": "pallium_remember", "description": "Remember", "parameters": {
                    "properties": {"text": {}, "type": {}},
                }})

        def call(self, name, arguments, identity, reply=None):
            calls.append((name, dict(arguments), tuple(identity), dict(reply) if reply else None))
            return json.dumps({"message_id": "relay-msg-test"})

        def close(self):
            pass

    bridge_module.RelayMcpBridge = Bridge
    monkeypatch.setitem(sys.modules, bridge_module.__name__, bridge_module)
    return create, config, calls


def _mcp_tool(ctx, name, args, session="session_שלום", turn="turn-1"):
    return ctx.middleware["tool_execution"](
        tool_name=name, args=args, session_id=session, turn_id=turn,
        next_call=lambda actual: ctx.tools[name](actual, session_id=session),
    )


def test_memory_opt_in_reaches_bridge_and_change_refuses_calls(mcp_plugin_context):
    create, config, calls = mcp_plugin_context
    settings = config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]
    assert "pallium_remember" not in create().tools
    settings["memory_enabled"] = True
    ctx = create()
    assert "pallium_remember" in ctx.tools
    ctx.hooks["pre_llm_call"](session_id="session_שלום", turn_id="seed", user_message="hello")
    result = _mcp_tool(ctx, "pallium_remember", {"text": "note ✓", "type": "note"})
    assert "message_id" in json.loads(result)
    count = len(calls)
    settings["memory_enabled"] = False
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_remember", {"text": "refused", "type": "note"}))
    assert len(calls) == count


@pytest.mark.parametrize("invalid", ["true", 1, None, {}])
def test_memory_setting_requires_boolean(mcp_plugin_context, invalid):
    create, config, _ = mcp_plugin_context
    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["memory_enabled"] = invalid
    with pytest.raises(ValueError, match="boolean"):
        create()


def test_packaged_mcp_binds_each_conversation_and_never_model_identity(client, mcp_plugin_context):
    from concurrent.futures import ThreadPoolExecutor

    create, config, calls = mcp_plugin_context
    ctx = create()
    for session in ("session_שלום", "session_世界"):
        orientation = ctx.hooks["pre_llm_call"](session_id=session, turn_id="seed", user_message="hello")
        assert json.loads(orientation["context"].split("— ", 1)[1].split("]\n", 1)[0])["thread_ref"] == session
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda session: _mcp_tool(
            ctx, "pallium_relay_send", {"recipient": "@peer", "message": "hello 🌍"}, session=session),
            ("session_שלום", "session_世界")))
    assert all("message_id" in json.loads(result) for result in results)
    assert {call[2] for call in calls} == {("session_שלום", "turn-1"), ("session_世界", "turn-1")}
    count = len(calls)
    for args in (
        {"recipient": "@peer", "message": "x", "sender_session_ref": "other"},
        {"recipient": "@peer", "message": "x", "container_ref": "elsewhere"},
        {"recipient": "@peer", "message": "x", "receipt": "private"},
    ):
        assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_send", args))
    assert "error" in json.loads(ctx.tools["pallium_relay_send"](
        {"recipient": "@peer", "message": "x"}, session_id="session_שלום"))
    assert len(calls) == count
    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["actor_ref"] = "changed"
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}))
    assert len(calls) == count


@pytest.mark.parametrize("session,turn", [("", "turn"), ("unknown", "turn"), ("session_שלום", ""),
                                        ("session_שלום", "bad\nturn")])
def test_packaged_mcp_refuses_missing_or_unregistered_host_context(client, mcp_plugin_context, session, turn):
    create, _, calls = mcp_plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="session_שלום", turn_id="seed", user_message="hello")
    result = _mcp_tool(ctx, "pallium_relay_address", {}, session=session, turn=turn)
    assert "error" in json.loads(result)
    assert not calls


def test_packaged_mcp_reply_receipt_stays_in_host_memory(client, mcp_plugin_context):
    create, _, calls = mcp_plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    rendered = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"messages": [{"role": "user", "content": marker + "\n" + rendered}]}
    _observe_request(ctx, request)
    _execute_request(ctx, request, lambda actual: "provider", session_id="ses_שלום",
                                    turn_id="wake", **HOST_EXECUTION)
    delivery = status(client, message)["deliveries"][0]
    args = {"delivery_id": delivery["delivery_id"], "message": "reply שלום"}
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="wrong"))
    result = _mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="wake")
    assert json.loads(result)["message_id"] == "relay-msg-test"
    assert len(calls) == 1
    assert calls[0][1] == args
    assert calls[0][3]["delivery_id"] == delivery["delivery_id"]
    receipt = calls[0][3]["receipt"]
    assert isinstance(receipt, str) and 0 < len(receipt) <= 64
    assert delivery["receipt"] is None  # Delivered status deliberately redacts the private receipt.
    assert receipt not in rendered and receipt not in result and receipt not in json.dumps(args)
    assert "error" in json.loads(_mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="wake"))
    assert len(calls) == 1


def test_cached_session_refreshes_after_a_day_without_claiming_mail(
    client, plugin_context, mcp_plugin_context, monkeypatch,
):
    import storage.sqlite_relay as sqlite_relay

    module, _, _ = plugin_context
    create, _, calls = mcp_plugin_context
    current = datetime.now(timezone.utc)
    clock = [current - timedelta(hours=25)]
    original_now = sqlite_relay._now
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: clock[0] if value is None else original_now(value))
    ctx = create()
    hook = ctx.hooks["pre_llm_call"]
    hook(session_id="ses_שלום", turn_id="seed", user_message="hello")
    before = client.get("/relay/sessions", params={**SCOPE, "include_inactive": True}).json()[0]
    clock[0] = current
    message = send(client, before["endpoint_id"])
    assert client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json() == []
    requests = []
    http = module._json_request

    def record(base, method, path, **kwargs):
        if method == "POST" and path == "/relay/turn":
            requests.append(kwargs["body"])
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", record)
    assert hook(session_id="ses_שלום", turn_id="ordinary", user_message="still here")
    refreshed = client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json()[0]
    assert refreshed["endpoint_id"] == before["endpoint_id"]
    assert refreshed["scope_generation"] == before["scope_generation"]
    assert refreshed["last_seen_at"] > before["last_seen_at"]
    assert requests == [{
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
        "max_chars": 1, "max_response_chars": 1, "max_messages": 1,
        "previous_container_ref": SCOPE["container_ref"],
        "previous_endpoint_id": before["endpoint_id"],
        "previous_scope_generation": before["scope_generation"],
    }]
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0
    assert delivery["claim_token"] is None and delivery["receipt"] is None
    assert "message_id" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="ses_שלום"))
    assert len(calls) == 1
    assert calls[0][2] == ("ses_שלום", "turn-1")
    _await(lambda: ctx.injections)
    _admit_plugin_wake(ctx, ctx.injections[0][0], "wake")
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("changed", [
    {"state": "closed"}, {"destination_health": "unreachable"},
    {"endpoint_id": "relay-session-" + "f" * 32}, {"runtime": "codex"},
    {"session_ref": "other"}, {"container_ref": "other"},
    {"scope_generation": True}, {"scope_generation": -1}, {"scope_generation": 1.5},
    None, "missing", "duplicate", "missing_generation",
])
def test_cached_refresh_refuses_changed_or_malformed_session(client, plugin_context, monkeypatch, changed):
    module, create, _ = plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="hello")
    http = module._json_request
    posts, reads = [], []

    def changed_session(base, method, path, **kwargs):
        if method == "POST":
            posts.append(path)
        result = http(base, method, path, **kwargs)
        if path == "/relay/sessions":
            reads.append(kwargs["query"])
            if changed is None:
                return None
            if changed == "missing":
                return []
            if changed == "duplicate":
                return result * 2
            if changed == "missing_generation":
                result[0].pop("scope_generation")
                return result
            return [{**result[0], **changed}]
        return result

    monkeypatch.setattr(module, "_json_request", changed_session)
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="later", user_message="hello") is None
    assert reads == [{"runtime": "hermes", "session_ref": "ses_שלום", **SCOPE, "include_inactive": "true"}]
    assert posts == []


@pytest.mark.parametrize("race", ["closed", "missing", "moved", "replaced", "generation", "unreachable"])
@pytest.mark.parametrize("source", ["ordinary", "wake"])
def test_cached_refresh_uses_atomic_endpoint_and_generation_fence(client, plugin_context, monkeypatch, race, source):
    from storage.sqlite_schema import RelayEndpointGenerationRecord, RelaySessionRecord

    module, create, _ = plugin_context
    ctx = create()
    hook = ctx.hooks["pre_llm_call"]
    hook(session_id="ses_שלום", turn_id="seed", user_message="hello")
    before = client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json()[0]
    if source == "wake":
        message = send(client, before["endpoint_id"])
        _await(lambda: ctx.injections)
    storage = client.app.state.pallium_service._storage
    http = module._json_request
    attempted = []

    def race_after_lookup(base, method, path, **kwargs):
        if method == "POST" and path == "/relay/turn" and kwargs["body"].get("register_session") is not False:
            attempted.append(kwargs["body"])
            with storage._relay_session_factory.begin() as db:
                row = db.get(RelaySessionRecord, before["endpoint_id"])
                if race == "missing":
                    db.delete(row)
                elif race == "moved":
                    row.container_ref = "git:example.test/team/elsewhere"
                elif race == "replaced":
                    row.id = "relay-session-" + "f" * 32
                elif race == "generation":
                    db.add(RelayEndpointGenerationRecord(endpoint_id=row.id, generation=1))
                else:
                    row.state = race
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", race_after_lookup)
    result = hook(session_id="ses_שלום", turn_id="later", user_message=(
        ctx.injections[0][0] if source == "wake" else "fresh ordinary activity"))
    assert len(attempted) == 1
    assert attempted[0]["previous_endpoint_id"] == before["endpoint_id"]
    assert attempted[0]["previous_scope_generation"] == before["scope_generation"]
    rows = client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes", "include_inactive": True}).json()
    if race in {"missing", "moved"}:
        assert rows == []
    elif race == "unreachable":
        assert rows[0]["endpoint_id"] == before["endpoint_id"]
        assert rows[0]["destination_health"] == "active"
        assert rows[0]["last_seen_at"] > before["last_seen_at"]
    else:
        assert rows[0]["last_seen_at"] == before["last_seen_at"]
        assert rows[0]["state"] == ("closed" if race == "closed" else "recent")
        if race == "replaced":
            assert rows[0]["endpoint_id"] != before["endpoint_id"]
        if race == "generation":
            assert rows[0]["scope_generation"] == 1
    if source == "wake":
        delivery = status(client, message)["deliveries"][0]
        assert delivery["state"] == ("claimed" if race == "unreachable" else "pending")
        assert delivery["attempts"] == (1 if race == "unreachable" else 0)
        assert _persisted_wake(ctx)["state"] == ("claimed" if race == "unreachable" else "injection_attempted")
        assert (result is not None) == (race == "unreachable")


@pytest.mark.parametrize("payload", ['"\\\n\r\t' * 3200, "🌍" * 16000], ids=["escaped", "astral"])
def test_full_payload_with_maximum_metadata_then_reload_and_next_delivery(
    client, plugin_context, monkeypatch, payload,
):
    module, create, config = plugin_context
    container = "git:" + ('"\\' * 254)
    session = "s" + ('"\\' * 127)
    turn_id = "t" + ('"\\' * 127)
    monkeypatch.setitem(SCOPE, "container_ref", container)
    config["plugins"]["entries"]["pallium-hermes-relay"]["settings"]["container_ref"] = container
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id=session, turn_id="seed", user_message="hello")
    endpoint = client.get("/relay/sessions", params=SCOPE).json()[0]["endpoint_id"]
    sender = "p" + ('"\\' * 127)
    assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": sender, **SCOPE}).status_code == 200
    response = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": sender,
        "recipient": endpoint, "payload": payload, **SCOPE,
    })
    assert response.status_code == 200, response.text
    message = response.json()
    _await(lambda: ctx.injections)
    marker = ctx.injections[0][0]
    placeholder = ctx.hooks["pre_llm_call"](session_id=session, turn_id=turn_id, user_message=marker)["context"]
    assert len(placeholder) < 10000 and payload not in placeholder
    request = {"messages": [{"role": "user", "content": marker + "\n" + placeholder}]}
    expanded = _request_stage(ctx, request, session=session, turn=turn_id)
    context = expanded["messages"][0]["content"].split(marker + "\n", 1)[1]
    fields = json.loads(context.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert fields["payload"] == payload and fields["payload_total_chars"] == 16000
    assert fields["host_session_id"] == session and fields["host_turn_id"] == turn_id
    assert fields["recipient_container_ref"] == container and fields["sender_session_ref"] == sender
    assert len(context) <= module.MAX_CONTEXT_CHARS
    assert status(client, message)["deliveries"][0]["state"] == "claimed"
    _observe_request(ctx, expanded, session=session, turn=turn_id)
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    ctx.hooks["on_session_end"](session_id=session, turn_id=turn_id)
    for cleanup in ctx.cleanups:
        cleanup()
    import storage.sqlite_relay as sqlite_relay

    original_now = sqlite_relay._now
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: later if value is None else original_now(value))
    reloaded = create(ctx.state)
    reloaded.hooks["pre_llm_call"](session_id=session, turn_id="resumed", user_message="hello again")
    next_message = send(client, endpoint, "next short delivery")
    _await(lambda: reloaded.injections)
    _admit_plugin_wake(reloaded, reloaded.injections[0][0], "next", session=session)
    assert status(client, next_message)["deliveries"][0]["state"] == "delivered"
    assert _plugin_reply(reloaded, {
        "delivery_id": next_message["deliveries"][0]["delivery_id"], "payload": "received ✓",
    }, session_id=session, turn_id="next") == "Relay reply sent."


@pytest.mark.parametrize("payload", ["", " \t\n", "unsafe\x01", "x" * 16001],
                         ids=["empty", "blank", "control", "over-max"])
def test_rejected_send_leaves_plugin_session_ready_for_valid_delivery(client, plugin_context, payload):
    _, create, _ = plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="hello")
    endpoint = client.get("/relay/sessions", params=SCOPE).json()[0]["endpoint_id"]
    assert client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    }).status_code == 200
    refused = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": endpoint, "payload": payload, **SCOPE,
    })
    assert refused.status_code == 422, refused.text
    assert pending(client).json() is None
    message = send(client, endpoint, "valid after rejection")
    _await(lambda: ctx.injections)
    _admit_plugin_wake(ctx, ctx.injections[0][0], "valid")
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("corrupt", ["truncated", "offset", "total", "oversized", "missing", "malformed"])
def test_invalid_full_claim_stays_fenced_after_lease_expiry_and_reload(client, plugin_context, monkeypatch, corrupt):
    import storage.sqlite_relay as sqlite_relay

    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    http = module._json_request

    def corrupt_claim(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if method == "POST" and path == "/relay/turn" and kwargs["body"].get("register_session") is False:
            delivery = result["deliveries"][0]
            if corrupt == "truncated":
                delivery["content_truncated"] = True
            elif corrupt == "offset":
                delivery["payload_offset"] = 1
            elif corrupt == "total":
                delivery["payload_total_chars"] += 1
            elif corrupt == "oversized":
                delivery.update(payload="x" * 16001, payload_total_chars=16001)
            elif corrupt == "missing":
                result["deliveries"] = []
            else:
                delivery["payload"] = None
        return result

    monkeypatch.setattr(module, "_json_request", corrupt_claim)
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert _persisted_wake(ctx)["state"] == "claim_attempted"
    assert status(client, message)["deliveries"][0]["attempts"] == 1
    for cleanup in ctx.cleanups:
        cleanup()
    original_now = sqlite_relay._now
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: later if value is None else original_now(value))
    reloaded = create(ctx.state)
    reloaded.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="resumed", user_message="hello again")
    assert pending(client).json()["state"] == "pending"
    reloaded.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake-again", user_message=marker)
    assert reloaded.injections == []
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "claimed" and delivery["attempts"] == 1
    assert delivery["delivered_at"] is None


@pytest.mark.parametrize("encoding", ["utf8", "escaped", "oversized"])
def test_real_http_response_bound_handles_full_unicode_and_rejects_overflow(plugin_context, encoding):
    module, _, _ = plugin_context
    expected = {"payload": "🌍" * 16000}
    wire = (json.dumps(expected, ensure_ascii=encoding == "escaped").encode("utf-8")
            if encoding != "oversized" else b" " * (256 * 1024 + 1))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            if encoding == "oversized":
                with pytest.raises(ValueError, match="response exceeded"):
                    module._real_json_request(base, "GET", "/full")
            else:
                assert module._real_json_request(base, "GET", "/full") == expected
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_idle_session_wake_refreshes_before_claim_without_an_ordinary_turn(
    client, plugin_context, mcp_plugin_context, monkeypatch,
):
    import storage.sqlite_relay as sqlite_relay

    module, _, _ = plugin_context
    create, _, calls = mcp_plugin_context
    current = datetime.now(timezone.utc)
    clock = [current - timedelta(hours=25)]
    original_now = sqlite_relay._now
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: clock[0] if value is None else original_now(value))
    ctx = create()
    hook = ctx.hooks["pre_llm_call"]
    hook(session_id="ses_שלום", turn_id="seed", user_message="hello")
    before = client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json()[0]
    clock[0] = current
    message = send(client, before["endpoint_id"], "incoming after a day")
    _await(lambda: ctx.injections)
    assert client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json() == []
    http = module._json_request
    registrations = []

    def observe_refresh(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if method == "POST" and path == "/relay/turn" and kwargs["body"].get("register_session") is not False:
            registrations.append(kwargs["body"])
            assert result["deliveries"] == []
            assert _persisted_wake(ctx)["state"] == "injection_attempted"
            delivery = status(client, message)["deliveries"][0]
            assert delivery["state"] == "pending" and delivery["attempts"] == 0
            assert delivery["receipt"] is None and delivery["claim_token"] is None
        return result

    monkeypatch.setattr(module, "_json_request", observe_refresh)
    _admit_plugin_wake(ctx, ctx.injections[0][0], "idle-wake")
    assert len(registrations) == 1
    assert registrations[0] == {
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
        "max_chars": 1, "max_response_chars": 1, "max_messages": 1,
        "previous_container_ref": SCOPE["container_ref"],
        "previous_endpoint_id": before["endpoint_id"],
        "previous_scope_generation": before["scope_generation"],
    }
    refreshed = client.get("/relay/sessions", params={**SCOPE, "runtime": "hermes"}).json()[0]
    assert refreshed["endpoint_id"] == before["endpoint_id"]
    assert refreshed["scope_generation"] == before["scope_generation"]
    assert refreshed["last_seen_at"] > before["last_seen_at"]
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    assert "message_id" in json.loads(_mcp_tool(ctx, "pallium_relay_address", {}, session="ses_שלום", turn="idle-wake"))
    assert calls[0][2] == ("ses_שלום", "idle-wake")
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="idle-wake")
    monkeypatch.setattr(module, "_json_request", http)
    next_message = send(client, before["endpoint_id"], "next wake")
    _await(lambda: len(ctx.injections) == 2)
    _admit_plugin_wake(ctx, ctx.injections[1][0], "next")
    assert status(client, next_message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("change", ["missing", "replaced"])
@pytest.mark.parametrize("phase", ["before-helper", "after-lookup", "after-refresh"])
def test_wake_refresh_never_falls_back_to_registration_or_overwrites_changed_host_scope(
    client, plugin_context, monkeypatch, change, phase,
):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    http, get, set_state = module._json_request, ctx.state.get, ctx.state.set
    posts = []
    changed = False

    def change_scope():
        nonlocal changed
        if changed:
            return
        changed = True
        key = next(key for key in ctx.state.values if key.startswith("session:"))
        if change == "missing":
            ctx.state.values.pop(key)
        else:
            ctx.state.values[key]["endpoint_id"] = "relay-session-" + "f" * 32

    def get_state(key, default=None):
        result = get(key, default)
        if phase == "before-helper" and key.startswith("session:") and threading.current_thread() is threading.main_thread():
            change_scope()
        return result

    def write_state(key, value):
        set_state(key, value)
        if phase == "after-refresh" and key.startswith("session:"):
            change_scope()

    def request(base, method, path, **kwargs):
        if method == "POST":
            posts.append(kwargs["body"])
        result = http(base, method, path, **kwargs)
        if phase == "after-lookup" and path == "/relay/sessions":
            change_scope()
        return result

    monkeypatch.setattr(ctx.state, "get", get_state)
    monkeypatch.setattr(ctx.state, "set", write_state)
    monkeypatch.setattr(module, "_json_request", request)
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert changed
    assert len(posts) == (1 if phase == "after-refresh" else 0)
    assert all(post.get("previous_endpoint_id") for post in posts)
    assert _persisted_wake(ctx)["state"] == "injection_attempted"
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0


@pytest.mark.parametrize("failure", ["lookup", "lost-refresh-response"])
def test_failed_wake_refresh_keeps_unclaimed_mail_retryable(client, plugin_context, monkeypatch, failure):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    http = module._json_request

    def fail_refresh(base, method, path, **kwargs):
        if failure == "lookup" and path == "/relay/sessions":
            raise OSError("session lookup unavailable")
        result = http(base, method, path, **kwargs)
        if failure == "lost-refresh-response" and method == "POST" and path == "/relay/turn":
            raise OSError("registration response lost")
        return result

    monkeypatch.setattr(module, "_json_request", fail_refresh)
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert _persisted_wake(ctx)["state"] == "injection_attempted"
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0
    monkeypatch.setattr(module, "_json_request", http)
    _admit_plugin_wake(ctx, marker, "wake")
    assert status(client, message)["deliveries"][0]["attempts"] == 1
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


def test_concurrent_matching_wake_callbacks_refresh_but_claim_once(client, plugin_context, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    http = module._json_request
    barrier = threading.Barrier(2)
    registrations, claims = [], []

    def simultaneous_refresh(base, method, path, **kwargs):
        if method == "POST" and path == "/relay/turn":
            if kwargs["body"].get("register_session") is False:
                claims.append(kwargs["body"])
            else:
                registrations.append(kwargs["body"])
                barrier.wait(timeout=3)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", simultaneous_refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ctx.hooks["pre_llm_call"], session_id="ses_שלום", turn_id="wake", user_message=marker)
                   for _ in range(2)]
        outcomes = [future.result(timeout=5) for future in futures]
    assert len(registrations) == 2 and len(claims) == 1
    assert sum(outcome is not None for outcome in outcomes) == 1
    assert status(client, message)["deliveries"][0]["attempts"] == 1
    context = next(outcome["context"] for outcome in outcomes if outcome is not None)
    _observe_request(ctx, {"messages": [{"role": "user", "content": marker + "\n" + context}]})
    assert status(client, message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("change", ["profile", "wake", "state"])
def test_wake_rechecks_host_fences_after_successful_refresh(client, plugin_context, monkeypatch, change):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    http = module._json_request
    posts = []

    def change_after_refresh(base, method, path, **kwargs):
        result = http(base, method, path, **kwargs)
        if method == "POST" and path == "/relay/turn":
            posts.append(kwargs["body"])
            if change == "profile":
                ctx.profile_name = "changed-profile"
            else:
                key = next(key for key in ctx.state.values if key.startswith("wake:"))
                ctx.state.values[key]["nonce" if change == "wake" else "state"] = (
                    "changed-nonce" if change == "wake" else "injection_refused")
        return result

    monkeypatch.setattr(module, "_json_request", change_after_refresh)
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert len(posts) == 1 and posts[0].get("previous_endpoint_id")
    assert posts[0].get("register_session") is not False
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0


@pytest.mark.parametrize("check", ["bounded-hook", "complete-admission"])
def test_full_payload_survives_default_host_hook_spill(client, plugin_context, check):
    _, create, _ = plugin_context
    payload = "🌍" * 16000
    ctx, marker, message = _plugin_wake(client, create, payload)
    context = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    if check == "bounded-hook":
        assert len(context) <= 10000
        assert payload not in context
    else:
        request = {"messages": [{"role": "user", "content": marker + "\n" + context[:10000]}]}
        observed = []
        _execute_request(ctx, request, lambda actual: observed.append(actual))
        assert status(client, message)["deliveries"][0]["state"] == "delivered"
        assert payload in observed[0]["messages"][0]["content"]


@pytest.mark.parametrize("change,relay_admission_clock", [
    pytest.param(change, "semantic", id=change)
    for change in (
        "missing", "rewritten", "duplicate", "split", "historical", "tool", "system",
        "nontext", "duplicate-history", "wrong-marker",
    )
], indirect=["relay_admission_clock"])
def test_request_stage_never_reconstructs_missing_or_ambiguous_context(
    client, plugin_context, change, relay_admission_clock,
):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(
        client, create,
        preparation=relay_admission_clock(client.app.state.pallium_service._storage, expected_admissions=1),
    )
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    text = marker + "\n" + token
    request = {"messages": [{"role": "user", "content": text}]}
    if change in {"missing", "rewritten", "duplicate", "wrong-marker"}:
        request["messages"][0]["content"] = {
            "missing": marker, "rewritten": marker + "\n" + token[:-1],
            "duplicate": text + token, "wrong-marker": marker[:-1] + "\n" + token,
        }[change]
    elif change == "split":
        middle = len(token) // 2
        request["messages"][0]["content"] = [marker, token[:middle], token[middle:]]
    elif change == "historical":
        request["messages"].append({"role": "user", "content": "later input"})
    elif change in {"tool", "system"}:
        request["messages"] = [{"role": change, "content": token}, {"role": "user", "content": marker}]
    elif change == "nontext":
        request["messages"][0]["content"] = [{"type": "image", "text": text}]
    else:
        request["messages"].insert(0, {"role": "user", "content": token})
    original = json.loads(json.dumps(request))
    assert _request_stage(ctx, request) is request
    assert request == original
    _observe_request(ctx, request)
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


@pytest.mark.parametrize("change", ["session", "turn", "api-request", "profile", "scope", "container", "state", "ended"])
def test_request_stage_requires_live_exact_host_identity(client, plugin_context, change):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"input": marker + "\n" + token}
    identity = {"session": "ses_שלום", "turn": "wake", "api_request_id": "request-1"}
    if change in {"session", "turn", "api-request"}:
        identity[{"api-request": "api_request_id"}.get(change, change)] = "" if change == "api-request" else "foreign"
    elif change == "profile":
        ctx.profile_name = "foreign-profile"
    elif change in {"scope", "container", "state"}:
        key = next(key for key in ctx.state.values if key.startswith("wake:" if change == "state" else "session:"))
        field = {"scope": "endpoint_id", "container": "container_ref", "state": "state"}[change]
        ctx.state.values[key][field] = {
            "scope": "relay-session-" + "f" * 32, "container": "foreign", "state": "claim_attempted",
        }[change]
    else:
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    assert _request_stage(ctx, request, **identity) is request
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


def test_request_stage_idempotence_precedes_tokens_inside_payload(client, plugin_context, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    module, create, _ = plugin_context
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="hello")
    endpoint = client.get("/relay/sessions", params=SCOPE).json()[0]["endpoint_id"]
    assert client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": "sender", **SCOPE}).status_code == 200
    delivery_id, nonce = "relay-delivery-" + "a" * 32, "known-test-nonce"
    token = module._placeholder(delivery_id, nonce)
    payload = "Literal placeholder in untrusted data: " + token
    monkeypatch.setattr(sqlite_relay, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="a" * 32)))
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda _size: nonce)
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": endpoint,
        "payload": payload, **SCOPE,
    })
    assert response.status_code == 200, response.text
    message = response.json()
    _await(lambda: ctx.injections)
    marker = ctx.injections[0][0]
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"] == token
    request = {"input": marker + "\n" + token}
    expanded = _request_stage(ctx, request)
    assert payload in module._current_user_text(expanded)
    assert _request_stage(ctx, expanded) is expanded
    _observe_request(ctx, expanded)
    retry = _request_stage(ctx, request, api_request_id="retry-request")
    assert retry == expanded and retry is not expanded
    assert _request_stage(ctx, retry, api_request_id="retry-request") is retry
    assert status(client, message)["deliveries"][0]["attempts"] == 1


@pytest.mark.parametrize("stage", ["later-llm-request", "pre-api"])
def test_later_host_stages_can_remove_expanded_context_without_ack(client, plugin_context, stage):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    original = {"messages": [{"role": "user", "content": marker + "\n" + token}]}
    expanded = _request_stage(ctx, original)
    assert expanded is not original
    changed = {**expanded, "messages": [{"role": "user", "content": marker}]}
    calls = []
    ctx.middleware["llm_execution"](changed, lambda actual: calls.append((stage, actual)),
        session_id="ses_שלום", turn_id="wake", api_request_id="request-1")
    assert calls == [(stage, changed)]
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


@pytest.mark.parametrize("surface,relay_admission_clock", [
    ("direct", "native"), ("mcp", "native"), ("direct", "semantic"),
], indirect=["relay_admission_clock"])
def test_reply_keeps_context_for_fresh_provider_continuation_without_authority(
    client, plugin_context, monkeypatch, request, surface, relay_admission_clock,
):
    module, create, _ = plugin_context
    calls = None
    if surface == "mcp":
        create, _, calls = request.getfixturevalue("mcp_plugin_context")
    ctx, marker, message = _plugin_wake(
        client, create, preparation=relay_admission_clock(client.app.state.pallium_service._storage),
    )
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    original = {"messages": [{"role": "user", "content": marker + "\n" + token}]}
    http = module._json_request
    mutations = []

    def record_mutations(base, method, path, **kwargs):
        if method == "POST":
            mutations.append(path)
        return http(base, method, path, **kwargs)

    monkeypatch.setattr(module, "_json_request", record_mutations)
    _observe_request(ctx, original)
    delivery_id = message["deliveries"][0]["delivery_id"]
    args = {"delivery_id": delivery_id, "message" if surface == "mcp" else "payload": "reply ✓"}
    result = (_mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="wake")
              if surface == "mcp" else _plugin_reply(ctx, args, session_id="ses_שלום", turn_id="wake"))
    assert ("message_id" in json.loads(result)) if surface == "mcp" else result == "Relay reply sent."
    before = list(mutations)
    continuation = {"messages": [*original["messages"], {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "reply-call", "type": "function", "function": {
                "name": "pallium_relay_reply", "arguments": json.dumps(args),
            },
        }],
    }, {"role": "tool", "tool_call_id": "reply-call", "content": result}]}
    snapshot = json.loads(json.dumps(continuation))
    expanded = _request_stage(ctx, continuation, api_request_id="post-reply")
    assert message["payload"] in module._current_user_text(expanded)
    assert continuation == snapshot
    assert expanded["messages"][1] is continuation["messages"][1]
    assert expanded["messages"][2] is continuation["messages"][2]
    observed = []
    ctx.middleware["llm_execution"](expanded, lambda actual: observed.append(actual),
        session_id="ses_שלום", turn_id="wake", api_request_id="post-reply")
    assert observed == [expanded] and mutations == before
    refused = (_mcp_tool(ctx, "pallium_relay_reply", args, session="ses_שלום", turn="wake")
               if surface == "mcp" else _plugin_reply(ctx, args, session_id="ses_שלום", turn_id="wake"))
    assert "error" in json.loads(refused) if surface == "mcp" else "refused" in refused
    if calls is not None:
        assert len(calls) == 1
    next_message = send(client, message["deliveries"][0]["recipient_endpoint_id"], "next pending wake")
    _await(lambda: len(ctx.injections) == 2)
    assert _request_stage(ctx, continuation, api_request_id="old-continuation") == expanded
    ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    assert _request_stage(ctx, continuation, api_request_id="ended") is continuation
    assert ctx.middleware["llm_execution"](expanded, lambda _actual: pytest.fail("ended turn reached provider"),
        session_id="ses_שלום", turn_id="wake", api_request_id="ended") is None
    assert _persisted_wake(ctx)["delivery_id"] == next_message["deliveries"][0]["delivery_id"]
    assert _persisted_wake(ctx)["state"] == "injection_attempted"
    _admit_plugin_wake(ctx, ctx.injections[1][0], "next")
    assert status(client, next_message)["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("change", ["session", "turn", "api-request", "profile", "scope", "container", "end", "unload", "reload"])
def test_postreply_context_view_obeys_scope_and_lifetime(client, plugin_context, change):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"input": marker + "\n" + token}
    expanded = _request_stage(ctx, request)
    _observe_request(ctx, expanded)
    assert _plugin_reply(ctx, {"delivery_id": message["deliveries"][0]["delivery_id"], "payload": "reply"},
                         session_id="ses_שלום", turn_id="wake") == "Relay reply sent."
    identity = {"session": "ses_שלום", "turn": "wake", "api_request_id": "continued"}
    target = ctx
    if change in {"session", "turn", "api-request"}:
        identity[{"api-request": "api_request_id"}.get(change, change)] = "" if change == "api-request" else "foreign"
    elif change == "profile":
        ctx.profile_name = "foreign-profile"
    elif change in {"scope", "container"}:
        key = next(key for key in ctx.state.values if key.startswith("session:"))
        ctx.state.values[key]["endpoint_id" if change == "scope" else "container_ref"] = (
            "relay-session-" + "f" * 32 if change == "scope" else "foreign")
    elif change == "end":
        ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
    else:
        for cleanup in ctx.cleanups:
            cleanup()
        if change == "reload":
            target = create(ctx.state)
    assert _request_stage(target, request, **identity) is request
    assert ctx.middleware["llm_execution"](expanded, lambda _actual: pytest.fail("stale context reached provider"),
        session_id=identity["session"], turn_id=identity["turn"], api_request_id=identity["api_request_id"]) is None
    if change == "reload":
        assert "refused" in _plugin_reply(target, {
            "delivery_id": message["deliveries"][0]["delivery_id"], "payload": "stale reply",
        }, session_id="ses_שלום", turn_id="wake")


def test_request_stage_does_not_mutate_state_or_call_service(client, plugin_context, monkeypatch):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"input": marker + "\n" + token}
    state = json.loads(json.dumps(ctx.state.values))
    http = module._json_request

    def no_request_stage_http(*args, **kwargs):
        if threading.current_thread() is threading.main_thread():
            pytest.fail("request stage called service")
        return http(*args, **kwargs)

    monkeypatch.setattr(module, "_json_request", no_request_stage_http)
    monkeypatch.setattr(ctx.state, "set", lambda *_args, **_kwargs: pytest.fail("request stage mutated state"))
    expanded = _request_stage(ctx, request)
    assert expanded is not request and message["payload"] in module._current_user_text(expanded)
    assert ctx.state.values == state


@pytest.mark.parametrize("change", ["profile", "wake", "scope", "ended"])
def test_request_stage_rechecks_fences_before_returning_expansion(client, plugin_context, monkeypatch, change):
    module, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"input": marker + "\n" + token}
    replace = module._replace_current_text

    def change_after_copy(*args):
        result = replace(*args)
        assert result is not None
        if change == "profile":
            ctx.profile_name = "foreign-profile"
        elif change == "ended":
            ctx.hooks["on_session_end"](session_id="ses_שלום", turn_id="wake")
        else:
            key = next(key for key in ctx.state.values if key.startswith("wake:" if change == "wake" else "session:"))
            ctx.state.values[key]["nonce" if change == "wake" else "endpoint_id"] = "changed"
        return result

    monkeypatch.setattr(module, "_replace_current_text", change_after_copy)
    assert _request_stage(ctx, request) is request
    assert status(client, message)["deliveries"][0]["state"] == "claimed"


@pytest.mark.parametrize("admit", [False, True], ids=["claimed", "admitted"])
def test_unload_disables_old_callbacks_and_reload_preserves_uncertain_authority_fence(client, plugin_context, admit):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    token = ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker)["context"]
    request = {"input": marker + "\n" + token}
    expanded = _request_stage(ctx, request)
    if admit:
        _observe_request(ctx, expanded)
    for cleanup in ctx.cleanups:
        cleanup()
    assert _request_stage(ctx, request) is request
    assert ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert ctx.middleware["llm_execution"](expanded, lambda _actual: pytest.fail("unloaded callback reached provider"),
        session_id="ses_שלום", turn_id="wake", api_request_id="old-request") is None
    reloaded = create(ctx.state)
    reloaded.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="resumed", user_message="hello again")
    assert reloaded.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="wake", user_message=marker) is None
    assert _request_stage(reloaded, request) is request
    assert "refused" in _plugin_reply(reloaded, {
        "delivery_id": message["deliveries"][0]["delivery_id"], "payload": "stale authority",
    }, session_id="ses_שלום", turn_id="wake")
    delivery = status(client, message)["deliveries"][0]
    assert delivery["attempts"] == 1 and delivery["state"] == ("delivered" if admit else "claimed")
