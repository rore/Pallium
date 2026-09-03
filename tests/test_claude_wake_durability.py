from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.claude_wake import ClaudeWakeRegistry


PAYLOAD = {
    "runtime": "claude-code",
    "session_ref": "session-α",
    "container_ref": "git:example/repo",
    "actor_ref": "local",
    "socket_path": "/missing/claude.sock",
    "token": "test-token",
    "idle": True,
}


def _intent_path(root: Path, session_ref: str) -> Path:
    return root / "intents" / (hashlib.sha256(session_ref.encode("utf-8")).hexdigest() + ".json")


def _write_intent(root: Path, payload: dict, intent_id: str) -> None:
    path = _intent_path(root, payload["session_ref"])
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
    assert restarted.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=lambda _path, token: observed.append(token) or True)
    assert observed == ["new-token"]


def test_startup_recovers_pre_http_write_ahead_intent_without_relay_mutation(tmp_path: Path) -> None:
    _write_intent(tmp_path, PAYLOAD, "before-http")
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    registry.recover_intents()
    observed: list[bool] = []
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=lambda *_: observed.append(True) or True)
    assert observed == [True]


def test_busy_persistence_failure_fences_stale_idle_across_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    assert registry.mark_busy(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"])
    assert (tmp_path / "store-unusable").exists() or (tmp_path / "capabilities.unusable").exists()
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    assert restarted.recovery_candidates() == []
    assert not restarted.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=lambda *_: pytest.fail("stale idle must not rehydrate"))


def test_capacity_keeps_live_endpoint_without_admitting_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.claude_wake as wake

    monkeypatch.setattr(wake, "MAX_REGISTRATIONS", 2)
    live = tmp_path / "live.sock"
    live.write_text("not-probed", encoding="utf-8")
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, {**PAYLOAD, "session_ref": "live", "socket_path": str(live)}, "live")
    assert _register(registry, tmp_path, {**PAYLOAD, "session_ref": "other"}, "other")
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
    assert not common.register_claude_wake("session-hook", "git:example/repo", "local", idle=True)
    saved = json.loads(_intent_path(tmp_path, "session-hook").read_text(encoding="utf-8"))
    assert saved["idle"] is True and isinstance(saved["intent_id"], str)

def test_closed_intent_removes_capability_after_outage(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "open")
    closed = {
        "runtime": "claude-code", "session_ref": PAYLOAD["session_ref"],
        "container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"],
        "intent_id": "close", "closed": True,
    }
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    assert registry.close(**{key: closed[key] for key in ("runtime", "session_ref", "container_ref", "actor_ref", "intent_id")})
    assert ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates() == []


def test_pending_candidate_is_read_only_at_the_real_relay_surface(client) -> None:
    from core.relay import RelayService

    relay = RelayService(client.app.state.pallium_service._storage)
    scope = {"container_ref": "git:example/repo", "actor_ref": "local"}
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref="target", **scope)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="claude-code:target", payload="pending", **scope)
    before = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    candidate = relay.pending_candidate(runtime="claude-code", session_ref="target", **scope)
    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert candidate == {"delivery_id": before["delivery_id"], "state": "pending"}
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
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="claude-code:" + PAYLOAD["session_ref"], payload="pending", **scope)
    before = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    assert not registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        delivery_id=before["delivery_id"], transport=lambda path, token: calls.append((path, token)) or "accepted",
    )
    assert calls == []
    candidates = registry.recovery_candidates()
    assert [(item["state"], item["delivery_id"]) for item in candidates] == [("idle", None)]
    assert [(item["state"], item["delivery_id"]) for item in ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates()] == [("idle", None)]
    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert after["state"] == "pending" and after["claim_token"] is None and after["receipt"] is None and after["attempts"] == 0


