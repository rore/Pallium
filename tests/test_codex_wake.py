from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from app.dependencies import build_router
from app import codex_wake
from app.config import AppConfig
from app.main import create_app
from core.codex_wake import CodexWakeRegistry
from core.relay import RelayService
from integrations.codex.hooks import user_prompt_submit as hook_module
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


SCOPE = {
    "container_ref": "git:example.test/wake",
}


def _delivery(delivery_id: str = "delivery-1", runtime: str = "codex") -> dict:
    return {
        "recipient": "codex:target-session",
        "deliveries": [
            {
                "delivery_id": delivery_id,
                "recipient_endpoint_id": "relay-session-" + "a" * 32,
                "recipient_runtime": runtime,
                "state": "pending",
                "recipient_session_ref": "target-session",
            }
        ]
    }


def _schedule(result: dict) -> None:
    codex_wake.schedule_codex_relay_wake(result, SCOPE)


def _log_fp(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]


@pytest.fixture(autouse=True)
def isolated_codex_registry(monkeypatch: pytest.MonkeyPatch) -> CodexWakeRegistry:
    registry = CodexWakeRegistry()
    process = MagicMock(returncode=0)
    process.communicate.return_value = (None, "")
    monkeypatch.setattr(codex_wake, "get_codex_wake_registry", lambda *_args, **_kwargs: registry)
    monkeypatch.setattr(codex_wake, "_popen", lambda *_args, **_kwargs: process)
    return registry


def setup_function() -> None:
    hook_module._common._HOOK_DEADLINE = None
    codex_wake._scheduled_delivery_ids.clear()
    codex_wake._scheduled_session_generations.clear()
    codex_wake._scheduled_session_delivery_ids.clear()


