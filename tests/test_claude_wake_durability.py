from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import FunctionType, SimpleNamespace
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


@pytest.mark.parametrize("phase", ["mkdir", "temporary_write", "atomic_replace"])
@pytest.mark.parametrize("codes", ["native", "untrusted", "logger-failure"])
def test_atomic_reservation_failure_reports_only_safe_metadata(
    tmp_path, monkeypatch, caplog, phase, codes,
):
    import core.claude_wake as wake

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "initial")
    canonical = registry._canonical
    before = canonical.read_bytes()
    failure = PermissionError("private exception detail", str(canonical))
    failure.errno = 13 if codes != "untrusted" else "private errno"
    failure.winerror = 32 if codes != "untrusted" else True
    native_replace = wake._replace_atomic_state_file

    class FailurePath(type(tmp_path)):
        def mkdir(self, *args, **kwargs):
            if phase == "mkdir" and self == tmp_path:
                raise failure
            return super().mkdir(*args, **kwargs)

        def write_text(self, *args, **kwargs):
            if phase == "temporary_write" and self == canonical.with_name(canonical.name + ".tmp"):
                raise failure
            return super().write_text(*args, **kwargs)

    def replace(source, destination):
        if phase == "atomic_replace" and destination == canonical:
            raise failure
        return native_replace(source, destination)

    transport_calls = []
    scope = {key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}
    with monkeypatch.context() as fault:
        fault.setattr(registry, "_canonical", FailurePath(canonical))
        fault.setattr(wake, "_replace_atomic_state_file", replace)
        if codes == "logger-failure":
            def broken_log(*_args, **_kwargs):
                raise RuntimeError("private logging failure")
            fault.setattr(wake.logger, "warning", broken_log)
        result = registry.attempt(**scope, transport=lambda *_: transport_calls.append(True) or True)
    assert (result.outcome, result.reason) == ("deferred", "reservation_write_failed")
    assert not transport_calls and canonical.read_bytes() == before
    if codes != "logger-failure":
        records = [record for record in caplog.records if record.name == "core.claude_wake"]
        assert len(records) == 1
        expected_codes = "errno=13 winerror=32" if codes == "native" else "errno=None winerror=None"
        assert records[0].getMessage() == (
            f"claude_wake_atomic_write_failed phase={phase} error_type=PermissionError {expected_codes}"
        )
        assert records[0].exc_info is None
    assert registry.probe(**scope, transport=lambda *_: transport_calls.append(True) or True)
    assert transport_calls == [True]
    assert len(caplog.records) == (0 if codes == "logger-failure" else 1)


def test_open_canonical_reader_preserves_snapshot_through_http_wake_and_ack(
    client, tmp_path, monkeypatch,
):
    import core.claude_wake as wake

    registry = client.app.state.claude_wake_registry
    assert registry.persistent
    scope = {"container_ref": PAYLOAD["container_ref"]}
    for runtime, session in (("codex", "sender"), ("claude-code", PAYLOAD["session_ref"])):
        assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **scope}).status_code == 200
    assert _register(registry, registry._state_dir, PAYLOAD, "idle")
    canonical = registry._canonical
    previous = json.loads(canonical.read_text(encoding="utf-8"))
    opened, release, notified = threading.Event(), threading.Event(), threading.Event()
    snapshots, transport_calls = [], []
    native_open = wake._open_atomic_state_file
    reader_id = []

    @contextmanager
    def held_reader(path):
        with native_open(path) as source:
            if path == canonical and reader_id == [threading.get_ident()]:
                opened.set()
                release.wait()
            yield source

    def reader():
        reader_id.append(threading.get_ident())
        snapshots.append(registry._read_json(canonical))

    def transport(*_args):
        transport_calls.append(True)
        notified.set()
        return True

    monkeypatch.setattr(wake, "_open_atomic_state_file", held_reader)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    worker = threading.Thread(target=reader)
    worker.start()
    try:
        assert opened.wait(1)
        sent = client.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "claude-code:" + PAYLOAD["session_ref"],
            "payload": "canonical reader snapshot ✓", **scope,
        })
        assert sent.status_code == 200, sent.text
        assert notified.wait(1) and worker.is_alive()
        assert json.loads(canonical.read_text(encoding="utf-8"))["registrations"][0]["state"] == "wake_inflight"
        claimed = client.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": PAYLOAD["session_ref"], **scope,
        })
        assert claimed.status_code == 200, claimed.text
        delivery = claimed.json()["deliveries"][0]
        assert client.post("/relay/deliveries/ack", json={
            "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **scope,
        }).status_code == 200
        public = client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
        assert public.status_code == 200 and public.json()["deliveries"][0]["state"] == "delivered"
        assert transport_calls == [True] and worker.is_alive()
    finally:
        release.set()
        worker.join(1)
        assert not worker.is_alive()
    assert snapshots == [previous]


