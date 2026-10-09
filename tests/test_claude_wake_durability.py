from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from core.claude_wake import ClaudeWakeRegistry
from core.relay_activation import ActivationAttemptResult


ENDPOINT_ID = "relay-session-" + "a" * 32


PAYLOAD = {
    "runtime": "claude-code",
    "session_ref": "session-α",
    "container_ref": "git:example/repo",
    "socket_path": "/missing/claude.sock",
    "token": "test-token",
    "idle": True,
}


def _intent_path(
    root: Path,
    session_ref: str,
    container_ref: str = PAYLOAD["container_ref"],
) -> Path:
    identity = json.dumps(
        ["claude-code", session_ref, container_ref],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return root / "intents" / (
        hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json"
    )


def _write_intent(root: Path, payload: dict, intent_id: str) -> None:
    path = _intent_path(root, payload["session_ref"], payload["container_ref"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**payload, "intent_id": intent_id}), encoding="utf-8")


def _register(registry: ClaudeWakeRegistry, root: Path, payload: dict, intent_id: str) -> bool:
    _write_intent(root, payload, intent_id)
    return registry.register(**payload, intent_id=intent_id)


def test_compare_before_apply_rejects_delayed_intent_and_restart_uses_latest(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "A")
    newer = {**PAYLOAD, "token": "new-token"}
    assert _register(registry, tmp_path, newer, "B")
    assert not registry.register(**PAYLOAD, intent_id="A")
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    observed: list[str] = []
    assert restarted.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], transport=lambda _path, token: observed.append(token) or True)
    assert observed == ["new-token"]


def test_startup_recovers_pre_http_write_ahead_intent_without_relay_mutation(tmp_path: Path) -> None:
    _write_intent(tmp_path, PAYLOAD, "before-http")
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    registry.recover_intents()
    observed: list[bool] = []
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], transport=lambda *_: observed.append(True) or True)
    assert observed == [True]


def test_busy_persistence_failure_fences_stale_idle_across_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    assert registry.mark_busy(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"])
    assert (tmp_path / "store-unusable").exists() or (tmp_path / "capabilities.unusable").exists()
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    assert restarted.recovery_candidates() == []
    assert not restarted.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], transport=lambda *_: pytest.fail("stale idle must not rehydrate"))


def test_capacity_keeps_live_endpoint_without_admitting_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.claude_wake as wake

    monkeypatch.setattr(wake, "MAX_REGISTRATIONS", 2)
    live = tmp_path / "live.sock"
    live.write_text("not-probed", encoding="utf-8")
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, {**PAYLOAD, "session_ref": "live", "socket_path": str(live)}, "live")
    assert _register(registry, tmp_path, {**PAYLOAD, "session_ref": "other", "socket_path": str(live)}, "other")
    monkeypatch.setattr(registry, "probe", lambda *_args, **_kwargs: pytest.fail("capacity check must not admit a turn"))
    assert not _register(registry, tmp_path, {**PAYLOAD, "session_ref": "overflow"}, "overflow")


def test_hook_writes_intent_before_loopback_and_keeps_it_after_ambiguous_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_claude_code_integration import _load_claude_hook

    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", tmp_path)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", tmp_path / "intents")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/missing/claude.sock")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "test-token")

    def open_request(request, **_kwargs):
        body = json.loads(request.data.decode("utf-8"))
        assert _intent_path(tmp_path, "session-hook").exists()
        assert body["intent_id"]
        raise TimeoutError("ambiguous")

    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    assert not common.register_claude_wake("session-hook", "git:example/repo", idle=True)
    saved = json.loads(_intent_path(tmp_path, "session-hook").read_text(encoding="utf-8"))
    assert saved["idle"] is True and isinstance(saved["intent_id"], str)


def test_hook_replace_failure_cleans_credentials_before_loopback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_claude_code_integration import _load_claude_hook

    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", tmp_path)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", tmp_path / "intents")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/missing/claude.sock")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "test-token")
    opener_calls: list[bool] = []
    def fail_replace(source, _target):
        assert Path(source).exists()
        raise OSError("replace failed")

    monkeypatch.setattr(common.os, "replace", fail_replace)
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: opener_calls.append(True) or pytest.fail("write-ahead failure must not loop back"))
    assert not common.register_claude_wake("replace-failure", "git:example/repo", idle=True)
    assert opener_calls == [] and list((tmp_path / "intents").glob("*.tmp")) == []
    assert not _intent_path(tmp_path, "replace-failure").exists()
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    restarted.recover_intents()
    assert restarted.recovery_candidates() == []


def test_closed_intent_removes_capability_after_outage(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "open")
    closed = {
        "runtime": "claude-code", "session_ref": PAYLOAD["session_ref"],
        "container_ref": PAYLOAD["container_ref"],
        "intent_id": "close", "closed": True,
    }
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    assert registry.close(**{key: closed[key] for key in ("runtime", "session_ref", "container_ref", "intent_id")})
    assert ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates() == []


def test_pending_candidate_is_read_only_at_the_real_relay_surface(client) -> None:
    from core.relay import RelayService

    relay = RelayService(client.app.state.pallium_service._storage)
    scope = {"container_ref": "git:example/repo"}
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref="target", **scope)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="claude-code:target", payload="pending", **scope)
    before = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    candidate = relay.pending_candidate(runtime="claude-code", session_ref="target", **scope)
    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert candidate == {
        "delivery_id": before["delivery_id"],
        "state": "pending",
        "recipient_endpoint_id": before["recipient_endpoint_id"],
    }
    assert after["state"] == "pending" and after["attempts"] == before["attempts"] == 0

def test_persistent_register_rejection_is_http_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_claude_wake_registration import _client

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    monkeypatch.setattr(registry, "register", lambda **_kwargs: False)
    response = _client(registry).post("/internal/claude-wake/register", json={**PAYLOAD, "intent_id": "rejected"})
    assert response.status_code == 409

def test_idle_registration_write_failure_rejects_and_preserves_recoverable_intent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_claude_wake_registration import _client

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    _write_intent(tmp_path, PAYLOAD, "idle")
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    assert _client(registry).post("/internal/claude-wake/register", json={**PAYLOAD, "intent_id": "idle"}).status_code == 409
    assert registry.recovery_candidates() == []
    assert json.loads(_intent_path(tmp_path, PAYLOAD["session_ref"]).read_text(encoding="utf-8"))["intent_id"] == "idle"
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    restarted.recover_intents()
    assert restarted.recovery_candidates()[0]["state"] == "idle"


def test_inflight_write_failure_never_transports_or_claims_relay(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.relay import RelayService

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="claude-code:" + PAYLOAD["session_ref"], payload="pending", **scope)
    before = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    assert not registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        delivery_id=before["delivery_id"], recipient_endpoint_id=ENDPOINT_ID, transport=lambda path, token: calls.append((path, token)) or "accepted",
    )
    assert calls == []
    candidates = registry.recovery_candidates()
    assert [(item["state"], item["delivery_id"]) for item in candidates] == [("idle", None)]
    assert [(item["state"], item["delivery_id"]) for item in ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates()] == [("idle", None)]
    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert after["state"] == "pending" and after["claim_token"] is None and after["receipt"] is None and after["attempts"] == 0