def test_queue_writes_once_from_neutral_codex_home(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    process = MagicMock(returncode=0)
    process.communicate.return_value = (None, "")
    prompt = codex_wake._wake_prompt() + " →"
    with patch("app.codex_wake._codex_home", return_value=codex_home), patch(
        "app.codex_wake._popen", return_value=process,
    ) as popen:
        assert codex_wake._launch("target-session", prompt) == "queued"
    assert popen.call_args.args[0] == [
        codex_wake._codex_executable(), "queue", "--profile", "pallium-relay",
        "--thread", "target-session", "--message", prompt,
    ]
    assert popen.call_args.kwargs["cwd"] == str(codex_home)
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is subprocess.PIPE
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    process.communicate.assert_called_once_with(timeout=30)


def test_queue_failure(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    process = MagicMock(returncode=1)
    process.communicate.return_value = (None, "queue rejected")
    with patch("app.codex_wake._codex_home", return_value=codex_home), patch(
        "app.codex_wake._popen", return_value=process,
    ):
        assert codex_wake._launch("target-session", "wake") == "failed"


def test_queue_timeout_is_ambiguous(tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    process = MagicMock()
    process.communicate.side_effect = [
        subprocess.TimeoutExpired([], 30),
        (None, ""),
    ]
    with patch("app.codex_wake._codex_home", return_value=codex_home), patch(
        "app.codex_wake._popen", return_value=process,
    ):
        assert codex_wake._launch("target-session", "wake") == "ambiguous"
    process.kill.assert_called_once_with()

def test_launch_result_classifies_without_exposing_process_details(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    cases = (
        (("queued", None, 0), "accepted", True),
        (("failed", "nonzero_exit", 7), "uncertain", True),
        (("ambiguous", "timeout", None), "uncertain", True),
        (("failed", "os_error", None), "deferred", False),
        (("failed", "value_error", None), "deferred", False),
        (("failed", "invalid_codex_home", None), "deferred", False),
    )
    for index, (native, outcome, retained) in enumerate(cases):
        caplog.clear()
        registry = CodexWakeRegistry(tmp_path / str(index))
        endpoint_id = f"relay-session-{index:032x}"
        reservation = registry.reserve(
            recipient_endpoint_id=endpoint_id,
            delivery_id=f"relay-delivery-{index:032x}",
            session_ref=f"session-{index}",
            container_ref="container-秘密",
        )
        assert reservation is not None
        with caplog.at_level(logging.INFO, logger="app.codex_wake"), patch(
            "app.codex_wake._start_launch", return_value=(None, native),
        ):
            codex_wake._wake_after_debounce(reservation, registry)
        message = next(
            record.getMessage() for record in caplog.records
            if record.getMessage().startswith("codex_relay_wake delivery_ref=")
        )
        assert f"outcome={outcome}" in message
        assert "秘密" not in message
        assert registry.reserved(endpoint_id) is retained

def test_interleaved_wake_logs_correlate_without_free_form_identifiers(
    isolated_codex_registry: CodexWakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = "session-secret-C:/private/token-é-" + "x" * 200
    containers = (
        "git:example.test/private-one-秘密-SECRET_ONE",
        "C:/private/two/秘密/SECRET_TWO",
    )
    deliveries = (
        "relay-delivery-" + "a" * 32,
        "relay-delivery-" + "b" * 32,
    )
    workers = []
    unreachable = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)

    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        for delivery_id, container_ref in zip(deliveries, containers):
            result = _delivery(delivery_id)
            result["recipient"] = f"codex:{session}"
            result["deliveries"][0]["recipient_session_ref"] = session
            result["deliveries"][0]["recipient_endpoint_id"] = (
                "relay-session-" + ("a" if delivery_id == deliveries[0] else "b") * 32
            )
            codex_wake.schedule_codex_relay_wake(
                result,
                {"container_ref": container_ref},
                on_unreachable=unreachable.append,
            )

    with caplog.at_level(logging.INFO, logger="app.codex_wake"), patch(
        "app.codex_wake._start_launch",
        side_effect=(
            (None, ("failed", "nonzero_exit", 7)),
            (None, ("ambiguous", "timeout", None)),
        ),
    ):
        for worker in workers:
            codex_wake._wake_after_debounce(*worker)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("codex_relay_wake delivery_ref=")
    ]
    assert len(messages) == 2
    assert f"delivery_ref={deliveries[0]}" in messages[0]
    assert f"delivery_ref={deliveries[1]}" in messages[1]
    assert f"session_fp={_log_fp(session)}" in messages[0]
    assert f"session_fp={_log_fp(session)}" in messages[1]
    assert f"container_fp={_log_fp(containers[0])}" in messages[0]
    assert f"container_fp={_log_fp(containers[1])}" in messages[1]
    assert "outcome=uncertain reason=nonzero_exit" in messages[0]
    assert "outcome=uncertain reason=timeout" in messages[1]
    combined = "\n".join(messages)
    assert session not in combined
    assert containers[0] not in combined
    assert containers[1] not in combined
    assert "SECRET" not in combined
    assert unreachable == []
    assert codex_wake._scheduled_delivery_ids == set(deliveries)
    assert isolated_codex_registry.reserved("relay-session-" + "a" * 32)
    assert isolated_codex_registry.reserved("relay-session-" + "b" * 32)

@pytest.mark.parametrize("kind", ["missing", "file"])
def test_missing_or_non_directory_neutral_cwd_does_not_spawn(monkeypatch, tmp_path, kind) -> None:
    home = tmp_path / "home"
    home.mkdir()
    codex_home = home / ".codex"
    if kind == "file":
        codex_home.write_text("x", encoding="utf-8")
    monkeypatch.setattr(codex_wake.Path, "home", classmethod(lambda cls: home))
    with patch("app.codex_wake.subprocess.run") as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()

@pytest.mark.parametrize("cwd", [r"\\server\share\.codex", r"\\?\C:\.codex", r"\\.\C:\.codex"])
def test_windows_unsafe_neutral_cwd_does_not_spawn(monkeypatch, tmp_path, cwd) -> None:
    monkeypatch.setattr(codex_wake.os, "name", "nt")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(codex_wake.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(codex_wake.Path, "resolve", lambda self: type(self)(cwd))
    with patch("app.codex_wake.subprocess.run") as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()


def test_windows_remote_drive_neutral_cwd_does_not_spawn(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(codex_wake.os, "name", "nt")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(codex_wake.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(codex_wake.Path, "resolve", lambda self: self)
    monkeypatch.setattr(codex_wake.os.path, "splitdrive", lambda _: ("Z:", "\\.codex"))
    monkeypatch.setattr(codex_wake, "_windows_drive_is_local", lambda _: False)
    with patch("app.codex_wake.subprocess.run") as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()

@pytest.mark.parametrize("home", [codex_wake.Path("relative-home")])
def test_relative_neutral_cwd_does_not_spawn(monkeypatch, home) -> None:
    monkeypatch.setattr(codex_wake.Path, "home", classmethod(lambda cls: home))
    with patch("app.codex_wake.subprocess.run") as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()


def test_neutral_cwd_redirected_into_service_checkout_does_not_spawn(
    monkeypatch, tmp_path,
) -> None:
    home = tmp_path / "home"
    codex_home = home / ".codex"
    service_cwd = tmp_path / "service-checkout"
    codex_home.mkdir(parents=True)
    service_cwd.mkdir()
    monkeypatch.setattr(codex_wake.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        codex_wake.Path, "cwd", classmethod(lambda cls: service_cwd),
    )
    monkeypatch.setattr(
        codex_wake.Path,
        "resolve",
        lambda self: service_cwd if self.name == ".codex" else self,
    )
    with patch("app.codex_wake.subprocess.run") as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()


def test_neutral_cwd_resolution_error_does_not_spawn() -> None:
    with patch("app.codex_wake.Path.home", side_effect=OSError("unavailable")), patch(
        "app.codex_wake.subprocess.run",
    ) as run:
        assert codex_wake._launch("target-session", "wake") == "failed"
    run.assert_not_called()


def test_wake_defers_claim_until_turn_execution() -> None:
    with patch(
        "app.codex_wake._launch_result", return_value=("queued", None, 0)
    ) as launch:
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
    other_scope = {"container_ref": "git:example.test/other-wake"}
    other = _delivery("delivery-2")
    other["deliveries"][0]["recipient_endpoint_id"] = "relay-session-" + "b" * 32
    with patch("app.codex_wake.threading.Thread") as thread:
        _schedule(_delivery())
        codex_wake.schedule_codex_relay_wake(other, other_scope)
    assert thread.call_count == 2
    assert codex_wake._scheduled_delivery_ids == {"delivery-1", "delivery-2"}

    codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)

    # Turn observation is not proof that either payload was admitted.
    assert codex_wake._scheduled_delivery_ids == {"delivery-1", "delivery-2"}

@pytest.mark.parametrize("outcome", ["queued", "ambiguous"])
def test_busy_wakes_coalesce_and_turn_observation_does_not_rearm(monkeypatch, outcome: str) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    native = ("queued", None, 0) if outcome == "queued" else ("ambiguous", "timeout", None)
    with patch("app.codex_wake.threading.Thread") as thread, patch("app.codex_wake._start_launch", return_value=(None, native)) as wake:
        thread.side_effect = lambda **kwargs: (workers.append(kwargs["args"]), type("Worker", (), {"start": lambda self: None})())[1]
        _schedule(_delivery())
        _schedule(_delivery("delivery-2"))
        assert len(workers) == 1
        codex_wake._wake_after_debounce(*workers[0])
        _schedule(_delivery("delivery-3"))
        assert len(workers) == 1
        codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)
        _schedule(_delivery("delivery-4"))
    wake.assert_called_once_with("target-session", codex_wake._wake_prompt())
    assert len(workers) == 1


@pytest.mark.parametrize("outcome", ["queued", "ambiguous"])
def test_busy_wake_holds_earliest_trigger_without_blind_retry(
    monkeypatch, outcome: str,
) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch(
        "app.codex_wake._start_launch", return_value=(None, ("queued", None, 0) if outcome == "queued" else ("ambiguous", "timeout", None))
    ):
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        _schedule(_delivery())
        codex_wake._wake_after_debounce(*workers[0])
        _schedule(_delivery("delivery-after-wake"))

    assert len(workers) == 1
    assert codex_wake._scheduled_delivery_ids == {"delivery-1"}


def test_recovery_log_correlates_without_free_form_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app import dependencies
    from core.claude_wake import ClaudeWakeRegistry

    delivery_id = "relay-delivery-" + "c" * 32
    session_ref = "session-C:/private/SECRET-é-" + "x" * 2048
    container_ref = "git:example.test/private\r\nSECRET\ud800"
    candidate = {
        "delivery_id": delivery_id,
        "recipient_endpoint_id": "relay-session-" + "d" * 32,
        "recipient_runtime": "codex",
        "recipient_session_ref": session_ref,
        "state": "pending",
        "container_ref": container_ref,
    }
    scheduled = []

    class Relay:
        def wake_candidates(self, delivery_id=None):
            return [candidate] if delivery_id in (None, candidate["delivery_id"]) else []

        def mark_unreachable(self, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        lambda result, scope, **_kwargs: scheduled.append((result, scope)),
    )
    with caplog.at_level(logging.INFO, logger="app.dependencies"):
        dependencies.recover_expired_relay_wakes(
            Relay(), ClaudeWakeRegistry()
        )

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("relay wake_recovery runtime=codex")
    )
    assert f"delivery_ref={delivery_id}" in message
    assert f"session_fp={_log_fp(session_ref)}" in message
    assert f"container_fp={_log_fp(container_ref)}" in message
    assert session_ref not in message
    assert container_ref not in message
    assert "SECRET" not in message
    assert len(scheduled) == 1

def test_concurrent_recovery_sweep_does_not_duplicate_busy_wake(monkeypatch) -> None:
    from app import dependencies
    from core.claude_wake import ClaudeWakeRegistry

    workers = []
    real_thread = threading.Thread
    start = threading.Barrier(3)
    candidate = {
        "delivery_id": "delivery-1",
        "recipient_endpoint_id": "relay-session-" + "a" * 32,
        "recipient_runtime": "codex",
        "recipient_session_ref": "target-session",
        "state": "pending",
        **SCOPE,
    }

    class Relay:
        def wake_candidates(self, delivery_id=None):
            return [candidate] if delivery_id in (None, "delivery-1") else []

        def mark_unreachable(self, **_kwargs):
            return None

    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch(
        "app.codex_wake._start_launch", return_value=(None, ("queued", None, 0))
    ):
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        _schedule(_delivery())
        codex_wake._wake_after_debounce(*workers[0])

        def recover():
            start.wait()
            dependencies.recover_expired_relay_wakes(
                Relay(), ClaudeWakeRegistry()
            )

        recovery_threads = [real_thread(target=recover) for _ in range(2)]
        for recovery_thread in recovery_threads:
            recovery_thread.start()
        start.wait()
        for recovery_thread in recovery_threads:
            recovery_thread.join(timeout=1)
            assert not recovery_thread.is_alive()

    assert len(workers) == 1
    assert codex_wake._scheduled_delivery_ids == {"delivery-1"}

def test_turn_observation_during_queued_submission_does_not_release(monkeypatch) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        _schedule(_delivery())

    process = MagicMock(returncode=0)
    def turn_observed(*, timeout: float):
        assert timeout == 30
        codex_wake.mark_codex_relay_wake_admitted("target-session", **SCOPE)
        return None, ""

    process.communicate.side_effect = turn_observed
    with patch("app.codex_wake._popen", return_value=process):
        codex_wake._wake_after_debounce(*workers[0])

    assert codex_wake._scheduled_delivery_ids == {"delivery-1"}


def test_pre_submit_failure_releases_without_marking_unreachable(monkeypatch) -> None:
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
    with patch("app.codex_wake._start_launch", return_value=(None, ("failed", "os_error", None))):
        codex_wake._wake_after_debounce(*workers[0])

    assert unreachable == []
    assert not codex_wake._scheduled_delivery_ids


def test_unexpected_native_exception_retains_owner(monkeypatch) -> None:
    workers = []
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake.threading.Thread") as thread, patch(
        "app.codex_wake._start_launch", side_effect=RuntimeError("launch failed")
    ) as wake:
        thread.side_effect = lambda **kwargs: (
            workers.append(kwargs["args"]),
            type("Worker", (), {"start": lambda self: None})(),
        )[1]
        _schedule(_delivery())
        codex_wake._wake_after_debounce(*workers[0])
        _schedule(_delivery("delivery-2"))
    assert wake.call_count == 1
    assert codex_wake._scheduled_delivery_ids == {"delivery-1"}

def test_schedule_returns_before_child_exits(monkeypatch) -> None:
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    started = threading.Event()
    release = threading.Event()

    process = MagicMock(returncode=0)
    def slow_wait(*, timeout: float):
        assert timeout == 30
        started.set()
        release.wait(1)
        return None, ""

    process.communicate.side_effect = slow_wait
    with patch("app.codex_wake._popen", return_value=process):
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
        },
    ).status_code == 200
    assert route_client.post(
        "/relay/turn",
        json={
            "runtime": "claude-code",
            "session_ref": "sender",
            "container_ref": "git:example.test/wake",
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
        },
    )
    assert sent.status_code == 200
    assert len(seen) == 1
    assert seen[0][0]["message_id"] == sent.json()["message_id"]
    assert seen[0][1] == SCOPE
    assert seen[0][0]["deliveries"][0]["delivery_id"] == sent.json()["deliveries"][0]["delivery_id"]
    assert route_client.get(
        f"/relay/messages/{sent.json()['message_id']}",
        params={"container_ref": "git:example.test/wake"},
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
    scope = {"container_ref": "git:example.test/real-wake"}
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

    with patch("app.codex_wake._start_launch", return_value=(None, ("queued", None, 0))):
        codex_wake._wake_after_debounce(*workers[0])

    status = route.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]
    assert status["state"] == "pending"
    assert status["destination_health"] == "active"
    assert status["attempts"] == 0

    state_dir = tmp_path / "no-hook-state"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setattr(codex_wake, "_codex_home", lambda: codex_home)
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: scope["container_ref"])
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

    # The authoritative ACK performed by the hook releases the exact reservation.
    assert not codex_wake._scheduled_session_generations

