from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = {
    "delivery_id": "relay-delivery-1",
    "claim_token": "relay-claim-1",
    "message_id": "relay-message-1",
    "sender_runtime": "claude-code",
    "sender_session_ref": "sender-session",
    "recipient": "codex:target",
    "payload": "Review the migration before editing.",
    "redacted": False,
    "in_reply_to": None,
    "created_at": "2026-08-25T10:00:00+00:00",
    "expires_at": "2026-08-26T10:00:00+00:00",
}


TURN_SESSION = {
    "endpoint_id": "relay-session-test",
    "container_ref": "git:example/repo",
    "scope_generation": 0,
}


def _intercept_blocked_wake_exit(monkeypatch, hook):
    exits = []

    def exit_blocked():
        exits.append(2)
        raise SystemExit(2)

    monkeypatch.setattr(hook, "_exit_blocked_wake", exit_blocked)
    return exits


def _turn_response(deliveries=(), *, has_more=False, remaining_count=0, **session):
    return {
        "deliveries": list(deliveries),
        "has_more": has_more,
        "remaining_count": remaining_count,
        "session": {**TURN_SESSION, **session},
    }

@pytest.fixture(autouse=True)
def isolated_hook_state(monkeypatch, tmp_path):
    profile = tmp_path / "profile"
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("HOME", str(profile))
    sessions = tmp_path / "sessions"
    state = tmp_path / "state"
    for module in list(sys.modules.values()):
        if module is None:
            continue
        # Hook loaders replace codex_common, but existing hooks retain their own copy.
        for state_module in (module, getattr(module, "_common", None)):
            if hasattr(state_module, "SESSIONS_DIR"):
                monkeypatch.setattr(state_module, "SESSIONS_DIR", sessions, raising=False)
            if hasattr(state_module, "STATE_DIR"):
                monkeypatch.setattr(state_module, "STATE_DIR", state, raising=False)

def _load(name: str, relative: str):
    path = ROOT / relative
    module_name = "relay_test_" + name
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("name", "relative"),
    [
        ("claude_common", "integrations/claude-code/hooks/common.py"),
        ("codex_common", "integrations/codex/hooks/common.py"),
    ],
)
def test_relay_helpers_are_bounded_control_safe_and_use_requested_deadline(monkeypatch, capsys, name, relative):
    common = _load(name, relative)
    rendered, rendered_deliveries = common.format_relay([DELIVERY], budget_chars=2000)
    assert rendered.startswith("[Pallium Relay message from claude-code:sender-session]")
    assert "Lower-authority context" in rendered
    assert "delivery_id: relay-delivery-1" in rendered
    assert "pallium_relay_reply" in rendered
    assert "identify as Pallium Relay" in rendered
    assert "Reply only to substantive deliveries" in rendered
    assert "never to ACK-only deliveries" in rendered
    assert rendered_deliveries == [DELIVERY]
    assert "line one\nline two\tvalue" in common.format_relay(
        [{**DELIVERY, "payload": "line one\nline two\tvalue"}], budget_chars=2000
    )[0]
    assert common.format_relay([DELIVERY], budget_chars=20)[0] == ""
    assert common.format_relay([{**DELIVERY, "payload": "bad\x00value"}])[0] == ""
    maximum = {
        **DELIVERY,
        "delivery_id": "relay-delivery-" + "d" * 32,
        "claim_token": "relay-claim-" + "c" * 32,
        "message_id": "m" * 128,
        "sender_session_ref": "s" * 255,
        "in_reply_to": "p" * 128,
        "payload": "😀" * 1400,
        "payload_offset": 0,
        "payload_total_chars": 16000,
        "content_truncated": True,
        "next_offset": 1400,
        "created_at": "2026-09-05T12:34:56.123456+00:00",
    }
    maximum_output, maximum_rendered = common.format_relay(
        [maximum], budget_chars=2400, remaining_count=1000,
    )
    assert maximum_output == "" and maximum_rendered == []
    shorter = {**maximum, "payload": "😀" * 700, "next_offset": 700}
    maximum_output, maximum_rendered = common.format_relay(
        [shorter], budget_chars=2400, remaining_count=1000,
    )
    assert maximum_rendered == [shorter]
    assert 'Pallium Relay: 15300 characters omitted' in maximum_output
    assert f'pallium_relay_status(message_id="{maximum["message_id"]}", offset=700)' in maximum_output
    assert maximum_output.endswith("[Relay: 999+ more; Pallium continues.]")
    assert len(maximum_output) <= 2400
    assert common.format_relay([{**maximum, "next_offset": 1499}])[0] == ""

    quote = '"'
    maximum_scope = common.format_injection(
        [], "g" + quote * 511, budget_chars=2400,
        thread_ref=quote * 255, actor_ref=quote * 255,
        agent_ref="claude-code" if name == "claude_common" else "codex",
        visibility="private",
    )
    assert maximum_scope and len(maximum_scope) <= 2400

    observed = []

    def timeout(_request, timeout):
        observed.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(common.urllib.request, "urlopen", timeout)
    assert common.relay_request("POST", "/relay/turn", {}, timeout=0.75) is None
    assert observed == [0.75]
    error = capsys.readouterr().err
    assert "pallium relay: POST /relay/turn failed" in error
    assert "TimeoutError" in error
    assert "container" not in error

    calls = []
    monkeypatch.setattr(
        common,
        "relay_request",
        lambda method, path, payload, *, timeout: calls.append((method, path, payload, timeout)),
    )
    acknowledged = common.acknowledge_relay([DELIVERY], container_ref="container")
    assert acknowledged == []
    assert calls[0][1] == "/relay/deliveries/ack"
    assert calls[0][3] == 0.5


def _exercise_short_prompt(hook, monkeypatch, *, codex: bool):
    embedded_delivery_id = "relay-delivery-" + "f" * 32
    if codex:
        from app import codex_wake

        prompt = codex_wake._wake_prompt(embedded_delivery_id)
    else:
        prompt = "hi"
    payload = {"cwd": ".", "session_id": "target-session", "prompt": prompt}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    turn_calls = []
    expected_delivery = (
        {**DELIVERY, "delivery_id": embedded_delivery_id, "payload": "Unicode 😀"}
        if codex
        else DELIVERY
    )

    def relay(method, path, body, *, timeout, deadline=None):
        turn_calls.append((method, path, body, timeout, deadline))
        return _turn_response([
            {**DELIVERY, "delivery_id": "skipped", "payload": "bad\x00value"},
            expected_delivery,
        ])

    monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(hook, "pallium_request", lambda *_args, **_kwargs: pytest.fail("short prompt must skip memory"))
    acknowledged = []

    def acknowledge(deliveries, **scope):
        acknowledged.append((deliveries, scope))
        return deliveries

    monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)
    output = []
    wake_events = []
    if codex:
        monkeypatch.setattr(hook, "emit_context", lambda text, event: output.append((text, event)))
        monkeypatch.setattr(
            hook,
            "record_codex_wake_event",
            lambda **event: wake_events.append(
                (event["stage"], event.get("reason"))
            ),
        )
    else:
        monkeypatch.setattr(hook, "emit_utf8", lambda text, **_kwargs: output.append((text, None)) or True)

    with pytest.raises(SystemExit):
        hook.main()
    assert turn_calls[0][1] == "/relay/turn"
    expected_body = {
        "runtime": "codex" if codex else "claude-code",
        "session_ref": "target-session",
        "container_ref": "git:example/repo",
        "max_chars": 2360,
        "structural_work_refs": [],
    }
    if codex:
        expected_body["wake_delivery_id"] = embedded_delivery_id
    assert turn_calls[0][2] == expected_body
    if codex:
        assert 0 < turn_calls[0][3] <= 2.0
    else:
        assert turn_calls[0][3] == 0.75
    assert (turn_calls[0][4] is not None) is codex
    assert output and output[0][0].startswith("[Pallium Relay message")
    relay_text, scope_line = output[0][0].rsplit("\n\n", 1)
    assert ("Unicode 😀" if codex else "Review the migration before editing.") in relay_text
    assert not codex or embedded_delivery_id in relay_text
    injected_scope = json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    )
    assert injected_scope == {
        "container_ref": "git:example/repo",
        "thread_ref": "target-session",
        "actor_ref": "actor",
        "agent_ref": "codex" if codex else "claude-code",
        "visibility": "private",
    }
    assert acknowledged and acknowledged[0][0] == [expected_delivery]
    if codex:
        assert wake_events == [
            ("hook_started", None),
            ("relay_request_completed", None),
            ("payload_emitted", None),
            ("delivery_acked", None),
        ]