@pytest.mark.parametrize("result", [
    ActivationAttemptResult("deferred", "pre_frame", native_retry_safe=True),
    ActivationAttemptResult(
        "failed", "endpoint_missing", native_retry_safe=True,
        destination_health_update="unreachable",
    ),
])
def test_safe_reset_write_failure_remains_fenced_across_restart(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: ActivationAttemptResult,
) -> None:
    from core.relay import RelayService

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="pending", **scope,
    )
    delivery_id = relay.message_status(
        message_id=sent["message_id"], **scope,
    )["deliveries"][0]["delivery_id"]
    writes = 0
    original_write = registry._write_canonical_locked

    def write_reservation_then_fail_reset(records):
        nonlocal writes
        writes += 1
        return original_write(records) if writes == 1 else False

    monkeypatch.setattr(
        registry, "_write_canonical_locked", write_reservation_then_fail_reset,
    )
    calls = []
    assert not registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], delivery_id=delivery_id,
        recipient_endpoint_id=ENDPOINT_ID,
        transport=lambda path, token: calls.append((path, token)) or result,
    )
    assert writes == 2
    assert calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
    assert registry.recovery_candidates() == []

    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    assert restarted.recovery_candidates() == []
    assert not restarted.rearm_inflight(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], delivery_id=delivery_id,
        grace_seconds=0,
    )
    later_calls = []
    assert not restarted.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], delivery_id=delivery_id,
        recipient_endpoint_id=ENDPOINT_ID,
        transport=lambda *_: later_calls.append(True) or True,
    )
    assert later_calls == []

@pytest.mark.parametrize("item", [
    {"runtime": "claude-code", "session_ref": "s", "container_ref": "c", "socket_path": "p", "token": "t", "generation": "bad", "idle": True, "state": "idle", "delivery_id": None, "attempted_at": None, "expires_at": 1},
    {"runtime": "claude-code", "session_ref": "s", "container_ref": "c", "socket_path": "p", "token": "t", "generation": 1, "idle": True, "state": "wake_inflight", "delivery_id": None, "attempted_at": None, "expires_at": 1},
])
def test_corrupt_persisted_records_fail_closed(tmp_path: Path, item: dict) -> None:
    (tmp_path / "capabilities.json").write_text(json.dumps({"version": 1, "registrations": [item]}), encoding="utf-8")
    assert ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates() == []


def test_stale_closed_intent_cannot_remove_newer_intent(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    newer = {**PAYLOAD, "token": "new-token"}
    _write_intent(tmp_path, newer, "new")
    assert not registry.close(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], intent_id="old")
    assert registry.register(**newer, intent_id="new")


def test_reconciler_stop_joins_its_thread(tmp_path: Path) -> None:
    from app.claude_wake import ClaudeWakeReconciler

    reconciler = ClaudeWakeReconciler(ClaudeWakeRegistry(state_dir=tmp_path), SimpleNamespace(pending_candidate=lambda **_kwargs: None), interval_seconds=0.01)
    reconciler.start()
    reconciler.stop()
    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_accepted_inflight_rehydrates_without_elapsed_time_release(tmp_path: Path) -> None:
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "accepted")
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert restarted.recovery_candidates()[0]["attempted_at"] == 100.0
    assert not restarted.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", grace_seconds=1)
    wall[0] = 101.0
    assert not restarted.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", grace_seconds=1)


@pytest.mark.parametrize("native_outcome", ["accepted", "uncertain"])
def test_restricted_resume_fences_inflight_until_normal_turn_ack(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, native_outcome: str,
) -> None:
    from tests.test_claude_code_integration import _load_claude_hook

    common = _load_claude_hook("common", monkeypatch)
    registry = client.app.state.claude_wake_registry
    wake_dir = registry._state_dir
    assert wake_dir is not None
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", wake_dir)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", wake_dir / "intents")
    monkeypatch.setattr(common, "PALLIUM_BASE_URL", "http://testserver")
    wake_http = TestClient(client.app, client=("127.0.0.1", 50000))

    def open_wake(request, **_kwargs):
        response = wake_http.request(request.get_method(), urlsplit(request.full_url).path, content=request.data)
        assert response.status_code == 204
        return nullcontext(response)

    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_wake))
    scope = {"container_ref": "git:example/repo"}
    session_ref = "restricted-inflight"
    assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200
    assert client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": session_ref, **scope}).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "claude-code:" + session_ref, "payload": "Pending in-flight work.", **scope,
    })
    assert sent.status_code == 200
    delivery = sent.json()["deliveries"][0]
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "socket")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "token")
    assert common.register_claude_wake(session_ref, scope["container_ref"], idle=True)
    native_calls = []
    attempt = registry.attempt(
        runtime="claude-code", session_ref=session_ref, container_ref=scope["container_ref"],
        delivery_id=delivery["delivery_id"], recipient_endpoint_id=delivery["recipient_endpoint_id"],
        transport=lambda *_: native_calls.append(True) or (native_outcome == "accepted"),
    )
    assert attempt.outcome == native_outcome and native_calls == [True]
    monkeypatch.delenv("CLAUDE_CODE_MESSAGING_TOKEN")
    assert not common.register_claude_wake(session_ref, scope["container_ref"])
    restarted = ClaudeWakeRegistry(state_dir=wake_dir)
    restarted.recover_intents()
    assert restarted.state_for(
        recipient_endpoint_id=delivery["recipient_endpoint_id"], session_ref=session_ref,
        container_ref=scope["container_ref"],
    ) == "wake_inflight"
    assert restarted.attempt(
        runtime="claude-code", session_ref=session_ref, container_ref=scope["container_ref"],
        delivery_id=delivery["delivery_id"], recipient_endpoint_id=delivery["recipient_endpoint_id"],
        transport=lambda *_: pytest.fail("second native attempt"),
    ).outcome == "deferred"

    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    hook_common = sys.modules[prompt.register_claude_wake.__module__]
    monkeypatch.setattr(hook_common, "CLAUDE_WAKE_DIR", wake_dir)
    monkeypatch.setattr(hook_common, "CLAUDE_WAKE_INTENTS_DIR", wake_dir / "intents")
    monkeypatch.setattr(hook_common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_wake))

    def relay(method, path, body, **_kwargs):
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(prompt, "relay_request", relay)
    monkeypatch.setattr(hook_common, "relay_request", relay)
    monkeypatch.setattr(prompt, "read_hook_input", lambda: {"session_id": session_ref, "cwd": ".", "prompt": "hi"})
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
    monkeypatch.setattr(prompt, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(prompt, "pallium_request", lambda *_a, **_k: pytest.fail("short prompt should not query memory"))
    with pytest.raises(SystemExit) as exit_info:
        prompt.main()
    assert exit_info.value.code == 0
    assert "Pending in-flight work." in capsys.readouterr().out
    status = client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope).json()
    assert status["deliveries"][0]["state"] == "delivered"
    after_ack = ClaudeWakeRegistry(state_dir=wake_dir)
    assert after_ack.state_for(
        recipient_endpoint_id=delivery["recipient_endpoint_id"], session_ref=session_ref,
        container_ref=scope["container_ref"],
    ) == "busy"
    assert native_calls == [True]