def test_profile_is_idempotent_and_narrow(monkeypatch, tmp_path) -> None:
    from app.cli import setup_codex

    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    setup_codex._install_relay_profile()
    setup_codex._install_relay_profile()
    profile = (tmp_path / ".codex" / "pallium-relay.config.toml").read_text(encoding="utf-8")
    assert "required = true" in profile
    assert 'pallium_expand_source' in profile
    assert 'default_tools_approval_mode = "prompt"' in profile
    assert profile.count('approval_mode = "approve"') == 7
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
    scope = {"container_ref": "git:example.test/reply-wake"}
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
    assert seen[1][0]["recipient"] == parent["sender_endpoint_id"]

def test_busy_queue_claims_at_hook_execution_without_stale_receipt_or_duplicate_action(
    client, monkeypatch, tmp_path
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/wake",
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
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setattr(codex_wake, "_codex_home", lambda: codex_home)
    process = MagicMock(returncode=0)
    process.communicate.return_value = (None, "")
    with patch("app.codex_wake._popen", return_value=process) as popen:
        codex_wake._wake("target-session")
    assert popen.call_args.kwargs["cwd"] == str(codex_home)

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

    def run_hook(session_id: str, prompt: str) -> None:
        monkeypatch.setattr(
            hook, "read_hook_input",
            lambda: {"cwd": str(tmp_path), "session_id": session_id, "prompt": prompt},
        )
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0

    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: scope["container_ref"])
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
    run_hook("probe-missing", codex_wake._wake_prompt() + " missing scope")
    hook._common.pin_container("probe-wrong", "git:example.test/other")
    run_hook("probe-wrong", codex_wake._wake_prompt() + " wrong scope")
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
    run_hook("target-session", codex_wake._wake_prompt())

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
        "actor_ref": scope["container_ref"],
    }
    reply_body = {
        "delivery_id": delivery["delivery_id"],
        "payload": "handled once",
        "container_ref": injected_scope["container_ref"],
    }
    assert client.post(
        "/relay/replies", json={**reply_body, "container_ref": "git:example.test/other"}
    ).status_code == 200
    first = client.post("/relay/replies", json=reply_body)
    duplicate = client.post("/relay/replies", json=reply_body)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["message_id"] == duplicate.json()["message_id"]
    assert client.get(
        f"/relay/messages/{sent['message_id']}", params=scope
    ).json()["deliveries"][0]["state"] == "delivered"


