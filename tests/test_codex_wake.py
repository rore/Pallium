from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import threading
from unittest.mock import patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from app.dependencies import build_router
from app import codex_wake
from app.config import AppConfig
from app.main import create_app
from core.relay import RelayService
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


SCOPE = {
    "container_ref": "git:example.test/wake",
    "actor_ref": "wake-user",
}


def _delivery(delivery_id: str = "delivery-1", runtime: str = "codex") -> dict:
    return {
        "recipient": "codex:target-session",
        "deliveries": [
            {
                "delivery_id": delivery_id,
                "recipient_runtime": runtime,
                "state": "pending",
                "recipient_session_ref": "target-session",
            }
        ]
    }


def _schedule(result: dict) -> None:
    codex_wake.schedule_codex_relay_wake(result, SCOPE)


def setup_function() -> None:
    codex_wake._scheduled_delivery_ids.clear()
    codex_wake._scheduled_session_generations.clear()
    codex_wake._scheduled_session_delivery_ids.clear()


def test_successful_resume_does_not_queue_and_hides_process() -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    with patch("app.codex_wake.subprocess.run", return_value=completed) as run:
        assert codex_wake._launch("target-session", "wake prompt") == "exec_completed"
    assert run.call_args.args[0] == [
        codex_wake._codex_executable(), "exec", "--profile", "pallium-relay",
        "resume", "target-session", "-", "--json"
    ]
    assert run.call_args.kwargs["input"] == "wake prompt"
    assert run.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert run.call_args.kwargs["stderr"] is subprocess.PIPE
    assert "shell" not in run.call_args.kwargs


def test_exact_active_writer_queues_generic_trigger_hidden() -> None:
    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    queued = subprocess.CompletedProcess([], 0, stderr="")
    generic_prompt = codex_wake._wake_prompt()
    prompt = generic_prompt + " →"
    with patch("app.codex_wake.subprocess.run", side_effect=[active, queued]) as run:
        assert codex_wake._launch("target-session", prompt) == "queued"
    assert run.call_count == 2
    assert run.call_args_list[0].kwargs["input"] == prompt
    assert run.call_args_list[0].kwargs["encoding"] == "utf-8"
    assert run.call_args_list[1].kwargs["encoding"] == "utf-8"
    assert run.call_args_list[1].args[0] == [
        codex_wake._codex_executable(), "queue", "--profile", "pallium-relay",
        "--thread", "target-session", "--message", prompt
    ]
    assert "→" in prompt
    assert run.call_args_list[0].kwargs["input"].startswith(generic_prompt)
    assert codex_wake._wake_prompt() == generic_prompt
    assert "delivery_id" not in prompt
    assert "receipt" not in prompt
    assert run.call_args_list[1].kwargs["stdin"] is subprocess.DEVNULL
    assert "shell" not in run.call_args_list[1].kwargs

def test_non_active_writer_failure_and_exec_timeout_do_not_queue() -> None:
    ambiguous = subprocess.CompletedProcess([], 1, stderr="already has an active writer")
    with patch("app.codex_wake.subprocess.run", return_value=ambiguous) as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_called_once()
    with patch(
        "app.codex_wake.subprocess.run",
        side_effect=subprocess.TimeoutExpired([], 15),
    ) as run:
        assert codex_wake._launch("target-session", "wake") == "ambiguous"
    run.assert_called_once()


def test_queue_timeout_remains_ambiguous_without_a_second_write() -> None:
    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    with patch(
        "app.codex_wake.subprocess.run",
        side_effect=[active, subprocess.TimeoutExpired([], 30)],
    ) as run:
        assert codex_wake._launch("target-session", "wake") == "ambiguous"
    assert run.call_count == 2


def test_wake_defers_claim_until_turn_execution() -> None:
    with patch("app.codex_wake._launch", return_value="exec_completed") as launch:
        codex_wake._wake("target-session")
    launch.assert_called_once_with("target-session", codex_wake._wake_prompt())

def test_windows_resolver_survives_service_path_without_codex(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(codex_wake.os, "name", "nt")
    monkeypatch.setattr(codex_wake, "Path", type(tmp_path))
    monkeypatch.setattr(codex_wake.shutil, "which", lambda _: None)
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    install_root = tmp_path / "OpenAI" / "Codex" / "bin"
    old = install_root / "old" / "codex.exe"
    current = install_root / "current" / "codex.exe"
    old.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    current.write_text("current", encoding="utf-8")
    os.utime(old, (100, 100))
    os.utime(current, (200, 200))

    assert codex_wake._codex_executable() == str(current)
    monkeypatch.setenv("CODEX_CLI_PATH", str(old))
    assert codex_wake._codex_executable() == str(old)
    old.unlink()
    current.unlink()
    assert codex_wake._codex_executable() == "codex.exe"


def test_alias_and_exact_selectors_start_one_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery())
        _schedule({**_delivery("delivery-2"), "recipient": "codex:@relaydev"})
    assert thread.call_count == 1


def test_broadcast_and_malformed_selectors_do_not_start_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule({**_delivery(), "recipient": "codex"})
        _schedule({**_delivery("delivery-2"), "recipient": "codex:"})
        _schedule({**_delivery("delivery-3"), "recipient": "codex:@"})
    thread.assert_not_called()


def test_duplicate_and_non_codex_do_not_start_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery())
        _schedule(_delivery())
        _schedule(_delivery("delivery-2", "claude-code"))
        _schedule({**_delivery("delivery-3"), "recipient": "codex"})
    thread.assert_called_once()