def test_wall_clock_rollback_never_releases_inflight(tmp_path: Path) -> None:
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "accepted")
    wall[0] = 1.0
    assert not registry.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", grace_seconds=1)

def test_unreachable_transport_retains_capability_but_preserves_newer_intent(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    _write_intent(tmp_path, {**PAYLOAD, "token": "new"}, "new")
    assert not registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="d", recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "unreachable")
    assert registry.recovery_candidates() == []
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    assert restarted.recovery_candidates() == []
    assert json.loads((tmp_path / "capabilities.json").read_text(encoding="utf-8"))["registrations"][0]["state"] == "unreachable"
    assert registry.register(**{**PAYLOAD, "token": "new"}, intent_id="new")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], transport=lambda _path, token: token == "new")


def test_busy_persistence_failure_reports_degradation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    monkeypatch.setattr(registry, "_quarantine_or_mark_unusable_locked", lambda: False)
    assert registry.mark_busy(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"])
    assert registry.durability_degraded

def test_close_preserves_intent_replaced_after_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "open")
    closed = {"runtime": "claude-code", "session_ref": PAYLOAD["session_ref"], "container_ref": PAYLOAD["container_ref"], "intent_id": "close", "closed": True}
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    original = registry._delete_intent_locked
    def replace_then_delete(runtime, session_ref, container_ref, expected_intent_id) -> bool:
        path.write_text(json.dumps({**PAYLOAD, "token": "new", "intent_id": "new"}), encoding="utf-8")
        return original(runtime, session_ref, container_ref, expected_intent_id)
    monkeypatch.setattr(registry, "_delete_intent_locked", replace_then_delete)
    assert registry.close(**{key: closed[key] for key in ("runtime", "session_ref", "container_ref", "intent_id")})
    assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "new"

def test_recovery_never_retries_rollback_inflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import claude_wake
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], delivery_id="delivery", recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "accepted")
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    calls = []
    relay = SimpleNamespace(pending_candidate=lambda **kwargs: calls.append(kwargs) or {"delivery_id": "delivery", "state": "pending"})
    scheduled = []
    monkeypatch.setattr(claude_wake, "schedule_claude_relay_wake", lambda result, scope, *, registry, **_kwargs: scheduled.append((result, scope)) or None)
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert scheduled == []
    wall[0] = 1.0
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert scheduled == [] and calls == []

def test_expired_claim_recovery_does_not_release_inflight(

    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta, timezone
    import threading

    from app import claude_wake
    from core.relay import RelayService
    import storage.sqlite_relay as sqlite_relay

    clock = [datetime(2030, 9, 2, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="recover claimed", **scope,
    )
    claimed = relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)["deliveries"][0]
    assert claimed["state"] == "claimed"
    before = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]

    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        delivery_id=claimed["delivery_id"], recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "accepted",
    )
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])

    clock[0] += timedelta(seconds=61)
    assert relay.pending_candidate(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        delivery_id=claimed["delivery_id"], **scope,
    ) == {
        "delivery_id": claimed["delivery_id"],
        "state": "pending",
        "recipient_endpoint_id": claimed["recipient_endpoint_id"],
    }
    retried = threading.Event()
    transport_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        claude_wake,
        "claude_wake_transport",
        lambda socket_path, token: transport_calls.append((socket_path, token)) or retried.set() or True,
    )
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert not retried.is_set()
    wall[0] = 1.0
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert not retried.is_set()
    assert transport_calls == []

    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert after["state"] == "claimed" and after["delivered_at"] is None
    assert tuple(after[key] for key in ("claim_token", "receipt", "claimed_at", "lease_expires_at", "attempts")) == tuple(
        before[key] for key in ("claim_token", "receipt", "claimed_at", "lease_expires_at", "attempts")
    )

def test_reconciler_does_not_retry_uncertain_native_write(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from app import claude_wake
    from app.claude_wake import ClaudeWakeReconciler
    from core.relay import RelayService

    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    sent = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="retry until accepted", **scope,
    )

    observed: list[tuple[str, object, object, int]] = []
    accepted = threading.Event()

    def transport(_socket_path: str, _token: str) -> str:
        delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        observed.append((delivery["state"], delivery["claim_token"], delivery["receipt"], delivery["attempts"]))
        if len(observed) == 4:
            accepted.set()
            return "accepted"
        return "retryable"

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    reconciler = ClaudeWakeReconciler(registry, relay, interval_seconds=0.01)
    reconciler.start()
    try:
        assert not accepted.wait(timeout=0.1), observed
    finally:
        reconciler.stop()
    assert observed == [("pending", None, None, 0)]
    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_recovery_does_not_rearm_inflight_while_native_worker_is_active(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from app import claude_wake
    from core.relay import RelayService

    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    sent = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="active worker", **scope,
    )
    delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    result = {
        "recipient": "claude-code:" + PAYLOAD["session_ref"],
        "deliveries": [{
            "delivery_id": delivery["delivery_id"], "state": "pending",
            "recipient_runtime": "claude-code", "recipient_session_ref": PAYLOAD["session_ref"],
            "recipient_endpoint_id": delivery["recipient_endpoint_id"],
        }],
    }
    started = threading.Event()
    release = threading.Event()
    retried = threading.Event()
    transport_calls: list[tuple[str, str]] = []

    def transport(socket_path: str, token: str) -> str:
        transport_calls.append((socket_path, token))
        if len(transport_calls) == 1:
            started.set()
            assert release.wait(timeout=1)
        else:
            retried.set()
        return "accepted"

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    worker = claude_wake.schedule_claude_relay_wake(result, scope, registry=registry)
    assert worker is not None and started.wait(timeout=1)
    wall[0] = 102.0
    try:
        claude_wake.recover_claude_relay_wakes(registry, relay)
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        candidate = next(iter(registry.recovery_candidates()))
        assert candidate["state"] == "wake_inflight" and candidate["delivery_id"] == delivery["delivery_id"]
        pending = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert pending["state"] == "pending"
        assert tuple(pending[key] for key in ("claim_token", "receipt", "attempts")) == (None, None, 0)
    finally:
        release.set()
        worker.join(timeout=1)
    assert not worker.is_alive()

    claude_wake.recover_claude_relay_wakes(registry, relay)
    assert not retried.is_set()
    assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
    pending = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert pending["state"] == "pending"
    assert tuple(pending[key] for key in ("claim_token", "receipt", "attempts")) == (None, None, 0)