def test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake(
    client, monkeypatch, tmp_path, capsys,
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
        queued = subprocess.CompletedProcess([], 0, stderr="")
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
                recover_expired_relay_wakes(relay, ClaudeWakeRegistry())

    queue_calls = [call for call in native_calls if call[0][1] == "queue"]
    assert len(queue_calls) == 1
    queue_command, queue_kwargs = queue_calls[0]
    assert queue_kwargs["cwd"] == str(codex_home)
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


def test_redaction_expansion_is_compacted_and_internal_wake_delivers_once(
    client, monkeypatch, tmp_path, capsys,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {
        "container_ref": "git:example.test/oversized-wake",
    }
    sender = "s" * 255
    target = "oversized-target"
    state_dir = tmp_path / "oversized-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        lambda *_args, **_kwargs: None,
    )
    for runtime, session in (("claude-code", sender), ("codex", target)):
        assert client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    payload = "pwd:a\n" * 2600
    assert len(payload) == 15600
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code",
        "sender_session_ref": sender,
        "recipient": f"codex:{target}",
        "message_id": "m" * 128,
        "payload": payload,
        **scope,
    })
    assert sent.status_code == 200, sent.text
    assert sent.json()["redacted"] is True
    hook._common.pin_container(target, scope["container_ref"])
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path), "session_id": target, "prompt": hook.RELAY_WAKE_PROMPT,
    })
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_a, **_k: pytest.fail("Relay wake must not query memory"),
    )
    contexts: list[str] = []
    monkeypatch.setattr(hook, "emit_context", lambda output, _event: contexts.append(output))
    turns = []

    def relay_request(method: str, path: str, payload: dict, *, timeout: float):
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        body = response.json() if response.content else None
        if path == "/relay/turn":
            turns.append(body)
        return body

    monkeypatch.setattr(hook, "relay_request", relay_request)
    monkeypatch.setattr(hook._common, "relay_request", relay_request)
    with pytest.raises(SystemExit) as exited:
        hook.main()

    assert exited.value.code == 0
    assert len(turns[-1]["deliveries"]) == 1
    assert turns[-1]["has_more"] is False
    assert turns[-1]["remaining_count"] == 0
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert len(contexts) == 1
    assert "payload omitted because sanitization exceeded the Relay limit" in contexts[0]
    assert "pwd:a" not in contexts[0]
    delivery = client.get(
        f"/relay/messages/{sent.json()['message_id']}", params=scope,
    ).json()["deliveries"][0]
    assert delivery["state"] == "delivered" and delivery["attempts"] == 1