def test_codex_ack_helper_requires_exact_authoritative_response(monkeypatch):
    common = _load("codex_ack_strict", "integrations/codex/hooks/common.py")
    deliveries = [
        {**DELIVERY, "delivery_id": f"relay-delivery-{index:032x}"}
        for index in range(5)
    ]
    responses = iter([
        {
            "delivery_id": deliveries[1]["delivery_id"],
            "state": "delivered",
            "already_delivered": False,
        },
        {
            "delivery_id": deliveries[1]["delivery_id"],
            "state": "claimed",
            "already_delivered": False,
        },
        {
            "delivery_id": deliveries[2]["delivery_id"],
            "state": "delivered",
        },
        {
            "delivery_id": deliveries[3]["delivery_id"],
            "state": "delivered",
            "already_delivered": True,
        },
        OSError("later ACK failed"),
    ])

    def respond(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(common, "relay_request", respond)

    assert common.acknowledge_relay(
        deliveries, container_ref="container"
    ) == [deliveries[3]]


def test_codex_confirmed_empty_internal_wake_blocks_before_model(monkeypatch, capsys):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    assert hook.RELAY_WAKE_PROMPT == codex_wake._wake_prompt()
    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "prompt": hook.RELAY_WAKE_PROMPT},
    )
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook,
        "relay_request",
        lambda *_a, **_k: _turn_response(),
    )
    monkeypatch.setattr(
        hook, "check_dedup", lambda *_: pytest.fail("empty wake must block before dedup"),
    )
    monkeypatch.setattr(
        hook, "pallium_request", lambda *_a, **_k: pytest.fail("empty wake must not query memory"),
    )
    monkeypatch.setattr(
        hook, "emit_context", lambda *_a, **_k: pytest.fail("empty wake must not emit context"),
    )

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "decision": "block",
        "reason": "Pallium Relay wake suppressed: no verified pending delivery.",
    }
    assert captured.err == ""


@pytest.mark.parametrize(
    ("relay_response", "expected_outcome"),
    [
        (None, "unavailable"),
        ({}, "malformed"),
        ({"deliveries": None}, "malformed"),
        ({"deliveries": "invalid"}, "malformed"),
        (["invalid"], "unavailable"),
        ({"deliveries": []}, "malformed"),
        ({"deliveries": [], "has_more": True, "remaining_count": 1}, "malformed"),
        ({"deliveries": [], "has_more": False, "remaining_count": False}, "malformed"),
    ],
)
def test_codex_internal_wake_blocks_without_confirmed_empty(
    monkeypatch, capsys, relay_response, expected_outcome,
):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {
            "cwd": ".",
            "session_id": "target",
            "prompt": codex_wake._wake_prompt("relay-delivery-" + "e" * 32),
        },
    )
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: relay_response)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "emit_context", lambda *_a, **_k: None)
    wake_events = []
    monkeypatch.setattr(
        hook,
        "record_codex_wake_event",
        lambda **event: wake_events.append(
            (event["stage"], event.get("reason"))
        ),
    )

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["decision"] == "block"
    assert captured.err == f"pallium relay wake: outcome={expected_outcome}\n"
    assert wake_events == [
        ("hook_started", None),
        ("relay_request_completed", None),
        (
            "hook_failed",
            "relay_unavailable"
            if expected_outcome == "unavailable"
            else "malformed_response",
        ),
    ]


def test_codex_hook_records_unavailable_after_committed_http_claim(
    client, monkeypatch, tmp_path, capsys,
):
    from app import codex_readiness, codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    home = tmp_path
    codex_readiness.setup(
        python=sys.executable, script=hook.__file__, changed=True, home=home,
    )
    monkeypatch.setattr(hook, "record_codex_hook_execution", lambda **_kwargs: True)
    monkeypatch.setattr(hook._common, "STATE_DIR", tmp_path)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(
        hook, "record_codex_wake_event",
        lambda **event: codex_readiness.record_wake_event(
            python=sys.executable, home=home, **event
        ),
    )
    scope = {"container_ref": "git:example/repo"}
    assert client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target-session", **scope,
    }).status_code == 200
    assert client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender-session", **scope,
    }).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code",
        "sender_session_ref": "sender-session",
        "recipient": "codex:target-session",
        "payload": "one persisted request",
        **scope,
    }).json()
    delivery_id = sent["deliveries"][0]["delivery_id"]

    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path),
        "session_id": "target-session",
        "prompt": codex_wake._wake_prompt(delivery_id),
    })
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: pytest.fail("wake must not query memory"))
    monkeypatch.setattr(hook, "emit_context", lambda *_a, **_k: pytest.fail("unavailable wake must not emit"))
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: pytest.fail("unavailable wake must not ACK"))
    claimed = {}

    def committed_then_unavailable(method, path, body, *, timeout, deadline=None):
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        claimed.update(response.json()["deliveries"][0])
        import time
        time.sleep(0.02)
        return None

    monkeypatch.setattr(hook, "relay_request", committed_then_unavailable)
    monkeypatch.setattr(hook._common, "relay_request", committed_then_unavailable)
    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    assert claimed["delivery_id"] == delivery_id
    assert claimed["attempts"] == 1
    assert claimed["state"] == "claimed"
    event = next(
        event for event in codex_readiness.read(home)["relay_wake_evidence"]
        if event["stage"] == "relay_request_completed"
    )
    assert event["delivery_id"] == delivery_id
    assert event["outcome"] == "unavailable"
    assert 10 <= event["elapsed_ms"] <= 30000
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