@pytest.mark.parametrize("terminal_state", ("claimed", "delivered", "expired"))
def test_recovery_terminal_reads_never_release_or_reschedule_inflight(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal_state: str,
) -> None:
    from datetime import datetime, timedelta, timezone

    from app import claude_wake
    import core.relay as relay_module
    from core.relay import RelayService
    import storage.sqlite_relay as sqlite_relay

    clock = [datetime(2030, 9, 2, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = clock[0] if value is None else value
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    monkeypatch.setattr(relay_module, "datetime", SimpleNamespace(now=lambda _tz: clock[0]))
    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="non-pending recovery",
        expires_in_seconds=60, **scope,
    )

    if terminal_state != "expired":
        claimed = relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)["deliveries"][0]
        if terminal_state == "delivered":
            relay.acknowledge(delivery_id=claimed["delivery_id"], claim_token=claimed["claim_token"], **scope)
    else:
        clock[0] += timedelta(seconds=61)

    def status(message_id: str) -> dict:
        response = client.get(f"/relay/messages/{message_id}", params=scope)
        assert response.status_code == 200
        return response.json()["deliveries"][0]

    before = status(sent["message_id"])
    assert before["state"] == terminal_state

    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        delivery_id=before["delivery_id"], recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: "accepted",
    )
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])

    transport_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        claude_wake,
        "claude_wake_transport",
        lambda socket_path, token: transport_calls.append((socket_path, token)) or "accepted",
    )
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert transport_calls == []
    candidates = restarted.recovery_candidates()
    assert len(candidates) == 1 and candidates[0]["state"] == "wake_inflight"
    assert candidates[0]["delivery_id"] == before["delivery_id"]
    assert status(sent["message_id"]) == before

    fresh = relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"], payload="fresh recovery", **scope,
    )
    scheduled = []
    monkeypatch.setattr(
        claude_wake,
        "schedule_claude_relay_wake",
        lambda result, wake_scope, *, registry, **_kwargs: scheduled.append(
            (result, wake_scope, registry)
        ),
    )
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert scheduled == []
    assert transport_calls == []
    assert status(fresh["message_id"])["state"] == "pending"


def test_online_close_removes_only_exact_durable_capability_and_intent(tmp_path: Path) -> None:
    from tests.test_claude_wake_registration import _client

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    other = {**PAYLOAD, "session_ref": "other"}
    assert _register(registry, tmp_path, PAYLOAD, "open")
    assert _register(registry, tmp_path, other, "other-open")
    closed = {
        "runtime": "claude-code", "session_ref": PAYLOAD["session_ref"],
        "container_ref": PAYLOAD["container_ref"],
        "intent_id": "closed", "closed": True,
    }
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    http = _client(registry)
    close_request = {key: closed[key] for key in ("runtime", "session_ref", "container_ref", "intent_id")}
    mismatch = http.post("/internal/claude-wake/close", json={**close_request, "intent_id": "stale"})
    assert mismatch.status_code == 400
    assert path.exists()
    assert {candidate["session_ref"] for candidate in registry.recovery_candidates()} == {PAYLOAD["session_ref"], "other"}

    assert http.post("/internal/claude-wake/close", json=close_request).status_code == 204
    assert not path.exists()
    assert [candidate["session_ref"] for candidate in registry.recovery_candidates()] == ["other"]


def test_session_end_outage_preserves_newer_registration_intent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from tests.test_claude_code_integration import _load_claude_hook

    state_dir = tmp_path / "wake"
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(state_dir))
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    assert _register(registry, state_dir, PAYLOAD, "open")
    session_end = _load_claude_hook("session_end", monkeypatch)
    common = sys.modules["common"]
    monkeypatch.setattr(session_end, "read_hook_input", lambda: {"session_id": PAYLOAD["session_ref"], "cwd": str(tmp_path)})
    monkeypatch.setattr(session_end, "resolve_container_ref", lambda *_: PAYLOAD["container_ref"])
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())))
    session_end.main()
    closed_path = _intent_path(state_dir, PAYLOAD["session_ref"])
    closed = json.loads(closed_path.read_text(encoding="utf-8"))
    assert closed["closed"] is True

    restarted = ClaudeWakeRegistry(state_dir=state_dir)
    newer = {**PAYLOAD, "token": "new-token"}
    original_delete = restarted._delete_intent_locked

    def replace_closed_intent(runtime, session_ref, container_ref, expected_intent_id) -> bool:
        _write_intent(state_dir, newer, "newer")
        return original_delete(runtime, session_ref, container_ref, expected_intent_id)

    monkeypatch.setattr(restarted, "_delete_intent_locked", replace_closed_intent)
    restarted.recover_intents()
    assert restarted.recovery_candidates() == []
    assert json.loads(closed_path.read_text(encoding="utf-8"))["intent_id"] == "newer"