def test_same_session_in_two_scopes_has_independent_ownership() -> None:
    other_scope = {
        "container_ref": "git:example.test/other-wake",
        "actor_ref": "other-user",
    }
    first_key = ("target-session", SCOPE["container_ref"], SCOPE["actor_ref"])
    other_key = (
        "target-session",
        other_scope["container_ref"],
        other_scope["actor_ref"],
    )
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery())
        codex_wake.schedule_codex_relay_wake(_delivery("delivery-2"), other_scope)
    assert thread.call_count == 2
    assert set(codex_wake._scheduled_session_generations) == {first_key, other_key}

    codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)

    assert first_key not in codex_wake._scheduled_session_generations
    assert other_key in codex_wake._scheduled_session_generations
    assert codex_wake._scheduled_delivery_ids == {"delivery-2"}


@pytest.mark.parametrize("outcome", ["queued", "ambiguous"])
def test_busy_wakes_coalesce_until_admission_then_rearm(monkeypatch, outcome: str) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch("app.codex_wake._wake", return_value=outcome) as wake:
        thread.side_effect = lambda **kwargs: (workers.append(kwargs["args"]), type("Worker", (), {"start": lambda self: None})())[1]
        _schedule(_delivery())
        _schedule(_delivery("delivery-2"))
        assert len(workers) == 1
        codex_wake._wake_after_debounce(*workers[0])
        _schedule(_delivery("delivery-3"))
        assert len(workers) == 1
        codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)
        _schedule(_delivery("delivery-4"))
    wake.assert_called_once_with("target-session")
    assert len(workers) == 2


def test_exec_completion_requires_matching_admission_before_return(monkeypatch) -> None:
    workers = []
    unreachable = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        codex_wake.schedule_codex_relay_wake(
            _delivery(), SCOPE, on_unreachable=unreachable.append
        )

    def admitted(_: str) -> str:
        codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)
        return "exec_completed"

    with patch("app.codex_wake._wake", side_effect=admitted):
        codex_wake._wake_after_debounce(*workers[0])

    assert unreachable == []
    assert not codex_wake._scheduled_session_generations
    assert not codex_wake._scheduled_delivery_ids


def test_exec_completion_without_admission_releases_and_reports(monkeypatch) -> None:
    workers = []
    unreachable = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        codex_wake.schedule_codex_relay_wake(
            _delivery(), SCOPE, on_unreachable=unreachable.append
        )
    with patch("app.codex_wake._wake", return_value="exec_completed"):
        codex_wake._wake_after_debounce(*workers[0])

    assert len(unreachable) == 1 and unreachable[0].tzinfo is not None
    assert not codex_wake._scheduled_session_generations
    assert not codex_wake._scheduled_delivery_ids


def test_launch_failure_releases_owner_for_later_delivery(monkeypatch) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch(
        "app.codex_wake._wake", side_effect=RuntimeError("launch failed")
    ) as wake:
        thread.side_effect = lambda **kwargs: (workers.append(kwargs["args"]), type("Worker", (), {"start": lambda self: None})())[1]
        _schedule(_delivery())
        try:
            codex_wake._wake_after_debounce(*workers.pop(0))
        except RuntimeError:
            pass
        _schedule(_delivery("delivery-2"))
        try:
            codex_wake._wake_after_debounce(*workers.pop(0))
        except RuntimeError:
            pass
    assert wake.call_count == 2
    assert not codex_wake._scheduled_delivery_ids
    assert not codex_wake._scheduled_session_generations

def test_schedule_returns_before_child_exits(monkeypatch) -> None:
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    started = threading.Event()
    release = threading.Event()

    def slow_wake(_: str) -> None:
        started.set()
        release.wait(1)

    with patch("app.codex_wake._wake", side_effect=slow_wake):
        _schedule(_delivery())
        assert started.wait(0.2)
    release.set()

def test_http_route_persists_before_one_callback(client) -> None:
    seen: list[tuple[dict, dict[str, str]]] = []
    app = FastAPI()
    app.include_router(
        create_router(
            client.app.state.pallium_service,
            relay_service=RelayService(client.app.state.pallium_service._storage),
            relay_send_callback=lambda result, scope: seen.append((result, scope)),
        )
    )
    route_client = TestClient(app)
    assert route_client.post(
        "/relay/turn",
        json={
            "runtime": "codex",
            "session_ref": "target-session",
            "container_ref": "git:example.test/wake",
            "actor_ref": "wake-user",
        },
    ).status_code == 200
    assert route_client.post(
        "/relay/turn",
        json={
            "runtime": "claude-code",
            "session_ref": "sender",
            "container_ref": "git:example.test/wake",
            "actor_ref": "wake-user",
        },
    ).status_code == 200
    sent = route_client.post(
        "/relay/messages",
        json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target-session",
            "payload": "wake",
            "container_ref": "git:example.test/wake",
            "actor_ref": "wake-user",
        },
    )
    assert sent.status_code == 200
    assert len(seen) == 1
    assert seen[0][0]["message_id"] == sent.json()["message_id"]
    assert seen[0][1] == SCOPE
    assert seen[0][0]["deliveries"][0]["delivery_id"] == sent.json()["deliveries"][0]["delivery_id"]
    assert route_client.get(
        f"/relay/messages/{sent.json()['message_id']}",
        params={"container_ref": "git:example.test/wake", "actor_ref": "wake-user"},
    ).json()["deliveries"][0]["delivery_id"] == seen[0][0]["deliveries"][0]["delivery_id"]