@pytest.mark.parametrize(
    ("response_delay", "fragmented", "expected_state", "should_emit"),
    [
        (1.15, False, "delivered", True),
        (2.2, False, "claimed", False),
        (0.0, True, "claimed", False),
    ],
)
def test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable(
    client, monkeypatch, tmp_path, capsys, response_delay, fragmented,
    expected_state, should_emit,
):
    """Exercise actual hook urllib and /relay/turn through delayed loopback HTTP."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time

    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {"container_ref": "git:example/repo"}
    assert client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target-session", **scope,
    }).status_code == 200
    assert client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender-session", **scope,
    }).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender-session",
        "recipient": "codex:target-session",
        "payload": "bounded loopback response check", **scope,
    })
    assert sent.status_code == 200, sent.text
    message_id = sent.json()["message_id"]
    delivery_id = sent.json()["deliveries"][0]["delivery_id"]

    response_finished = threading.Event()

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = client.request(
                "POST", self.path, content=body,
                headers={"content-type": self.headers.get("Content-Type", "application/json")},
            )
            if self.path == "/relay/turn":
                time.sleep(response_delay)
            try:
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                if fragmented and self.path == "/relay/turn":
                    content = response.content
                    chunks = (content[:1], content[1:2], content[2:])
                    for index, chunk in enumerate(chunks):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if index < len(chunks) - 1:
                            time.sleep(1.1)
                else:
                    self.wfile.write(response.content)
            except (ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            finally:
                if self.path == "/relay/turn":
                    response_finished.set()

        def log_message(self, *_args):
            return

    server = Server(("127.0.0.1", 0), Handler)
    monkeypatch.setattr(
        hook._common, "PALLIUM_BASE_URL",
        f"http://127.0.0.1:{server.server_port}",
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    wake_events = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path), "session_id": "target-session",
        "prompt": codex_wake._wake_prompt(delivery_id),
    })
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(
        hook, "pallium_request",
        lambda *_a, **_k: pytest.fail("exact wake must not query memory"),
    )
    monkeypatch.setattr(
        hook, "record_codex_wake_event", lambda **event: wake_events.append(event),
    )

    try:
        hook_started = time.monotonic()
        with pytest.raises(SystemExit) as exited:
            hook.main()
        hook_elapsed = time.monotonic() - hook_started
        assert exited.value.code == 0
        assert hook_elapsed < 7.0  # eight-second host limit leaves one second outside the hook
        assert response_finished.wait(timeout=3)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    trace_response = client.get(f"/relay/messages/{message_id}/trace")
    assert trace_response.status_code == 200, trace_response.text
    snapshot = next(
        row for row in trace_response.json()["delivery_snapshots"]
        if row["delivery_id"] == delivery_id
    )
    assert snapshot["state"] == expected_state
    assert snapshot["attempts"] == 1
    request_event = next(
        event for event in wake_events
        if event["stage"] == "relay_request_completed"
    )
    assert request_event["delivery_id"] == delivery_id
    assert request_event["outcome"] == ("response" if should_emit else "unavailable")
    captured = capsys.readouterr()
    if should_emit:
        assert 1000 <= request_event["elapsed_ms"] < 1800
        assert json.loads(captured.out)["hookSpecificOutput"]["additionalContext"].count(delivery_id) == 1
        assert any(event["stage"] == "delivery_acked" for event in wake_events)
    else:
        assert 1800 <= request_event["elapsed_ms"] < 2400
        assert not any(event["stage"] == "payload_emitted" for event in wake_events)
        assert any(event.get("reason") == "relay_unavailable" for event in wake_events)
        assert json.loads(captured.out)["decision"] == "block"


@pytest.mark.parametrize("prompt", [
    "ordinary user turn",
    "Pallium Relay wake for relay-delivery-" + "a" * 32 + "!",
])
def test_codex_noncanonical_prompt_keeps_short_relay_timeout(
    monkeypatch, tmp_path, prompt,
):
    from integrations.codex.hooks import user_prompt_submit as hook

    calls = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path), "session_id": "target-session", "prompt": prompt,
    })
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_request", lambda *args, **kwargs: (
        calls.append((args, kwargs)) or _turn_response()
    ))

    with pytest.raises(SystemExit):
        hook.main()

    assert len(calls) == 1
    assert calls[0][0][:2] == ("POST", "/relay/turn")
    assert 0 < calls[0][1]["timeout"] <= 0.75  # Lock/state work consumes the same budget.
    assert "wake_delivery_id" not in calls[0][0][2]

def test_codex_internal_wake_without_valid_scope_blocks(monkeypatch, capsys):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {
            "cwd": ".",
            "session_id": "target",
            "prompt": codex_wake._wake_prompt("relay-delivery-" + "e" * 32),
        },
    )
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook, "relay_request", lambda *_a, **_k: pytest.fail("invalid scope must not claim Relay"),
    )
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    wake_events = []
    monkeypatch.setattr(
        hook,
        "record_codex_wake_event",
        lambda **event: wake_events.append(
            (event["stage"], event.get("reason"))
        ),
    )

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["decision"] == "block"
    assert captured.err == "pallium relay wake: outcome=invalid_scope\n"
    assert wake_events == [
        ("hook_started", None),
        ("hook_failed", "invalid_scope"),
    ]


@pytest.mark.parametrize(
    ("failure", "expected_events"),
    [
        (
            "emit",
            [("hook_started", None), ("relay_request_completed", None), ("hook_failed", "emit_failed")],
        ),
        (
            "ack",
            [
                ("hook_started", None),
                ("relay_request_completed", None),
                ("payload_emitted", None),
                ("hook_failed", "ack_failed"),
            ],
        ),
    ],
)
def test_codex_wake_records_only_proven_emit_and_ack_stages(
    monkeypatch, failure, expected_events,
):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    delivery_id = "relay-delivery-" + "d" * 32
    delivery = {
        **DELIVERY,
        "delivery_id": delivery_id,
        "payload": "Unicode payload 😀",
    }
    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {
            "cwd": ".",
            "session_id": "target",
            "prompt": codex_wake._wake_prompt(delivery_id),
        },
    )
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook,
        "relay_request",
        lambda *_args, **_kwargs: _turn_response([delivery]),
    )
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    wake_events = []
    monkeypatch.setattr(
        hook,
        "record_codex_wake_event",
        lambda **event: wake_events.append(
            (event["stage"], event.get("reason"))
        ),
    )
    blocked_exits = []
    if failure == "emit":
        blocked_exits = _intercept_blocked_wake_exit(monkeypatch, hook)
        monkeypatch.setattr(
            hook,
            "emit_context",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("output unavailable")
            ),
        )
        monkeypatch.setattr(
            hook,
            "acknowledge_relay",
            lambda *_args, **_kwargs: pytest.fail(
                "failed output must not be acknowledged"
            ),
        )
    else:
        monkeypatch.setattr(hook, "emit_context", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(hook, "acknowledge_relay", lambda *_args, **_kwargs: [])

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == (2 if failure == "emit" else 0)
    assert blocked_exits == ([2] if failure == "emit" else [])
    assert wake_events == expected_events


@pytest.mark.parametrize("failure_stage", ["scope", "discovery"])
def test_codex_recognized_wake_exceptions_before_emission_block(
    monkeypatch, failure_stage,
):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    delivery_id = "relay-delivery-" + "b" * 32
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session",
        "prompt": codex_wake._wake_prompt(delivery_id),
    })
    monkeypatch.setattr(hook, "record_codex_wake_event", lambda **_event: None)
    if failure_stage == "scope":
        monkeypatch.setattr(
            hook, "resolve_container_ref",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("private scope failure")),
        )
    else:
        monkeypatch.setattr(hook, "resolve_container_ref", lambda *_a, **_k: "git:example/repo")
        monkeypatch.setattr(hook, "derive_actor_ref", lambda *_a, **_k: "actor")
        monkeypatch.setattr(
            hook, "discover_work_refs",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("private discovery failure")),
        )
    monkeypatch.setattr(hook, "relay_turn", lambda *_a, **_k: pytest.fail("must fail before Relay"))
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: pytest.fail("wake must not query memory"))
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: pytest.fail("wake must not ACK"))
    blocked_exits = _intercept_blocked_wake_exit(monkeypatch, hook)

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 2
    assert blocked_exits == [2]


def test_codex_ordinary_prompt_exception_remains_fail_open(monkeypatch):
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session", "prompt": "ordinary prompt",
    })
    monkeypatch.setattr(
        hook, "resolve_container_ref",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("private scope failure")),
    )
    blocked_exits = _intercept_blocked_wake_exit(monkeypatch, hook)

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    assert blocked_exits == []


@pytest.mark.parametrize("failure", ["diagnostic", "ack"])
def test_codex_wake_post_emission_exceptions_do_not_retroactively_block(
    monkeypatch, failure,
):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    delivery_id = "relay-delivery-" + "d" * 32
    delivery = {**DELIVERY, "delivery_id": delivery_id, "payload": "sent payload"}
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target", "prompt": codex_wake._wake_prompt(delivery_id),
    })
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: _turn_response([delivery]))
    outputs, events, acknowledgments = [], [], []
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: outputs.append(text))

    def record(**event):
        events.append(event["stage"])
        if failure == "diagnostic" and event["stage"] == "payload_emitted":
            raise OSError("private diagnostic failure")

    def acknowledge(*_a, **_k):
        acknowledgments.append(True)
        if failure == "ack":
            raise OSError("private ACK failure")
        return [delivery]

    monkeypatch.setattr(hook, "record_codex_wake_event", record)
    monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)
    blocked_exits = _intercept_blocked_wake_exit(monkeypatch, hook)

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    assert outputs and "sent payload" in outputs[0]
    assert acknowledgments == ([] if failure == "diagnostic" else [True])
    assert blocked_exits == []


def test_codex_unreadable_hook_input_is_not_classified_as_wake(monkeypatch):
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(hook, "read_hook_input", lambda: {})
    blocked_exits = _intercept_blocked_wake_exit(monkeypatch, hook)

    assert hook.main() is None
    assert blocked_exits == []


def test_codex_recognized_wake_output_failures_exit_two_in_subprocess():
    source = r'''
import json, os, sys, time
from app import codex_wake
from integrations.codex.hooks import user_prompt_submit as hook
mode = __MODE__
hook.start_hook_deadline = lambda *a, **k: hook._common.start_hook_deadline(
    0 if mode == "deadline" else 8, host_reserve=0,
    clock=(lambda: 0.0) if mode == "deadline" else time.monotonic,
)
hook.record_codex_hook_execution = lambda **k: True
hook.record_codex_wake_event = lambda **k: None
hook.read_hook_input = lambda: {
    "cwd": ".", "session_id": "target-session",
    "prompt": codex_wake._wake_prompt("relay-delivery-" + "c" * 32),
}
hook.resolve_container_ref = lambda *a, **k: "git:example/repo"
hook.derive_actor_ref = lambda *a, **k: "actor"
hook.discover_work_refs = lambda *a, **k: ()
hook.injected_work_ref = lambda *a, **k: None
hook.structural_work_refs_payload = lambda *a, **k: []
delivery = {
    "delivery_id": "relay-delivery-" + "c" * 32,
    "claim_token": "claim-token", "message_id": "message-id",
    "sender_runtime": "codex", "sender_session_ref": "sender",
    "recipient": "codex:target-session", "payload": "payload sentinel",
    "created_at": "2026-10-07T00:00:00Z", "attempts": 1,
}
has_delivery = mode.startswith("payload_")
hook.relay_turn = lambda *a, **k: {
    "deliveries": [delivery] if has_delivery else [],
    "has_more": False, "remaining_count": 0,
    "session": {"endpoint_id": "relay-session-test", "container_ref": "git:example/repo", "scope_generation": 0},
}
hook.pallium_request = lambda *a, **k: os.write(2, b"MEMORY_SENTINEL")
hook.acknowledge_relay = lambda *a, **k: os.write(2, b"ACK_SENTINEL")
if mode in ("payload_partial", "payload_flush", "stderr_write", "stderr_flush"):
    real_stdout = sys.__stdout__
    class Buffer:
        def write(self, data):
            if mode == "payload_partial":
                prefix = b'{"hookSpecificOutput": {'
                real_stdout.buffer.write(data[:len(prefix)])
                real_stdout.buffer.flush()
                raise OSError("private stdout write failure")
            if mode == "stderr_write":
                raise OSError("private stdout write failure")
            real_stdout.buffer.write(data)
            real_stdout.buffer.flush()
        def flush(self):
            if mode in ("payload_flush", "stderr_flush"):
                raise OSError("private stdout flush failure")
            real_stdout.buffer.flush()
    class Stdout:
        buffer = Buffer()
    sys.stdout = Stdout()
    class Stderr:
        def write(self, value):
            if mode == "stderr_write":
                raise OSError("private stderr write failure")
            os.write(2, value.encode("utf-8"))
        def flush(self):
            if mode == "stderr_flush":
                raise OSError("private stderr flush failure")
    sys.stderr = Stderr()
hook.main()
'''
    modes = (
        "payload_partial", "payload_flush", "stderr_write", "stderr_flush",
        "deadline", "block_success", "payload_success",
    )
    for mode in modes:
        result = subprocess.run(
            [sys.executable, "-c", source.replace("__MODE__", json.dumps(mode))],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        expected_exit = 0 if mode.endswith("success") else 2
        assert result.returncode == expected_exit, (mode, result.stdout, result.stderr)
        assert "MEMORY_SENTINEL" not in result.stderr
        assert ("ACK_SENTINEL" in result.stderr) == (mode == "payload_success")
        assert "private " not in result.stderr
        if mode == "payload_partial":
            assert result.stdout == '{"hookSpecificOutput": {'
            with pytest.raises(json.JSONDecodeError):
                json.loads(result.stdout)
        elif mode == "payload_flush":
            assert json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        elif mode == "payload_success":
            assert "payload sentinel" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            assert "delivery_id: relay-delivery-" in result.stdout
        elif mode == "block_success":
            assert json.loads(result.stdout)["decision"] == "block"
            assert result.stderr == ""
        elif mode == "stderr_flush":
            assert json.loads(result.stdout)["decision"] == "block"
        else:
            assert result.stdout == ""
        if mode == "stderr_flush":
            assert "pallium relay wake blocked: output was not verified." in result.stderr
        elif mode == "stderr_write":
            assert result.stderr == ""


@pytest.mark.parametrize(
    ("relative", "runtime", "imported"),
    [
        ("integrations/claude-code/hooks/user_prompt_submit.py", "claude-code", False),
        ("integrations/codex/hooks/user_prompt_submit.py", "codex", True),
    ],
)

def test_short_turn_without_delivery_still_exposes_current_relay_identity(
    monkeypatch, relative, runtime, imported,
):
    if imported:
        from integrations.codex.hooks import user_prompt_submit as hook
    else:
        hook = _load("claude_short_scope", relative)
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target-session", "prompt": "hi"},
    )
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: _turn_response())
    monkeypatch.setattr(
        hook, "pallium_request",
        lambda *_a, **_k: pytest.fail("short prompt must skip memory"),
    )
    outputs = []
    if imported:
        monkeypatch.setattr(hook, "emit_context", lambda text, _event: outputs.append(text))
    else:
        monkeypatch.setattr(hook, "emit_utf8", lambda text, **_kwargs: outputs.append(text) or True)
    with pytest.raises(SystemExit):
        hook.main()
    assert len(outputs) == 1
    scope_line = outputs[0].splitlines()[0]
    scope = json.loads(scope_line.removeprefix("[Pallium scope — ").removesuffix("]"))
    assert "association enrichment was unavailable" in outputs[0]
    assert scope == {
        "container_ref": "git:example/repo",
        "thread_ref": "target-session",
        "actor_ref": "actor",
        "agent_ref": runtime,
        "visibility": "private",
    }


@pytest.mark.parametrize(
    ("relative", "imported"),
    [
        ("integrations/claude-code/hooks/user_prompt_submit.py", False),
        ("integrations/codex/hooks/user_prompt_submit.py", True),
    ],
)
def test_invalid_scope_never_claims_prompt_delivery(monkeypatch, relative, imported):
    if imported:
        from integrations.codex.hooks import user_prompt_submit as hook
    else:
        hook = _load("claude_invalid_scope", relative)
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target-session", "prompt": "hi"},
    )
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(
        hook, "relay_request",
        lambda *_a, **_k: pytest.fail("invalid scope must not claim Relay"),
    )
    monkeypatch.setattr(
        hook, "pallium_request",
        lambda *_a, **_k: pytest.fail("short prompt must skip memory"),
    )
    if not imported:
        monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: None)
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0


def test_claude_session_start_delivery_includes_exact_scope(monkeypatch, capsys):
    hook = _load("claude_session_start_scope", "integrations/claude-code/hooks/session_start.py")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target-session", "source": "startup"},
    )
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: None)
    monkeypatch.setattr(
        hook, "relay_request", lambda *_a, **_k: _turn_response([DELIVERY]),
    )
    acknowledged = []
    monkeypatch.setattr(
        hook, "acknowledge_relay",
        lambda deliveries, **_scope: acknowledged.append(deliveries),
    )
    monkeypatch.setattr(
        hook, "_fetch_orientation",
        lambda *_: pytest.fail("Relay delivery must skip orientation"),
    )

    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    relay_text, scope_line = capsys.readouterr().out.rstrip().rsplit("\n\n", 1)
    assert "Review the migration before editing." in relay_text
    assert json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    ) == {
        "container_ref": "git:example/repo", "thread_ref": "target-session",
        "actor_ref": "actor", "agent_ref": "claude-code", "visibility": "private",
    }
    assert acknowledged == [[DELIVERY]]


def test_codex_session_start_delivers_and_acks_before_orientation(monkeypatch):
    hook = _load("codex_session_start_relay", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session", "source": "resume",
    })
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: _turn_response([DELIVERY]))
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: pytest.fail("Relay must precede orientation"))
    events = []
    monkeypatch.setattr(hook, "emit_context", lambda text, event: events.append(("emit", text, event)))
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **scope: events.append(("ack", deliveries, scope)))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    assert [event[0] for event in events] == ["emit", "ack"]
    assert events[0][2] == "SessionStart"
    assert "Review the migration before editing." in events[0][1]
    assert '"thread_ref":"target-session"' in events[0][1]
    assert events[1] == ("ack", [DELIVERY], {"container_ref": "git:example/repo"})


@pytest.mark.parametrize("exhausted", [False, True])
def test_codex_session_start_allows_bounded_delayed_claim_response(client, monkeypatch, tmp_path, capsys, exhausted):
    """A real delayed claim response fits the host budget; exhausted hooks do no I/O."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time

    monkeypatch.setitem(sys.modules, "codex_common", sys.modules.get("codex_common"))
    hook = _load("codex_session_start_delayed", "integrations/codex/hooks/session_start.py")
    scope = {"container_ref": "git:example/repo"}
    for runtime, session in (("codex", "target-session"), ("claude-code", "sender-session")):
        assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **scope}).status_code == 200
    sent = client.post("/relay/messages", json={"sender_runtime": "claude-code", "sender_session_ref": "sender-session",
        "recipient": "codex:target-session", "payload": "delayed-response-東京", **scope}).json()
    paths, events = [], []
    response_finished = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            paths.append(self.path)
            body = self.rfile.read(int(self.headers["Content-Length"]))
            response = client.request("POST", self.path, content=body, headers={"content-type": "application/json"})
            if self.path == "/relay/turn":
                time.sleep(3)
            else:
                events.append("ack")
            try:
                self.send_response(response.status_code)
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except OSError:
                pass
            finally:
                response_finished.set()
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    monkeypatch.setattr(hook._common, "PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(hook._common, "STATE_DIR", tmp_path)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": str(tmp_path), "session_id": "target-session", "source": "resume"})
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: scope["container_ref"])
    def actor(*_args):
        if exhausted:
            hook._common._HOOK_DEADLINE = hook._common.HookDeadline(time.monotonic())
        return "actor"
    monkeypatch.setattr(hook, "derive_actor_ref", actor)
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: [])
    original_emit = hook.emit_context
    def emit(text, event):
        events.append("emit")
        original_emit(text, event)
    monkeypatch.setattr(hook, "emit_context", emit)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0 and time.monotonic() - started < 7
        if not exhausted:
            assert response_finished.wait(4)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert not thread.is_alive()
    delivery = client.get(f"/relay/messages/{sent['message_id']}", params=scope).json()["deliveries"][0]
    output = capsys.readouterr()
    if exhausted:
        assert paths == [] and "ack" not in events
        assert delivery["state"] == "pending" and delivery["attempts"] == 0
        assert "[Pallium Relay message" not in output.out
    else:
        assert paths == ["/relay/turn", "/relay/deliveries/ack"]
        assert events == ["emit", "ack"]
        assert delivery["state"] == "delivered" and delivery["attempts"] == 1
        assert "delayed-response-東京" in json.loads(output.out)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("response", [
    None, _turn_response(),
    _turn_response([{**DELIVERY, "payload": "x" * 5000}]),
    {"error": "unavailable"},
])
def test_codex_session_start_without_rendered_delivery_does_not_ack(monkeypatch, response):
    hook = _load("codex_session_start_empty", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session", "source": "startup",
    })
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_turn", lambda *_a, **_k: response)
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: [])
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: pytest.fail("must not ACK"))
    outputs = []
    monkeypatch.setattr(hook, "emit_context", lambda text, *_a: outputs.append(text))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    assert all("[Pallium Relay message" not in output for output in outputs)