def _modern_admission_fixture(root: Path) -> ClaudeWakeRegistry:
    """Persist the modern row shape; hosted tests do not require Git history."""
    registry = ClaudeWakeRegistry(state_dir=root)
    assert _register(registry, root, PAYLOAD, "A")
    path = root / "capabilities.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["registrations"][0]["admission_id"] = "A"
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    loaded = ClaudeWakeRegistry(state_dir=root)
    assert path.read_bytes() == before
    return loaded


@pytest.mark.parametrize("scenario", ["remove", "transition", "replacement", "pending", "inflight"])
def test_compatibility_reader_consumes_modern_notice_without_rewinding(tmp_path, scenario):
    registry = _modern_admission_fixture(tmp_path)
    scope = {key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}
    if scenario == "transition":
        assert registry.mark_busy(**scope)
        assert json.loads((tmp_path / "capabilities.json").read_text())["registrations"][0]["admission_id"] == "A"
    elif scenario == "inflight":
        assert registry.attempt(
            **scope, delivery_id="relay-delivery-" + "a" * 32,
            recipient_endpoint_id=ENDPOINT_ID, transport=lambda *_: True,
        ).outcome == "accepted"
    elif scenario == "replacement":
        assert _register(registry, tmp_path, PAYLOAD, "B")
        assert "admission_id" not in json.loads((tmp_path / "capabilities.json").read_text())["registrations"][0]
    elif scenario == "pending":
        _write_intent(tmp_path, {**PAYLOAD, "token": "replacement-token"}, "B")

    identity = [*scope.values(), "A"]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    notice = tmp_path / "intents" / ("revoke-" + digest + ".json")
    notice.write_text(json.dumps({**scope, "admission_id": "A", "closed": True}), encoding="utf-8")
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    registry.recover_intents()
    registry.recover_intents()
    state = registry.state_for(recipient_endpoint_id=ENDPOINT_ID, session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"])
    assert state == ("idle" if scenario in {"replacement", "pending"} else "wake_inflight" if scenario == "inflight" else None)
    assert not notice.exists()
    if scenario == "pending":
        tokens = []
        assert registry.probe(**scope, transport=lambda _path, token: tokens.append(token) or True)
        assert tokens == ["replacement-token"]
    if scenario == "inflight":
        assert not registry.probe(**scope, transport=lambda *_: pytest.fail("spent authority must not reopen"))
        assert _register(registry, tmp_path, PAYLOAD, "B")
        raw = json.loads((tmp_path / "capabilities.json").read_text())["registrations"][0]
        assert raw["state"] == "wake_inflight" and "admission_id" not in raw


def test_compatibility_writer_keeps_legacy_rows_and_disables_deferred_publication(tmp_path, monkeypatch):
    from tests.test_claude_code_integration import _load_claude_hook

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "legacy")
    assert "admission_id" not in json.loads((tmp_path / "capabilities.json").read_text())["registrations"][0]
    registry = _modern_admission_fixture(tmp_path)
    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", tmp_path)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", tmp_path / "intents")
    monkeypatch.setattr(common, "_wake_binding_matches_service", lambda: True)
    written = []
    monkeypatch.setattr(common, "_write_wake_intent", lambda payload: written.append(payload) or False)
    assert common.close_claude_wake(PAYLOAD["session_ref"], PAYLOAD["container_ref"], credential_loss=True) is False
    assert len(written) == 1 and written[0]["expected_admission_id"] == "A"
    assert not list((tmp_path / "intents").glob("revoke-*.json"))
    assert registry.probe(**{key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}, transport=lambda *_: True)


