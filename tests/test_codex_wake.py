from __future__ import annotations

import os
import subprocess
import threading
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import create_router
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
                "recipient_session_ref": "target-session",
            }
        ]
    }


def _claimed(delivery_id: str = "delivery-1", payload: str = "wake") -> dict:
    return {
        "delivery_id": delivery_id,
        "receipt": f"receipt-{delivery_id}",
        "message_id": f"message-{delivery_id}",
        "sender_runtime": "claude-code",
        "sender_session_ref": "sender-session",
        "recipient_runtime": "codex",
        "recipient_session_ref": "target-session",
        "recipient": "codex:target-session",
        "payload": payload,
        "redacted": False,
        "in_reply_to": None,
        "created_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-09-02T00:00:00Z",
        "state": "claimed",
    }


def _service(*deliveries: dict, has_more: bool = False) -> Mock:
    service = Mock(spec=RelayService)
    service.turn.return_value = {
        "session": {},
        "deliveries": list(deliveries),
        "has_more": has_more,
        "remaining_count": 1 if has_more else 0,
    }
    return service


def _schedule(result: dict, service: Mock | None = None) -> None:
    codex_wake.schedule_codex_relay_wake(
        result, SCOPE, relay_service=service or _service(_claimed())
    )


def setup_function() -> None:
    codex_wake._scheduled_delivery_ids.clear()
    codex_wake._scheduled_session_generations.clear()


def test_successful_resume_does_not_queue_and_hides_process() -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    with patch("app.codex_wake.subprocess.run", return_value=completed) as run:
        assert codex_wake._launch("target-session", "wake prompt") is True
    assert run.call_args.args[0][-5:] == [
        "pallium-relay", "resume", "target-session", "-", "--json"
    ]
    assert run.call_args.kwargs["input"] == "wake prompt"
    assert run.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert run.call_args.kwargs["stderr"] is subprocess.PIPE
    assert "shell" not in run.call_args.kwargs


def test_exact_active_writer_queues_same_prompt_hidden() -> None:
    active = subprocess.CompletedProcess(
        [], 1, stderr="already has an active writer (code -32600)"
    )
    queued = subprocess.CompletedProcess([], 0, stderr="")
    prompt = codex_wake._wake_prompt([_claimed()], **SCOPE)
    with patch("app.codex_wake.subprocess.run", side_effect=[active, queued]) as run:
        assert codex_wake._launch("target-session", prompt) is True
    assert run.call_count == 2
    assert run.call_args_list[1].args[0][1:] == [
        "queue", "--profile", "pallium-relay", "--thread", "target-session", "--message", prompt
    ]
    assert "already_delivered=true" in run.call_args_list[1].args[0][-1]
    assert "do not retry, reply, or act" in run.call_args_list[1].args[0][-1]
    assert run.call_args_list[1].kwargs["stdin"] is subprocess.DEVNULL
    assert "shell" not in run.call_args_list[1].kwargs


def test_ambiguous_failure_and_timeout_do_not_queue() -> None:
    ambiguous = subprocess.CompletedProcess([], 1, stderr="already has an active writer")
    with patch("app.codex_wake.subprocess.run", return_value=ambiguous) as run:
        assert codex_wake._launch("target-session", "wake") is False
    run.assert_called_once()
    with patch(
        "app.codex_wake.subprocess.run",
        side_effect=subprocess.TimeoutExpired([], 15),
    ) as run:
        assert codex_wake._launch("target-session", "wake") is False
    run.assert_called_once()


def test_wake_claims_without_registration_and_renders_scope_receipts_unicode() -> None:
    service = _service(_claimed(payload="שלום relay"))
    with patch("app.codex_wake._launch", return_value=True) as launch:
        codex_wake._wake("target-session", service, **SCOPE)
    service.turn.assert_called_once_with(
        runtime="codex",
        session_ref="target-session",
        max_chars=codex_wake._MAX_BATCH_CHARS,
        register_session=False,
        **SCOPE,
    )
    prompt = launch.call_args.args[1]
    assert "שלום relay" in prompt
    assert "receipt-delivery-1" in prompt
    assert SCOPE["container_ref"] in prompt
    assert SCOPE["actor_ref"] in prompt


def test_wake_launches_every_bounded_batch() -> None:
    service = _service()
    service.turn.side_effect = [
        {"deliveries": [_claimed("d-1")], "has_more": True},
        {"deliveries": [_claimed("d-2")], "has_more": False},
    ]
    with patch("app.codex_wake._launch", return_value=True) as launch:
        codex_wake._wake("target-session", service, **SCOPE)
    assert launch.call_count == 2
    assert "d-1" in launch.call_args_list[0].args[1]
    assert "d-2" in launch.call_args_list[1].args[1]


def test_wake_without_claimed_deliveries_does_not_launch() -> None:
    service = _service()
    with patch("app.codex_wake._launch") as launch:
        codex_wake._wake("target-session", service, **SCOPE)
    launch.assert_not_called()


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
    assert thread.call_count == 2


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


def test_burst_coalesces_to_one_wake(monkeypatch) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch("app.codex_wake._wake") as wake:
        thread.side_effect = lambda **kwargs: (workers.append(kwargs["args"]), type("Worker", (), {"start": lambda self: None})())[1]
        _schedule(_delivery())
        _schedule(_delivery("delivery-2"))
        codex_wake._wake_after_debounce(*workers[0])
        codex_wake._wake_after_debounce(*workers[1])
    wake.assert_called_once_with("target-session", workers[1][3], *workers[1][4:])


def test_stale_worker_cannot_clear_newer_generation(monkeypatch) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch("app.codex_wake._wake") as wake:
        thread.side_effect = lambda **kwargs: (workers.append(kwargs["args"]), type("Worker", (), {"start": lambda self: None})())[1]
        _schedule(_delivery())
        _schedule(_delivery("delivery-2"))
        codex_wake._wake_after_debounce(*workers[0])
        assert "delivery-1" not in codex_wake._scheduled_delivery_ids
        assert codex_wake._scheduled_session_generations["target-session"] == 2
        codex_wake._wake_after_debounce(*workers[1])
    wake.assert_called_once_with("target-session", workers[1][3], *workers[1][4:])
    assert not codex_wake._scheduled_session_generations


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

    def slow_wake(_: str, __: RelayService, ___: str, ____: str) -> None:
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


def test_profile_is_idempotent_and_narrow(monkeypatch, tmp_path) -> None:
    from app.cli import setup_codex

    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    setup_codex._install_relay_profile()
    setup_codex._install_relay_profile()
    profile = (tmp_path / ".codex" / "pallium-relay.config.toml").read_text(encoding="utf-8")
    assert "required = true" in profile
    assert 'enabled_tools = ["pallium_relay_send", "pallium_relay_reply", "pallium_relay_ack"]' in profile
    assert 'default_tools_approval_mode = "prompt"' in profile
    assert profile.count('approval_mode = "approve"') == 3
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