@pytest.mark.parametrize("failing_step", ["emit", "ack"])
def test_codex_session_start_emit_precedes_ack_even_on_failure(monkeypatch, failing_step):
    hook = _load("codex_session_start_failure", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session", "source": "resume",
    })
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_turn", lambda *_a, **_k: _turn_response([DELIVERY]))
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: pytest.fail("must skip orientation"))
    events = []
    def emit(*_args):
        events.append("emit")
        if failing_step == "emit":
            raise OSError("output unavailable")
    def ack(*_args, **_kwargs):
        events.append("ack")
        raise OSError("ack unavailable")
    monkeypatch.setattr(hook, "emit_context", emit)
    monkeypatch.setattr(hook, "acknowledge_relay", ack)
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    assert events == (["emit"] if failing_step == "emit" else ["emit", "ack"])


def test_codex_session_start_actual_hook_input_output(monkeypatch, capsys):
    hook = _load("codex_session_start_io", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "cwd": ".", "session_id": "target-session", "source": "resume",
    })))
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_turn", lambda *_a, **_k: _turn_response([DELIVERY]))
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: pytest.fail("must skip orientation"))
    acknowledged = []
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **_k: acknowledged.extend(deliveries))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Review the migration before editing." in context
    assert '"thread_ref":"target-session"' in context
    assert acknowledged == [DELIVERY]


def test_codex_session_start_invalid_scope_never_claims(monkeypatch):
    hook = _load("codex_session_start_invalid", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target-session", "source": "startup",
    })
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: pytest.fail("invalid scope must not claim"))
    monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *_: [])
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0