def test_callback_failure_does_not_undo_persisted_send(client) -> None:
    app = FastAPI()

    def fail_after_persistence(_: dict, __: dict[str, str]) -> None:
        raise RuntimeError("wake unavailable")

    app.include_router(
        create_router(
            client.app.state.pallium_service,
            relay_service=RelayService(client.app.state.pallium_service._storage),
            relay_send_callback=fail_after_persistence,
        )
    )
    route_client = TestClient(app)
    for runtime, session in (("codex", "target-session"), ("claude-code", "sender")):
        assert route_client.post(
            "/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE}
        ).status_code == 200
    sent = route_client.post(
        "/relay/messages",
        json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target-session",
            "payload": "still persisted",
            **SCOPE,
        },
    )
    assert sent.status_code == 200
    status = route_client.get(
        f"/relay/messages/{sent.json()['message_id']}", params=SCOPE
    ).json()
    assert status["deliveries"][0]["state"] == "pending"


def test_wake_claim_does_not_reopen_or_claim_for_closed_session(client) -> None:
    service = RelayService(client.app.state.pallium_service._storage)
    service.turn(runtime="codex", session_ref="closed-target", **SCOPE)
    service.turn(runtime="claude-code", session_ref="sender", **SCOPE)
    sent = service.send(
        sender_runtime="claude-code",
        sender_session_ref="sender",
        recipient="codex:closed-target",
        payload="wait for a natural turn",
        in_reply_to=None,
        **SCOPE,
    )
    service.close_session(runtime="codex", session_ref="closed-target", **SCOPE)

    result = service.turn(
        runtime="codex", session_ref="closed-target", register_session=False, **SCOPE
    )

    assert result["session"]["state"] == "closed"
    assert result["deliveries"] == []
    assert service.message_status(message_id=sent["message_id"], **SCOPE)["deliveries"][0]["state"] == "pending"

def test_create_app_keeps_real_wake_wiring(test_db_url: str) -> None:
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        )
    )
    route_client = TestClient(app)
    scope = {"container_ref": "git:example.test/real-wake", "actor_ref": "wake-user"}
    for runtime, session in (("codex", "target"), ("claude-code", "sender")):
        assert route_client.post(
            "/relay/turn", json={"runtime": runtime, "session_ref": session, **scope}
        ).status_code == 200
    with patch("app.codex_wake.threading.Thread") as thread:
        sent = route_client.post(
            "/relay/messages",
            json={
                "sender_runtime": "claude-code",
                "sender_session_ref": "sender",
                "recipient": "codex:target",
                "payload": "wake",
                **scope,
            },
        )
    assert sent.status_code == 200
    thread.assert_called_once()


def test_no_hook_completion_preserves_delivery_until_real_hook_recovery(
    client, monkeypatch, tmp_path,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/no-hook",
        "actor_ref": hook.derive_actor_ref(),
    }
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        codex_wake.schedule_codex_relay_wake,
    )
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        for runtime, session in (("claude-code", "sender"), ("codex", "target")):
            assert route.post("/relay/turn", json={
                "runtime": runtime,
                "session_ref": session,
                **scope,
            }).status_code == 200
        sent = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "preserve until hook →",
            **scope,
        }).json()
    assert len(workers) == 1

    with patch("app.codex_wake._wake", return_value="exec_completed"):
        codex_wake._wake_after_debounce(*workers[0])

    status = route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert status["state"] == "pending"
    assert status["destination_health"] == "unreachable"
    assert status["attempts"] == 0

    state_dir = tmp_path / "no-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: scope["actor_ref"])
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("Relay wake must not become memory"),
    )
    contexts = []
    monkeypatch.setattr(hook, "emit_context", lambda output, _event: contexts.append(output))

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
        response = route.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        return response.json() if response.content else None

    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)
    hook._common.pin_container("target", scope["container_ref"])
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path),
        "session_id": "target",
        "prompt": codex_wake._wake_prompt(),
    })

    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    assert len(contexts) == 1 and "preserve until hook →" in contexts[0]
    delivered = route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert delivered["state"] == "delivered"
    assert delivered["destination_health"] == "active"
    assert delivered["attempts"] == 1
    assert route.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", **scope,
    }).json()["deliveries"] == []

    contexts.clear()
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        admitted = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "admitted before child return →",
            **scope,
        }).json()
    assert len(workers) == 2

    original_run = subprocess.run

    def run_admitted_hook(*args, **kwargs):
        command = args[0]
        if len(command) > 1 and command[1] == "exec":
            with pytest.raises(SystemExit) as hook_exit:
                hook.main()
            assert hook_exit.value.code == 0
            return subprocess.CompletedProcess(command, 0, stderr="")
        return original_run(*args, **kwargs)

    with patch(
        "app.codex_wake.subprocess.run", side_effect=run_admitted_hook
    ) as run:
        codex_wake._wake_after_debounce(*workers[1])
    assert sum(len(call.args[0]) > 1 and call.args[0][1] == "exec" for call in run.call_args_list) == 1
    admitted_status = route.get(
        f"/relay/messages/{admitted['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert admitted_status["state"] == "delivered"
    assert admitted_status["destination_health"] == "active"
    assert admitted_status["attempts"] == 1
    assert len(contexts) == 1 and "admitted before child return →" in contexts[0]
    assert not codex_wake._scheduled_session_generations

    contexts.clear()
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        ambiguous = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "queue timeout stays pending →",
            **scope,
        }).json()
    assert len(workers) == 3
    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    with patch(
        "app.codex_wake.subprocess.run",
        side_effect=[active, subprocess.TimeoutExpired([], 30)],
    ) as run:
        codex_wake._wake_after_debounce(*workers[2])
    assert run.call_count == 2
    ambiguous_status = route.get(
        f"/relay/messages/{ambiguous['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert ambiguous_status["state"] == "pending"
    assert ambiguous_status["destination_health"] == "active"
    assert ambiguous_status["attempts"] == 0
    assert not contexts
    assert (
        "target", scope["container_ref"], scope["actor_ref"]
    ) in codex_wake._scheduled_session_generations
    with patch("app.codex_wake.threading.Thread") as thread:
        duplicate = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "coalesced behind ambiguous write",
            **scope,
        })
    assert duplicate.status_code == 200
    thread.assert_not_called()