def test_actual_codex_hook_drains_bounded_backlog_and_arrival_once(
    client, monkeypatch, tmp_path,
) -> None:
    from integrations.codex.hooks import user_prompt_submit as hook

    scope = {"container_ref": SCOPE["container_ref"]}
    state_dir = tmp_path / "drain-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
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
    }
    state_dir = tmp_path / "maximum-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
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
            "recipient_endpoint_id": sent[1]["deliveries"][0]["recipient_endpoint_id"],
            "recipient_runtime": "codex",
            "recipient_session_ref": "target",
            "recipient_container_ref": SCOPE["container_ref"],
        }]

        duplicate = route.post("/relay/deliveries/ack", json=ack_body)
        assert duplicate.status_code == 200
        assert duplicate.json()["already_delivered"] is True
        assert schedule.call_count == 2

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

def test_build_router_normalizes_endpoint_send_for_codex_wake(client) -> None:
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    target_scope = {"container_ref": "git:example.test/target"}
    source_scope = {"container_ref": "git:example.test/source"}
    target = route.post("/relay/turn", json={"runtime": "codex", "session_ref": "target-session", **target_scope})
    assert target.status_code == 200
    endpoint_id = target.json()["session"]["endpoint_id"]
    assert route.post("/relay/turn", json={"runtime": "claude-code", "session_ref": "sender", **source_scope}).status_code == 200
    assert route.post("/relay/sessions/name", json={"runtime": "codex", "session_ref": "target-session", "alias": "target", **target_scope}).status_code == 200
    with patch("app.dependencies.schedule_codex_relay_wake") as schedule:
        response = route.post("/relay/messages", json={
            "sender_runtime": "claude-code", "sender_session_ref": "sender",
            "recipient": endpoint_id, "payload": "wake", **source_scope,
        })
    assert response.status_code == 200
    wake, scope = schedule.call_args.args
    assert scope == target_scope
    assert wake["recipient"] == "codex:target-session"