def test_codex_session_start_clear_skips_relay(monkeypatch):
    hook = _load("codex_session_start_clear", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"source": "clear"})
    monkeypatch.setattr(hook, "relay_turn", lambda *_a, **_k: pytest.fail("clear must skip Relay"))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0


def test_codex_session_start_then_prompt_does_not_emit_acked_delivery_twice(monkeypatch):
    start = _load("codex_session_start_then_prompt", "integrations/codex/hooks/session_start.py")
    from integrations.codex.hooks import user_prompt_submit as prompt
    session = "target-session"
    container = "git:example/repo"
    monkeypatch.setattr(start, "read_hook_input", lambda: {
        "cwd": ".", "session_id": session, "source": "startup",
    })
    monkeypatch.setattr(start, "derive_container_ref", lambda *_: container)
    monkeypatch.setattr(start, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(start, "pin_container", lambda *_a, **_k: None)
    acknowledged = []
    outputs = []
    monkeypatch.setattr(start, "relay_turn", lambda *_a, **_k: _turn_response([DELIVERY]))
    monkeypatch.setattr(start, "emit_context", lambda text, *_a: outputs.append(text))
    monkeypatch.setattr(start, "acknowledge_relay", lambda deliveries, **_k: acknowledged.extend(deliveries))
    with pytest.raises(SystemExit):
        start.main()
    monkeypatch.setattr(prompt, "read_hook_input", lambda: {
        "cwd": ".", "session_id": session, "prompt": "hi",
    })
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_a: container)
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda *_a: "actor")
    monkeypatch.setattr(prompt, "discover_work_refs", lambda *_a: None)
    monkeypatch.setattr(prompt, "injected_work_ref", lambda *_a: None)
    monkeypatch.setattr(prompt, "structural_work_refs_payload", lambda *_a: None)
    monkeypatch.setattr(prompt, "check_dedup", lambda *_a: False)
    monkeypatch.setattr(prompt, "relay_turn", lambda *_a, **_k: _turn_response() if acknowledged else pytest.fail("not ACKed"))
    monkeypatch.setattr(prompt, "emit_context", lambda text, *_a: outputs.append(text))
    with pytest.raises(SystemExit):
        prompt.main()
    assert acknowledged == [DELIVERY]
    assert sum("[Pallium Relay message" in output for output in outputs) == 1


def test_claude_session_start_invalid_scope_never_claims(monkeypatch):
    hook = _load("claude_session_start_invalid", "integrations/claude-code/hooks/session_start.py")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target-session", "source": "startup"},
    )
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: None)
    monkeypatch.setattr(
        hook, "relay_request",
        lambda *_a, **_k: pytest.fail("invalid scope must not claim Relay"),
    )
    monkeypatch.setattr(hook, "_fetch_orientation", lambda *_: [])
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0


def test_claude_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    hook = _load("claude_prompt", "integrations/claude-code/hooks/user_prompt_submit.py")
    _exercise_short_prompt(hook, monkeypatch, codex=False)


def test_codex_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    from integrations.codex.hooks import user_prompt_submit as hook

    _exercise_short_prompt(hook, monkeypatch, codex=True)


@pytest.mark.parametrize(
    ("relative", "runtime"),
    [
        ("integrations/claude-code/hooks/common.py", "claude-code"),
        ("integrations/codex/hooks/common.py", "codex"),
    ],
)
def test_relay_turn_replays_without_claiming_until_final_destination(
    monkeypatch, tmp_path: Path, relative: str, runtime: str,
):
    common = _load(f"replay_{runtime}", relative)
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "sessions")
    session_id = "replay-session"
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    (state_dir / f"{session_id}.json").write_text(json.dumps({
        "container_ref": "git:old/repo",
        "last_confirmed_container_ref": "git:old/repo",
        "last_confirmed_endpoint_id": "relay-session-old",
        "last_confirmed_scope_generation": 0,
        "relay_turn_intent": {
            "runtime": runtime,
            "source_container_ref": "git:old/repo",
            "destination_container_ref": "git:middle/repo",
            "endpoint_id": "relay-session-old",
            "scope_generation": 0,
        },
    }), encoding="utf-8")
    replay_delivery = {**DELIVERY, "delivery_id": "replayed-delivery"}
    calls = []

    def request(method, path, body, *, timeout):
        calls.append(body)
        if body["container_ref"] == "git:middle/repo":
            return _turn_response(
                [],
                container_ref="git:middle/repo",
                endpoint_id="relay-session-old",
                scope_generation=1,
            )
        if body["container_ref"] == "git:new/repo":
            return _turn_response(
                [replay_delivery],
                container_ref="git:new/repo",
                endpoint_id="relay-session-old",
                scope_generation=2,
            )
        return None

    result = common.relay_turn(runtime, session_id, "git:new/repo", request=request)
    assert result is not None
    assert [item["delivery_id"] for item in result["deliveries"]] == ["replayed-delivery"]
    assert [body["container_ref"] for body in calls] == [
        "git:middle/repo", "git:new/repo",
    ]
    assert calls[0]["max_chars"] == 1 and calls[0]["max_messages"] == 1
    assert "max_messages" not in calls[1]
    state = json.loads((state_dir / f"{session_id}.json").read_text(encoding="utf-8"))
    assert state["last_confirmed_container_ref"] == "git:new/repo"
    assert state["last_confirmed_scope_generation"] == 2


@pytest.mark.parametrize(
    ("relative", "runtime"),
    [
        ("integrations/claude-code/hooks/common.py", "claude-code"),
        ("integrations/codex/hooks/common.py", "codex"),
    ],
)
def test_non_registering_hook_probe_omits_persisted_transition_fields(
    monkeypatch, tmp_path: Path, relative: str, runtime: str,
) -> None:
    common = _load(f"non_registering_{runtime}", relative)
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    monkeypatch.setattr(common, "SESSIONS_DIR", state_dir)
    session_id = "non-registering-session"
    (state_dir / f"{session_id}.json").write_text(json.dumps({
        "container_ref": "git:old/repo",
        "last_confirmed_container_ref": "git:old/repo",
        "last_confirmed_endpoint_id": "relay-session-old",
        "last_confirmed_scope_generation": 0,
        "relay_turn_intent": {
            "runtime": runtime,
            "source_container_ref": "git:old/repo",
            "destination_container_ref": "git:middle/repo",
            "endpoint_id": "relay-session-old",
            "scope_generation": 0,
        },
    }), encoding="utf-8")
    calls = []

    def request(_method, _path, body, **_kwargs):
        calls.append(body)
        return None

    assert common.relay_turn(
        runtime, session_id, "git:new/repo",
        register_session=False, request=request,
    ) is None
    assert len(calls) == 1
    assert calls[0]["register_session"] is False
    assert not {
        "previous_container_ref",
        "previous_endpoint_id",
        "previous_scope_generation",
    }.intersection(calls[0])



@pytest.mark.parametrize((
    "runtime", "relative",
), [
    ("claude-code", "integrations/claude-code/hooks/common.py"),
    ("codex", "integrations/codex/hooks/common.py"),
])
def test_failed_provisional_switch_does_not_bounce_to_pinned_scope(
    monkeypatch, tmp_path: Path, runtime: str, relative: str,
):
    common = _load(f"provisional_{runtime}", relative)
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / f"{runtime}-sessions")
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    session_id = "provisional-session"
    common.pin_container(session_id, "git:old/repo")
    monkeypatch.setattr(common, "_identity_context", lambda _cwd: {
        "identity_cwd": "git:new/repo", "repo_config_fingerprint": "new",
    })
    monkeypatch.setattr(common, "derive_container_ref", lambda _cwd: "git:new/repo")
    monkeypatch.setattr(common, "_bounded_timeout", lambda _value: 0)
    assert common.resolve_container_ref("new", session_id, True, False) == "git:new/repo"
    common.derive_actor_ref("new", session_id)
    assert common.resolve_container_ref("new", session_id, True, False) == "git:new/repo"


@pytest.mark.parametrize((
    "runtime", "relative",
), [
    ("claude-code", "integrations/claude-code/hooks/common.py"),
    ("codex", "integrations/codex/hooks/common.py"),
])
def test_confirmed_switch_does_not_attach_old_identity_to_new_pin(
    monkeypatch, tmp_path: Path, runtime: str, relative: str,
):
    from itertools import count
    from types import SimpleNamespace
    import time

    common = _load(f"confirmed_identity_{runtime}", relative)
    original_monotonic = time.monotonic
    # This state contract uses logical time; disk setup is covered by deadline tests.
    private_time = SimpleNamespace(**vars(common.time))
    private_time.monotonic = count(step=0.001).__next__
    monkeypatch.setattr(common, "time", private_time)
    sessions = tmp_path / f"{runtime}-confirmed-sessions"
    monkeypatch.setattr(common, "SESSIONS_DIR", sessions)
    sessions.mkdir()
    session_id = "confirmed-session"
    (sessions / f"{session_id}.json").write_text(json.dumps({
        "container_ref": "git:a",
        "last_confirmed_container_ref": "git:a",
        "last_confirmed_endpoint_id": "relay-session-e1",
        "last_confirmed_scope_generation": 0,
        "identity_cwd": "a",
        "repo_config_fingerprint": "a",
        "actor_ref": "actor-a",
    }), encoding="utf-8")
    contexts = {
        "a": {"identity_cwd": "a", "repo_config_fingerprint": "a"},
        "b": {"identity_cwd": "b", "repo_config_fingerprint": "b"},
    }
    monkeypatch.setattr(common, "_identity_context", lambda cwd: contexts[cwd])
    monkeypatch.setattr(common, "derive_container_ref", lambda cwd: f"git:{cwd}")
    monkeypatch.setattr(common, "_bounded_timeout", lambda _value: 0)
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
    assert common.resolve_container_ref("b", session_id, True, False) == "git:b"
    common.derive_actor_ref("b", session_id)
    result = common.relay_turn(runtime, session_id, "git:b", request=lambda *_a, **_k: _turn_response(
        container_ref="git:b", endpoint_id="relay-session-e1", scope_generation=1,
    ))
    assert result is not None
    state = json.loads((sessions / f"{session_id}.json").read_text(encoding="utf-8"))
    assert state["container_ref"] == state["last_confirmed_container_ref"] == "git:b"
    assert state["last_confirmed_endpoint_id"] == "relay-session-e1"
    assert state["last_confirmed_scope_generation"] == 1
    assert not {"identity_cwd", "repo_config_fingerprint", "actor_ref", "provisional_identity_context"}.intersection(state)
    assert common.resolve_container_ref("a", session_id, True, False) == "git:a"
    assert time.monotonic is original_monotonic