def test_profile_is_idempotent_and_narrow(monkeypatch, tmp_path) -> None:
    from app.cli import setup_codex

    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    setup_codex._install_relay_profile()
    setup_codex._install_relay_profile()
    profile = (tmp_path / ".codex" / "pallium-relay.config.toml").read_text(encoding="utf-8")
    assert "required = true" in profile
    assert 'enabled_tools = ["pallium_relay_send", "pallium_relay_reply", "pallium_relay_ack", "pallium_relay_receive"]' in profile
    assert 'default_tools_approval_mode = "prompt"' in profile
    assert profile.count('approval_mode = "approve"') == 4
    setup_codex._remove_relay_profile()
    assert not (tmp_path / ".codex" / "pallium-relay.config.toml").exists()

def test_http_reply_uses_the_same_post_persistence_callback(client) -> None:
    seen: list[tuple[dict, dict[str, str]]] = []
    app = FastAPI()
    app.include_router(
        create_router(
            client.app.state.pallium_service,
            relay_service=RelayService(client.app.state.pallium_service._storage),
            relay_send_callback=lambda result, scope: seen.append((result, scope)),
        )
    )
    route_client = TestClient(app)
    scope = {"container_ref": "git:example.test/reply-wake", "actor_ref": "wake-user"}
    for runtime, session in (("codex", "original"), ("claude-code", "responder")):
        assert route_client.post(
            "/relay/turn", json={"runtime": runtime, "session_ref": session, **scope}
        ).status_code == 200
    parent = route_client.post(
        "/relay/messages",
        json={
            "sender_runtime": "codex",
            "sender_session_ref": "original",
            "recipient": "claude-code:responder",
            "payload": "question",
            **scope,
        },
    ).json()
    claim = route_client.post(
        "/relay/turn", json={"runtime": "claude-code", "session_ref": "responder", **scope}
    ).json()["deliveries"][0]
    reply = route_client.post(
        "/relay/replies",
        json={"delivery_id": claim["delivery_id"], "receipt": claim["receipt"], "payload": "answer", **scope},
    )
    assert reply.status_code == 200
    assert len(seen) == 2
    assert seen[1][0]["in_reply_to"] == parent["message_id"]
    assert seen[1][0]["recipient"] == "codex:original"

def test_busy_queue_claims_at_hook_execution_without_stale_receipt_or_duplicate_action(
    client, monkeypatch, tmp_path
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/wake",
        "actor_ref": hook.derive_actor_ref(),
    }
    state_dir = tmp_path / "hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    for runtime, session in (("claude-code", "sender"), ("codex", "target-session")):
        assert client.post(
            "/relay/turn", json={"runtime": runtime, "session_ref": session, **scope}
        ).status_code == 200
    sent = client.post(
        "/relay/messages",
        json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target-session",
            "payload": "delayed busy delivery",
            **scope,
        },
    ).json()
    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    queued = subprocess.CompletedProcess([], 0, stderr="")
    with patch("app.codex_wake.subprocess.run", side_effect=[active, queued]):
        codex_wake._wake("target-session")

    before_execution = client.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]
    # No lease exists while queued, so any queue delay cannot stale a receipt.
    assert before_execution["state"] == "pending"
    assert before_execution["lease_expires_at"] is None
    # Simulate queue execution after the normal 60-second claim lease window.
    with client.app.state.pallium_service._storage._relay_engine.begin() as connection:
        connection.execute(
            text("UPDATE relay_messages SET created_at=:past WHERE id=:id"),
            {
                "past": datetime.now(timezone.utc) - timedelta(seconds=61),
                "id": sent["message_id"],
            },
        )
    contexts: list[str] = []
    turns: list[dict] = []

    def relay_request(method: str, path: str, payload: dict, *, timeout: float) -> dict | None:
        response = client.request(method, path, json=payload)
        if response.status_code != 200:
            return None
        body = response.json()
        if path == "/relay/turn":
            turns.append(body)
        return body

    def run_hook(prompt: str) -> None:
        monkeypatch.setattr(
            hook, "read_hook_input",
            lambda: {"cwd": str(tmp_path), "session_id": "target-session", "prompt": prompt},
        )
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0

    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)

    def pallium_request(method: str, path: str, payload: dict | None = None, *, quiet: bool = False) -> dict | None:
        response = client.request(method, path, json=payload)
        if response.status_code != 200:
            return None
        return response.json()

    monkeypatch.setattr(hook, "pallium_request", pallium_request)
    monkeypatch.setattr(hook._common, "pallium_request", pallium_request)
    monkeypatch.setattr(
        hook._common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("caller-surface test escaped to live HTTP"),
    )
    monkeypatch.setattr(hook, "emit_context", lambda text, _: contexts.append(text))

    # The production resolver's no-pin and wrong-pin paths fail closed.
    run_hook(codex_wake._wake_prompt() + " missing scope")
    hook._common.pin_container("target-session", "git:example.test/other")
    run_hook(codex_wake._wake_prompt() + " wrong scope")
    with client.app.state.pallium_service._storage._engine.begin() as connection:
        wrong_scope_items = connection.execute(
            text("SELECT id, content FROM source_items WHERE content LIKE :needle"),
            {"needle": "%wrong scope"},
        ).mappings().all()
    assert wrong_scope_items, "wrong-scope ingestion must stay in the isolated client DB"
    assert all("delayed busy delivery" not in context for context in contexts)
    assert all(not turn["deliveries"] for turn in turns)
    assert client.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]["state"] == "pending"

    hook._common.pin_container("target-session", scope["container_ref"])
    run_hook(codex_wake._wake_prompt())

    assert len(turns) == 3
    delivery = turns[-1]["deliveries"][0]
    assert delivery["receipt"]
    assert sent["deliveries"][0]["delivery_id"] == delivery["delivery_id"]
    assert "delayed busy delivery" in contexts[-1]
    scope_line = next(
        line for line in contexts[-1].splitlines()
        if line.startswith("[Pallium scope — ")
    )
    injected_scope = json.loads(
        scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
    )
    assert injected_scope == {
        **scope,
        "thread_ref": "target-session",
        "agent_ref": "codex",
        "visibility": "private",
    }
    reply_body = {
        "delivery_id": delivery["delivery_id"],
        "payload": "handled once",
        "container_ref": injected_scope["container_ref"],
        "actor_ref": injected_scope["actor_ref"],
    }
    assert client.post(
        "/relay/replies", json={**reply_body, "container_ref": "git:example.test/other"}
    ).status_code == 404
    first = client.post("/relay/replies", json=reply_body)
    duplicate = client.post("/relay/replies", json=reply_body)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["message_id"] == duplicate.json()["message_id"]
    assert client.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]["state"] == "delivered"