def test_ack_rearm_after_scope_transition_uses_live_container_and_historical_delivery_snapshot(client) -> None:
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
    ))
    route = TestClient(app)
    old = {"container_ref": "git:example.test/wake-old"}
    new = {"container_ref": "git:example.test/wake-new"}
    sender = {"container_ref": "git:example.test/wake-sender"}
    with patch("app.dependencies.schedule_codex_relay_wake") as schedule:
        assert route.post("/relay/turn", json={"runtime": "claude-code", "session_ref": "sender", **sender}).status_code == 200
        registered = route.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **old})
        assert registered.status_code == 200
        endpoint = registered.json()["session"]["endpoint_id"]
        sent = []
        for message_id in ("transition-batch-1", "transition-batch-2"):
            response = route.post("/relay/messages", json={
                "sender_runtime": "claude-code", "sender_session_ref": "sender",
                "recipient": endpoint, "message_id": message_id,
                "payload": "wake payload", **sender,
            })
            assert response.status_code == 200, response.text
            sent.append(response.json())

        schedule.reset_mock()
        claimed = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", "max_messages": 1, **old,
        }).json()["deliveries"][0]
        moved = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", "max_chars": 1, "max_messages": 1,
            "previous_container_ref": old["container_ref"],
            "previous_endpoint_id": endpoint, "previous_scope_generation": 0, **new,
        })
        assert moved.status_code == 200, moved.text
        assert moved.json()["session"]["endpoint_id"] == endpoint
        assert moved.json()["session"]["scope_generation"] == 1
        assert moved.json()["deliveries"] == []

        # ACK through the historical snapshot: the endpoint is now live in new.
        ack = route.post("/relay/deliveries/ack", json={
            "delivery_id": claimed["delivery_id"],
            "claim_token": claimed["claim_token"],
            **old,
        })
        assert ack.status_code == 200, ack.text
        schedule.assert_called_once()
        wake, live_scope = schedule.call_args.args
        assert live_scope == new
        assert wake["recipient"] == "codex:target"
        assert wake["deliveries"][0]["delivery_id"] == sent[1]["deliveries"][0]["delivery_id"]
        assert wake["deliveries"][0]["recipient_container_ref"] == new["container_ref"]

        stored = route.get(f"/relay/messages/{sent[1]['message_id']}", params=old).json()["deliveries"][0]
        assert stored["recipient_container_ref"] == old["container_ref"]
        assert stored["state"] == "pending"

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

def test_build_router_turn_never_releases_actual_codex_wake_state(client, monkeypatch) -> None:
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
        }).status_code == 200
        assert codex_wake._scheduled_session_generations
        assert route.post("/relay/turn", json={"runtime": "codex", "session_ref": "target-session", **SCOPE}).status_code == 200
        assert codex_wake._scheduled_session_generations
        assert codex_wake._scheduled_delivery_ids == {"delivery-1"}
        _schedule(_delivery("delivery-2"))
    assert thread.call_count == 1


def test_failed_old_generation_cannot_submit_or_clear_replacement(monkeypatch) -> None:
    registry = CodexWakeRegistry()
    endpoint_id = "relay-session-" + "a" * 32
    old = registry.reserve(
        recipient_endpoint_id=endpoint_id, delivery_id="delivery-old",
        session_ref="target-session", container_ref=SCOPE["container_ref"],
    )
    assert old is not None
    assert registry.release_delivery("delivery-old") == old
    new = registry.reserve(
        recipient_endpoint_id=endpoint_id, delivery_id="delivery-new",
        session_ref="target-session", container_ref=SCOPE["container_ref"],
    )
    assert new is not None and new.generation > old.generation
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake._start_launch") as start:
        codex_wake._wake_after_debounce(old, registry)
    start.assert_not_called()
    assert registry.snapshot(endpoint_id) == new