@pytest.mark.parametrize("runtime", ["claude-code", "codex"])
def test_legacy_pin_bootstraps_endpoint_alias_and_queued_delivery(
    client, monkeypatch, tmp_path: Path, runtime: str,
):
    relative = "integrations/claude-code/hooks/common.py" if runtime == "claude-code" else "integrations/codex/hooks/common.py"
    common = _load(f"legacy_{runtime}", relative)
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / f"{runtime}-sessions")
    old = "git:legacy/old"
    new = "git:legacy/new"
    sender = "git:legacy/sender"
    old_response = client.post("/relay/turn", json={
        "runtime": runtime, "session_ref": "legacy-target", "container_ref": old,
    })
    assert old_response.status_code == 200
    endpoint = old_response.json()["session"]["endpoint_id"]
    assert client.post("/relay/sessions/name", json={
        "runtime": runtime, "session_ref": "legacy-target", "container_ref": old,
        "alias": "legacy-alias",
    }).status_code == 200
    assert client.post("/relay/turn", json={
        "runtime": runtime, "session_ref": "legacy-sender", "container_ref": sender,
    }).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": runtime, "sender_session_ref": "legacy-sender",
        "recipient": endpoint, "payload": "queued legacy delivery", "container_ref": sender,
    })
    assert sent.status_code == 200
    state_dir = common.SESSIONS_DIR
    state_dir.mkdir(parents=True)
    (state_dir / "legacy-target.json").write_text(json.dumps({
        "container_ref": old,
    }), encoding="utf-8")

    def request(method, path, body, *, timeout):
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    result = common.relay_turn(runtime, "legacy-target", new, max_chars=1000, request=request)


    assert result["session"]["endpoint_id"] == endpoint
    assert result["session"]["alias"] == "legacy-alias"
    assert [item["payload"] for item in result["deliveries"]] == ["queued legacy delivery"]

@pytest.mark.parametrize(
    ("relative", "runtime", "imported"),
    [
        ("integrations/claude-code/hooks/user_prompt_submit.py", "claude-code", False),
        ("integrations/codex/hooks/user_prompt_submit.py", "codex", True),
    ],
)

def test_project_switch_uses_atomic_turn_transition_without_relay_close(
    monkeypatch, relative, runtime, imported
):
    from time import monotonic

    if imported:
        from integrations.codex.hooks import user_prompt_submit as hook
    else:
        hook = _load("claude_switch", relative)
    session_id = "target"
    old_container = "git:old/repo"
    new_container = "git:new/repo"
    session_dir = hook.relay_turn.__globals__["SESSIONS_DIR"]
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f"{session_id}.json").write_text(json.dumps({
        "container_ref": old_container,
        "last_confirmed_container_ref": old_container,
        "last_confirmed_endpoint_id": "relay-session-old",
        "last_confirmed_scope_generation": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": session_id, "prompt": "hi"},
    )
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: new_container)
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    calls = []
    turn_globals = hook.relay_turn.__globals__
    diagnostics = []

    def trace_phase(stage, original):
        def traced(*args, **kwargs):
            remaining_before = turn_globals["remaining_safe_time"]()
            started = monotonic()
            result = original(*args, **kwargs)
            diagnostics.append({
                "stage": stage,
                "elapsed_seconds": monotonic() - started,
                "remaining_before": remaining_before,
                "remaining_after": turn_globals["remaining_safe_time"](),
                "result": result if stage == "intent_write" else result is not None,
            })
            return result
        return traced

    for name, stage in (
        ("_acquire_session_lock", "session_lock"),
        ("_read_session_state", "state_read"),
        ("_write_session_state_locked", "intent_write"),
    ):
        monkeypatch.setitem(turn_globals, name, trace_phase(stage, turn_globals[name]))

    def relay(method, path, body, *, timeout):
        calls.append((method, path, body, timeout))
        assert path == "/relay/turn"
        return _turn_response(
            [], container_ref=new_container,
            endpoint_id="relay-session-old", scope_generation=1,
        )

    monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    if imported:
        monkeypatch.setattr(hook, "emit_context", lambda *_: None)
    else:
        monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: None)

    with pytest.raises(SystemExit):
        hook.main()

    assert len(calls) == 1, diagnostics
    assert calls[0][1] == "/relay/turn"
    assert calls[0][2]["container_ref"] == new_container
    assert calls[0][2]["previous_container_ref"] == old_container
    assert calls[0][2]["previous_endpoint_id"] == "relay-session-old"
    assert calls[0][2]["previous_scope_generation"] == 0
    state = json.loads((session_dir / f"{session_id}.json").read_text(encoding="utf-8"))
    assert state["last_confirmed_container_ref"] == new_container
    assert state["last_confirmed_endpoint_id"] == "relay-session-old"
    assert state["last_confirmed_scope_generation"] == 1

@pytest.mark.parametrize(
    ("relative", "imported"),
    [
        ("integrations/claude-code/hooks/user_prompt_submit.py", False),
        ("integrations/codex/hooks/user_prompt_submit.py", True),
    ],
)
def test_slash_and_duplicate_turns_never_claim(monkeypatch, relative, imported):
    if imported:
        from integrations.codex.hooks import user_prompt_submit as hook
    else:
        hook = _load("claude_skip", relative)
    payload = {"cwd": ".", "session_id": "target", "prompt": "/command"}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: pytest.fail("slash command must not claim"))
    hook.main()

    payload["prompt"] = "a duplicate model prompt"
    monkeypatch.setattr(hook, "check_dedup", lambda *_: True)
    if imported:
        calls = []
        monkeypatch.setattr(
            hook, "relay_request",
            lambda *_a, **_k: calls.append((_a, _k)) or _turn_response(),
        )
        hook.main()
        assert len(calls) == 1
    else:
        monkeypatch.setattr(
            hook, "relay_request",
            lambda *_a, **_k: pytest.fail("Claude duplicate must not claim"),
        )
        hook.main()


def test_codex_combined_output_is_relay_first_and_bounded(monkeypatch):
    from integrations.codex.hooks import user_prompt_submit as hook

    payload = {
        "cwd": ".",
        "session_id": "target",
        "prompt": "Please inspect the migration details and prior decisions carefully.",
    }
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook, "relay_request",
        lambda *_a, **_k: _turn_response([DELIVERY], has_more=True, remaining_count=2),
    )
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_a, **_k: {
            "source_item_id": "request-1",
            "injectable_blocks": [{
                "title": "Prior",
                "memory_object_id": "memory-1",
                "text": "x" * 2200,
                "expand_available": False,
            }],
        },
    )
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: None)
    outputs = []
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: outputs.append(text))
    with pytest.raises(SystemExit):
        hook.main()
    relay_text, scope_line = outputs[0].rsplit("\n\n", 1)
    assert relay_text.startswith("[Pallium Relay")
    assert relay_text.endswith("[Relay: 2 more; Pallium continues.]")
    assert len(relay_text) <= 2400
    assert len(scope_line) <= 2400
    assert json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    ) == {
        "container_ref": "git:example/repo", "thread_ref": "target",
        "actor_ref": "actor", "agent_ref": "codex", "visibility": "private",
    }


def test_claude_relay_uses_utf8_and_skips_memory_after_a_claim(monkeypatch):
    from io import BytesIO

    hook = _load("claude_utf8", "integrations/claude-code/hooks/user_prompt_submit.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "utf8", "prompt": "a sufficiently long prompt that must not query memory"})
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook,
        "relay_request",
        lambda *_args, **_kwargs: _turn_response([{**DELIVERY, "payload": "review → then continue"}], has_more=True, remaining_count=1),
    )
    monkeypatch.setattr(hook, "pallium_request", lambda *_args, **_kwargs: pytest.fail("claimed Relay must not wait for memory"))
    acknowledgements = []
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **_scope: acknowledgements.append(deliveries))

    class Cp1252Output:
        encoding = "cp1252"

        def __init__(self):
            self.buffer = BytesIO()

    output = Cp1252Output()
    monkeypatch.setattr(hook.sys, "stdout", output)
    with pytest.raises(SystemExit):
        hook.main()

    rendered = output.buffer.getvalue().decode("utf-8")
    relay_text, scope_line = rendered.rstrip().rsplit("\n\n", 1)
    assert "→" in relay_text
    assert relay_text.endswith("[Relay: 1 more; Pallium continues.]")
    assert len(relay_text) <= 2400
    assert len(scope_line) <= 2400
    assert json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    ) == {
        "container_ref": "git:example/repo", "thread_ref": "utf8",
        "actor_ref": "actor", "agent_ref": "claude-code", "visibility": "private",
    }
    assert acknowledgements == [[{**DELIVERY, "payload": "review → then continue"}]]

