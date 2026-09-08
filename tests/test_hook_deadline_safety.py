from __future__ import annotations

import importlib.util
import io
import sys
import threading
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
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
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


@pytest.mark.parametrize("relative", COMMONS)
def test_partial_hook_input_cannot_outlive_deadline(relative, monkeypatch):
    common = _load("deadline_stdin_" + relative.replace("/", "_"), relative)
    common.start_hook_deadline(2.0, host_reserve=0.5, clock=lambda: 10.0)
    started = threading.Event()
    release = threading.Event()
    joined = []
    workers = []
    real_thread = threading.Thread

    class BlockingInput:
        def read(self, _limit):
            started.set()
            release.wait(1)
            return "{}"

    class DeadlineThread:
        def __init__(self, *, target, daemon):
            self.thread = real_thread(target=target, daemon=daemon)
            workers.append(self.thread)

        def start(self):
            self.thread.start()

        def join(self, timeout):
            joined.append(timeout)
            assert started.wait(1)

        def is_alive(self):
            return self.thread.is_alive()

    monkeypatch.setattr(common.threading, "Thread", DeadlineThread)
    monkeypatch.setattr(common.sys, "stdin", BlockingInput())
    assert common.read_hook_input() == {}
    assert joined == [1.5]
    release.set()
    workers[0].join(1)


@pytest.mark.parametrize("relative", COMMONS)
@pytest.mark.parametrize("request_kind", ("pallium", "relay"))
def test_slow_response_body_cannot_outlive_deadline(
    relative, request_kind, monkeypatch,
):
    common = _load(
        f"deadline_response_{request_kind}_" + relative.replace("/", "_"),
        relative,
    )
    common.start_hook_deadline(2.0, host_reserve=0.5, clock=lambda: 10.0)
    started = threading.Event()
    release = threading.Event()
    joined = []
    workers = []
    real_thread = threading.Thread

    class BlockingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            started.set()
            release.wait(1)
            return b'{}'

    class DeadlineThread:
        def __init__(self, *, target, daemon):
            self.thread = real_thread(target=target, daemon=daemon)
            workers.append(self.thread)

        def start(self):
            self.thread.start()

        def join(self, timeout):
            joined.append(timeout)
            assert started.wait(1)

        def is_alive(self):
            return self.thread.is_alive()

    monkeypatch.setattr(common.threading, "Thread", DeadlineThread)
    monkeypatch.setattr(common.urllib.request, "urlopen", lambda *_a, **_k: BlockingResponse())
    if request_kind == "pallium":
        result = common.pallium_request("GET", "/health")
    else:
        result = common.relay_request("POST", "/relay/turn", {}, timeout=3.0)
    assert result is None
    assert joined == [1.5]
    release.set()
    workers[0].join(1)


@pytest.mark.parametrize("operation", ("register", "close"))
def test_claude_wake_control_request_cannot_outlive_deadline(operation, monkeypatch):
    common = _load(f"deadline_claude_wake_{operation}", "integrations/claude-code/hooks/common.py")
    common.start_hook_deadline(2.0, host_reserve=0.5, clock=lambda: 10.0)
    started = threading.Event()
    release = threading.Event()
    joined = []
    workers = []
    real_thread = threading.Thread

    class BlockingOpener:
        def open(self, *_args, **_kwargs):
            started.set()
            release.wait(1)
            return None

    class DeadlineThread:
        def __init__(self, *, target, daemon):
            self.thread = real_thread(target=target, daemon=daemon)
            workers.append(self.thread)

        def start(self):
            self.thread.start()

        def join(self, timeout):
            joined.append(timeout)
            assert started.wait(1)

        def is_alive(self):
            return self.thread.is_alive()

    monkeypatch.setattr(common.threading, "Thread", DeadlineThread)
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_args: BlockingOpener())
    monkeypatch.setattr(common, "_write_wake_intent", lambda _payload: True)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "socket")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "token")

    if operation == "register":
        result = common.register_claude_wake("session", "container")
    else:
        result = common.close_claude_wake("session", "container")

    assert not result
    assert joined == [1.5]
    release.set()
    workers[0].join(1)


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


def test_claude_user_prompt_outer_timeout_preserves_process_startup_slack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.cli import setup_claude_code

    hook = _load(
        "deadline_claude_prompt_outer_contract",
        "integrations/claude-code/hooks/user_prompt_submit.py",
    )
    started = []

    class Halt(BaseException):
        pass

    monkeypatch.setattr(
        hook,
        "start_hook_deadline",
        lambda *args, **kwargs: started.append((args, kwargs)),
    )
    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: (_ for _ in ()).throw(Halt()),
    )
    with pytest.raises(Halt):
        hook.main()

    settings = setup_claude_code._register_hooks({})
    managed = [
        item
        for entry in settings["hooks"]["UserPromptSubmit"]
        for item in entry["hooks"]
        if item["command"].endswith("user_prompt_submit.py")
    ]
    assert len(managed) == 1
    active_budget = started[0][0][0] - started[0][1]["host_reserve"]
    assert managed[0]["timeout"] - active_budget == 5
