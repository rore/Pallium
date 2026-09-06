from __future__ import annotations

import importlib.util
import json
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
        "payload": "😀" * 1500,
        "created_at": "2026-09-05T12:34:56.123456+00:00",
    }
    maximum_output, maximum_rendered = common.format_relay(
        [maximum], budget_chars=2400, remaining_count=1000,
    )
    assert maximum_rendered == [maximum]
    assert maximum_output.endswith("[Relay: 999+ more; Pallium continues.]")
    assert len(maximum_output) <= 2400

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
    acknowledged = common.acknowledge_relay([DELIVERY], container_ref="container", actor_ref="actor")
    if name == "claude_common":
        assert acknowledged == []
    else:
        assert acknowledged is None
    assert calls[0][1] == "/relay/deliveries/ack"
    assert calls[0][3] == 0.5


def _exercise_short_prompt(hook, monkeypatch, *, codex: bool):
    payload = {"cwd": ".", "session_id": "target-session", "prompt": "hi"}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    turn_calls = []

    def relay(method, path, body, *, timeout):
        turn_calls.append((method, path, body, timeout))
        return {"deliveries": [
            {**DELIVERY, "delivery_id": "skipped", "payload": "bad\x00value"},
            DELIVERY,
        ]}

    monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(hook, "pallium_request", lambda *_args, **_kwargs: pytest.fail("short prompt must skip memory"))
    acknowledged = []
    monkeypatch.setattr(
        hook,
        "acknowledge_relay",
        lambda deliveries, **scope: acknowledged.append((deliveries, scope)),
    )
    output = []
    if codex:
        monkeypatch.setattr(hook, "emit_context", lambda text, event: output.append((text, event)))
    else:
        monkeypatch.setattr("builtins.print", lambda text, **_kwargs: output.append((text, None)))

    with pytest.raises(SystemExit):
        hook.main()
    assert turn_calls[0][1:] == (
        "/relay/turn",
        {
            "runtime": "codex" if codex else "claude-code",
            "session_ref": "target-session",
            "container_ref": "git:example/repo",
            "actor_ref": "actor",
            "max_chars": 2360,
        },
        0.75,
    )
    assert output and output[0][0].startswith("[Pallium Relay message")
    relay_text, scope_line = output[0][0].rsplit("\n\n", 1)
    assert "Review the migration before editing." in relay_text
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
    assert acknowledged and acknowledged[0][0] == [DELIVERY]


def test_codex_confirmed_empty_internal_wake_blocks_before_model(monkeypatch, capsys):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    assert hook.RELAY_WAKE_PROMPT == codex_wake._wake_prompt()
    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "prompt": hook.RELAY_WAKE_PROMPT},
    )
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(
        hook,
        "relay_request",
        lambda *_a, **_k: {
            "deliveries": [], "has_more": False, "remaining_count": 0,
        },
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
        "reason": "Pallium Relay wake superseded: no pending delivery.",
    }
    assert captured.err == ""


@pytest.mark.parametrize(
    "relay_response",
    [
        None,
        {},
        {"deliveries": None},
        {"deliveries": "invalid"},
        ["invalid"],
        {"deliveries": []},
        {"deliveries": [], "has_more": True, "remaining_count": 1},
        {"deliveries": [], "has_more": False, "remaining_count": False},
    ],
)
def test_codex_internal_wake_blocks_without_confirmed_empty(
    monkeypatch, capsys, relay_response,
):
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "prompt": hook.RELAY_WAKE_PROMPT},
    )
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: relay_response)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "emit_context", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["decision"] == "block"
    assert captured.err == ""


