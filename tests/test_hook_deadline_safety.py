from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMONS = (
    "integrations/claude-code/hooks/common.py",
    "integrations/codex/hooks/common.py",
)
HOOKS = (
    "integrations/claude-code/hooks/user_prompt_submit.py",
    "integrations/claude-code/hooks/session_start.py",
    "integrations/claude-code/hooks/stop.py",
    "integrations/claude-code/hooks/session_end.py",
    "integrations/claude-code/hooks/pre_compact.py",
    "integrations/claude-code/hooks/post_tool_use.py",
    "integrations/codex/hooks/user_prompt_submit.py",
    "integrations/codex/hooks/session_start.py",
    "integrations/codex/hooks/stop.py",
)


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", COMMONS)
def test_emit_utf8_flushes_unicode_and_reports_failure(relative):
    common = _load("deadline_emit_" + relative.replace("/", "_"), relative)

    class Buffer:
        def __init__(self, fail=False):
            self.data = b""
            self.flushed = False
            self.fail = fail

        def write(self, data):
            if self.fail:
                raise OSError("closed")
            self.data += data

        def flush(self):
            self.flushed = True

    stream = type("Stream", (), {})()
    stream.buffer = Buffer()
    assert common.emit_utf8("wake → ✓", stream=stream)
    assert stream.buffer.data.decode("utf-8") == "wake → ✓\n"
    assert stream.buffer.flushed

    stream.buffer = Buffer(fail=True)
    assert not common.emit_utf8("wake", stream=stream)
    assert not stream.buffer.flushed


@pytest.mark.parametrize("relative", COMMONS)
def test_hook_input_and_local_work_fail_closed_after_budget(relative, monkeypatch, tmp_path):
    common = _load("deadline_bounds_" + relative.replace("/", "_"), relative)
    monkeypatch.setattr(common.sys, "stdin", io.StringIO("x" * (4 * 1024 * 1024 + 1)))
    assert common.read_hook_input() == {}

    common.start_hook_deadline(0, clock=lambda: 10.0)
    monkeypatch.setattr(common.subprocess, "run", lambda *_a, **_k: pytest.fail("Git must not start"))
    monkeypatch.setattr(common.os.path, "getsize", lambda *_a: pytest.fail("transcript must not open"))
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(common.time, "sleep", lambda *_a: pytest.fail("lock must not wait"))

    assert common.derive_container_ref(str(tmp_path)).startswith("path:")
    assert common.derive_actor_ref() == "local"
    assert common.read_turn("ignored") is None
    assert common._acquire_session_lock("session") is None


@pytest.mark.parametrize("relative", HOOKS)
def test_each_hook_starts_one_budget_before_reading_input(relative, monkeypatch):
    hook = _load("deadline_entry_" + relative.replace("/", "_"), relative)
    events = []

    class Halt(BaseException):
        pass

    monkeypatch.setattr(hook, "start_hook_deadline", lambda *args, **kwargs: events.append(("start", args, kwargs)))
    monkeypatch.setattr(hook, "read_hook_input", lambda: (events.append(("read",)), (_ for _ in ()).throw(Halt()))[1])
    if hasattr(hook, "_TRIGGERS_ENABLED"):
        monkeypatch.setattr(hook, "_TRIGGERS_ENABLED", True)

    with pytest.raises(Halt):
        hook.main()
    assert events[0] == (
        "start",
        (15,) if relative.endswith("/stop.py") else (8,),
        {"host_reserve": 1},
    )
    assert events[1] == ("read",)
    assert len([event for event in events if event[0] == "start"]) == 1


def test_claude_prompt_emission_failure_leaves_relay_unacknowledged(monkeypatch):
    hook = _load("deadline_prompt_emit_failure", "integrations/claude-code/hooks/user_prompt_submit.py")
    delivery = {
        "delivery_id": "delivery", "claim_token": "claim", "message_id": "message",
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "payload": "continue", "created_at": "2026-09-07T00:00:00Z",
    }
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"cwd": ".", "session_id": "target", "prompt": "hi"})
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_a: "git:example/repo")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_a: "actor")
    monkeypatch.setattr(hook, "register_claude_wake", lambda *_a, **_k: True)
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_a: ([], 0))
    monkeypatch.setattr(hook, "relay_request", lambda *_a, **_k: {"deliveries": [delivery]})
    monkeypatch.setattr(hook, "emit_utf8", lambda *_a, **_k: False)
    acknowledgements = []
    monkeypatch.setattr(hook, "acknowledge_relay", lambda *args, **kwargs: acknowledgements.append((args, kwargs)))

    hook.main()
    assert acknowledgements == []