@pytest.mark.parametrize(
    ("name", "relative", "runtime"),
    [
        ("claude_unsafe_backlog", "integrations/claude-code/hooks/user_prompt_submit.py", "claude-code"),
        ("codex_unsafe_backlog", "integrations/codex/hooks/user_prompt_submit.py", "codex"),
    ],
)
def test_unsafe_only_relay_backlog_does_not_skip_memory(monkeypatch, name, relative, runtime):
    hook = _load(name, relative)
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "unsafe", "prompt": "a sufficiently long prompt for memory retrieval"})
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: _turn_response([{**DELIVERY, "payload": "unsafe\x00legacy"}], has_more=True, remaining_count=1))
    memory_calls = []
    monkeypatch.setattr(hook, "pallium_request", lambda *args, **kwargs: memory_calls.append((args, kwargs)) or None)
    acknowledgements = []
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **_scope: acknowledgements.append(deliveries))
    emitted = []
    if runtime == "codex":
        monkeypatch.setattr(hook, "emit_context", lambda *args: emitted.append(args))
    else:
        monkeypatch.setattr(hook, "emit_utf8", lambda *args, **kwargs: emitted.append(args) or True)

    with pytest.raises(SystemExit):
        hook.main()

    assert memory_calls
    assert acknowledgements == []
    assert emitted
    assert emitted[0][0].startswith("[Pallium scope — ")
    assert "[Pallium Relay message" not in emitted[0][0]


def test_claude_stop_emits_rendered_subset_before_ack(monkeypatch):
    hook = _load("claude_stop_relay", "integrations/claude-code/hooks/stop.py")
    deliveries = [{**DELIVERY, "payload": "first ✓"}, {**DELIVERY, "delivery_id": "relay-delivery-2", "payload": "second"}]
    calls = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        hook, "relay_request",
        lambda method, path, payload, *, timeout: calls.append((method, path, payload, timeout)) or _turn_response(deliveries, has_more=True, remaining_count=1),
    )
    events = []
    monkeypatch.setattr(hook, "_emit_relay", lambda text: events.append(("emit", text)))
    monkeypatch.setattr(
        hook, "acknowledge_relay",
        lambda claimed, **_scope: events.append(("ack", list(claimed))) or claimed[:1],
    )
    original_format = hook.format_relay
    formatted = []
    monkeypatch.setattr(
        hook, "format_relay",
        lambda rendered, **kwargs: formatted.append((rendered, kwargs))
        or original_format(rendered, **kwargs),
    )

    with pytest.raises(SystemExit) as stopped:
        hook.main()

    assert stopped.value.code == 2
    assert calls == [("POST", "/relay/turn", {
        "runtime": "claude-code", "session_ref": "target", "container_ref": "git:example/repo",
        "max_chars": 2360,
    }, 0.75)]
    assert [event[0] for event in events] == ["emit", "ack"]
    output = events[0][1]
    assert "first ✓" in output and "second" in output
    assert events[1][1] == deliveries
    relay_text, scope_line = output.rstrip().rsplit("\n\n", 1)
    assert relay_text.endswith("[Relay: 1 more; Pallium continues.]")
    assert json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    ) == {
        "container_ref": "git:example/repo", "thread_ref": "target",
        "actor_ref": "actor", "agent_ref": "claude-code", "visibility": "private",
    }
    assert formatted == [
        (deliveries, {"budget_chars": 2400, "remaining_count": 1}),
    ]


def test_claude_stop_invalid_scope_never_claims(monkeypatch):
    hook = _load("claude_stop_invalid_scope", "integrations/claude-code/hooks/stop.py")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "transcript_path": ""},
    )
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    registrations = []
    monkeypatch.setattr(
        hook, "register_claude_wake",
        lambda *_a, **kwargs: registrations.append(kwargs["idle"]),
    )
    monkeypatch.setattr(
        hook, "relay_request",
        lambda *_a, **_k: pytest.fail("invalid scope must not claim Relay"),
    )

    hook.main()
    assert registrations == [True, True]


def test_claude_stop_does_not_claim_during_recursive_continuation(monkeypatch):
    hook = _load("claude_stop_recursive", "integrations/claude-code/hooks/stop.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": "target", "stop_hook_active": True,
    })
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: pytest.fail("recursive Stop must not claim"))

    hook.main()


def test_acknowledge_relay_returns_only_successful_acknowledgments(monkeypatch):
    common = _load("claude_ack_success", "integrations/claude-code/hooks/common.py")
    responses = iter([{"state": "delivered"}, None])
    monkeypatch.setattr(common, "relay_request", lambda *_args, **_kwargs: next(responses))
    second = {**DELIVERY, "delivery_id": "relay-delivery-2"}

    assert common.acknowledge_relay([DELIVERY, second], container_ref="container") == [DELIVERY]

def test_claude_stop_emits_and_leaves_lease_when_acknowledgment_fails(monkeypatch, capsys):
    hook = _load("claude_stop_ack_failure", "integrations/claude-code/hooks/stop.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: _turn_response([DELIVERY]))
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_args, **_kwargs: [])

    with pytest.raises(SystemExit) as stopped:
        hook.main()
    assert stopped.value.code == 2
    assert "Review the migration" in capsys.readouterr().err


def test_claude_stop_does_not_ack_when_emission_fails(monkeypatch):
    hook = _load("claude_stop_emit_failure", "integrations/claude-code/hooks/stop.py")
    registrations = []
    acknowledgements = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(
        hook, "register_claude_wake",
        lambda *_args, **kwargs: registrations.append(kwargs["idle"]),
    )
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: _turn_response([DELIVERY]))
    monkeypatch.setattr(hook, "_emit_relay", lambda _text: (_ for _ in ()).throw(OSError("closed")))
    monkeypatch.setattr(
        hook, "acknowledge_relay",
        lambda deliveries, **_kwargs: acknowledgements.append(deliveries),
    )

    hook.main()

    assert acknowledgements == []
    assert registrations == [True, True]


@pytest.mark.parametrize("broken_format", [False, True])
def test_claude_stop_rearms_after_noncontinuing_probe(monkeypatch, broken_format):
    hook = _load("claude_stop_rearm_" + str(broken_format), "integrations/claude-code/hooks/stop.py")
    registrations = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **kwargs: registrations.append(kwargs["idle"]))
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: _turn_response())
    if broken_format:
        monkeypatch.setattr(hook, "format_relay", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    hook.main()
    assert registrations == [True, True]


def test_claude_stop_emits_unicode_to_utf8_stderr_buffer(monkeypatch):
    from io import BytesIO

    hook = _load("claude_stop_utf8_stderr", "integrations/claude-code/hooks/stop.py")

    class Cp1252Error:
        encoding = "cp1252"

        def __init__(self):
            self.buffer = BytesIO()

    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: _turn_response([{**DELIVERY, "payload": "review → ✓"}]))
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **_kwargs: deliveries)
    output = Cp1252Error()
    monkeypatch.setattr(hook.sys, "stderr", output)

    with pytest.raises(SystemExit) as stopped:
        hook.main()
    assert stopped.value.code == 2
    assert "review → ✓" in output.buffer.getvalue().decode("utf-8")


def test_storage_budget_reserves_notice_without_dropping_claim(client):
    common = _load("claude_boundary_format", "integrations/claude-code/hooks/common.py")
    scope = {"container_ref": "git:example/repo", "actor_ref": "actor"}
    sender = "s" * 255
    target = "t" * 255
    payload = "x" * 1500

    for runtime, session in (("codex", sender), ("claude-code", target)):
        assert client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    def send(message_id: str, body: str):
        response = client.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": sender,
            "recipient": f"claude-code:{target}", "message_id": message_id,
            "payload": body, **scope,
        })
        assert response.status_code == 200
        return response.json()["message_id"]

    baseline_id = send("a" * 128, payload)
    baseline = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": target, "max_chars": 10_000, **scope,
    }).json()["deliveries"]
    baseline_text, _ = common.format_relay(baseline)
    boundary = len(baseline_text)
    assert client.post("/relay/deliveries/ack", json={
        "delivery_id": baseline[0]["delivery_id"], "claim_token": baseline[0]["claim_token"], **scope,
    }).status_code == 200

    near_id = send("b" * 128, payload)
    fits_id = send("fits", "fits")
    turn = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": target, "max_chars": common.RELAY_TURN_BUDGET, **scope,
    }).json()
    rendered, rendered_deliveries = common.format_relay(
        turn["deliveries"],
        budget_chars=common.RELAY_OUTPUT_BUDGET,
        remaining_count=turn["remaining_count"],
    )

    assert baseline_id != near_id
    assert [delivery["message_id"] for delivery in turn["deliveries"]] == [near_id]
    assert rendered_deliveries == turn["deliveries"]
    assert rendered.endswith("[Relay: 1 more; Pallium continues.]")
    assert len(rendered) <= common.RELAY_OUTPUT_BUDGET
    assert fits_id != near_id
    assert turn["has_more"] is True and turn["remaining_count"] == 1