def test_ack_during_process_wait_releases_without_deadlock(monkeypatch) -> None:
    registry = CodexWakeRegistry()
    endpoint_id = "relay-session-" + "a" * 32
    reservation = registry.reserve(
        recipient_endpoint_id=endpoint_id, delivery_id="delivery",
        session_ref="target-session", container_ref=SCOPE["container_ref"],
    )
    assert reservation is not None
    started = threading.Event()
    finish = threading.Event()
    process = MagicMock(returncode=0)

    def communicate(*, timeout: float):
        assert timeout == 30
        started.set()
        assert finish.wait(1)
        return None, ""

    process.communicate.side_effect = communicate
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    with patch("app.codex_wake._popen", return_value=process):
        worker = threading.Thread(
            target=codex_wake._wake_after_debounce, args=(reservation, registry),
        )
        worker.start()
        assert started.wait(1)
        assert codex_wake.release_codex_relay_wake(
            "delivery", registry=registry,
        )
        finish.set()
        worker.join(timeout=1)
    assert not worker.is_alive()
    assert registry.snapshot(endpoint_id) is None

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
    client, monkeypatch: pytest.MonkeyPatch, tmp_path, capsys,
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

    state_dir = tmp_path / "timeout-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: SCOPE["container_ref"])
    monkeypatch.setattr(
        hook,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("timed-out Relay wake must not query memory"),
    )
    timeout_contexts: list[str] = []
    monkeypatch.setattr(
        hook, "emit_context", lambda output, _event: timeout_contexts.append(output)
    )
    timed_out_turn: dict = {}

    def timeout_after_server_claim(
        method: str, path: str, payload: dict, *, timeout: float
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        body = response.json() if response.content else None
        if path == "/relay/turn":
            timed_out_turn.update(body)
            return None
        return body

    monkeypatch.setattr(hook, "relay_request", timeout_after_server_claim)
    monkeypatch.setattr(hook._common, "relay_request", timeout_after_server_claim)
    hook._common.pin_container("crash-target", SCOPE["container_ref"])
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path),
        "session_id": "crash-target",
        "prompt": codex_wake._wake_prompt(),
    })
    with pytest.raises(SystemExit):
        hook.main()

    assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert timeout_contexts == []
    claimed = timed_out_turn["deliveries"][0]
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
        "recipient_endpoint_id": claimed["recipient_endpoint_id"],
        "recipient_runtime": "codex",
        "recipient_session_ref": "crash-target",
        "recipient_container_ref": SCOPE["container_ref"],
    }

    state_dir = tmp_path / "crash-hook-state"
    monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: SCOPE["container_ref"])
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

def test_pending_and_expired_codex_work_rewakes_after_real_app_restart(
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
        relay.turn(runtime="codex", session_ref="pending-target", **SCOPE)
        pending = relay.send(
            sender_runtime="claude-code",
            sender_session_ref="sender",
            recipient="codex:pending-target",
            payload="persisted pending Codex wake ✓",
            **SCOPE,
        )

    clock[0] += timedelta(seconds=61)
    scheduled = threading.Event()
    wake_calls: list[tuple[dict, dict]] = []

    def schedule(result: dict, scope: dict, **_kwargs) -> None:
        wake_calls.append((result, scope))
        if len(wake_calls) == 2:
            scheduled.set()

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", schedule)
    monkeypatch.setattr(main, "start_claude_wake_reconciler", original_start)
    app_b = create_app(config)
    with TestClient(app_b, client=("127.0.0.1", 50000)) as http_b:
        assert scheduled.wait(timeout=1)
        assert len(wake_calls) == 2
        assert {
            call[0]["deliveries"][0]["delivery_id"] for call in wake_calls
        } == {
            claimed["delivery_id"],
            pending["deliveries"][0]["delivery_id"],
        }
        assert all(call[1] == SCOPE for call in wake_calls)

        from integrations.codex.hooks import user_prompt_submit as hook

        state_dir = tmp_path / "restart-hook-state"
        monkeypatch.setattr(hook._common, "STATE_DIR", state_dir)
        monkeypatch.setattr(hook._common, "SESSIONS_DIR", state_dir / "sessions")
        monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda _: ([], 0))
        monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: SCOPE["container_ref"])
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
        hook._common.pin_container("pending-target", SCOPE["container_ref"])
        monkeypatch.setattr(hook, "read_hook_input", lambda: {
            "cwd": str(tmp_path),
            "session_id": "pending-target",
            "prompt": codex_wake._wake_prompt(),
        })
        with pytest.raises(SystemExit):
            hook.main()

        relay = RelayService(http_b.app.state.pallium_service._storage)
        assert len(contexts) == 2
        assert any("persisted Codex crash ✓" in context for context in contexts)
        assert any("persisted pending Codex wake ✓" in context for context in contexts)
        delivered = relay.message_status(message_id=sent["message_id"], **SCOPE)["deliveries"][0]
        assert delivered["state"] == "delivered" and delivered["attempts"] == 2
        pending_delivered = relay.message_status(
            message_id=pending["message_id"], **SCOPE
        )["deliveries"][0]
        assert pending_delivered["state"] == "delivered"
        assert pending_delivered["attempts"] == 1
        wake_calls.clear()
        assert relay.turn(
            runtime="codex", session_ref="restart-target", **SCOPE
        )["deliveries"] == []
        assert wake_calls == []

    reconciler = app_b.state._claude_wake_reconciler
    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_relay_profile_parses_to_exact_read_only_tools(monkeypatch, tmp_path) -> None:
    from app.cli import setup_codex
    import tomllib

    monkeypatch.setattr(setup_codex.Path, "home", lambda: tmp_path)
    setup_codex._install_relay_profile()
    profile = tomllib.loads((tmp_path / ".codex" / "pallium-relay.config.toml").read_text(encoding="utf-8"))["mcp_servers"]["pallium"]
    expected = {"pallium_relay_send", "pallium_relay_reply", "pallium_relay_ack", "pallium_relay_receive", "pallium_search_history_by_work_ref", "pallium_search_history", "pallium_expand_source"}
    assert set(profile["enabled_tools"]) == expected == set(profile["tools"])
    assert {tool["approval_mode"] for tool in profile["tools"].values()} == {"approve"}