def test_compatibility_qualified_close_preserves_replacement_and_pending_intent(tmp_path, monkeypatch):
    from tests.test_claude_code_integration import _load_claude_hook
    import core.claude_wake as wake

    canonical = tmp_path / "capabilities.json"
    temporary = tmp_path / "capabilities.json.tmp"
    intent_path = _intent_path(tmp_path, PAYLOAD["session_ref"])
    phases = []
    original_write, original_replace = Path.write_text, wake._replace_atomic_state_file
    original_acquire = wake._acquire_intent_lock

    def observe(phase, callback, *args, **kwargs):
        entry = {"phase": phase, "started": time.monotonic(),
                 "thread_id": threading.get_ident(), "path_length": len(str(args[0]))}
        if len(phases) < 64:
            phases.append(entry)
        try:
            result = callback(*args, **kwargs)
            entry["ok"] = True
            if phase == "acquire":
                entry["acquired"] = result is not None
            return result
        except BaseException as error:
            entry.update(ok=False, error_type=type(error).__name__,
                         errno=getattr(error, "errno", None), winerror=getattr(error, "winerror", None))
            raise
        finally:
            entry["finished"] = time.monotonic()

    def write(path, *args, **kwargs):
        if path == temporary:
            return observe("write", original_write, path, *args, **kwargs)
        return original_write(path, *args, **kwargs)

    def replace(source, destination, *args, **kwargs):
        if Path(source) == temporary and Path(destination) == canonical:
            return observe("replace", original_replace, source, destination, *args, **kwargs)
        return original_replace(source, destination, *args, **kwargs)

    def acquire(path):
        if path == intent_path:
            return observe("acquire", original_acquire, path)
        return original_acquire(path)

    monkeypatch.setattr(wake, "_replace_atomic_state_file", replace)
    monkeypatch.setattr(wake, "_acquire_intent_lock", acquire)
    monkeypatch.setattr(Path, "write_text", write)

    registry = _modern_admission_fixture(tmp_path)
    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", tmp_path)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", tmp_path / "intents")
    monkeypatch.setattr(common, "_wake_binding_matches_service", lambda: True)
    _write_intent(tmp_path, {**PAYLOAD, "token": "new-token"}, "B")
    intent = _intent_path(tmp_path, PAYLOAD["session_ref"])
    pending = intent.read_bytes()
    assert common.close_claude_wake(PAYLOAD["session_ref"], PAYLOAD["container_ref"], credential_loss=True) is False
    assert intent.read_bytes() == pending
    assert not list((tmp_path / "intents").glob("revoke-*.json"))

    assert registry.register(**{**PAYLOAD, "token": "new-token"}, intent_id="B")
    intent.write_text(json.dumps({
        **{key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")},
        "intent_id": "old-close", "closed": True, "expected_admission_id": "A",
    }), encoding="utf-8")
    assert not registry.close(**{key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}, intent_id="old-close")
    tokens = []
    original_attempt = registry.attempt

    def attempt(*args, **kwargs):
        result = original_attempt(*args, **kwargs)
        phases.append({"phase": "attempt", "outcome": result.outcome, "reason": result.reason})
        return result

    monkeypatch.setattr(registry, "attempt", attempt)
    try:
        assert registry.probe(**{key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}, transport=lambda _path, token: tokens.append(token) or True), phases
    finally:
        (tmp_path / "canonical-publication-diagnostics.json").write_text(json.dumps(phases), encoding="utf-8")
    assert tokens == ["new-token"]


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

    reconciler = ClaudeWakeReconciler(ClaudeWakeRegistry(state_dir=tmp_path), SimpleNamespace(wake_candidates=lambda **_kwargs: []), interval_seconds=0.01)
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
    request: pytest.FixtureRequest, tmp_path: Path,
) -> None:
    from itertools import count
    from threading import get_ident
    from storage import sqlite_queue
    from tests.test_claude_code_integration import _load_claude_hook
    from tests.test_codex_wake_retry_edges import _observe_relay_busy_acquisition

    _observe_relay_busy_acquisition(client.app.state.pallium_service._storage, monkeypatch, request, tmp_path)
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
    storage = client.app.state.pallium_service._storage
    native_mark_active, native_queue_time = storage.relay_mark_active, sqlite_queue.time
    native_monotonic = time.monotonic

    def setup_mark_active(**kwargs):
        provider_thread = get_ident()
        logical_monotonic = count(step=.001).__next__
        qualified_time = SimpleNamespace(**vars(native_queue_time))
        qualified_time.monotonic = lambda: (
            logical_monotonic() if get_ident() == provider_thread else native_monotonic())
        with monkeypatch.context() as setup:
            setup.setattr(sqlite_queue, "time", qualified_time)
            return native_mark_active(**kwargs)

    with monkeypatch.context() as setup:
        setup.setattr(storage, "relay_mark_active", setup_mark_active)
        assert common.register_claude_wake(session_ref, scope["container_ref"], idle=True)
    assert storage.relay_mark_active == native_mark_active and sqlite_queue.time is native_queue_time
    assert time.monotonic is native_monotonic
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
    relay = SimpleNamespace(wake_candidates=lambda **kwargs: calls.append(kwargs) or [{"delivery_id": "delivery", "state": "pending"}])
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
    first_transport_finished = threading.Event()
    accepted = threading.Event()
    workers: list[threading.Thread] = []
    original_schedule = claude_wake.schedule_claude_relay_wake

    def capture_worker(*args, **kwargs):
        worker = original_schedule(*args, **kwargs)
        if worker is not None:
            workers.append(worker)
        return worker

    monkeypatch.setattr(claude_wake, "schedule_claude_relay_wake", capture_worker)

    def transport(_socket_path: str, _token: str) -> str:
        delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        observed.append((delivery["state"], delivery["claim_token"], delivery["receipt"], delivery["attempts"]))
        if len(observed) == 1:
            first_transport_finished.set()
        if len(observed) == 4:
            accepted.set()
            return "accepted"
        return "retryable"

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    reconciler = ClaudeWakeReconciler(registry, relay, interval_seconds=0.01)
    reconciler.start()
    try:
        assert first_transport_finished.wait(timeout=5), "wake transport did not complete its status read"
        assert not accepted.wait(timeout=0.1), observed
    finally:
        reconciler.stop()
        reconciler_thread = reconciler._thread
        if reconciler_thread is not None:
            reconciler_thread.join(timeout=2)
        for worker in tuple(workers):
            worker.join(timeout=5)
        assert reconciler_thread is not None and not reconciler_thread.is_alive()
        assert all(not worker.is_alive() for worker in workers)

    assert observed == [("pending", None, None, 0)]