@pytest.mark.parametrize(
    "startup_delay,exhaust_budget", [(0.0, False), (1.2, False), (0.0, True)],
    ids=["normal-startup", "delayed-startup", "admission-refusal"],
)
def test_new_publisher_waits_for_registry_compare_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, startup_delay: float, exhaust_budget: bool,
) -> None:
    state_dir = tmp_path / "wake"
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    old_intent = {**PAYLOAD, "intent_id": "older"}
    newer = {**PAYLOAD, "token": "new-token", "intent_id": "newer", "idle": False}
    _write_intent(state_dir, old_intent, "older")
    (state_dir / "relay-owner.json").write_text(
        json.dumps({"relay_id": "0" * 64}), encoding="utf-8"
    )
    path = _intent_path(state_dir, PAYLOAD["session_ref"])
    before = json.loads(path.read_text(encoding="utf-8"))
    deleting = threading.Event()
    finish_delete = threading.Event()
    result: list[bool] = []
    original_unlink = Path.unlink

    def pause_after_compare(candidate: Path, *args, **kwargs):
        if candidate == path and threading.current_thread().name == "register-old":
            deleting.set()
            finish_delete.wait()
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", pause_after_compare)
    worker = threading.Thread(
        target=lambda: result.append(registry.register(**old_intent)),
        name="register-old",
    )
    worker.start()
    process = None
    try:
        assert deleting.wait(timeout=1)
        hook_dir = Path(__file__).parents[1] / "integrations" / "claude-code" / "hooks"
        script = """
import json, os, sys, time
from pathlib import Path
time.sleep(float(sys.argv[6]))
sys.path.insert(0, sys.argv[1])
import common
common.CLAUDE_WAKE_DIR = Path(sys.argv[2])
common.CLAUDE_WAKE_INTENTS_DIR = Path(sys.argv[3])
common.PALLIUM_PORT = 65534
common._WAKE_BINDING = {"port": 65534, "relay_id": "0" * 64, "wake_dir": str(common.CLAUDE_WAKE_DIR)}
exhaust_budget = sys.argv[7] == "True"
evidence = {"replace_calls": 0}
now = [0.0]
if exhaust_budget:
    from types import SimpleNamespace
    common.time = SimpleNamespace(**vars(time))
    common.time.monotonic = lambda: now[0]
    acquire = common._acquire_file_lock
    def observe_acquire(path, budget):
        result = acquire(path, budget)
        evidence.update(budget=budget, refused=result is None, clock=now[0])
        return result
    common._acquire_file_lock = observe_acquire
    common.os = SimpleNamespace(**vars(os))
    replace = common.os.replace
    def observe_replace(*args, **kwargs):
        evidence["replace_calls"] += 1
        return replace(*args, **kwargs)
    common.os.replace = observe_replace
else:
    from itertools import count
    from types import SimpleNamespace
    # Qualify compare-delete ordering independently of parent/child scheduling latency.
    common.time = SimpleNamespace(**vars(time))
    common.time.monotonic = count(step=0.001).__next__

def observe_contention(error):
    if exhaust_budget:
        evidence["errno"] = error.errno
        now[0] = 0.101

if os.name == "nt":
    import msvcrt
    native_lock = msvcrt.locking
    reported = [False]
    def observe_lock(fd, mode, count):
        try:
            return native_lock(fd, mode, count)
        except OSError as error:
            if mode == msvcrt.LK_NBLCK and not reported[0]:
                reported[0] = True
                observe_contention(error)
                Path(sys.argv[5]).write_text("contended", encoding="utf-8")
                print("contended", flush=True)
            raise
    msvcrt.locking = observe_lock
else:
    import fcntl
    native_lock = fcntl.flock
    reported = [False]
    def observe_lock(fd, operation):
        try:
            return native_lock(fd, operation)
        except OSError as error:
            if operation & fcntl.LOCK_NB and not reported[0]:
                reported[0] = True
                observe_contention(error)
                Path(sys.argv[5]).write_text("contended", encoding="utf-8")
                print("contended", flush=True)
            raise
    fcntl.flock = observe_lock
print("publishing", flush=True)
print(common._write_wake_intent(json.loads(sys.argv[4])), flush=True)
if exhaust_budget:
    print(json.dumps(evidence), file=sys.stderr, flush=True)
"""
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(hook_dir), str(state_dir),
             str(state_dir / "intents"), json.dumps(newer),
             str(tmp_path / "contended"), str(startup_delay), str(exhaust_budget)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        )
        marker_deadline = time.monotonic() + 5
        marker = tmp_path / "contended"
        while not marker.exists() and process.poll() is None and time.monotonic() < marker_deadline:
            time.sleep(0.01)
        assert marker.exists(), "child did not observe real OS lock contention before timeout"
        if exhaust_budget:
            import errno

            output, errors = process.communicate(timeout=3)
            assert process.returncode == 0, errors
            assert output.splitlines() == ["publishing", "contended", "False"], errors
            evidence = json.loads(errors)
            assert evidence["errno"] in (errno.EACCES, errno.EAGAIN), evidence
            assert evidence["budget"] == 0.1 and evidence["clock"] == 0.101, evidence
            assert evidence["refused"] is True and evidence["replace_calls"] == 0, evidence
            assert worker.is_alive() and not finish_delete.is_set()
            assert json.loads(path.read_text(encoding="utf-8")) == before
            finish_delete.set()
            worker.join(timeout=2)
            assert not worker.is_alive() and result == [True]
            assert not path.exists()
            return
        finish_delete.set()
        output, errors = process.communicate(timeout=3)
        worker.join(timeout=2)
        assert not worker.is_alive(), "registry worker did not finish after deletion was released"
        assert process.returncode == 0, errors
        assert output.splitlines() == ["publishing", "contended", "True"]
        assert result == [True]

        assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "newer"
        restarted = ClaudeWakeRegistry(state_dir=state_dir)
        restarted.recover_intents()
        recovered = restarted._registrations[(PAYLOAD["runtime"], PAYLOAD["session_ref"], PAYLOAD["container_ref"])]
        assert recovered.token == "new-token" and recovered.state == "busy"
    finally:
        finish_delete.set()
        try:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        finally:
            worker.join(timeout=2)
            assert not worker.is_alive(), "registry worker leaked after bounded cleanup"