def test_competing_hook_consumes_delivery_before_accepted_queue_blocks_empty_wake(
    client, monkeypatch, tmp_path, capsys,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/overtaken-wake",
        "actor_ref": hook.derive_actor_ref(),
    }
    state_dir = tmp_path / "overtaken-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        codex_wake.schedule_codex_relay_wake,
    )
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    for runtime, session in (("claude-code", "sender"), ("codex", "target")):
        assert route.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
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

    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    queued = subprocess.CompletedProcess([], 0, stderr="")
    with patch(
        "app.codex_wake.subprocess.run", side_effect=[active, queued],
    ) as run:
        codex_wake._wake_after_debounce(*workers[0])
    queue_command = run.call_args_list[1].args[0]
    queued_prompt = queue_command[queue_command.index("--message") + 1]
    assert queued_prompt == codex_wake._wake_prompt()
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

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
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
    with pytest.raises(SystemExit) as overtaken:
        hook.main()
    assert overtaken.value.code == 2
    assert contexts == []
    assert "Pallium Relay wake" in capsys.readouterr().err
    assert route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0] == delivered
    assert route.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", **scope,
    }).json()["deliveries"] == []

def test_actual_codex_hook_drains_bounded_backlog_and_arrival_once(
    client, monkeypatch, tmp_path,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {"container_ref": SCOPE["container_ref"], "actor_ref": hook.derive_actor_ref()}
    state_dir = tmp_path / "drain-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    scheduled = []
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        lambda result, scope, **_kwargs: scheduled.append((result, scope)),
    )
    for runtime, session in (("claude-code", "drain-sender"), ("codex", "drain-target")):
        assert client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    sent = []
    contexts = []

    def send(index: int) -> None:
        response = client.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "drain-sender",
            "recipient": "codex:drain-target",
            "message_id": f"drain-{index}",
            "payload": f"work-{index} →",
            **scope,
        })
        assert response.status_code == 200
        sent.append(response.json())

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, f"{path}: {response.text}"
        return response.json()

    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("Relay wake text must not become memory"),
    )
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: contexts.append(text))
    hook._common.pin_container("drain-target", scope["container_ref"])
    monkeypatch.setattr(
        hook,
        "read_hook_input",
        lambda: {
            "cwd": str(tmp_path),
            "session_id": "drain-target",
            "prompt": codex_wake._wake_prompt(),
        },
    )

    for index in range(4):
        send(index)
    assert len(scheduled) == 4
    scheduled.clear()

    with pytest.raises(SystemExit):
        hook.main()
    assert len(scheduled) == 3
    assert {
        call[0]["deliveries"][0]["delivery_id"] for call in scheduled
    } == {sent[3]["deliveries"][0]["delivery_id"]}
    first_relay, first_scope = contexts[0].rsplit("\n\n", 1)
    assert first_relay.count("[Pallium Relay message") == 3
    assert first_relay.endswith("[Relay: 1 more; Pallium continues.]")
    assert first_scope.startswith("[Pallium scope — ")

    send(4)
    assert len(scheduled) == 4
    with pytest.raises(SystemExit):
        hook.main()
    assert len(scheduled) == 4
    assert contexts[1].count("[Pallium Relay message") == 2
    assert "[Relay:" not in contexts[1]
    combined = "\n".join(contexts)
    for index in range(5):
        assert combined.count(f"message_id: drain-{index}\n") == 1
        status = client.get(f"/relay/messages/{sent[index]['message_id']}", params=scope)
        assert status.json()["deliveries"][0]["state"] == "delivered"