@pytest.mark.parametrize(
    ("name", "relative"),
    [
        ("claude_deadline", "integrations/claude-code/hooks/common.py"),
        ("codex_deadline", "integrations/codex/hooks/common.py"),
    ],
)
def test_hook_deadline_clamps_requests_and_skips_when_exhausted(
    monkeypatch, name, relative
):
    common = _load(name, relative)
    now = [100.0]
    common.start_hook_deadline(
        2.0, host_reserve=0.5, clock=lambda: now[0]
    )
    observed = []

    def timeout(_request, timeout):
        observed.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(common.urllib.request, "urlopen", timeout)
    assert common.relay_request("POST", "/relay/turn", {}, timeout=3.0) is None
    assert observed == [1.5]

    now[0] = 101.75
    assert common.pallium_request("GET", "/health") is None
    assert observed == [1.5]


@pytest.mark.parametrize(
    ("name", "relative", "returns_acknowledged"),
    [
        (
            "claude_ack_deadline",
            "integrations/claude-code/hooks/common.py",
            True,
        ),
        (
            "codex_ack_deadline",
            "integrations/codex/hooks/common.py",
            False,
        ),
    ],
)
def test_relay_ack_batch_stops_at_shared_deadline(
    monkeypatch, name, relative, returns_acknowledged
):
    common = _load(name, relative)
    now = [0.0]
    common.start_hook_deadline(
        0.8, host_reserve=0.1, clock=lambda: now[0]
    )
    observed = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def respond(_request, timeout):
        observed.append(timeout)
        now[0] = 0.71
        return Response()

    monkeypatch.setattr(common.urllib.request, "urlopen", respond)
    second = {
        **DELIVERY,
        "delivery_id": "relay-delivery-2",
        "claim_token": "relay-claim-2",
    }
    result = common.acknowledge_relay(
        [DELIVERY, second], container_ref="container"
    )

    assert observed == [0.5]
    if returns_acknowledged:
        assert result == [DELIVERY]
    else:
        assert result == []


@pytest.mark.parametrize(
    ("attempts", "claim_attempt", "possible_redelivery"),
    [
        (1, "1", "false"), (2, "2", "true"), (None, "unknown", "unknown"),
        (True, "unknown", "unknown"), (1.5, "unknown", "unknown"),
        ("2", "unknown", "unknown"), (0, "unknown", "unknown"),
        (-1, "unknown", "unknown"), (2**53 - 1, str(2**53 - 1), "true"),
        (2**53, "unknown", "unknown"), (float("inf"), "unknown", "unknown"),
        (float("nan"), "unknown", "unknown"), (1.0, "1", "false"),
    ],
)
@pytest.mark.parametrize(
    ("name", "relative"),
    [
        ("claude_common", "integrations/claude-code/hooks/common.py"),
        ("codex_common", "integrations/codex/hooks/common.py"),
    ],
)
def test_relay_formatter_exposes_normalized_redelivery_envelope(name, relative, attempts, claim_attempt, possible_redelivery):
    common = _load(name, relative)
    delivery = {**DELIVERY, "attempts": attempts, "delivery_id": "relay-Ünicode-😀"}
    text, rendered = common.format_relay([delivery])
    assert rendered == [delivery]
    assert "delivery_id: relay-Ünicode-😀" in text
    assert f"claim_attempt: {claim_attempt}" in text
    assert "possible_redelivery: " + possible_redelivery in text
    assert "Check exact delivery_id in context/artifacts." in text
    assert "Skip completed actions; if unknown, inspect target state before irreversible retry." in text
    assert "Attempts do not prove emission/actions." in text
    assert "ACK: receipt, not completion" in text
    assert (
        "Check exact delivery_id in context/artifacts. Skip completed actions; if unknown, inspect target state before irreversible retry. "
        "Attempts do not prove emission/actions. ACK: receipt, not completion"
    ) in text


def test_relay_formatter_redelivery_envelope_respects_budget_without_acknowledging_omitted_delivery():
    common = _load("codex_common_budget", "integrations/codex/hooks/common.py")
    delivery = {**DELIVERY, "attempts": 2}
    full, _ = common.format_relay([delivery])
    exact, included = common.format_relay([delivery], budget_chars=len(full))
    over, omitted = common.format_relay([delivery], budget_chars=len(full) - 1)
    assert exact == full and included == [delivery]
    assert over == "" and omitted == []


@pytest.mark.parametrize(
    ("runtime", "relative", "codex"),
    [
        ("claude-code", "integrations/claude-code/hooks/user_prompt_submit.py", False),
        ("codex", "integrations/codex/hooks/user_prompt_submit.py", True),
    ],
)
@pytest.mark.parametrize(
    "advance_empty_optional_lookup",
    [False, True],
    ids=["normal-deadline", "empty-discovery-optional-lookup"],
)
def test_configured_actor_hook_registers_and_delivers_across_git_containers(
    client, monkeypatch, tmp_path: Path, runtime: str, relative: str, codex: bool,
    advance_empty_optional_lookup: bool,
):
    """Relay delivery crosses containers and configured actor metadata."""
    # This test drives an ordinary turn; native wake/trace workers have separate coverage.
    monkeypatch.setattr("app.dependencies.schedule_claude_relay_wake", lambda *_args, **_kwargs: None)
    hook = _load(f"stable_actor_{runtime}", relative)
    lookup_calls = []
    discoveries = []
    if advance_empty_optional_lookup:
        common_namespace = hook.structural_work_refs_payload.__globals__
        monkeypatch.setitem(common_namespace, "_HOOK_DEADLINE", common_namespace["_HOOK_DEADLINE"])
        logical_now = [0.0]
        original_start_deadline = hook.start_hook_deadline

        def start_private_deadline(seconds, *, host_reserve=0.0):
            return original_start_deadline(
                seconds, host_reserve=host_reserve, clock=lambda: logical_now[0]
            )

        monkeypatch.setattr(hook, "start_hook_deadline", start_private_deadline)
        original_repository_scope_ref = common_namespace["repository_scope_ref"]

        def delayed_repository_scope_ref(cwd):
            lookup_calls.append(cwd)
            result = original_repository_scope_ref(cwd)
            logical_now[0] += 7.01
            return result

        monkeypatch.setitem(
            common_namespace, "repository_scope_ref", delayed_repository_scope_ref
        )
        original_discover_work_refs = hook.discover_work_refs

        def observe_discovery(cwd):
            discovery = original_discover_work_refs(cwd)
            discoveries.append(discovery)
            return discovery

        monkeypatch.setattr(hook, "discover_work_refs", observe_discovery)
    repos = []
    for name, git_name in (("source", "Source Git Name"), ("target", "Target Git Name")):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", git_name], cwd=repo, check=True, capture_output=True)
        repos.append(repo)
    source, target = repos
    monkeypatch.setitem(hook.derive_actor_ref.__globals__, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_args: ([], 0))
    monkeypatch.setattr(hook, "check_dedup", lambda *_args: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_args, **_kwargs: None)

    def relay(method, path, body, *, timeout):
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def acknowledge(deliveries, *, container_ref):
        for delivery in deliveries:
            response = client.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"],
                "container_ref": container_ref,
            })
            assert response.status_code == 200, response.text
        return deliveries if runtime == "claude-code" else None

    monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)
    emitted: list[str] = []
    if codex:
        monkeypatch.setattr(hook, "emit_context", lambda text, _event: emitted.append(text))
    else:
        monkeypatch.setattr(hook, "emit_utf8", lambda text, **_kwargs: emitted.append(text) or True)
        monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)

    payload = {"cwd": str(source), "session_id": "source-session", "prompt": "hi"}
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "מפעיל מקור")
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    with pytest.raises(SystemExit):
        hook.main()
    payload = {"cwd": str(target), "session_id": "target-session", "prompt": "hi"}
    monkeypatch.setenv("PALLIUM_HOOK_ACTOR_REF", "操作员目标")
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    with pytest.raises(SystemExit):
        hook.main()

    target_container = hook.resolve_container_ref(str(target), "target-session")
    sessions = client.get("/relay/sessions", params={"container_ref": target_container}).json()
    assert [(row["runtime"], row["session_ref"]) for row in sessions] == [(runtime, "target-session")]
    target_endpoint = sessions[0]["endpoint_id"]
    source_container = hook.resolve_container_ref(str(source), "source-session")
    sent = client.post("/relay/messages", json={
        "sender_runtime": runtime, "sender_session_ref": "source-session",
        "recipient": target_endpoint, "payload": "cross-container delivery",
        "container_ref": source_container,
    })
    assert sent.status_code == 200, sent.text
    payload = {"cwd": str(target), "session_id": "target-session", "prompt": "deliver this"}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    with pytest.raises(SystemExit):
        hook.main()
    assert any("cross-container delivery" in text for text in emitted)
    assert client.get(f"/relay/messages/{sent.json()['message_id']}", params={"container_ref": target_container}).json()["deliveries"][0]["state"] == "delivered"
    if advance_empty_optional_lookup:
        assert discoveries and all(not discovery.structural_refs for discovery in discoveries)
        assert lookup_calls == []