@pytest.mark.parametrize("portal_start_delay", [0.0, 0.6], ids=["normal-portal", "delayed-portal"])
def test_crashed_intent_lock_owner_allows_hook_publication_and_http_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    portal_start_delay: float,
) -> None:
    import contextlib
    import time
    from types import FunctionType

    import anyio.from_thread
    import fastapi.routing
    import core.claude_wake as wake
    from fastapi import FastAPI
    from tests.test_claude_code_integration import _load_claude_hook
    from tests.test_claude_wake_registration import _client

    timing_origin = None
    timing_samples = []

    @contextlib.contextmanager
    def measure(label):
        origin = timing_origin
        if origin is None:
            yield
            return
        try:
            wall_start, cpu_start = time.monotonic(), time.thread_time()
        except Exception:
            yield
            return
        try:
            yield
        finally:
            try:
                wall_end, cpu_end = time.monotonic(), time.thread_time()
                if len(timing_samples) < 32:
                    timing_samples.append({
                        "phase": label,
                        "start_ms": round((wall_start - origin) * 1000, 3),
                        "end_ms": round((wall_end - origin) * 1000, 3),
                        "wall_ms": round((wall_end - wall_start) * 1000, 3),
                        "cpu_ms": round((cpu_end - cpu_start) * 1000, 3),
                    })
            except Exception:
                pass  # Diagnostics must not replace an operation's result or exception.

    def timed_sync(label, original):
        def wrapped(*args, **kwargs):
            with measure(label):
                return original(*args, **kwargs)
        return wrapped

    original_asgi = FastAPI.__call__

    async def timed_asgi(app, scope, receive, send):
        if scope["type"] != "http":
            return await original_asgi(app, scope, receive, send)

        async def timed_send(message):
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                with measure("response_send"):
                    return await send(message)
            return await send(message)

        with measure("asgi"):
            return await original_asgi(app, scope, receive, timed_send)

    monkeypatch.setattr(FastAPI, "__call__", timed_asgi)
    monkeypatch.setattr(wake, "_acquire_intent_lock", timed_sync("intent_lock", wake._acquire_intent_lock))
    included_router = vars(fastapi.routing).get("_IncludedRouter")
    router_setup = vars(included_router).get("effective_candidates") if isinstance(included_router, type) else None
    router_setup_probe = isinstance(router_setup, FunctionType)
    if router_setup_probe:
        monkeypatch.setattr(included_router, "effective_candidates", timed_sync("router_setup", router_setup))

    portal_starts = 0
    original_start_portal = anyio.from_thread.start_blocking_portal

    @contextlib.contextmanager
    def start_portal_with_delay(**kwargs):
        nonlocal portal_starts
        portal_starts += 1
        if portal_start_delay:
            time.sleep(portal_start_delay)
        with original_start_portal(**kwargs) as portal:
            yield portal

    monkeypatch.setattr(anyio.from_thread, "start_blocking_portal", start_portal_with_delay)

    state_dir = tmp_path / "wake"
    old = {**PAYLOAD, "intent_id": "old"}
    _write_intent(state_dir, old, "old")
    path = _intent_path(state_dir, PAYLOAD["session_ref"])
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    monkeypatch.setattr(registry, "register", timed_sync("registry", registry.register))
    script = (
        "import sys; from pathlib import Path; "
        "from core.claude_wake import _acquire_intent_lock; "
        "lock=_acquire_intent_lock(Path(sys.argv[1])); "
        "print('locked' if lock else 'failed',flush=True); "
        "sys.stdin.read()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline() == "locked\n"
        monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(state_dir))
        common = _load_claude_hook("common", monkeypatch)
        common.CLAUDE_WAKE_DIR = state_dir
        common.CLAUDE_WAKE_INTENTS_DIR = state_dir / "intents"
        monkeypatch.setattr(common, "_acquire_file_lock", timed_sync("hook_lock", common._acquire_file_lock))
        monkeypatch.setattr(common, "register_claude_wake", timed_sync("hook", common.register_claude_wake))
        with _client(registry) as http:
            monkeypatch.setattr(http, "post", timed_sync("http", http.post))
            started = time.monotonic()
            timing_origin = started
            rejected = http.post("/internal/claude-wake/register", json=old)
            timing_origin = None
            assert rejected.status_code == 409
            assert time.monotonic() - started < 0.5, json.dumps({
                "router_setup_probe": int(router_setup_probe), "timings": timing_samples,
            })
            assert registry._registrations == {} and not registry._canonical.exists()
            assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "old"

            monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", PAYLOAD["socket_path"])
            monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "new-token")
            http_requests: list[object] = []

            def open_request(request, **_kwargs):
                http_requests.append(request)
                response = http.post(
                    "/internal/claude-wake/register", json=json.loads(request.data),
                )
                if response.status_code != 204:
                    raise OSError("local registration rejected")
                return contextlib.nullcontext(response)

            monkeypatch.setattr(
                common.urllib.request, "build_opener",
                lambda *_args: SimpleNamespace(open=open_request),
            )
            with monkeypatch.context() as failure:
                failure.setattr(
                    common, "open",
                    lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("lock open failed")),
                    raising=False,
                )
                assert not common.register_claude_wake(
                    PAYLOAD["session_ref"], PAYLOAD["container_ref"], idle=True,
                )
            assert http_requests == []
            assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "old"

            timing_samples.clear()
            started = time.monotonic()
            timing_origin = started
            assert not common.register_claude_wake(
                PAYLOAD["session_ref"], PAYLOAD["container_ref"], idle=True,
            )
            timing_origin = None
            assert time.monotonic() - started < 0.5, json.dumps({
                "router_setup_probe": int(router_setup_probe), "timings": timing_samples,
            })
            assert http_requests == []
            assert registry._registrations == {} and not registry._canonical.exists()
            assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "old"

            process.kill()
            process.wait(timeout=1)
            registry.recover_intents()
            assert registry._registrations[(PAYLOAD["runtime"], PAYLOAD["session_ref"], PAYLOAD["container_ref"])].token == PAYLOAD["token"]

            assert common.register_claude_wake(
                PAYLOAD["session_ref"], PAYLOAD["container_ref"], idle=True,
            )
            assert len(http_requests) == 1
            assert not path.exists()
            recovered = ClaudeWakeRegistry(state_dir=state_dir)
            assert recovered._registrations[(PAYLOAD["runtime"], PAYLOAD["session_ref"], PAYLOAD["container_ref"])].token == "new-token"
            assert portal_starts == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)


def test_distinct_intent_scopes_use_independent_lock_files(tmp_path: Path) -> None:
    from core.claude_wake import _acquire_intent_lock, _release_intent_lock

    first = _intent_path(tmp_path, PAYLOAD["session_ref"], PAYLOAD["container_ref"])
    second = _intent_path(tmp_path, PAYLOAD["session_ref"], "git:example/other")
    first_lock = _acquire_intent_lock(first)
    second_lock = None
    try:
        assert first_lock is not None
        assert first.with_suffix(".lock") != second.with_suffix(".lock")
        second_lock = _acquire_intent_lock(second)
        assert second_lock is not None
    finally:
        if second_lock is not None:
            _release_intent_lock(second_lock)
        if first_lock is not None:
            _release_intent_lock(first_lock)

@pytest.mark.parametrize(("present", "accepted"), [(False, True), (True, False)])
def test_posix_capacity_reclaims_only_provably_absent_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, present: bool, accepted: bool) -> None:
    import core.claude_wake as wake

    monkeypatch.setattr(wake, "MAX_REGISTRATIONS", 1)
    state_dir = tmp_path / "wake"
    endpoint = tmp_path / "endpoint.sock"
    if present:
        endpoint.write_text("present", encoding="utf-8")
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    assert _register(registry, state_dir, {**PAYLOAD, "socket_path": str(endpoint)}, "old")
    monkeypatch.setattr(wake.os, "name", "posix")
    monkeypatch.setattr(registry, "probe", lambda *_args, **_kwargs: pytest.fail("capacity cleanup must not admit a turn"))
    assert _register(registry, state_dir, {**PAYLOAD, "session_ref": "new"}, "new") is accepted
    assert [candidate["session_ref"] for candidate in registry.recovery_candidates()] == (["new"] if accepted else [PAYLOAD["session_ref"]])


@pytest.mark.parametrize(("code", "accepted"), [(2, True), (231, False), (121, False)])
def test_windows_capacity_reclaims_only_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, accepted: bool) -> None:
    import sys
    import core.claude_wake as wake

    class PipeError(Exception):
        def __init__(self, winerror):
            self.winerror = winerror

    monkeypatch.setattr(wake, "MAX_REGISTRATIONS", 1)
    state_dir = tmp_path / "wake"
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    assert _register(registry, state_dir, {**PAYLOAD, "socket_path": r"\\.\pipe\old"}, "old")
    monkeypatch.setattr(wake.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=PipeError))
    monkeypatch.setitem(sys.modules, "winerror", SimpleNamespace(ERROR_FILE_NOT_FOUND=2))
    monkeypatch.setitem(sys.modules, "win32pipe", SimpleNamespace(WaitNamedPipe=lambda *_: (_ for _ in ()).throw(PipeError(code))))
    monkeypatch.setattr(registry, "probe", lambda *_args, **_kwargs: pytest.fail("capacity cleanup must not admit a turn"))
    assert _register(registry, state_dir, {**PAYLOAD, "session_ref": "new", "socket_path": r"\\.\pipe\new"}, "new") is accepted
    assert [candidate["session_ref"] for candidate in registry.recovery_candidates()] == (["new"] if accepted else [PAYLOAD["session_ref"]])