def test_actual_codex_hook_keeps_maximum_delivery_with_notice_inside_budget(
    client, monkeypatch, tmp_path,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": SCOPE["container_ref"],
        "actor_ref": hook.derive_actor_ref(),
    }
    state_dir = tmp_path / "maximum-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *_: None)

    sender = "s" * 255
    target = "maximum-target"
    for runtime, session in (("claude-code", sender), ("codex", target)):
        assert client.post("/relay/turn", json={
            "runtime": runtime,
            "session_ref": session,
            **scope,
        }).status_code == 200

    parent_id = "p" * 128
    parent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code",
        "sender_session_ref": sender,
        "recipient": f"codex:{target}",
        "message_id": parent_id,
        "payload": "parent",
        **scope,
    }).json()
    parent_claim = client.post("/relay/turn", json={
        "runtime": "codex",
        "session_ref": target,
        "max_messages": 1,
        **scope,
    }).json()["deliveries"][0]
    assert client.post("/relay/deliveries/ack", json={
        "delivery_id": parent_claim["delivery_id"],
        "claim_token": parent_claim["claim_token"],
        **scope,
    }).status_code == 200
    assert parent["message_id"] == parent_id

    maximum = client.post("/relay/messages", json={
        "sender_runtime": "claude-code",
        "sender_session_ref": sender,
        "recipient": f"codex:{target}",
        "message_id": "m" * 128,
        "in_reply_to": parent_id,
        "payload": "😀" * 1500,
        **scope,
    }).json()
    later = client.post("/relay/messages", json={
        "sender_runtime": "claude-code",
        "sender_session_ref": sender,
        "recipient": f"codex:{target}",
        "message_id": "later",
        "payload": "later",
        **scope,
    }).json()

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, f"{path}: {response.text}"
        return response.json()

    contexts = []
    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("Relay must skip memory"),
    )
    monkeypatch.setattr(hook, "emit_context", lambda text, _event: contexts.append(text))
    hook._common.pin_container(target, scope["container_ref"])
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path),
        "session_id": target,
        "prompt": codex_wake._wake_prompt(),
    })

    with pytest.raises(SystemExit):
        hook.main()

    assert len(contexts) == 1
    relay_text, scope_line = contexts[0].rsplit("\n\n", 1)
    assert relay_text.count("😀") == 1500
    assert relay_text.endswith("[Relay: 1 more; Pallium continues.]")
    assert len(relay_text) <= hook.RELAY_OUTPUT_BUDGET
    assert len(scope_line) <= hook.RELAY_OUTPUT_BUDGET
    assert client.get(
        f"/relay/messages/{maximum['message_id']}", params=scope,
    ).json()["deliveries"][0]["state"] == "delivered"
    assert client.get(
        f"/relay/messages/{later['message_id']}", params=scope,
    ).json()["deliveries"][0]["state"] == "pending"

def test_hook_ack_rearms_next_codex_batch_without_changing_ack_contract(client) -> None:
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    with patch("app.dependencies.schedule_codex_relay_wake") as schedule:
        for runtime, session in (("claude-code", "sender"), ("codex", "target")):
            assert route.post("/relay/turn", json={
                "runtime": runtime, "session_ref": session, **SCOPE,
            }).status_code == 200
        sent = []
        for message_id in ("batch-1", "batch-2"):
            response = route.post("/relay/messages", json={
                "sender_runtime": "claude-code",
                "sender_session_ref": "sender",
                "recipient": "codex:target",
                "message_id": message_id,
                "payload": "x" * 1500,
                **SCOPE,
            })
            assert response.status_code == 200
            sent.append(response.json())

        schedule.reset_mock()
        turn = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", "max_chars": 2400, **SCOPE,
        }).json()
        assert len(turn["deliveries"]) == 1 and turn["has_more"] is True
        claimed = turn["deliveries"][0]
        ack_body = {
            "delivery_id": claimed["delivery_id"],
            "claim_token": claimed["claim_token"],
            **SCOPE,
        }
        assert route.post(
            "/relay/deliveries/ack", json={**ack_body, "claim_token": "stale"},
        ).status_code == 409
        schedule.assert_not_called()

        ack = route.post("/relay/deliveries/ack", json=ack_body)
        assert ack.status_code == 200
        assert set(ack.json()) == {
            "delivery_id", "state", "delivered_at", "already_delivered",
        }
        wake, scope = schedule.call_args.args
        assert scope == SCOPE
        assert wake["recipient"] == "codex:target"
        assert wake["deliveries"] == [{
            "delivery_id": sent[1]["deliveries"][0]["delivery_id"],
            "state": "pending",
            "recipient_runtime": "codex",
            "recipient_session_ref": "target",
        }]

        duplicate = route.post("/relay/deliveries/ack", json=ack_body)
        assert duplicate.status_code == 200
        assert duplicate.json()["already_delivered"] is True
        assert schedule.call_count == 1

        second = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", **SCOPE,
        }).json()["deliveries"][0]
        schedule.reset_mock()
        assert route.post("/relay/deliveries/mcp-ack", json={
            "delivery_id": second["delivery_id"],
            "receipt": second["receipt"],
            **SCOPE,
        }).status_code == 200
        schedule.assert_not_called()

        third = route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "callback failure remains fail-soft",
            **SCOPE,
        }).json()
        route.post("/relay/messages", json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "pending candidate invokes the callback",
            **SCOPE,
        }).raise_for_status()
        claimed_third = route.post("/relay/turn", json={
            "runtime": "codex",
            "session_ref": "target",
            "max_messages": 1,
            **SCOPE,
        }).json()["deliveries"][0]
        schedule.reset_mock()
        schedule.side_effect = RuntimeError("wake failure")
        assert route.post("/relay/deliveries/ack", json={
            "delivery_id": claimed_third["delivery_id"],
            "claim_token": claimed_third["claim_token"],
            **SCOPE,
        }).status_code == 200
        assert third["deliveries"][0]["delivery_id"] == claimed_third["delivery_id"]
        schedule.assert_called_once()

    properties = app.openapi()["components"]["schemas"]["RelayAckResponse"]["properties"]
    assert set(properties) == {
        "delivery_id", "state", "delivered_at", "already_delivered",
    }

    turn_limit = (
        app.openapi()["components"]["schemas"]["RelayTurnRequest"]
        ["properties"]["max_messages"]
    )
    assert turn_limit["default"] == 3
    assert turn_limit["minimum"] == 0

