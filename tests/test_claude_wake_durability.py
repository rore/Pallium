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