@pytest.mark.parametrize("outcome", ["retryable", "terminal"])
def test_post_transport_write_failure_rearms_durable_inflight_for_later_retry(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    from core.relay import RelayService

    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender", recipient="claude-code:" + PAYLOAD["session_ref"], payload="pending", **scope)
    delivery_id = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]["delivery_id"]
    writes = 0
    initial_calls: list[tuple[str, str]] = []
    original_write = registry._write_canonical_locked

    def write_through_inflight_then_fail(records):
        nonlocal writes
        writes += 1
        return original_write(records) if writes == 1 else False

    monkeypatch.setattr(registry, "_write_canonical_locked", write_through_inflight_then_fail)
    assert not registry.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        delivery_id=delivery_id, transport=lambda path, token: initial_calls.append((path, token)) or outcome,
    )
    assert writes == 2 and initial_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
    assert [(item["state"], item["delivery_id"]) for item in registry.recovery_candidates()] == [("wake_inflight", delivery_id)]

    def assert_relay_pending() -> None:
        status = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert status["state"] == "pending" and status["claim_token"] is None and status["receipt"] is None and status["attempts"] == 0

    assert_relay_pending()
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert [(item["state"], item["delivery_id"]) for item in restarted.recovery_candidates()] == [("wake_inflight", delivery_id)]
    wall[0] = 101.0
    assert restarted.rearm_inflight(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        delivery_id=delivery_id, grace_seconds=1,
    )
    later_calls: list[tuple[str, str]] = []
    assert restarted.probe(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        delivery_id=delivery_id, transport=lambda path, token: later_calls.append((path, token)) or "accepted",
    )
    assert later_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
    assert_relay_pending()


@pytest.mark.parametrize("item", [
    {"runtime": "claude-code", "session_ref": "s", "container_ref": "c", "actor_ref": "a", "socket_path": "p", "token": "t", "generation": "bad", "idle": True, "state": "idle", "delivery_id": None, "attempted_at": None, "expires_at": 1},
    {"runtime": "claude-code", "session_ref": "s", "container_ref": "c", "actor_ref": "a", "socket_path": "p", "token": "t", "generation": 1, "idle": True, "state": "wake_inflight", "delivery_id": None, "attempted_at": None, "expires_at": 1},
])
def test_corrupt_persisted_records_fail_closed(tmp_path: Path, item: dict) -> None:
    (tmp_path / "capabilities.json").write_text(json.dumps({"version": 1, "registrations": [item]}), encoding="utf-8")
    assert ClaudeWakeRegistry(state_dir=tmp_path).recovery_candidates() == []


def test_stale_closed_intent_cannot_remove_newer_intent(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    newer = {**PAYLOAD, "token": "new-token"}
    _write_intent(tmp_path, newer, "new")
    assert not registry.close(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], intent_id="old")
    assert registry.register(**newer, intent_id="new")


def test_reconciler_stop_joins_its_thread(tmp_path: Path) -> None:
    from app.claude_wake import ClaudeWakeReconciler

    reconciler = ClaudeWakeReconciler(ClaudeWakeRegistry(state_dir=tmp_path), SimpleNamespace(pending_candidate=lambda **_kwargs: None), interval_seconds=0.01)
    reconciler.start()
    reconciler.stop()
    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_accepted_inflight_rehydrates_and_rearms_after_grace(tmp_path: Path) -> None:
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", transport=lambda *_: "accepted")
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert restarted.recovery_candidates()[0]["attempted_at"] == 100.0
    assert not restarted.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", grace_seconds=1)
    wall[0] = 101.0
    assert restarted.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", grace_seconds=1)


def test_wall_clock_rollback_rearms_inflight_for_eventual_wake(tmp_path: Path) -> None:
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", transport=lambda *_: "accepted")
    wall[0] = 1.0
    assert registry.rearm_inflight(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", grace_seconds=1)

def test_terminal_transport_deletes_capability_but_preserves_newer_intent(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    _write_intent(tmp_path, {**PAYLOAD, "token": "new"}, "new")
    assert not registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="d", transport=lambda *_: "terminal")
    assert registry.recovery_candidates() == []
    assert registry.register(**{**PAYLOAD, "token": "new"}, intent_id="new")


def test_busy_persistence_failure_reports_degradation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)
    monkeypatch.setattr(registry, "_quarantine_or_mark_unusable_locked", lambda: False)
    assert registry.mark_busy(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"])
    assert registry.durability_degraded

def test_close_preserves_intent_replaced_after_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "open")
    closed = {"runtime": "claude-code", "session_ref": PAYLOAD["session_ref"], "container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"], "intent_id": "close", "closed": True}
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    original = registry._delete_intent_locked
    def replace_then_delete(session_ref: str, expected_intent_id: str | None) -> bool:
        path.write_text(json.dumps({**PAYLOAD, "token": "new", "intent_id": "new"}), encoding="utf-8")
        return original(session_ref, expected_intent_id)
    monkeypatch.setattr(registry, "_delete_intent_locked", replace_then_delete)
    assert registry.close(**{key: closed[key] for key in ("runtime", "session_ref", "container_ref", "actor_ref", "intent_id")})
    assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "new"