def test_relay_turn_callback_rearms_only_after_success(client) -> None:
    callbacks = []
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service,
        relay_service=RelayService(client.app.state.pallium_service._storage),
        relay_turn_callback=lambda request: callbacks.append(request),
    ))
    route_client = TestClient(app)
    assert route_client.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE}).status_code == 200
    assert len(callbacks) == 1
    assert route_client.post("/relay/turn", json={"runtime": "bad", "session_ref": "target", **SCOPE}).status_code == 422
    assert len(callbacks) == 1

def test_relay_turn_callback_failure_keeps_successful_response(client) -> None:
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service,
        relay_service=RelayService(client.app.state.pallium_service._storage),
        relay_turn_callback=lambda _: (_ for _ in ()).throw(RuntimeError("callback")),
    ))
    response = TestClient(app).post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE})
    assert response.status_code == 200

def test_build_router_turn_rearms_actual_codex_wake_state(client, monkeypatch) -> None:
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery())
        assert codex_wake._scheduled_session_generations
        app = FastAPI()
        app.include_router(build_router(
            client.app.state.pallium_service,
            relay_storage=client.app.state.pallium_service._storage,
        ))
        route = TestClient(app)
        assert route.post("/relay/turn", json={"runtime": "bad", "session_ref": "target-session", **SCOPE}).status_code == 422
        assert codex_wake._scheduled_session_generations
        assert route.post("/relay/turn", json={
            "runtime": "codex",
            "session_ref": "target-session",
            "container_ref": "git:example.test/wrong",
            "actor_ref": SCOPE["actor_ref"],
        }).status_code == 200
        assert codex_wake._scheduled_session_generations
        assert route.post("/relay/turn", json={"runtime": "codex", "session_ref": "target-session", **SCOPE}).status_code == 200
        assert not codex_wake._scheduled_session_generations
        assert not codex_wake._scheduled_delivery_ids
        _schedule(_delivery("delivery-2"))
    assert thread.call_count == 2


def test_failed_old_generation_cannot_clear_replacement(monkeypatch) -> None:
    wake_key = ("target-session", SCOPE["container_ref"], SCOPE["actor_ref"])
    codex_wake._scheduled_session_generations[wake_key] = 2
    codex_wake._scheduled_session_delivery_ids[wake_key] = "delivery-new"
    codex_wake._scheduled_delivery_ids.add("delivery-new")
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    monkeypatch.setattr(codex_wake, "_wake", lambda _: "failed")
    codex_wake._wake_after_debounce("delivery-old", wake_key, 1)
    assert codex_wake._scheduled_session_generations[wake_key] == 2
    assert codex_wake._scheduled_session_delivery_ids[wake_key] == "delivery-new"
    assert codex_wake._scheduled_delivery_ids == {"delivery-new"}


def test_old_scheduled_worker_cannot_clear_new_schedule(monkeypatch) -> None:
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        codex_wake, "_wake",
        lambda _session: pytest.fail("stale worker must not launch"),
    )
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery("delivery-old"))
        old_args = thread.call_args.kwargs["args"]
        codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)
        _schedule(_delivery("delivery-new"))
        wake_key = ("target-session", SCOPE["container_ref"], SCOPE["actor_ref"])
        new_generation = codex_wake._scheduled_session_generations[wake_key]

    assert old_args[2] != new_generation
    codex_wake._wake_after_debounce(*old_args)
    assert codex_wake._scheduled_session_generations[wake_key] == new_generation
    assert codex_wake._scheduled_session_delivery_ids[wake_key] == "delivery-new"
    assert codex_wake._scheduled_delivery_ids == {"delivery-new"}


