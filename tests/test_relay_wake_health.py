from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.claude_wake import ClaudeWakeReconciler
from app import codex_bridge_pipe as bridge
from storage.sqlite_schema import RelayCodexWakeReservationRecord, RelayCodexWakeStateRecord, RelayDeliveryRecord, RelayMessageRecord, RelaySessionRecord
from tests.test_dashboard import _test_config


def _assert_snapshot_shape(snapshot: dict) -> None:
    assert snapshot["assessment"] == "codex_scheduling_only"
    assert snapshot["state"] in {"usable", "degraded", "unknown"}
    assert snapshot["reason"] in {
        "authority_unavailable", "authority_uninitialized", "recovery_unobserved",
        "recovery_not_running", "recovery_running",
    }
    datetime.fromisoformat(snapshot["observed_at"])
    assert snapshot["authority_initialized"] in {True, False, None}
    assert snapshot["recovery_running"] in {True, False, None}
    assert type(snapshot["eligible_pending_count"]) is int or snapshot["eligible_pending_count"] is None
    assert type(snapshot["oldest_pending_age_seconds"]) in {int, float} or snapshot["oldest_pending_age_seconds"] is None
    assert snapshot["pending_evidence"] in {"complete", "row_limit", "incomplete", "unavailable"}
    assert snapshot["reservations"] is None or set(snapshot["reservations"]) == {"prepared", "reserved", "accepted", "uncertain"}
    assert type(snapshot["unresolved_uncertain_count"]) is int or snapshot["unresolved_uncertain_count"] is None
    assert snapshot["uncertainty_evidence"] in {"complete", "incomplete", "unavailable"}
    assert snapshot["uncertainty_reason"] in {None, "retry_held", "evidence_incomplete"}
    assert snapshot["recovery_progress_evidence"] == "not_recorded"
    assert snapshot["last_recovery_progress_at"] is None
    assert snapshot["trace_loss_evidence"] == "not_recorded"
    assert snapshot["trace_loss_count"] is None
    enrollment = snapshot["native_enrollment"]
    assert enrollment["state"] in {
        "unavailable", "never_registered", "registered", "retained_disconnected",
        "authority_cleared", "unresolved_handles", "released",
    }
    assert enrollment["evidence"] in {"unavailable", "cached_lifecycle_observation"}
    assert enrollment["accepted"] in {True, False, None}
    assert enrollment["registration_remembered"] in {True, False, None}
    assert enrollment["custody_present"] in {True, False, None}
    assert enrollment["unresolved_handles"] in {True, False, None}
    assert enrollment["continuity_opted_in"] in {True, False, None}
    assert enrollment["last_failure_stage"] in {None, "register", "maintenance", "reopen", "state-read", "owner-result"}
    assert enrollment["last_failure_reason"] in {
        None, "busy", "deadline", "file-unavailable", "file-write-failed", "invalid-message",
        "invalid-path", "invalid-policy", "invalid-policy-lock", "invalid-response",
        "message-limit", "native-failed", "native-tool-failed", "path-unavailable",
        "peer-gone", "peer-mismatch", "peer-unavailable", "policy-busy", "policy-changed",
        "policy-inactive", "stopped", "timeout", "transport-failed", "unsafe-acl",
        "unsafe-owner", "unsafe-path", "unsupported-acl",
    } or enrollment["state"] == "unavailable"
    fields = {
        "state", "evidence", "observed_at", "accepted", "registration_remembered",
        "custody_present", "unresolved_handles", "continuity_opted_in",
        "last_failure_stage", "last_failure_reason",
    }
    if enrollment["state"] == "unavailable":
        assert set(enrollment) == fields | {"reason"}
        assert enrollment["reason"] in {"service_missing", "snapshot_unavailable"}
    else:
        assert set(enrollment) == fields
        assert enrollment["evidence"] == "cached_lifecycle_observation"
        datetime.fromisoformat(enrollment["observed_at"])

    expected = {
        (None, None): ("unknown", "authority_unavailable"),
        (False, None): ("degraded", "authority_uninitialized"),
        (True, None): ("unknown", "recovery_unobserved"),
        (True, False): ("degraded", "recovery_not_running"),
        (True, True): ("usable", "recovery_running"),
    }
    for running in (False, True):
        expected[(None, running)] = ("unknown", "authority_unavailable")
        expected[(False, running)] = ("degraded", "authority_uninitialized")
    assert (snapshot["state"], snapshot["reason"]) == expected[
        (snapshot["authority_initialized"], snapshot["recovery_running"])
    ]