def test_unreachable_feedback_requires_durable_registry_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    registry = ClaudeWakeRegistry(state_dir=tmp_path / "success")
    root = tmp_path / "success"
    assert _register(registry, root, PAYLOAD, "success")
    assert not registry.probe(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: "unreachable", on_unreachable=lambda: events.append("unreachable"),
    )
    assert events == ["unreachable"]

    retry_root = tmp_path / "retry"
    retry_registry = ClaudeWakeRegistry(state_dir=retry_root)
    assert _register(retry_registry, retry_root, PAYLOAD, "retry")
    assert not retry_registry.probe(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: "retryable", on_unreachable=lambda: events.append("retryable"),
    )
    assert events == ["unreachable"]

    failed_root = tmp_path / "failed"
    failed_registry = ClaudeWakeRegistry(state_dir=failed_root)
    assert _register(failed_registry, failed_root, PAYLOAD, "failed")
    original_write = failed_registry._write_canonical_locked
    writes = 0

    def fail_unreachable_persist(state: object) -> bool:
        nonlocal writes
        writes += 1
        return original_write(state) if writes == 1 else False

    monkeypatch.setattr(failed_registry, "_write_canonical_locked", fail_unreachable_persist)
    assert not failed_registry.probe(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: "unreachable", on_unreachable=lambda: events.append("failed"),
    )
    assert events == ["unreachable"]
    assert failed_registry.recovery_candidates() == []



def test_restart_recovery_persists_unreachable_relay_health(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from app import claude_wake
    from core.relay import RelayService

    relay = RelayService(client.app.state.pallium_service._storage)
    scope = {"container_ref": PAYLOAD["container_ref"]}
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "restart-health")
    sent = relay.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient=f"claude-code:{PAYLOAD['session_ref']}",
        payload="persist health after restart",
        **scope,
    )
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    persisted = threading.Event()

    class RelayWitness:
        def pending_candidate(self, **kwargs: object) -> dict | None:
            return relay.pending_candidate(**kwargs)

        def mark_unreachable(self, **kwargs: object) -> bool:
            changed = relay.mark_unreachable(**kwargs)
            persisted.set()
            return changed

    monkeypatch.setattr(claude_wake, "claude_wake_transport", lambda *_: "unreachable")
    claude_wake.recover_claude_relay_wakes(restarted, RelayWitness())
    assert persisted.wait(timeout=1)
    delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert delivery["state"] == "pending"
    assert delivery["destination_health"] == "unreachable"
    assert restarted.recovery_candidates() == []

def test_recovery_health_callbacks_bind_each_exact_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    from app import claude_wake

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    second = {**PAYLOAD, "session_ref": "session-β"}
    assert _register(registry, tmp_path, PAYLOAD, "first")
    assert _register(registry, tmp_path, second, "second")
    callbacks = []
    marked: list[tuple[str, str]] = []

    def schedule(_result: object, _scope: object, *, registry: object, on_unreachable, **_kwargs) -> None:
        callbacks.append(on_unreachable)

    relay = SimpleNamespace(
        pending_candidate=lambda **kwargs: {
            "delivery_id": "delivery-" + str(kwargs["session_ref"]),
            "recipient_endpoint_id": (
                "relay-session-"
                + ("b" if kwargs["session_ref"] == second["session_ref"] else "a") * 32
            ),
            "state": "pending",
        },
        mark_unreachable=lambda **kwargs: marked.append((
            str(kwargs["session_ref"]), str(kwargs["container_ref"])
        )) or True,
    )
    monkeypatch.setattr(claude_wake, "schedule_claude_relay_wake", schedule)
    claude_wake.recover_claude_relay_wakes(registry, relay)
    assert len(callbacks) == 2
    for callback in callbacks:
        callback(datetime.now(timezone.utc))
    assert marked == [(PAYLOAD["session_ref"], PAYLOAD["container_ref"]),
                      (second["session_ref"], second["container_ref"])]


def test_expired_claim_recovery_rechecks_and_isolates_candidate_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import dependencies

    def candidate(delivery_id: str) -> dict:
        return {
            "delivery_id": delivery_id,
            "state": "pending",
            "recipient_endpoint_id": "relay-session-" + "a" * 32,
            "recipient_runtime": "codex",
            "recipient_session_ref": "target",
            "container_ref": "git:example/repo",
        }

    broken, stale, current = (candidate(name) for name in ("broken", "stale", "current"))

    class Relay:
        def wake_candidates(self, *, delivery_id=None, include_coalesced=False):
            if delivery_id is None:
                assert include_coalesced is True
                return [broken, stale, current]
            if delivery_id == "broken":
                raise RuntimeError("candidate changed during recheck")
            return [current] if delivery_id == "current" else []

    dispatched: list[tuple[dict, dict]] = []
    monkeypatch.setattr(
        dependencies,
        "dispatch_relay_wake",
        lambda result, scope, **_kwargs: dispatched.append((result, scope)),
    )

    dependencies.recover_expired_relay_wakes(Relay(), ClaudeWakeRegistry())

    assert [item[0]["deliveries"][0]["delivery_id"] for item in dispatched] == ["current"]
    assert dispatched[0][1] == {
        "container_ref": current["container_ref"],
    }


def test_relay_claim_recovery_is_startup_immediate_rate_limited_and_resilient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import claude_wake

    clock = [0.0]
    calls: list[float] = []
    called = threading.Event()

    def recover() -> None:
        calls.append(clock[0])
        called.set()
        if len(calls) == 1:
            raise RuntimeError("one failed sweep must not stop the loop")

    monkeypatch.setattr(
        claude_wake,
        "recover_claude_relay_wakes",
        lambda *_: (_ for _ in ()).throw(RuntimeError("Claude capability failure")),
    )
    reconciler = claude_wake.ClaudeWakeReconciler(
        ClaudeWakeRegistry(),
        SimpleNamespace(),
        claim_recovery=recover,
        interval_seconds=0.01,
        claim_interval_seconds=30.0,
        clock=lambda: clock[0],
    )
    reconciler.start()
    try:
        assert called.wait(timeout=0.5)
        called.clear()
        reconciler.signal()
        assert not called.wait(timeout=0.05)
        assert calls == [0.0]

        clock[0] = 30.0
        reconciler.signal()
        assert called.wait(timeout=0.5)
        assert calls == [0.0, 30.0]
    finally:
        reconciler.stop()

    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_legacy_inflight_without_endpoint_fences_duplicate_session_across_scopes(
    tmp_path: Path,
) -> None:
    first = {**PAYLOAD, "session_ref": "duplicate", "container_ref": "container-a", "socket_path": "socket-a", "token": "token-a"}
    second = {**PAYLOAD, "session_ref": "duplicate", "container_ref": "container-b", "socket_path": "socket-b", "token": "token-b"}
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, first, "first")
    assert _register(registry, tmp_path, second, "second")

    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    assert {
        (item["session_ref"], item["container_ref"])
        for item in restarted.recovery_candidates()
    } == {
        ("duplicate", "container-a"),
        ("duplicate", "container-b"),
    }
    observed: list[tuple[str, str]] = []
    assert restarted.probe(
        runtime="claude-code", session_ref="duplicate",
        container_ref=first["container_ref"],
        transport=lambda socket, token: observed.append((socket, token)) or "accepted",
    )
    assert not restarted.probe(
        runtime="claude-code", session_ref="duplicate",
        container_ref=second["container_ref"],
        transport=lambda *_: pytest.fail("legacy fence must exclude duplicate session"),
    )
    assert observed == [("socket-a", "token-a")]