def test_idempotent_send_schedules_one_codex_wake(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        codex_wake.schedule_codex_relay_wake,
    )
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    assert route.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "sender", **SCOPE},
    ).status_code == 200
    assert route.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "target-session", **SCOPE},
    ).status_code == 200
    body = {
        "sender_runtime": "codex",
        "sender_session_ref": "sender",
        "recipient": "codex:target-session",
        "payload": "one persisted request",
        "message_id": "stable-wake-message",
        **SCOPE,
    }
    with patch("app.codex_wake.threading.Thread") as thread:
        first = route.post("/relay/messages", json=body)
        second = route.post("/relay/messages", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["message_id"] == second.json()["message_id"]
    assert thread.call_count == 1
    assert codex_wake._scheduled_delivery_ids == {
        first.json()["deliveries"][0]["delivery_id"]
    }


def test_crash_after_claim_rewakes_and_actual_codex_hook_delivers_once(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    import storage.sqlite_relay as sqlite_relay
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry
    from integrations.codex.hooks import user_prompt_submit as hook

    clock = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    scheduled: list[tuple[dict, dict]] = []
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        lambda result, scope, **_kwargs: scheduled.append((result, scope)),
    )
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="claude-code", session_ref="sender", **SCOPE)
    relay.turn(runtime="codex", session_ref="crash-target", **SCOPE)
    sent = relay.send(
        sender_runtime="claude-code",
        sender_session_ref="sender",
        recipient="codex:crash-target",
        payload="😀" * 1500,
        **SCOPE,
    )
    scheduled.clear()

    claimed = relay.turn(
        runtime="codex", session_ref="crash-target", max_messages=1, **SCOPE
    )["deliveries"][0]
    assert claimed["delivery_id"] == sent["deliveries"][0]["delivery_id"]
    assert relay.message_status(message_id=sent["message_id"], **SCOPE)["deliveries"][0]["state"] == "claimed"

    clock[0] += timedelta(seconds=61)
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry())
    assert len(scheduled) == 1
    wake, wake_scope = scheduled[0]
    assert wake_scope == SCOPE
    assert wake["recipient"] == "codex:crash-target"
    assert wake["deliveries"][0] == {
        "delivery_id": claimed["delivery_id"],
        "state": "pending",
        "recipient_runtime": "codex",
        "recipient_session_ref": "crash-target",
    }

    state_dir = tmp_path / "crash-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
    monkeypatch.setattr(hook, "derive_actor_ref", lambda: SCOPE["actor_ref"])
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("Relay recovery must not ingest synthetic memory"),
    )
    contexts: list[str] = []
    monkeypatch.setattr(hook, "emit_context", lambda output, _event: contexts.append(output))

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        return response.json() if response.content else None

    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)
    hook._common.pin_container("crash-target", SCOPE["container_ref"])
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path),
        "session_id": "crash-target",
        "prompt": codex_wake._wake_prompt(),
    })

    with pytest.raises(SystemExit):
        hook.main()

    assert len(contexts) == 1 and contexts[0].count("😀") == 1500
    delivered = relay.message_status(message_id=sent["message_id"], **SCOPE)["deliveries"][0]
    assert delivered["state"] == "delivered" and delivered["attempts"] == 2
    scheduled.clear()
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry())
    assert scheduled == []
    assert relay.turn(runtime="codex", session_ref="crash-target", **SCOPE)["deliveries"] == []

def test_expired_codex_claim_rewakes_once_after_real_app_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    import app.main as main
    import storage.sqlite_relay as sqlite_relay
    from app.config import AppConfig
    from storage.vector_index import VectorIndexConfig

    clock = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    original_start = main.start_claude_wake_reconciler
    monkeypatch.setattr(
        main, "start_claude_wake_reconciler", lambda *_args, **_kwargs: None
    )
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as http_a:
        relay = RelayService(http_a.app.state.pallium_service._storage)
        relay.turn(runtime="claude-code", session_ref="sender", **SCOPE)
        relay.turn(runtime="codex", session_ref="restart-target", **SCOPE)
        sent = relay.send(
            sender_runtime="claude-code",
            sender_session_ref="sender",
            recipient="codex:restart-target",
            payload="persisted Codex crash ✓",
            **SCOPE,
        )
        claimed = relay.turn(
            runtime="codex", session_ref="restart-target", **SCOPE
        )["deliveries"][0]
        assert claimed["delivery_id"] == sent["deliveries"][0]["delivery_id"]

    clock[0] += timedelta(seconds=61)
    scheduled = threading.Event()
    wake_calls: list[tuple[dict, dict]] = []

    def schedule(result: dict, scope: dict, **_kwargs) -> None:
        wake_calls.append((result, scope))
        scheduled.set()

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", schedule)
    monkeypatch.setattr(main, "start_claude_wake_reconciler", original_start)
    app_b = create_app(config)
    with TestClient(app_b, client=("127.0.0.1", 50000)) as http_b:
        assert scheduled.wait(timeout=1)
        assert len(wake_calls) == 1
        assert wake_calls[0][0]["deliveries"][0]["delivery_id"] == claimed["delivery_id"]
        assert wake_calls[0][1] == SCOPE

        from integrations.codex.hooks import user_prompt_submit as hook

        state_dir = tmp_path / "restart-hook-state"
        monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
        monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
        monkeypatch.setattr(hook, "get_pending_relay_closes", lambda _: [])
        monkeypatch.setattr(hook, "derive_actor_ref", lambda: SCOPE["actor_ref"])
        monkeypatch.setattr(
            hook,
            "pallium_request",
            lambda *_args, **_kwargs: pytest.fail("Relay recovery must not ingest synthetic memory"),
        )
        contexts: list[str] = []
        monkeypatch.setattr(hook, "emit_context", lambda output, _event: contexts.append(output))

        def relay_request(method: str, path: str, payload: dict, *, timeout: float):
            response = http_b.request(method, path, json=payload)
            assert response.status_code == 200, response.text
            return response.json() if response.content else None

        monkeypatch.setattr(hook, "relay_request", relay_request)
        monkeypatch.setattr(hook._common, "relay_request", relay_request)
        hook._common.pin_container("restart-target", SCOPE["container_ref"])
        monkeypatch.setattr(hook, "read_hook_input", lambda: {
            "cwd": str(tmp_path),
            "session_id": "restart-target",
            "prompt": codex_wake._wake_prompt(),
        })
        with pytest.raises(SystemExit):
            hook.main()

        relay = RelayService(http_b.app.state.pallium_service._storage)
        assert len(contexts) == 1 and "persisted Codex crash ✓" in contexts[0]
        delivered = relay.message_status(message_id=sent["message_id"], **SCOPE)["deliveries"][0]
        assert delivered["state"] == "delivered" and delivered["attempts"] == 2
        wake_calls.clear()
        assert relay.turn(
            runtime="codex", session_ref="restart-target", **SCOPE
        )["deliveries"] == []
        assert wake_calls == []

    reconciler = app_b.state._claude_wake_reconciler
    assert reconciler._thread is not None and not reconciler._thread.is_alive()