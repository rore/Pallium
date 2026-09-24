from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import codex_wake
from app.dependencies import build_router
from core.codex_wake import CodexWakeRegistry
from core.relay import RelayService
from integrations.codex.hooks import user_prompt_submit as hook_module


@pytest.fixture(autouse=True)
def isolate_codex_wake(monkeypatch):
    registry = CodexWakeRegistry()
    process = MagicMock(returncode=0)
    process.communicate.return_value = (None, "")
    monkeypatch.setattr(codex_wake, "get_codex_wake_registry", lambda *_args, **_kwargs: registry)
    monkeypatch.setattr(codex_wake, "_popen", lambda *_args, **_kwargs: process)
    previous_deadline = hook_module._common._HOOK_DEADLINE
    hook_module._common._HOOK_DEADLINE = None
    for state in (
        codex_wake._scheduled_delivery_ids,
        codex_wake._scheduled_session_generations,
        codex_wake._scheduled_session_delivery_ids,
        codex_wake._scheduled_session_attempt_ids,
    ):
        state.clear()
    yield registry
    hook_module._common._HOOK_DEADLINE = previous_deadline
    for state in (
        codex_wake._scheduled_delivery_ids,
        codex_wake._scheduled_session_generations,
        codex_wake._scheduled_session_delivery_ids,
        codex_wake._scheduled_session_attempt_ids,
    ):
        state.clear()

def test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake(
    client, monkeypatch, tmp_path, capsys, isolate_codex_wake,
) -> None:
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/overtaken-wake",
    }
    state_dir = tmp_path / "overtaken-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        codex_wake.schedule_codex_relay_wake,
    )
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        codex_wake_registry=isolate_codex_wake,
    ))
    route = TestClient(app)
    for runtime, session in (("claude-code", "sender"), ("codex", "target")):
        assert route.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    workers = []
    clock = [10.0]
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    monkeypatch.setattr(codex_wake.time, "monotonic", lambda: clock[0])
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        sent = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "consume before queued wake executes →",
            **scope,
        }).json()
        assert len(workers) == 1

        codex_home = tmp_path / "codex-home"
        codex_home.mkdir()
        monkeypatch.setattr(codex_wake, "_codex_home", lambda: codex_home)
        native_calls = []

        def native_run(command, **kwargs):
            native_calls.append((command, kwargs))
            process = MagicMock(returncode=0)
            process.communicate.return_value = (None, "")
            return process

        processed = 0
        relay = RelayService(client.app.state.pallium_service._storage)
        with patch("app.codex_wake._popen", side_effect=native_run):
            for _ in range(6):
                while processed < len(workers):
                    codex_wake._wake_after_debounce(*workers[processed])
                    processed += 1
                clock[0] += 31
                recover_expired_relay_wakes(
                    relay, ClaudeWakeRegistry(), codex_registry=isolate_codex_wake,
                )

    queue_calls = [call for call in native_calls if call[0][1] == "queue"]
    assert len(queue_calls) == 1
    queue_command, queue_kwargs = queue_calls[0]
    assert queue_kwargs["cwd"] == str(codex_home)
    queued_prompt = queue_command[queue_command.index("--message") + 1]
    assert queued_prompt == codex_wake._wake_prompt(
        sent["deliveries"][0]["delivery_id"]
    )
    assert route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]["state"] == "pending"

    hook._common.pin_container("target", scope["container_ref"])
    prompts = iter(("a competing natural turn", queued_prompt))
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path), "session_id": "target", "prompt": next(prompts),
    })
    contexts = []
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: contexts.append(text))
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("empty wake must not query memory"),
    )

    def relay_request(method: str, path: str, payload: dict, *, timeout: float, deadline=None):
        response = route.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        return response.json() if response.content else None

    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)

    with pytest.raises(SystemExit) as competing:
        hook.main()
    assert competing.value.code == 0
    assert len(contexts) == 1
    assert "consume before queued wake executes →" in contexts[0]
    delivered = route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert delivered["state"] == "delivered" and delivered["attempts"] == 1
    assert not codex_wake._scheduled_session_generations

    contexts.clear()
    capsys.readouterr()
    with pytest.raises(SystemExit) as overtaken:
        hook.main()
    assert overtaken.value.code == 0
    assert contexts == []
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "decision": "block",
        "reason": "Pallium Relay wake suppressed: no verified pending delivery.",
    }
    assert captured.err == ""
    assert route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0] == delivered
    assert route.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", **scope,
    }).json()["deliveries"] == []