def test_recovery_retries_rollback_inflight_once_without_relay_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import claude_wake
    wall = [100.0]
    registry = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    assert _register(registry, tmp_path, PAYLOAD, "idle")
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], delivery_id="delivery", transport=lambda *_: "accepted")
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])
    calls = []
    relay = SimpleNamespace(pending_candidate=lambda **kwargs: calls.append(kwargs) or {"delivery_id": "delivery", "state": "pending"})
    scheduled = []
    monkeypatch.setattr(claude_wake, "schedule_claude_relay_wake", lambda result, scope, *, registry: scheduled.append((result, scope)) or None)
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert scheduled == []
    wall[0] = 1.0
    claude_wake.recover_claude_relay_wakes(restarted, relay)
    assert len(scheduled) == 1 and len(calls) == 2

def test_expired_claim_recovery_retries_without_mutating_relay(
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
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
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
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        delivery_id=claimed["delivery_id"], transport=lambda *_: "accepted",
    )
    restarted = ClaudeWakeRegistry(state_dir=tmp_path, wall_clock=lambda: wall[0])

    clock[0] += timedelta(seconds=61)
    assert relay.pending_candidate(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"],
        delivery_id=claimed["delivery_id"], **scope,
    ) == {"delivery_id": claimed["delivery_id"], "state": "pending"}
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
    assert retried.wait(timeout=1)
    assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]

    after = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert after["state"] == "claimed" and after["delivered_at"] is None
    assert tuple(after[key] for key in ("claim_token", "receipt", "claimed_at", "lease_expires_at", "attempts")) == tuple(
        before[key] for key in ("claim_token", "receipt", "claimed_at", "lease_expires_at", "attempts")
    )

def test_online_close_removes_only_exact_durable_capability_and_intent(tmp_path: Path) -> None:
    from tests.test_claude_wake_registration import _client

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    other = {**PAYLOAD, "session_ref": "other"}
    assert _register(registry, tmp_path, PAYLOAD, "open")
    assert _register(registry, tmp_path, other, "other-open")
    closed = {
        "runtime": "claude-code", "session_ref": PAYLOAD["session_ref"],
        "container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"],
        "intent_id": "closed", "closed": True,
    }
    path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    path.write_text(json.dumps(closed), encoding="utf-8")
    http = _client(registry)
    close_request = {key: closed[key] for key in ("runtime", "session_ref", "container_ref", "actor_ref", "intent_id")}
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
    monkeypatch.setattr(session_end, "derive_actor_ref", lambda: PAYLOAD["actor_ref"])
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())))
    session_end.main()
    closed_path = _intent_path(state_dir, PAYLOAD["session_ref"])
    closed = json.loads(closed_path.read_text(encoding="utf-8"))
    assert closed["closed"] is True

    restarted = ClaudeWakeRegistry(state_dir=state_dir)
    newer = {**PAYLOAD, "token": "new-token"}
    original_delete = restarted._delete_intent_locked

    def replace_closed_intent(session_ref: str, expected_intent_id: str | None) -> bool:
        _write_intent(state_dir, newer, "newer")
        return original_delete(session_ref, expected_intent_id)

    monkeypatch.setattr(restarted, "_delete_intent_locked", replace_closed_intent)
    restarted.recover_intents()
    assert restarted.recovery_candidates() == []
    assert json.loads(closed_path.read_text(encoding="utf-8"))["intent_id"] == "newer"

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