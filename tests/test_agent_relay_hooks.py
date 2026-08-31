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
def test_relay_helpers_are_bounded_control_safe_and_use_requested_deadline(monkeypatch, name, relative):
    common = _load(name, relative)
    rendered, rendered_deliveries = common.format_relay([DELIVERY], budget_chars=2000)
    assert rendered.startswith("[Pallium Relay message from claude-code:sender-session]")
    assert "lower authority" in rendered
    assert "delivery_id: relay-delivery-1" in rendered
    assert "pallium_relay_reply" in rendered
    assert "make its Pallium Relay origin clear" in rendered
    assert rendered_deliveries == [DELIVERY]
    assert "line one\nline two\tvalue" in common.format_relay(
        [{**DELIVERY, "payload": "line one\nline two\tvalue"}], budget_chars=2000
    )[0]
    assert common.format_relay([DELIVERY], budget_chars=20)[0] == ""
    assert common.format_relay([{**DELIVERY, "payload": "bad\x00value"}])[0] == ""
    maximum = {
        **DELIVERY,
        "message_id": "m" * 128,
        "sender_session_ref": "s" * 255,
        "in_reply_to": "p" * 128,
        "payload": "😀" * 1500,
    }
    assert common.format_relay([maximum], budget_chars=2400)[0]

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
        },
        0.75,
    )
    assert output and output[0][0].startswith("[Pallium Relay message")
    assert "[Pallium scope — " not in output[0][0]
    assert acknowledged and acknowledged[0][0] == [DELIVERY]


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
        hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")
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


def test_claude_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    hook = _load("claude_prompt", "integrations/claude-code/hooks/user_prompt_submit.py")
    _exercise_short_prompt(hook, monkeypatch, codex=False)


def test_codex_short_prompt_delivers_relay_before_memory_gate(monkeypatch):
    hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")

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
        hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")
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

def test_slash_turn_never_claims(monkeypatch):
    hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")

    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target", "prompt": "/command"})
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: pytest.fail("slash command must not claim"))
    hook.main()


def test_codex_duplicate_prompt_still_drains_new_relay_mail(monkeypatch):
    hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")

    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target", "prompt": "same prompt"})
    monkeypatch.setattr(hook, "check_dedup", lambda *_: True)
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda *_: [])
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: "actor")
    calls = []
    monkeypatch.setattr(hook, "relay_request", lambda method, path, body, *, timeout: calls.append((path, body)) or {"deliveries": [DELIVERY]})
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: None)
    output = []
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: output.append(text))
    with pytest.raises(SystemExit):
        hook.main()
    assert calls[0][0] == "/relay/turn"
    assert output[0].startswith("[Pallium Relay message")


def test_codex_candidate_envelope_is_fenced_and_never_auto_acked(monkeypatch):
    common = _load("codex_candidate", "integrations/codex/hooks/common.py")
    envelope = "[Pallium Relay batch from claude-code:sender]\\n[Pallium scope — {}]\\n[End Pallium Relay batch]"
    candidate = {**DELIVERY, "protocol_version": "batch_v2_candidate", "envelope": envelope,
                 "envelope_digest": __import__("hashlib").sha256(envelope.encode()).hexdigest()}
    rendered, selected = common.format_relay([candidate])
    assert rendered == envelope
    calls = []
    monkeypatch.setattr(common, "relay_request", lambda method, path, body, *, timeout: calls.append((path, body)) or {"ok": True})
    assert common.begin_relay_publication(selected, container_ref="container", actor_ref="actor") == [candidate]
    common.acknowledge_relay([candidate], container_ref="container", actor_ref="actor")
    assert [path for path, _ in calls] == ["/relay/deliveries/publication"]

def test_codex_combined_output_is_relay_first_and_bounded(monkeypatch):
    hook = _load("codex_hook", "integrations/codex/hooks/user_prompt_submit.py")

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
    assert "→" in rendered
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
