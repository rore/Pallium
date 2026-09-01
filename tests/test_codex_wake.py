from __future__ import annotations

import subprocess
import threading
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import create_router
from app import codex_wake
from core.relay import RelayService


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


def setup_function() -> None:
    codex_wake._scheduled_delivery_ids.clear()


def test_success_does_not_queue_and_hides_process() -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    with patch("app.codex_wake.subprocess.run", return_value=completed) as run, patch(
        "app.codex_wake.subprocess.Popen"
    ) as popen:
        codex_wake._wake("delivery-1", "target-session")
    assert run.call_args.args[0][-5:] == ["pallium-relay", "resume", "target-session", "-", "--json"]
    assert run.call_args.kwargs["input"] == "Pallium Relay message pending."
    assert run.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert run.call_args.kwargs["stderr"] is subprocess.PIPE
    assert "shell" not in run.call_args.kwargs
    popen.assert_not_called()


def test_only_exact_active_writer_queues_once() -> None:
    completed = subprocess.CompletedProcess([], 1, stderr="already has an active writer (code -32600)")
    with patch("app.codex_wake.subprocess.run", return_value=completed), patch(
        "app.codex_wake.subprocess.Popen"
    ) as popen:
        codex_wake._wake("delivery-1", "target-session")
    assert popen.call_args.args[0][-5:] == ["queue", "--thread", "target-session", "--message", "Pallium Relay message pending."]
    assert "shell" not in popen.call_args.kwargs


def test_ambiguous_failure_and_timeout_do_not_queue() -> None:
    ambiguous = subprocess.CompletedProcess([], 1, stderr="already has an active writer")
    with patch("app.codex_wake.subprocess.run", return_value=ambiguous), patch(
        "app.codex_wake.subprocess.Popen"
    ) as popen:
        codex_wake._wake("delivery-1", "target-session")
        with patch("app.codex_wake.subprocess.run", side_effect=subprocess.TimeoutExpired([], 15)):
            codex_wake._wake("delivery-1", "target-session")
    popen.assert_not_called()


def test_alias_and_exact_selectors_start_one_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        codex_wake.schedule_codex_relay_wake(_delivery())
        codex_wake.schedule_codex_relay_wake({**_delivery("delivery-2"), "recipient": "codex:@relaydev"})
    assert thread.call_count == 2


def test_broadcast_and_malformed_selectors_do_not_start_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        codex_wake.schedule_codex_relay_wake({**_delivery(), "recipient": "codex"})
        codex_wake.schedule_codex_relay_wake({**_delivery("delivery-2"), "recipient": "codex:"})
        codex_wake.schedule_codex_relay_wake({**_delivery("delivery-3"), "recipient": "codex:@"})
    thread.assert_not_called()


def test_duplicate_and_non_codex_do_not_start_child() -> None:
    with patch("app.codex_wake.threading.Thread") as thread:
        codex_wake.schedule_codex_relay_wake(_delivery())
        codex_wake.schedule_codex_relay_wake(_delivery())
        codex_wake.schedule_codex_relay_wake(_delivery("delivery-2", "claude-code"))
        codex_wake.schedule_codex_relay_wake({**_delivery("delivery-3"), "recipient": "codex"})
    thread.assert_called_once()


def test_schedule_returns_before_child_exits() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_wake(_: str, __: str) -> None:
        started.set()
        release.wait(1)

    with patch("app.codex_wake._wake", side_effect=slow_wake):
        codex_wake.schedule_codex_relay_wake(_delivery())
        assert started.wait(0.2)
    release.set()

def test_http_route_persists_before_one_callback(client) -> None:
    seen: list[dict] = []
    app = FastAPI()
    app.include_router(
        create_router(
            client.app.state.pallium_service,
            relay_service=RelayService(client.app.state.pallium_service._storage),
            relay_send_callback=seen.append,
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
    assert seen[0]["message_id"] == sent.json()["message_id"]
    assert seen[0]["deliveries"][0]["delivery_id"] == sent.json()["deliveries"][0]["delivery_id"]
    assert route_client.get(
        f"/relay/messages/{sent.json()['message_id']}",
        params={"container_ref": "git:example.test/wake", "actor_ref": "wake-user"},
    ).json()["deliveries"][0]["delivery_id"] == seen[0]["deliveries"][0]["delivery_id"]


def test_profile_is_idempotent_and_narrow(monkeypatch, tmp_path) -> None:
    from app.cli import setup_codex

    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    setup_codex._install_relay_profile()
    setup_codex._install_relay_profile()
    profile = (tmp_path / ".codex" / "pallium-relay.config.toml").read_text(encoding="utf-8")
    assert "required = true" in profile
    assert 'enabled_tools = ["pallium_relay_send", "pallium_relay_reply"]' in profile
    assert 'default_tools_approval_mode = "prompt"' in profile
    assert profile.count('approval_mode = "approve"') == 2
    setup_codex._remove_relay_profile()
    assert not (tmp_path / ".codex" / "pallium-relay.config.toml").exists()

def test_http_reply_uses_the_same_post_persistence_callback(client) -> None:
    seen: list[dict] = []
    app = FastAPI()
    app.include_router(
        create_router(
            client.app.state.pallium_service,
            relay_service=RelayService(client.app.state.pallium_service._storage),
            relay_send_callback=seen.append,
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
    assert seen[-1]["in_reply_to"] == parent["message_id"]
    assert seen[-1]["recipient"] == "codex:original"