def test_legacy_intent_fences_existing_idle_capability_on_upgrade(
    tmp_path: Path,
) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    legacy_path = tmp_path / "intents" / (
        hashlib.sha256(PAYLOAD["session_ref"].encode("utf-8")).hexdigest() + ".json"
    )
    legacy_path.write_text(
        json.dumps({
            "runtime": PAYLOAD["runtime"],
            "session_ref": PAYLOAD["session_ref"],
            "container_ref": PAYLOAD["container_ref"],
            "intent_id": "legacy-close",
            "closed": True,
        }),
        encoding="utf-8",
    )

    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    restarted.recover_intents()
    assert restarted.recovery_candidates() == []
    assert not restarted.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: pytest.fail("legacy close must fence wake"),
    )
    assert not legacy_path.exists()

def test_legacy_intent_fences_memory_when_canonical_removal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    legacy_path = tmp_path / "intents" / (
        hashlib.sha256(PAYLOAD["session_ref"].encode("utf-8")).hexdigest() + ".json"
    )
    legacy_path.write_text(
        json.dumps({
            "runtime": PAYLOAD["runtime"],
            "session_ref": PAYLOAD["session_ref"],
            "container_ref": PAYLOAD["container_ref"],
            "intent_id": "legacy-close",
            "closed": True,
        }),
        encoding="utf-8",
    )
    original_write = registry._write_canonical_locked
    attempts = 0

    def fail_once(registrations) -> bool:
        nonlocal attempts
        attempts += 1
        return False if attempts == 1 else original_write(registrations)

    monkeypatch.setattr(registry, "_write_canonical_locked", fail_once)
    monkeypatch.setattr(registry, "_quarantine_or_mark_unusable_locked", lambda: False)

    registry.recover_intents()

    assert registry.durability_degraded
    assert legacy_path.exists()
    assert not registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: pytest.fail("failed persistence must still fence memory"),
    )

    registry.recover_intents()
    assert not legacy_path.exists()
    assert ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates() == []


def test_corrupt_scoped_intent_cannot_suppress_valid_legacy_fence(
    tmp_path: Path,
) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    legacy_path = tmp_path / "intents" / (
        hashlib.sha256(PAYLOAD["session_ref"].encode("utf-8")).hexdigest() + ".json"
    )
    legacy_path.write_text(
        json.dumps({
            "runtime": PAYLOAD["runtime"],
            "session_ref": PAYLOAD["session_ref"],
            "container_ref": PAYLOAD["container_ref"],
            "intent_id": "legacy-close",
            "closed": True,
        }),
        encoding="utf-8",
    )
    _intent_path(tmp_path, PAYLOAD["session_ref"]).write_text("{", encoding="utf-8")

    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    restarted.recover_intents()

    assert restarted.recovery_candidates() == []
    assert not legacy_path.exists()
    assert not restarted.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: pytest.fail("corrupt scoped intent must not suppress fence"),
    )


@pytest.mark.parametrize("outcome", ("accepted", "uncertain"))
def test_durable_attempt_fences_same_endpoint_after_scope_move(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    from app import claude_wake
    from core.relay import RelayService

    relay = RelayService(client.app.state.pallium_service._storage)
    source = {"container_ref": "git:example/source"}
    old = {"container_ref": "git:example/old"}
    new = {"container_ref": "git:example/new"}
    relay.turn(runtime="codex", session_ref="sender", **source)
    registered = relay.turn(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"], **old,
    )["session"]
    endpoint_id = registered["endpoint_id"]
    old_payload = {**PAYLOAD, **old}
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, old_payload, "old")
    sent = relay.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient=endpoint_id,
        payload="scope movement fence",
        **source,
    )
    delivery = sent["deliveries"][0]
    result = {
        "recipient": "claude-code:" + PAYLOAD["session_ref"],
        "deliveries": [{
            "delivery_id": delivery["delivery_id"],
            "state": "pending",
            "recipient_endpoint_id": endpoint_id,
            "recipient_runtime": "claude-code",
            "recipient_session_ref": PAYLOAD["session_ref"],
            "recipient_container_ref": old["container_ref"],
        }],
    }
    native_writes = []

    def transport(socket_path: str, token: str) -> ActivationAttemptResult:
        native_writes.append((socket_path, token))
        evidence = (
            ("submission_attempted", "transport_accepted")
            if outcome == "accepted" else ("submission_attempted",)
        )
        return ActivationAttemptResult(outcome, "controlled", evidence)

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    worker = claude_wake.schedule_claude_relay_wake(
        result, old, registry=registry, relay_service=relay,
    )
    assert worker is not None
    worker.join(timeout=1)
    assert not worker.is_alive() and len(native_writes) == 1
    retained = registry.recovery_candidates()
    assert len(retained) == 1
    assert retained[0]["state"] == "wake_inflight"
    assert retained[0]["delivery_id"] == delivery["delivery_id"]

    moved = relay.turn(
        runtime="claude-code",
        session_ref=PAYLOAD["session_ref"],
        max_chars=1,
        max_messages=1,
        previous_container_ref=old["container_ref"],
        previous_endpoint_id=endpoint_id,
        previous_scope_generation=0,
        **new,
    )
    assert moved["session"]["endpoint_id"] == endpoint_id
    assert moved["deliveries"] == []
    new_payload = {**PAYLOAD, **new}
    assert _register(registry, tmp_path, new_payload, "new")

    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    retry_result = {
        "recipient": "claude-code:" + PAYLOAD["session_ref"],
        "deliveries": [{
            **result["deliveries"][0],
            "recipient_container_ref": new["container_ref"],
        }],
    }
    retry = claude_wake.schedule_claude_relay_wake(
        retry_result, new, registry=restarted,
    )
    assert retry is not None
    retry.join(timeout=1)
    assert not retry.is_alive()
    assert len(native_writes) == 1
    retained = [
        item for item in restarted.recovery_candidates()
        if item["state"] == "wake_inflight"
    ]
    assert len(retained) == 1
    assert retained[0]["delivery_id"] == delivery["delivery_id"]
    stored = relay.message_status(
        message_id=sent["message_id"], **source,
    )["deliveries"][0]
    assert stored["delivery_id"] == delivery["delivery_id"]
    assert stored["recipient_endpoint_id"] == endpoint_id
    assert stored["recipient_container_ref"] == old["container_ref"]
    assert stored["state"] == "pending"
    assert restarted.release_delivery(delivery["delivery_id"])
    assert all(
        item["state"] != "wake_inflight"
        for item in restarted.recovery_candidates()
    )