@pytest.mark.parametrize("transport_result", ("accepted", "retryable"))
def test_recovery_does_not_rearm_inflight_while_native_worker_is_active(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport_result: str,
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
    recovery_started = threading.Event()
    recovery_finished = threading.Event()
    transport_watchdog_failed = threading.Event()
    retried = threading.Event()
    transport_calls: list[tuple[str, str]] = []

    def transport(socket_path: str, token: str) -> str:
        transport_calls.append((socket_path, token))
        if len(transport_calls) == 1:
            started.set()
            if not release.wait(timeout=5):
                transport_watchdog_failed.set()
        else:
            retried.set()
        return transport_result

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    original_recover_registration_intents = claude_wake.recover_claude_registration_intents

    def observe_recovery_start(registry_arg, relay_arg):
        recovery_started.set()
        return original_recover_registration_intents(registry_arg, relay_arg)

    monkeypatch.setattr(claude_wake, "recover_claude_registration_intents", observe_recovery_start)
    worker = claude_wake.schedule_claude_relay_wake(result, scope, registry=registry)
    assert worker is not None
    recovery_errors: list[BaseException] = []

    def recover() -> None:
        try:
            claude_wake.recover_claude_relay_wakes(registry, relay)
        except BaseException as exc:
            recovery_errors.append(exc)
        finally:
            recovery_finished.set()

    recovery_thread: threading.Thread | None = None
    try:
        assert started.wait(timeout=1)
        wall[0] = 102.0
        recovery_thread = threading.Thread(target=recover, name="claude-wake-held-recovery")
        recovery_thread.start()
        assert recovery_started.wait(timeout=5)
        assert not recovery_finished.wait(timeout=0.1)
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        pending = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert pending["state"] == "pending"
        assert tuple(pending[key] for key in ("claim_token", "receipt", "attempts")) == (None, None, 0)
    finally:
        release.set()
        worker.join(timeout=5)
        if recovery_thread is not None:
            recovery_thread.join(timeout=5)
        assert not worker.is_alive()
        assert recovery_thread is None or not recovery_thread.is_alive()

    assert not transport_watchdog_failed.is_set(), "held native transport exceeded its bounded release wait"
    assert recovery_finished.is_set()
    assert not recovery_errors, recovery_errors
    candidate = next(iter(registry.recovery_candidates()))
    assert candidate["state"] == "wake_inflight" and candidate["delivery_id"] == delivery["delivery_id"]
    pending = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    assert pending["state"] == "pending"
    assert tuple(pending[key] for key in ("claim_token", "receipt", "attempts")) == (None, None, 0)

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


def test_online_close_removes_only_exact_durable_capability_and_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from itertools import count
    import core.claude_wake as wake
    from tests.test_claude_wake_registration import _client

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    other = {**PAYLOAD, "session_ref": "other"}
    native_time = wake.time
    private_time = SimpleNamespace(**vars(native_time))
    private_time.monotonic = count(step=.001).__next__
    # Setup needs durable identities; lock setup expiry has dedicated coverage.
    with monkeypatch.context() as setup:
        setup.setattr(wake, "time", private_time)
        assert _register(registry, tmp_path, PAYLOAD, "open")
        assert _register(registry, tmp_path, other, "other-open")
    assert wake.time is native_time
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
    print("admission-evidence=" + json.dumps(evidence), file=sys.stderr, flush=True)
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
            error_lines = errors.splitlines()
            assert len(error_lines) == 2, errors
            assert error_lines[1].startswith("admission-evidence="), errors
            evidence = json.loads(error_lines[1].removeprefix("admission-evidence="))
            error_class = "PermissionError" if os.name == "nt" else "BlockingIOError"
            assert error_lines[0] == (
                "pallium hook: session_state_write_failed phase=native_wait_exhausted "
                f"error={error_class} errno={evidence['errno']} winerror=None"
            ), errors
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
    from unittest.mock import patch

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
    ready = tmp_path / "intent-owner-ready"
    script = """
import os, sys
from pathlib import Path
path = Path(sys.argv[1]).with_suffix(".lock")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a+b") as lock:
    lock.seek(0, os.SEEK_END)
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
    print("locked", flush=True)
    sys.stdin.read()
"""
    process = subprocess.Popen(
        [sys._base_executable, "-c", script, str(path), str(ready)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        startup_deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < startup_deadline:
            time.sleep(0.01)
        assert ready.exists(), (
            process.stderr.read() if process.poll() is not None and process.stderr is not None
            else "child did not acquire the real intent lock before startup timeout"
        )
        assert int(ready.read_text(encoding="utf-8")) == process.pid
        assert process.poll() is None, "intent lock owner exited before the caller journey"
        monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(state_dir))
        common = _load_claude_hook("common", monkeypatch)
        common.CLAUDE_WAKE_DIR = state_dir
        common.CLAUDE_WAKE_INTENTS_DIR = state_dir / "intents"
        monkeypatch.setattr(common, "_acquire_file_lock", timed_sync("hook_lock", common._acquire_file_lock))
        monkeypatch.setattr(common, "register_claude_wake", timed_sync("hook", common.register_claude_wake))
        with _client(registry) as http:
            monkeypatch.setattr(http, "post", timed_sync("http", http.post))
            # Qualify steady-state lock refusal separately from cold router setup.
            old_intent_before_warmup = path.read_bytes()
            timing_origin = time.monotonic()
            with patch.object(registry, "register", wraps=registry.register) as register:
                warmup = http.post("/internal/claude-wake/register", json={})
                assert warmup.status_code == 400
                assert warmup.json()["detail"] == "invalid registration"
                register.assert_not_called()
            timing_origin = None
            cold_setup_samples = list(timing_samples)
            timing_samples.clear()
            assert registry._registrations == {} and not registry._canonical.exists()
            assert path.read_bytes() == old_intent_before_warmup
            started = time.monotonic()
            timing_origin = started
            rejected = http.post("/internal/claude-wake/register", json=old)
            timing_origin = None
            assert rejected.status_code == 409
            assert time.monotonic() - started < 0.5, json.dumps({
                "router_setup_probe": int(router_setup_probe), "timings": timing_samples,
                "cold_setup": cold_setup_samples,
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
                "cold_setup": cold_setup_samples,
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
    endpoint_probe = ClaudeWakeRegistry._endpoint_is_provably_absent
    namespace = dict(endpoint_probe.__globals__)
    namespace["os"] = SimpleNamespace(**dict(vars(wake.os), name="posix"))
    monkeypatch.setattr(ClaudeWakeRegistry, "_endpoint_is_provably_absent",
                        staticmethod(FunctionType(endpoint_probe.__code__, namespace)))
    monkeypatch.setattr(registry, "probe", lambda *_args, **_kwargs: pytest.fail("capacity cleanup must not admit a turn"))
    from itertools import count
    native_registry_time = wake.time
    with monkeypatch.context() as admission:
        registry_time = SimpleNamespace(**vars(native_registry_time))
        registry_time.monotonic = count(step=.001).__next__
        admission.setattr(wake, "time", registry_time)
        assert _register(registry, state_dir, {**PAYLOAD, "session_ref": "new"}, "new") is accepted
    assert wake.time is native_registry_time
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
    endpoint_probe = ClaudeWakeRegistry._endpoint_is_provably_absent
    namespace = dict(endpoint_probe.__globals__)
    namespace["os"] = SimpleNamespace(**dict(vars(wake.os), name="nt"))
    monkeypatch.setattr(ClaudeWakeRegistry, "_endpoint_is_provably_absent",
                        staticmethod(FunctionType(endpoint_probe.__code__, namespace)))
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=PipeError))
    monkeypatch.setitem(sys.modules, "winerror", SimpleNamespace(ERROR_FILE_NOT_FOUND=2))
    monkeypatch.setitem(sys.modules, "win32pipe", SimpleNamespace(WaitNamedPipe=lambda *_: (_ for _ in ()).throw(PipeError(code))))
    monkeypatch.setattr(registry, "probe", lambda *_args, **_kwargs: pytest.fail("capacity cleanup must not admit a turn"))
    # Exercise capacity policy independently of its separately covered lock-admission deadline.
    from itertools import count
    native_registry_time = wake.time
    with monkeypatch.context() as admission:
        registry_time = SimpleNamespace(**vars(native_registry_time))
        registry_time.monotonic = count(step=.001).__next__
        admission.setattr(wake, "time", registry_time)
        assert _register(registry, state_dir, {**PAYLOAD, "session_ref": "new", "socket_path": r"\\.\pipe\new"}, "new") is accepted
    assert wake.time is native_registry_time
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
        def wake_candidates(self, **kwargs: object) -> list[dict]:
            return relay.wake_candidates(**kwargs)

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
    from core import claude_wake as wake_core

    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    second = {**PAYLOAD, "session_ref": "session-β"}
    stages = []

    def observe(stage, original):
        def call(*args, **kwargs):
            started = time.monotonic()
            result, error = None, None
            try:
                result = original(*args, **kwargs)
                return result
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                stages.append({
                    "stage": stage, "elapsed_ms": (time.monotonic() - started) * 1000,
                    "result": result if type(result) is bool else result is not None,
                    "error": error,
                })
        return call

    # Keep real clocks and native locks; expose only the failed setup phase.
    with monkeypatch.context() as setup:
        setup.setattr(wake_core, "_acquire_intent_lock", observe("intent_lock", wake_core._acquire_intent_lock))
        for name in ("_read_intent_locked", "_intent_matches", "_write_canonical_locked", "_clear_unusable_locked", "register"):
            setup.setattr(registry, name, observe(name, getattr(registry, name)))
        try:
            assert _register(registry, tmp_path, PAYLOAD, "first"), json.dumps(stages)
            assert _register(registry, tmp_path, second, "second"), json.dumps(stages)
        except BaseException as exc:
            exc.add_note("Claude registration setup: " + json.dumps(stages))
            raise
    callbacks = []
    marked: list[tuple[str, str]] = []

    def schedule(_result: object, _scope: object, *, registry: object, on_unreachable, **_kwargs) -> None:
        callbacks.append(on_unreachable)

    metadata_reads = []

    def wake_candidates(**kwargs):
        metadata_reads.append(kwargs)
        return [
            {
                "delivery_id": "delivery-" + item["session_ref"],
                "recipient_endpoint_id": "relay-session-" + suffix * 32,
                "recipient_runtime": "claude-code",
                "recipient_session_ref": item["session_ref"],
                "container_ref": item["container_ref"],
                "state": "pending",
            }
            for item, suffix in ((PAYLOAD, "a"), (second, "b"))
            if kwargs.get("delivery_id") in (None, "delivery-" + item["session_ref"])
        ]

    relay = SimpleNamespace(
        wake_candidates=wake_candidates,
        mark_unreachable=lambda **kwargs: marked.append((
            str(kwargs["session_ref"]), str(kwargs["container_ref"])
        )) or True,
    )
    monkeypatch.setattr(claude_wake, "schedule_claude_relay_wake", schedule)
    claude_wake.recover_claude_relay_wakes(registry, relay)
    assert metadata_reads == [{}]
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


@pytest.mark.parametrize("health", ["closed", "unreachable"])
@pytest.mark.parametrize("idle", [False, True], ids=["busy", "idle"])
def test_registration_activation_refusal_recovers_before_new_http_delivery(
    tmp_path, monkeypatch, health, idle,
):
    from datetime import datetime, timezone
    from app import main, claude_wake
    from app.config import AppConfig
    from core.errors import ImmediateTransactionBusyError
    from core.relay import RelayService
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    state_dir = tmp_path / "activation-wake"
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(state_dir))
    config = AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'activation.db'}",
        default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    scope = {"container_ref": PAYLOAD["container_ref"]}
    identity = {key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}
    registration = {**PAYLOAD, "idle": idle, "intent_id": "activation-pending"}
    path = _intent_path(state_dir, PAYLOAD["session_ref"])
    original_start = main.start_claude_wake_reconciler
    monkeypatch.setattr(main, "start_claude_wake_reconciler", lambda *a, **k: None)

    def destination(http):
        response = http.get("/relay/sessions", params={**identity, "include_inactive": True})
        assert response.status_code == 200, response.text
        row, = response.json()
        return row

    with TestClient(main.create_app(config), client=("127.0.0.1", 50000)) as first:
        for runtime, session in (("codex", "activation-sender"), ("claude-code", PAYLOAD["session_ref"])):
            response = first.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **scope})
            assert response.status_code == 200, response.text
        storage = first.app.state.pallium_service._storage
        relay = RelayService(storage)
        if health == "closed":
            assert first.post("/relay/sessions/close", json=identity).status_code == 200
        else:
            assert relay.mark_unreachable(**identity, attempt_started_at=datetime.now(timezone.utc))
        row = destination(first)
        assert (row["state"] if health == "closed" else row["destination_health"]) == health
        _write_intent(state_dir, registration, registration["intent_id"])

        def refused_activation(**actual):
            assert actual == {**identity, "now": None}
            raise ImmediateTransactionBusyError("controlled activation refusal", acquisition_stage="local_gate")

        with monkeypatch.context() as fault:
            fault.setattr(storage, "relay_mark_active", refused_activation)
            response = first.post("/internal/claude-wake/register", json=registration)
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
        assert response.headers["Retry-After"] == "1"
        assert json.loads(path.read_text(encoding="utf-8")) == registration
        registry = first.app.state.claude_wake_registry
        assert registry.state_for(recipient_endpoint_id=row["endpoint_id"],
            session_ref=identity["session_ref"], container_ref=identity["container_ref"]) == ("idle" if idle else "busy")
        row = destination(first)
        assert (row["state"] if health == "closed" else row["destination_health"]) == health
    assert path.exists()  # Actual service/engine shutdown did not consume pending activation.

    recovered, notified = threading.Event(), threading.Event()
    native_calls = []

    def start_observed(*args, claim_recovery, **kwargs):
        def initial_recovery():
            try:
                return claim_recovery()
            finally:
                recovered.set()
        return original_start(*args, claim_recovery=initial_recovery, **kwargs)

    def transport(socket_path, token):
        native_calls.append((socket_path, token))
        notified.set()
        return "accepted"

    monkeypatch.setattr(main, "start_claude_wake_reconciler", start_observed)
    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    app = main.create_app(config)
    with TestClient(app, client=("127.0.0.1", 50000)) as restarted:
        assert recovered.wait(5), "initial native recovery did not settle"
        assert not path.exists()
        assert destination(restarted)["destination_health"] == "active"
        assert native_calls == []
        if not idle:
            ready = {**registration, "idle": True, "intent_id": "fresh-idle"}
            _write_intent(state_dir, ready, ready["intent_id"])
            assert restarted.post("/internal/claude-wake/register", json=ready).status_code == 204
        sent = restarted.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "activation-sender",
            "recipient": "claude-code:" + PAYLOAD["session_ref"],
            "payload": "fresh delivery after activation recovery 東京", **scope,
        })
        assert sent.status_code == 200, sent.text
        assert notified.wait(5)
        assert native_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        claimed = restarted.post("/relay/turn", json={**identity, "max_chars": 2400})
        assert claimed.status_code == 200, claimed.text
        item, = claimed.json()["deliveries"]
        assert item["payload"] == "fresh delivery after activation recovery 東京"
        assert restarted.post("/relay/deliveries/ack", json={
            "delivery_id": item["delivery_id"], "claim_token": item["claim_token"], **scope,
        }).status_code == 200
        response = restarted.get("/relay/messages/" + sent.json()["message_id"], params=scope)
        assert response.status_code == 200
        delivery, = response.json()["deliveries"]
        assert delivery["state"] == "delivered" and delivery["attempts"] == 1
        assert native_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        reconciler = app.state._claude_wake_reconciler
    assert reconciler is not None and not reconciler._thread.is_alive()
    assert all(not worker.is_alive() for owner, worker in claude_wake._workers if owner == id(app.state.claude_wake_registry))