def test_status_exposes_additive_codex_wake_snapshot(client):
    response = client.get("/status")
    assert response.status_code == 200
    _assert_snapshot_shape(response.json()["relay_wake"])


def test_status_can_skip_duplicate_wake_snapshot_and_rejects_invalid_flag(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.relay_wake_health", lambda *args: calls.append(args) or {})
    skipped = client.get("/status?include_relay_wake=false")
    assert skipped.status_code == 200
    assert skipped.json()["relay_wake"] is None
    assert calls == []

    included = client.get("/status?include_relay_wake=true")
    assert included.status_code == 200
    assert len(calls) == 1

    invalid = client.get("/status?include_relay_wake=perhaps")
    assert invalid.status_code == 422


def test_relay_summary_exposes_same_codex_wake_projection(tmp_path):
    app = create_app(_test_config(tmp_path))
    with TestClient(app) as client:
        response = client.get("/dashboard/api/relay/summary")
    assert response.status_code == 200
    _assert_snapshot_shape(response.json()["relay_wake"])


def test_status_snapshot_is_read_only_and_does_not_expose_relay_content(client, monkeypatch):
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *a, **kw: None)
    scope = {"container_ref": "wake-health-private-scope"}
    for runtime, session_ref in (("claude-code", "sender"), ("codex", "target")):
        assert client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, **scope}).status_code == 200
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": "codex:target", "payload": "wake-health-private-payload", **scope,
    })
    assert sent.status_code == 200
    relay = client.app.state.pallium_service._storage
    before = relay.relay_codex_wake_snapshot()
    first = client.get("/status").json()["relay_wake"]
    second = client.get("/status").json()["relay_wake"]
    after = relay.relay_codex_wake_snapshot()

    assert before == after
    datetime.fromisoformat(first["observed_at"])
    datetime.fromisoformat(second["observed_at"])
    assert {k: v for k, v in first.items() if k != "observed_at"} == {k: v for k, v in second.items() if k != "observed_at"}
    serialized = str(first)
    assert "wake-health-private-payload" not in serialized
    assert "wake-health-private-scope" not in serialized


SCOPE = {"container_ref": "git:example.test/health-東京"}
VIEWS = ("/status", "/dashboard/api/relay/summary")


@pytest.fixture
def world(tmp_path, monkeypatch):
    native = []
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *a, **kw: native.append(1))
    config = replace(_test_config(tmp_path), relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}")
    app = create_app(config)
    storage = app.state.pallium_service._storage
    http = TestClient(app)  # No live reconciliation lifecycle; native boundary is fake.
    registry = app.state.codex_wake_registry
    assert registry.initialize(old_owner_drained=True)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **SCOPE}).status_code == 200
    try:
        yield http, storage, registry, native
    finally:
        try:
            http.close()
        finally:
            try:
                app.state.pallium_service.close()
            finally:
                storage.close()


def _send(world, outcome=None):
    http, _, registry, _ = world
    sent = http.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "codex:target", "payload": "A private Unicode payload 東京", **SCOPE})
    assert sent.status_code == 200, sent.text
    delivery = sent.json()["deliveries"][0]
    if outcome:
        reservation = registry.reserve(recipient_endpoint_id=delivery["recipient_endpoint_id"], delivery_id=delivery["delivery_id"], session_ref="target", **SCOPE)
        assert reservation is not None
        reservation = registry.begin_native_attempt(reservation)
        assert reservation is not None
        if outcome == "accepted":
            assert registry.record_outcome(reservation, outcome)
    return sent.json()["message_id"], delivery


def _view(world, path):
    response = world[0].get(path)
    assert response.status_code == 200, response.text
    snapshot = response.json()["relay_wake"]
    _assert_snapshot_shape(snapshot)
    return snapshot


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("case,state", [
    ("missing", "unavailable"), ("malformed", "unavailable"),
    ("never", "never_registered"), ("registered", "registered"),
    ("disconnected", "retained_disconnected"), ("cleared", "authority_cleared"),
    ("unresolved", "unresolved_handles"), ("released", "released"),
])
def test_native_enrollment_is_cached_lifecycle_evidence(world, tmp_path, path, case, state):
    _, _, registry, _ = world
    if case != "missing":
        data = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "accepted": case not in {"never", "malformed"},
            "registration_remembered": case in {"registered", "disconnected"},
            "custody_present": case in {"registered", "cleared", "unresolved"},
            "unresolved_handles": case == "unresolved",
            "continuity_opted_in": case in {"registered", "disconnected", "released"},
            "last_failure_stage": "register" if case in {"disconnected", "released"} else None,
            "last_failure_reason": "peer-mismatch" if case in {"disconnected", "released"} else None,
        }
        if case == "malformed":
            data["private-path-sentinel"] = "must not be returned"
        service = bridge.RetainedService(tmp_path)
        service._enrollment_diagnostics = data
        registry.retained_service = service
    enrollment = _view(world, path)["native_enrollment"]
    assert enrollment["state"] == state
    assert "private-path-sentinel" not in json.dumps(enrollment)
    if case == "missing":
        assert enrollment["reason"] == "service_missing"
    elif case == "malformed":
        assert enrollment["reason"] == "snapshot_unavailable"
    else:
        assert enrollment["evidence"] == "cached_lifecycle_observation"