def test_codex_internal_wake_without_valid_scope_blocks(monkeypatch, capsys):
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "prompt": hook.RELAY_WAKE_PROMPT},
    )
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(
        hook, "relay_request", lambda *_a, **_k: pytest.fail("invalid scope must not claim Relay"),
    )
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["decision"] == "block"
    assert captured.err == ""

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
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: {"deliveries": []})
    monkeypatch.setattr(
        hook, "pallium_request",
        lambda *_a, **_k: pytest.fail("short prompt must skip memory"),
    )
    outputs = []
    if imported:
        monkeypatch.setattr(hook, "emit_context", lambda text, _event: outputs.append(text))
    else:
        monkeypatch.setattr("builtins.print", lambda text, **_kwargs: outputs.append(text))
    with pytest.raises(SystemExit):
        hook.main()
    assert len(outputs) == 1
    scope = json.loads(outputs[0].removeprefix("[Pallium scope — ").removesuffix("]"))
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
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
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
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "pin_container", lambda *_a, **_k: None)
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: None)
    monkeypatch.setattr(
        hook, "relay_request", lambda *_a, **_k: {"deliveries": [DELIVERY]},
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


def test_claude_session_start_invalid_scope_never_claims(monkeypatch):
    hook = _load("claude_session_start_invalid", "integrations/claude-code/hooks/session_start.py")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target-session", "source": "startup"},
    )
    monkeypatch.setattr(hook, "derive_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
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
    ("relative", "runtime", "imported"),
    [
        ("integrations/claude-code/hooks/user_prompt_submit.py", "claude-code", False),
        ("integrations/codex/hooks/user_prompt_submit.py", "codex", True),
    ],
)
def test_failed_project_close_is_retried(
    monkeypatch, relative, runtime, imported
):
    if imported:
        from integrations.codex.hooks import user_prompt_submit as hook
    else:
        hook = _load("claude_switch", relative)
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "prompt": "hi"},
    )
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:new/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    state = {"pending": ["git:old/repo"]}
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: list(state["pending"]))
    monkeypatch.setattr(
        hook, "pin_container",
        lambda _session, _container, *, pending_relay_closes: state.update(
            pending=list(pending_relay_closes)
        ),
    )
    calls = []
    close_attempts = 0

    def relay(method, path, body, *, timeout):
        nonlocal close_attempts
        calls.append((method, path, body, timeout))
        if path == "/relay/sessions/close":
            close_attempts += 1
            return None if close_attempts == 1 else {"state": "closed"}
        return {"deliveries": []}

    monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: None)
    if imported:
        monkeypatch.setattr(hook, "emit_context", lambda *_: None)
    for _ in range(2):
        with pytest.raises(SystemExit):
            hook.main()
    assert [call[1] for call in calls] == [
        "/relay/sessions/close", "/relay/turn",
        "/relay/sessions/close", "/relay/turn",
    ]
    assert calls[0][2] == {
        "runtime": runtime,
        "session_ref": "target",
        "container_ref": "git:old/repo",
        "actor_ref": "actor",
    }
    assert state["pending"] == []

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
            lambda *_a, **_k: calls.append((_a, _k)) or {"deliveries": []},
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
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(
        hook, "relay_request",
        lambda *_a, **_k: {"deliveries": [DELIVERY], "has_more": True, "remaining_count": 2},
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
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(
        hook,
        "relay_request",
        lambda *_args, **_kwargs: {"deliveries": [{**DELIVERY, "payload": "review → then continue"}], "has_more": True, "remaining_count": 1},
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
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: {"deliveries": [{**DELIVERY, "payload": "unsafe\x00legacy"}], "has_more": True, "remaining_count": 1})
    memory_calls = []
    monkeypatch.setattr(hook, "pallium_request", lambda *args, **kwargs: memory_calls.append((args, kwargs)) or None)
    acknowledgements = []
    monkeypatch.setattr(hook, "acknowledge_relay", lambda deliveries, **_scope: acknowledgements.append(deliveries))
    emitted = []
    if runtime == "codex":
        monkeypatch.setattr(hook, "emit_context", lambda *args: emitted.append(args))
    else:
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: emitted.append(args))

    with pytest.raises(SystemExit):
        hook.main()

    assert memory_calls
    assert acknowledgements == []
    assert emitted
    assert emitted[0][0].startswith("[Pallium scope — ")
    assert "[Pallium Relay message" not in emitted[0][0]


def test_claude_stop_claims_only_nonrecursive_turns_and_emits_acknowledged_subset(monkeypatch, capsys):
    hook = _load("claude_stop_relay", "integrations/claude-code/hooks/stop.py")
    deliveries = [{**DELIVERY, "payload": "first ✓"}, {**DELIVERY, "delivery_id": "relay-delivery-2", "payload": "second"}]
    calls = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        hook, "relay_request",
        lambda method, path, payload, *, timeout: calls.append((method, path, payload, timeout)) or {
            "deliveries": deliveries, "has_more": True, "remaining_count": 1,
        },
    )
    monkeypatch.setattr(hook, "acknowledge_relay", lambda claimed, **_scope: claimed[:1])
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
        "actor_ref": "actor", "max_chars": 2360,
    }, 0.75)]
    output = capsys.readouterr().err
    assert "first ✓" in output and "second" not in output
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
        (deliveries[:1], {"budget_chars": 2400, "remaining_count": 1}),
    ]


def test_claude_stop_invalid_scope_never_claims(monkeypatch):
    hook = _load("claude_stop_invalid_scope", "integrations/claude-code/hooks/stop.py")
    monkeypatch.setattr(
        hook, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "target", "transcript_path": ""},
    )
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "bad\nscope")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
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
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: pytest.fail("recursive Stop must not claim"))

    hook.main()


def test_acknowledge_relay_returns_only_successful_acknowledgments(monkeypatch):
    common = _load("claude_ack_success", "integrations/claude-code/hooks/common.py")
    responses = iter([{"state": "delivered"}, None])
    monkeypatch.setattr(common, "relay_request", lambda *_args, **_kwargs: next(responses))
    second = {**DELIVERY, "delivery_id": "relay-delivery-2"}

    assert common.acknowledge_relay([DELIVERY, second], container_ref="container", actor_ref="actor") == [DELIVERY]

def test_claude_stop_continues_normally_when_all_acknowledgments_fail(monkeypatch, capsys):
    hook = _load("claude_stop_ack_failure", "integrations/claude-code/hooks/stop.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: {"deliveries": [DELIVERY]})
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_args, **_kwargs: [])

    hook.main()
    assert "Review the migration" not in capsys.readouterr().err


@pytest.mark.parametrize("broken_format", [False, True])
def test_claude_stop_rearms_after_noncontinuing_probe(monkeypatch, broken_format):
    hook = _load("claude_stop_rearm_" + str(broken_format), "integrations/claude-code/hooks/stop.py")
    registrations = []
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **kwargs: registrations.append(kwargs["idle"]))
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: {"deliveries": []})
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
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(hook, "relay_request", lambda *_args, **_kwargs: {"deliveries": [{**DELIVERY, "payload": "review → ✓"}]})
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