@pytest.mark.parametrize("replacement", ["idle", "closed"])
@pytest.mark.parametrize("inflight", [False, True])
def test_activation_completion_preserves_newer_intent_and_inflight(
    tmp_path, monkeypatch, replacement, inflight,
):
    registry = ClaudeWakeRegistry(state_dir=tmp_path)
    assert _register(registry, tmp_path, PAYLOAD, "initial")
    native_calls = []
    identity = {key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref")}
    if inflight:
        assert registry.probe(**identity, delivery_id="held-delivery", recipient_endpoint_id=ENDPOINT_ID,
            transport=lambda *a: native_calls.append(a) or "accepted")
    pending = {**PAYLOAD, "idle": False}
    _write_intent(tmp_path, pending, "pending-activation")
    scope_calls = []

    def defer(**scope):
        scope_calls.append(scope)
        return False

    assert not registry.register(**pending, intent_id="pending-activation", complete_registration=defer)
    assert scope_calls == [identity]
    assert registry.state_for(recipient_endpoint_id=ENDPOINT_ID,
        session_ref=identity["session_ref"], container_ref=identity["container_ref"]) == ("wake_inflight" if inflight else "busy")
    assert json.loads(_intent_path(tmp_path, PAYLOAD["session_ref"]).read_text(encoding="utf-8"))["intent_id"] == "pending-activation"
    newer = ({**identity, "intent_id": "newer", "closed": True} if replacement == "closed"
             else {**PAYLOAD, "token": "new-token", "intent_id": "newer"})
    _write_intent(tmp_path, newer, "newer")
    assert not registry.register(**pending, intent_id="pending-activation", complete_registration=lambda **k: pytest.fail("stale activation"))
    restarted = ClaudeWakeRegistry(state_dir=tmp_path)
    completed = []
    restarted.recover_intents(complete_registration=lambda **scope: completed.append(scope))
    assert not _intent_path(tmp_path, PAYLOAD["session_ref"]).exists()
    assert completed == ([] if replacement == "closed" else [identity])
    expected = "wake_inflight" if inflight else None if replacement == "closed" else "idle"
    assert restarted.state_for(recipient_endpoint_id=ENDPOINT_ID,
        session_ref=identity["session_ref"], container_ref=identity["container_ref"]) == expected
    if inflight:
        result = restarted.attempt(**identity, delivery_id="new-delivery", recipient_endpoint_id=ENDPOINT_ID,
            transport=lambda *a: native_calls.append(a) or "accepted")
        assert result.outcome == "deferred" and len(native_calls) == 1


def test_recovery_defers_only_failed_registration_activation(client, tmp_path, monkeypatch):
    from app.claude_wake import recover_claude_relay_wakes
    from core.errors import ImmediateTransactionBusyError
    from core.relay import RelayService

    registry = ClaudeWakeRegistry(state_dir=tmp_path / "recovery-activation")
    relay = RelayService(client.app.state.pallium_service._storage)
    payloads = [PAYLOAD, {**PAYLOAD, "session_ref": "other-session"}]
    for index, payload in enumerate(payloads):
        relay.turn(runtime=payload["runtime"], session_ref=payload["session_ref"], container_ref=payload["container_ref"])
        _write_intent(registry._state_dir, payload, "pending-" + str(index))
    native_activation = relay.mark_active
    calls = []
    def one_failed_activation(**scope):
        calls.append(scope["session_ref"])
        if scope["session_ref"] == PAYLOAD["session_ref"]:
            raise ImmediateTransactionBusyError("controlled recovery refusal", acquisition_stage="local_gate")
        return native_activation(**scope)
    with monkeypatch.context() as fault:
        fault.setattr(relay, "mark_active", one_failed_activation)
        recover_claude_relay_wakes(registry, relay)
    assert sorted(calls) == sorted(payload["session_ref"] for payload in payloads)
    failed = _intent_path(registry._state_dir, PAYLOAD["session_ref"])
    assert failed.exists()
    assert not _intent_path(registry._state_dir, "other-session").exists()
    recover_claude_relay_wakes(registry, relay)
    assert not failed.exists()