@pytest.mark.parametrize("path", VIEWS)
def test_native_enrollment_never_invokes_foreign_getter(world, path):
    class ForeignService:
        def enrollment_diagnostics(self):
            pytest.fail("health invoked an unknown service getter")

    world[2].retained_service = ForeignService()
    enrollment = _view(world, path)["native_enrollment"]
    assert enrollment["state"] == "unavailable"
    assert enrollment["reason"] == "snapshot_unavailable"


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("kind,expected", [("missing", None), ("foreign", None), ("no_thread", False), ("dead", False), ("no_callback", False), ("stopped", False), ("running", True)])
def test_observes_actual_recovery_task_without_claiming_progress(world, path, kind, expected):
    http = world[0]
    release, started = threading.Event(), threading.Event()
    reconciler = ClaudeWakeReconciler(None, None, claim_recovery=lambda: None)
    thread = None
    if kind in {"running", "stopped", "no_callback"}:
        def hold():
            started.set()
            release.wait()
        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        assert started.wait(1)
        reconciler._thread = thread
    elif kind == "dead":
        reconciler._thread = threading.Thread(target=lambda: None)
    if kind == "no_callback":
        reconciler._claim_recovery = None
    if kind == "stopped":
        reconciler._stop.set()
    http.app.state._claude_wake_reconciler = None if kind == "missing" else object() if kind == "foreign" else reconciler
    try:
        snapshot = _view(world, path)
        assert snapshot["recovery_running"] is expected
        assert snapshot["state"] == ("unknown" if expected is None else "usable" if expected else "degraded")
        assert snapshot["last_recovery_progress_at"] is None
    finally:
        release.set()
        if thread:
            thread.join(1)
            assert not thread.is_alive()


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("outcome", ["accepted", "uncertain"])
def test_uncertain_guidance_and_terminal_precedence_through_claim_ack(world, path, outcome):
    http, storage, registry, native = world
    message_id, delivery = _send(world, outcome)
    old = registry.snapshot(delivery["recipient_endpoint_id"])
    before = _view(world, path)
    assert before["eligible_pending_count"] == 1
    assert before["reservations"][outcome] == 1
    assert before["unresolved_uncertain_count"] == (1 if outcome == "uncertain" else 0)
    assert before["uncertainty_reason"] == ("retry_held" if outcome == "uncertain" else None)
    baseline_native = len(native)
    claim = http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE})
    assert claim.status_code == 200
    claimed = claim.json()["deliveries"]
    assert len(claimed) == 1 and claimed[0]["payload"] == "A private Unicode payload 東京"
    ack = http.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"], "claim_token": claimed[0]["claim_token"], **SCOPE})
    assert ack.status_code == 200, ack.text
    observed = http.get(f"/relay/messages/{message_id}", params=SCOPE).json()["deliveries"][0]
    assert observed["state"] == "delivered" and observed["attempts"] == 1
    # Stage a valid stale fence to prove delivery state wins before cleanup.
    with storage._relay_session_factory() as db:
        if db.get(RelayCodexWakeReservationRecord, old.recipient_endpoint_id) is None:
            db.add(RelayCodexWakeReservationRecord(**asdict(old)))
            db.commit()
    after = _view(world, path)
    assert after["eligible_pending_count"] == 0
    assert after["reservations"][outcome] == 1
    assert after["unresolved_uncertain_count"] == 0 and after["uncertainty_reason"] is None
    assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE}).json()["deliveries"] == []
    assert len(native) == baseline_native


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("case,count,evidence", [("pending", 1, "complete"), ("claimed", 0, "complete"), ("expired_claim", 1, "complete"), ("expired", 0, "complete"), ("closed", 0, "complete"), ("unreachable", 0, "complete"), ("unsafe", 0, "complete"), ("missing_message", None, "incomplete"), ("missing_session", None, "incomplete"), ("runtime_mismatch", None, "incomplete"), ("scope_mismatch", None, "incomplete")])
def test_exact_pending_eligibility_and_incomplete_correlation(world, path, case, count, evidence):
    _, delivery = _send(world)
    current = datetime.now(timezone.utc)
    with world[1]._relay_session_factory() as db:
        row = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        message = db.get(RelayMessageRecord, row.message_id)
        session = db.get(RelaySessionRecord, row.recipient_endpoint_id)
        if case in {"claimed", "expired_claim"}:
            row.state, row.lease_expires_at = "claimed", current + timedelta(minutes=1 if case == "claimed" else -1)
        elif case == "expired":
            message.expires_at = current - timedelta(minutes=1)
        elif case in {"closed", "unreachable"}:
            session.state = case
        elif case == "unsafe":
            message.payload = "unsafe\x00payload"
        elif case == "missing_message":
            db.delete(message)
        elif case == "missing_session":
            db.delete(session)
        elif case == "runtime_mismatch":
            session.runtime = "claude-code"
        elif case == "scope_mismatch":
            session.container_ref = "git:example.test/other"
        db.commit()
    snapshot = _view(world, path)
    assert snapshot["eligible_pending_count"] == count
    assert snapshot["pending_evidence"] == evidence
    assert snapshot["oldest_pending_age_seconds"] is None if count != 1 else snapshot["oldest_pending_age_seconds"] >= 0


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("count", [0, 256, 257])
def test_candidate_cap_precedes_render_filtering(world, path, count):
    for _ in range(count):
        _send(world)
    if count == 257:
        with world[1]._relay_session_factory() as db:
            for message in db.query(RelayMessageRecord):
                message.payload = "unsafe\u2028payload"
            db.commit()
    snapshot = _view(world, path)
    assert snapshot["eligible_pending_count"] == (None if count == 257 else count)
    assert snapshot["pending_evidence"] == ("row_limit" if count == 257 else "complete")
    if count == 0 or count == 257:
        assert snapshot["oldest_pending_age_seconds"] is None


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("case", ["missing_delivery", "missing_message", "missing_session", "generation", "scope", "expired", "suppressed", "delivered_missing_message"])
def test_uncertain_correlation_is_unknown_unless_terminal(world, path, case):
    _, delivery = _send(world, "uncertain")
    with world[1]._relay_session_factory() as db:
        row = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        if case == "missing_delivery":
            db.delete(row)
        elif case == "missing_message":
            db.delete(db.get(RelayMessageRecord, row.message_id))
        elif case == "missing_session":
            db.delete(db.get(RelaySessionRecord, row.recipient_endpoint_id))
        elif case == "generation":
            row.codex_wake_generation = 999
        elif case == "scope":
            db.get(RelaySessionRecord, row.recipient_endpoint_id).container_ref = "git:example.test/other"
        elif case == "expired":
            db.get(RelayMessageRecord, row.message_id).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        elif case == "delivered_missing_message":
            row.state = "delivered"
            db.delete(db.get(RelayMessageRecord, row.message_id))
        else:
            row.state = "suppressed"
        db.commit()
    snapshot = _view(world, path)
    terminal = case in {"expired", "suppressed", "delivered_missing_message"}
    assert snapshot["reservations"]["uncertain"] == 1
    assert snapshot["unresolved_uncertain_count"] == (0 if terminal else None)
    assert snapshot["uncertainty_evidence"] == ("complete" if terminal else "incomplete")
    assert snapshot["uncertainty_reason"] == (None if terminal else "evidence_incomplete")


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("state", ["pending", "claimed", "delivered", "expired", "suppressed"])
def test_uncertain_delivery_scope_must_match_unless_terminal(world, path, state):
    _, delivery = _send(world, "uncertain")
    with world[1]._relay_session_factory() as db:
        row = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        session = db.get(RelaySessionRecord, row.recipient_endpoint_id)
        reservation = db.get(RelayCodexWakeReservationRecord, row.recipient_endpoint_id)
        assert session.container_ref == reservation.container_ref == SCOPE["container_ref"]
        row.state = state
        row.recipient_container_ref = "git:example.test/other"
        db.commit()
    snapshot = _view(world, path)
    terminal = state in {"delivered", "expired", "suppressed"}
    assert snapshot["reservations"]["uncertain"] == 1
    assert snapshot["unresolved_uncertain_count"] == (0 if terminal else None)
    assert snapshot["uncertainty_evidence"] == ("complete" if terminal else "incomplete")
    assert snapshot["uncertainty_reason"] == (None if terminal else "evidence_incomplete")


