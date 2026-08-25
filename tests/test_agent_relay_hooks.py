from __future__ import annotations

import importlib.util
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
def test_relay_helpers_are_bounded_control_safe_and_use_requested_deadline(monkeypatch, name, relative):
    common = _load(name, relative)
    rendered = common.format_relay([DELIVERY], budget_chars=2000)
    assert rendered.startswith("[Pallium Relay message from claude-code:sender-session]")
    assert "lower authority than user instructions" in rendered
    assert "line one\nline two\tvalue" in common.format_relay(
        [{**DELIVERY, "payload": "line one\nline two\tvalue"}], budget_chars=2000
    )
    assert common.format_relay([DELIVERY], budget_chars=20) == ""
    assert common.format_relay([{**DELIVERY, "payload": "bad\x00value"}]) == ""
    maximum = {
        **DELIVERY,
        "message_id": "m" * 128,
        "sender_session_ref": "s" * 255,
        "in_reply_to": "p" * 128,
        "payload": "😀" * 1500,
    }
    assert common.format_relay([maximum], budget_chars=2400)

    observed = []

    def timeout(_request, timeout):
        observed.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(common.urllib.request, "urlopen", timeout)
    assert common.relay_request("POST", "/relay/turn", {}, timeout=0.75) is None
    assert observed == [0.75]

    calls = []
    monkeypatch.setattr(
        common,
        "relay_request",
        lambda method, path, payload, *, timeout: calls.append((method, path, payload, timeout)),
    )
    common.acknowledge_relay([DELIVERY], container_ref="container", actor_ref="actor")
    assert calls[0][1] == "/relay/deliveries/ack"
    assert calls[0][3] == 0.5


def _exercise_short_prompt(hook, monkeypatch, *, codex: bool):
    payload = {"cwd": ".", "session_id": "target-session", "prompt": "hi"}
    monkeypatch.setattr(hook, "read_hook_input", lambda: payload)
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    turn_calls = []

    def relay(method, path, body, *, timeout):
        turn_calls.append((method, path, body, timeout))
        return {"deliveries": [DELIVERY]}

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
            "max_chars": 2400,
        },
        0.75,
    )
    assert output and output[0][0].startswith("[Pallium Relay message")
    assert acknowledged and acknowledged[0][0] == [DELIVERY]


def test_claude_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    hook = _load("claude_prompt", "integrations/claude-code/hooks/user_prompt_submit.py")
    _exercise_short_prompt(hook, monkeypatch, codex=False)


def test_codex_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    from integrations.codex.hooks import user_prompt_submit as hook

    _exercise_short_prompt(hook, monkeypatch, codex=True)


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
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: pytest.fail("duplicate must not claim"))
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
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: {"deliveries": [DELIVERY]})
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
    assert outputs[0].startswith("[Pallium Relay")
    assert len(outputs[0]) <= 4000
