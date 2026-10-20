"""Caller-visible Relay contracts for the experimental Hermes integration."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import create_router
from core.relay import RelayService


SCOPE = {"container_ref": "git:example.test/team/relay"}
HOST_EXECUTION = {
    "provider": "custom", "model": "pallium-local", "api_mode": "chat_completions",
    "base_url": "http://127.0.0.1:29998/v1",
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
        "model": {"provider": "custom", "default": "pallium-local",
                  "base_url": "http://127.0.0.1:29998/v1", "api_mode": "chat_completions"},
        "fallback_providers": [],
        "platform_toolsets": {"cli": ["hermes-cli"]},
        "tools": {"tool_search": {"enabled": "off"}},
        "plugins": {"enabled": ["pallium-hermes-relay"], "entries": {
            "pallium-hermes-relay": {"allow_gateway_injection": True, "settings": {
                "service_url": "http://127.0.0.1:29999", **SCOPE,
                "experimental_frozen_local_stub": True,
            }},
        }},
    }
    host = ModuleType("hermes_cli")
    host.__path__ = []
    host_config = ModuleType("hermes_cli.config")
    host_config.load_config_readonly = lambda: config
    monkeypatch.setitem(sys.modules, "hermes_cli", host)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", host_config)
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


def _plugin_wake(client, create, payload="Hello שלום 🌍"):
    ctx = create()
    ctx.hooks["pre_llm_call"](session_id="ses_שלום", turn_id="seed", user_message="seed")
    ctx.hooks["on_session_end"](session_id="ses_שלום")
    rows = client.get("/relay/sessions", params={"runtime": "hermes", **SCOPE}).json()
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


@pytest.mark.parametrize("failure", [
    "stripped", "wrong_session", "wrong_turn", "provider_error", "historical",
    "profile_changed", "config_changed", "wrong_provider",
])
def test_plugin_never_acks_unproven_admission(client, plugin_context, failure):
    module, create, config = plugin_context
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
    text = marker + "\n\n" + context
    request = {"model": "pallium-local", "messages": [{"role": "user", "content": text}]}
    if failure == "stripped":
        request["messages"][0]["content"] = marker
    if failure == "historical":
        request["messages"].append({"role": "user", "content": "a later input"})
    if failure == "profile_changed":
        ctx.profile_name = "other-profile"
    if failure == "config_changed":
        config["plugins"]["enabled"].append("other-plugin")

    def downstream(actual):
        assert actual is request
        if failure == "provider_error":
            raise OSError("local provider failed")
        return "provider result"

    kwargs = {"session_id": "ses_other" if failure == "wrong_session" else "ses_שלום",
              "turn_id": "other" if failure == "wrong_turn" else "wake", **HOST_EXECUTION}
    if failure == "wrong_provider":
        kwargs["base_url"] = "http://127.0.0.1:29997/v1"
    if failure == "provider_error":
        with pytest.raises(OSError):
            ctx.middleware["llm_execution"](request, downstream, **kwargs)
    else:
        ctx.middleware["llm_execution"](request, downstream, **kwargs)
    after = status(client, message)["deliveries"][0]
    assert after["state"] == "claimed"
    assert after["delivered_at"] is None


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
    request = {"model": "pallium-local", "messages": [{"role": "user", "content": marker + "\n\n" + context}]}
    calls = []

    def provider(actual):
        assert actual is request
        assert status(client, message)["deliveries"][0]["state"] == ("delivered" if calls else "claimed")
        calls.append(actual)
        return "provider accepted"

    for _ in range(2):
        assert ctx.middleware["llm_execution"](
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


@pytest.mark.parametrize("invalid", ["opt_in", "permission", "plugins", "remote", "fallback", "tool_search"])
def test_plugin_refuses_unqualified_configuration(plugin_context, invalid):
    _, create, config = plugin_context
    entry = config["plugins"]["entries"]["pallium-hermes-relay"]
    if invalid == "opt_in":
        entry["settings"].pop("experimental_frozen_local_stub")
    elif invalid == "permission":
        entry["allow_gateway_injection"] = False
    elif invalid == "plugins":
        config["plugins"]["enabled"].append("other-plugin")
    elif invalid == "remote":
        config["model"]["base_url"] = "https://example.test/v1"
    elif invalid == "tool_search":
        config["tools"]["tool_search"]["enabled"] = "auto"
    else:
        config["fallback_providers"] = ["remote"]
    with pytest.raises(ValueError):
        create()


@pytest.mark.parametrize("size,admitted", [(1, True), (1600, True), (1601, False), (16000, False)])
def test_plugin_payload_boundaries_never_ack_a_preview(client, plugin_context, size, admitted):
    _, create, _ = plugin_context
    payload = "é" * size
    ctx, marker, message = _plugin_wake(client, create, payload)
    result = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )
    if admitted:
        assert payload in result["context"]
        request = {"model": "pallium-local", "messages": [{
            "role": "user", "content": marker + "\n\n" + result["context"],
        }]}
        ctx.middleware["llm_execution"](
            request, lambda actual: "provider accepted", session_id="ses_שלום",
            turn_id="wake", **HOST_EXECUTION,
        )
    else:
        assert result is None
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == ("delivered" if admitted else "claimed")
    assert (delivery["delivered_at"] is not None) == admitted


@pytest.mark.parametrize("payload,accepted", [
    ("", False), ("  ", False), (None, False), ("é" * 2400, True), ("é" * 2401, False),
])
def test_plugin_reply_boundaries(client, plugin_context, payload, accepted):
    _, create, _ = plugin_context
    ctx, marker, message = _plugin_wake(client, create)
    context = ctx.hooks["pre_llm_call"](
        session_id="ses_שלום", turn_id="wake", user_message=marker,
    )["context"]
    request = {"model": "pallium-local", "messages": [{
        "role": "user", "content": marker + "\n\n" + context,
    }]}
    ctx.middleware["llm_execution"](
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
    request = {"model": "pallium-local", "messages": [{
        "role": "user", "content": marker + "\n\n" + context,
    }]}
    ctx.middleware["llm_execution"](
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
    request = {"model": "pallium-local", "messages": [{"role": "user", "content": marker + "\n" + rendered}]}
    ctx.middleware["llm_execution"](request, lambda actual: "provider", session_id="ses_שלום",
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