@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("count", [0, 256, 257])
def test_reservation_authority_bound_is_observed_without_weakening_validation(world, path, count):
    with world[1]._relay_session_factory() as db:
        db.get(RelayCodexWakeStateRecord, 1).generation = count
        for index in range(count):
            suffix = f"{index:032x}"
            db.add(RelayCodexWakeReservationRecord(recipient_endpoint_id=f"relay-session-{suffix}", delivery_id=f"relay-delivery-{suffix}", session_ref=f"target-{index}", container_ref=SCOPE["container_ref"], generation=index + 1, outcome="accepted"))
        db.commit()
    snapshot = _view(world, path)
    assert snapshot["authority_initialized"] is (None if count > 256 else True)
    assert snapshot["reservations"] == (None if count > 256 else {"prepared": 0, "reserved": 0, "accepted": count, "uncertain": 0})


@pytest.mark.parametrize("path", VIEWS)
def test_malformed_authority_is_unknown_without_private_errors(world, path):
    with world[1]._relay_session_factory() as db:
        db.get(RelayCodexWakeStateRecord, 1).generation = -1
        db.commit()
    snapshot = _view(world, path)
    assert snapshot["state"] == "unknown" and snapshot["reason"] == "authority_unavailable"
    assert snapshot["reservations"] is None and snapshot["eligible_pending_count"] is None
    assert snapshot["unresolved_uncertain_count"] is None