def test_http_repeat_ack_mcp_ack_and_atomic_reply_release_exact_codex_reservation(
    client, isolated_codex_registry: CodexWakeRegistry,
) -> None:
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        codex_wake_registry=isolated_codex_registry,
    ))
    route = TestClient(app)
    scope = {"container_ref": "git:example.test/ack-release"}
    for runtime, session in (("claude-code", "sender"), ("codex", "target")):
        assert route.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **scope,
        }).status_code == 200

    def send_and_claim(payload: str) -> tuple[dict, dict]:
        with patch("app.codex_wake.threading.Thread"):
            sent = route.post("/relay/messages", json={
                "sender_runtime": "claude-code",
                "sender_session_ref": "sender",
                "recipient": "codex:target",
                "payload": payload,
                **scope,
            }).json()
        delivery = sent["deliveries"][0]
        activation = delivery["activation"]
        assert activation["contract"] == "relay-activation/v1"
        assert activation["behavior"] == "busy_queue"
        assert activation["fallback"] == "next_natural_turn"
        assert "turn_started" not in activation["supported_evidence"]
        if not isolated_codex_registry.reserved(delivery["recipient_endpoint_id"]):
            assert isolated_codex_registry.reserve(
                recipient_endpoint_id=delivery["recipient_endpoint_id"],
                delivery_id=delivery["delivery_id"],
                session_ref="target", container_ref=scope["container_ref"],
            ) is not None
        assert isolated_codex_registry.reserved(delivery["recipient_endpoint_id"])
        turn = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", **scope,
        }).json()
        claim = next(
            item for item in turn["deliveries"]
            if item["delivery_id"] == delivery["delivery_id"]
        )
        assert isolated_codex_registry.reserved(delivery["recipient_endpoint_id"])
        return delivery, claim

    normal, normal_claim = send_and_claim("normal ACK")
    ack_body = {
        "delivery_id": normal_claim["delivery_id"],
        "claim_token": normal_claim["claim_token"],
        **scope,
    }
    assert route.post("/relay/deliveries/ack", json=ack_body).status_code == 200
    assert not isolated_codex_registry.reserved(normal["recipient_endpoint_id"])
    repeated = route.post("/relay/deliveries/ack", json=ack_body)
    assert repeated.status_code == 200 and repeated.json()["already_delivered"] is True
    assert not isolated_codex_registry.reserved(normal["recipient_endpoint_id"])

    mcp, mcp_claim = send_and_claim("MCP ACK")
    assert route.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": mcp_claim["delivery_id"],
        "receipt": mcp_claim["receipt"],
        **scope,
    }).status_code == 200
    assert not isolated_codex_registry.reserved(mcp["recipient_endpoint_id"])

    reply, reply_claim = send_and_claim("atomic reply")
    response = route.post("/relay/replies", json={
        "delivery_id": reply_claim["delivery_id"],
        "receipt": reply_claim["receipt"],
        "payload": "reply",
        **scope,
    })
    assert response.status_code == 200
    assert not isolated_codex_registry.reserved(reply["recipient_endpoint_id"])
    assert "turn_started" not in response.text