@pytest.mark.parametrize("path", VIEWS)
def test_failed_snapshot_read_is_unknown_and_bounded(world, path, monkeypatch):
    def denied(**kwargs):
        raise RuntimeError("private-path private-payload private-scope")
    monkeypatch.setattr(world[1], "relay_codex_wake_health", denied)
    snapshot = _view(world, path)
    assert snapshot["state"] == "unknown" and snapshot["authority_initialized"] is None
    assert snapshot["pending_evidence"] == "unavailable" and snapshot["reservations"] is None
    assert "private-" not in json.dumps(snapshot)


@pytest.mark.parametrize("path", VIEWS)
def test_status_does_not_take_native_guard_or_mutate_delivery(world, path):
    _, delivery = _send(world, "uncertain")
    http, _, registry, native = world
    before = registry.reservations()
    baseline_native = len(native)
    release, held = threading.Event(), threading.Event()
    def own_native():
        with registry._lock:
            held.set()
            release.wait()
    owner = threading.Thread(target=own_native, daemon=True)
    owner.start()
    assert held.wait(1)
    # Separate caller avoids a hanging test if health accidentally takes the guard.
    result, errors, phases, done = [], [], [], threading.Event()
    def observe():
        try:
            phases.append(("request_started", time.monotonic()))
            response = http.get(path)
            phases.append(("http_returned", time.monotonic()))
            assert response.status_code == 200, response.text
            snapshot = response.json()["relay_wake"]
            _assert_snapshot_shape(snapshot)
            result.append(snapshot)
            phases.append(("view_validated", time.monotonic()))
        except BaseException:
            errors.append(traceback.format_exc(limit=12))
        finally:
            done.set()
    reader = threading.Thread(target=observe, daemon=True)
    phases.append(("reader_start", time.monotonic()))
    reader.start()
    try:
        completed = done.wait(2)
        diagnostics = None
        if not completed:
            frames = sys._current_frames()
            threads = sorted(threading.enumerate(), key=lambda thread: (
                thread not in (reader, owner),
                not any(name in thread.name.lower() for name in ("anyio", "portal")),
            ))[:12]
            diagnostics = {
                "phases": list(phases), "errors": list(errors),
                "stacks": {
                    f"{thread.name}:{thread.ident}": "".join(traceback.format_stack(frames[thread.ident], limit=12))[-4096:]
                    for thread in threads if thread.ident in frames
                },
            }
        assert completed, f"status waited for native initiation ownership: {diagnostics}"
        assert not errors, errors
        assert result[0]["unresolved_uncertain_count"] == 1
    finally:
        release.set()
        owner.join(2)
        reader.join(2)
    assert not owner.is_alive() and not reader.is_alive()
    assert registry.reservations() == before and len(native) == baseline_native
    status = http.get(f"/relay/messages/{delivery['message_id']}", params=SCOPE).json()["deliveries"][0]
    assert status["state"] == "pending" and status["attempts"] == 0


def test_wake_health_ui_executes_shipped_javascript():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", str(repo / "tests/dashboard_relay_wake_health_ui.mjs"), str(repo / "app/dashboard.html")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
