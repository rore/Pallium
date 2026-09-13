from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app import claude_wake, codex_wake
from core.claude_wake import ClaudeWakeRegistry
from core.codex_wake import CodexWakeRegistry
from core.errors import is_transient_error
from core.relay import RelayService
from core.relay_activation import ActivationAttemptResult
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import RelayDeliveryRecord, RelayDeliveryTraceRecord


@pytest.fixture(autouse=True)
def clear_adapter_trace_state():
    with codex_wake._scheduled_lock:
        codex_wake._scheduled_delivery_ids.clear()
        codex_wake._scheduled_session_generations.clear()
        codex_wake._scheduled_session_delivery_ids.clear()
        codex_wake._scheduled_session_attempt_ids.clear()
    with claude_wake._workers_lock:
        claude_wake._workers.clear()
        claude_wake._worker_attempt_ids.clear()
    yield
    with codex_wake._scheduled_lock:
        codex_wake._scheduled_delivery_ids.clear()
        codex_wake._scheduled_session_generations.clear()
        codex_wake._scheduled_session_delivery_ids.clear()
        codex_wake._scheduled_session_attempt_ids.clear()
    with claude_wake._workers_lock:
        claude_wake._workers.clear()
        claude_wake._worker_attempt_ids.clear()


@pytest.fixture
def relay(tmp_path):
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'main.db'}")
    service = RelayService(storage)
    service.turn(runtime="codex", session_ref="sender", container_ref="git:test")
    receiver = service.turn(
        runtime="codex", session_ref="receiver", container_ref="git:test"
    )
    yield storage, service, receiver["session"]["endpoint_id"]
    storage.close()


def _message(service, payload="hello", recipient="codex:receiver"):
    return service.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient=recipient,
        payload=payload,
        container_ref="git:test",
    )


def _event(storage, message, attempt, stage, **extra):
    delivery = message["deliveries"][0]["delivery_id"]
    return storage.relay_trace_record(
        attempt_id=attempt,
        delivery_id=delivery,
        stage=stage,
        recorded_at=datetime.now(timezone.utc),
        **extra,
    )


def _completion(**overrides):
    values = {
        "outcome": "accepted",
        "reason": "transport_accepted",
        "evidence": ["submission_attempted", "transport_accepted"],
        "native_retry_safe": False,
    }
    values.update(overrides)
    return values


def test_trace_full_delivery_lifecycle_is_nonmutating_and_payload_free(relay):
    storage, service, _ = relay
    message = _message(service, "שלום 🌍 password=supersecret")
    attempt = "relay-activation-" + "a" * 32
    assert _event(storage, message, attempt, "prepared")["recorded"]
    assert _event(storage, message, attempt, "completed", **_completion())["recorded"]

    claimed = service.turn(
        runtime="codex", session_ref="receiver", container_ref="git:test"
    )["deliveries"][0]
    service.acknowledge(
        delivery_id=claimed["delivery_id"],
        claim_token=claimed["claim_token"],
        container_ref="git:test",
    )
    trace = service.trace_message(message_id=message["message_id"])

    assert [event["stage"] for event in trace["events"]] == [
        "prepared",
        "completed",
    ]
    assert trace["delivery_snapshots"][0]["state"] == "delivered"
    assert trace["delivery_snapshots"][0]["trace_version"] == 1
    assert trace["legacy"] is False
    assert trace["delivery_snapshots"][0]["attempts"] == 1
    assert trace["explanation"].startswith("Delivered to the recipient session")
    assert "שלום" not in str(trace) and "supersecret" not in str(trace)


def test_shared_attempt_completion_is_visible_to_every_associated_delivery(relay):
    storage, service, _ = relay
    first = _message(service)
    second = _message(service)
    attempt = "relay-activation-" + "b" * 32

    _event(storage, first, attempt, "prepared")
    _event(storage, second, attempt, "associated")
    _event(storage, first, attempt, "completed", **_completion())

    trace = service.trace_message(message_id=second["message_id"])
    assert [event["stage"] for event in trace["events"]] == [
        "prepared",
        "associated",
        "completed",
    ]
    assert len({event["attempt_id"] for event in trace["events"]}) == 1


def test_duplicate_conflict_and_completion_before_association(relay):
    storage, service, _ = relay
    message = _message(service)
    attempt = "relay-activation-" + "c" * 32
    failed = _completion(
        outcome="failed",
        reason="transport_failed",
        evidence=[],
        native_retry_safe=True,
    )
    first = _event(storage, message, attempt, "completed", **failed)
    duplicate = _event(storage, message, attempt, "completed", **failed)
    conflict = _event(
        storage,
        message,
        attempt,
        "completed",
        **_completion(
            outcome="uncertain",
            reason="transport_failed",
            evidence=[],
            native_retry_safe=False,
        ),
    )

    assert first["recorded"] and duplicate["duplicate"] and conflict["conflict"]
    assert _event(storage, message, attempt, "associated")["recorded"]
    assert [
        event["stage"]
        for event in service.trace_message(message_id=message["message_id"])[
            "events"
        ]
    ] == ["completed", "associated"]


def test_trace_validation_redaction_and_nonmutating_expired_read(relay):
    storage, service, _ = relay
    message = service.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient="codex:receiver",
        payload="secret token=payload-secret",
        container_ref="git:test",
        expires_in_seconds=60,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    delivery = message["deliveries"][0]
    before = dict(delivery)
    attempt = "relay-activation-" + "d" * 32
    secret = "ghp_" + "A" * 36
    _event(
        storage,
        message,
        attempt,
        "completed",
        **_completion(reason=f"api_key={secret}"),
    )

    trace = storage.relay_trace_message(
        message_id=message["message_id"],
        now=datetime(2020, 1, 1, 0, 2, tzinfo=timezone.utc),
    )
    assert trace["delivery_snapshots"][0]["state"] == "expired"
    assert secret not in str(trace) and "[REDACTED]" in trace["events"][0]["reason"]
    with storage._relay_session_factory() as db:
        row = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        assert row.state == before["state"] and row.claim_token == before["claim_token"]
    with pytest.raises(ValueError):
        storage.relay_trace_record(
            attempt_id="bad", delivery_id=delivery["delivery_id"], stage="prepared"
        )
    with pytest.raises(ValueError):
        _event(
            storage,
            message,
            "relay-activation-" + "e" * 32,
            "completed",
            **_completion(reason="line\nbreak"),
        )


def test_trace_paging_freezes_later_appends(relay):
    storage, service, _ = relay
    message = _message(service)
    attempt = "relay-activation-" + "f" * 32
    _event(storage, message, attempt, "prepared")
    upper = service.trace_message(message_id=message["message_id"])["as_of_sequence"]
    _event(
        storage,
        message,
        attempt,
        "completed",
        **_completion(
            outcome="deferred",
            reason="worker_error",
            evidence=[],
            native_retry_safe=True,
        ),
    )

    page = service.trace_message(
        message_id=message["message_id"], limit=1, as_of_sequence=upper
    )
    assert len(page["events"]) == 1 and page["has_more"] is False
    assert page["next_sequence"] == page["events"][0]["sequence"]
    with pytest.raises(ValueError):
        service.trace_message(
            message_id=message["message_id"],
            after_sequence=upper + 1,
            as_of_sequence=upper,
        )


def test_trace_bound_checks_do_not_reserve_the_correctness_writer(relay):
    storage, service, _ = relay
    message = _message(service)
    reached = threading.Event()
    release = threading.Event()
    trace_errors = []

    def pause_trace_read(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        if (
            threading.current_thread().name == "trace-contention-test"
            and "count(" in statement.lower()
            and "relay_delivery_trace" in statement.lower()
            and not reached.is_set()
        ):
            reached.set()
            assert release.wait(timeout=2)

    def record_trace():
        try:
            _event(
                storage,
                message,
                "relay-activation-" + "8" * 32,
                "prepared",
            )
        except Exception as exc:
            trace_errors.append(exc)

    event.listen(storage._relay_engine, "before_cursor_execute", pause_trace_read)
    worker = threading.Thread(target=record_trace, name="trace-contention-test")
    worker.start()
    try:
        assert reached.wait(timeout=2)
        result = service.turn(
            runtime="codex", session_ref="receiver", container_ref="git:test"
        )
        assert result["session"]["session_ref"] == "receiver"
    finally:
        release.set()
        worker.join(timeout=2)
        event.remove(storage._relay_engine, "before_cursor_execute", pause_trace_read)
    assert not worker.is_alive()
    assert all(is_transient_error(exc) for exc in trace_errors)


def test_trace_per_delivery_and_association_caps_mark_truncation(relay):
    storage, service, _ = relay
    message = _message(service)
    for index in range(8):
        attempt = f"relay-activation-{index:032x}"
        _event(storage, message, attempt, "prepared")
        _event(storage, message, attempt, "associated")
        _event(
            storage,
            message,
            attempt,
            "completed",
            **_completion(
                outcome="deferred",
                reason="worker_error",
                evidence=[],
                native_retry_safe=True,
            ),
        )
    assert _event(
        storage,
        message,
        "relay-activation-ffffffffffffffffffffffffffffffff",
        "prepared",
    )["dropped"]
    trace = service.trace_message(message_id=message["message_id"])
    assert len(trace["events"]) == 24 and trace["truncated"]

    shared_attempt = "relay-activation-" + "9" * 32
    messages = [_message(service) for _ in range(65)]
    _event(storage, messages[0], shared_attempt, "prepared")
    for associated in messages[1:64]:
        assert _event(storage, associated, shared_attempt, "associated")["recorded"]
    assert _event(storage, messages[64], shared_attempt, "associated")["dropped"]
    assert service.trace_message(message_id=messages[64]["message_id"])["truncated"]


def test_legacy_schema_reopens_and_separate_relay_database_stays_isolated(tmp_path):
    main = tmp_path / "legacy.db"
    first = SQLiteStorageProvider(f"sqlite:///{main}")
    with first._engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE relay_delivery_trace")
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_relay_trace_message_sequence")
        connection.exec_driver_sql("ALTER TABLE relay_deliveries DROP COLUMN trace_pruned")
    first.close()

    migrated = SQLiteStorageProvider(f"sqlite:///{main}")
    with migrated._engine.connect() as connection:
        assert migrated._engine.dialect.has_table(connection, "relay_delivery_trace")
        columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(relay_deliveries)"
            )
        }
    assert {"trace_version", "trace_truncated", "trace_pruned"} <= columns
    migrated.close()

    isolated_main = tmp_path / "main.db"
    relay_db = tmp_path / "relay.db"
    storage = SQLiteStorageProvider(
        f"sqlite:///{isolated_main}", relay_database_url=f"sqlite:///{relay_db}"
    )
    service = RelayService(storage)
    service.turn(runtime="codex", session_ref="s", container_ref="git:test")
    service.turn(runtime="codex", session_ref="r", container_ref="git:test")
    message = service.send(
        sender_runtime="codex",
        sender_session_ref="s",
        recipient="codex:r",
        payload="x",
        container_ref="git:test",
    )
    assert service.trace_message(message_id=message["message_id"])["legacy"] is False
    delivery_id = message["deliveries"][0]["delivery_id"]
    with storage._relay_session_factory.begin() as db:
        db.get(RelayDeliveryRecord, delivery_id).trace_version = None
    assert service.trace_message(message_id=message["message_id"])["legacy"] is True
    with storage._engine.connect() as main_connection:
        assert not storage._engine.dialect.has_table(
            main_connection, "relay_delivery_trace"
        )
    with storage._relay_engine.connect() as relay_connection:
        assert storage._relay_engine.dialect.has_table(
            relay_connection, "relay_delivery_trace"
        )
    storage.close()


def test_claude_scheduler_coalesces_one_attempt_and_forwards_completion(relay, monkeypatch):
    storage, service, endpoint = relay
    service.turn(
        runtime="claude-code", session_ref="claude", container_ref="git:test"
    )
    first = _message(service, recipient="claude-code:claude")
    second = _message(service, recipient="claude-code:claude")
    registry = ClaudeWakeRegistry()
    assert registry.register(
        runtime="claude-code",
        session_ref="claude",
        container_ref="git:test",
        socket_path="local-socket",
        token="local-token",
        idle=True,
    )
    started = threading.Event()
    release = threading.Event()
    calls = []

    def transport(*_args):
        calls.append(True)
        started.set()
        assert release.wait(timeout=2)
        return "accepted"

    monkeypatch.setattr(claude_wake, "claude_wake_transport", transport)
    events = []
    worker = claude_wake.schedule_claude_relay_wake(
        first,
        {"container_ref": "git:test"},
        registry=registry,
        relay_service=service,
        trace_callback=events.append,
    )
    assert worker is not None and started.wait(timeout=2)
    assert (
        claude_wake.schedule_claude_relay_wake(
            second,
            {"container_ref": "git:test"},
            registry=registry,
            relay_service=service,
            trace_callback=events.append,
        )
        is None
    )
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive() and calls == [True]
    assert [event["stage"] for event in events] == [
        "prepared",
        "associated",
        "completed",
    ]
    assert len({event["attempt_id"] for event in events}) == 1
    for event in events:
        assert storage.relay_record_trace_event(event)
    assert service.trace_message(message_id=second["message_id"])["events"][-1][
        "outcome"
    ] == "accepted"
    assert endpoint


def test_codex_scheduler_coalesces_without_starting_another_worker(relay, monkeypatch):
    _storage, service, _endpoint = relay
    first = _message(service)
    second = _message(service)
    registry = CodexWakeRegistry()
    events = []

    class ParkedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(codex_wake.threading, "Thread", ParkedThread)
    worker = codex_wake.schedule_codex_relay_wake(
        first,
        {"container_ref": "git:test"},
        registry=registry,
        relay_service=service,
        trace_callback=events.append,
    )
    assert worker is not None
    assert (
        codex_wake.schedule_codex_relay_wake(
            second,
            {"container_ref": "git:test"},
            registry=registry,
            relay_service=service,
            trace_callback=events.append,
        )
        is None
    )
    assert [event["stage"] for event in events] == ["prepared", "associated"]
    assert events[0]["attempt_id"] == events[1]["attempt_id"]
    assert codex_wake.release_codex_relay_wake(
        first["deliveries"][0]["delivery_id"], registry=registry
    )


def test_worker_start_failure_emits_deferred_without_native_attempt(relay, monkeypatch):
    _storage, service, _endpoint = relay
    message = _message(service)
    delivery = message["deliveries"][0]
    events = []
    reservation = SimpleNamespace(
        generation=1,
        delivery_id=delivery["delivery_id"],
        recipient_endpoint_id=delivery["recipient_endpoint_id"],
        session_ref="receiver",
        container_ref="git:test",
    )

    class Registry:
        def reserve(self, **_kwargs):
            return reservation

        def release_generation(self, _value):
            return True

    class FailingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("start failed")

    monkeypatch.setattr(codex_wake.threading, "Thread", FailingThread)
    assert (
        codex_wake.schedule_codex_relay_wake(
            {"recipient": "codex:receiver", "deliveries": [delivery]},
            {"container_ref": "git:test"},
            relay_service=service,
            registry=Registry(),
            trace_callback=events.append,
        )
        is None
    )
    assert [event["stage"] for event in events] == ["prepared", "completed"]
    assert events[-1]["outcome"] == "deferred"


def test_api_and_dashboard_share_projection_and_unknown_is_404(client):
    storage = client.app.state.pallium_service._storage
    scope = "git:example.test/team/relay-trace"
    for session in ("sender-trace", "receiver-trace"):
        assert (
            client.post(
                "/relay/turn",
                json={
                    "runtime": "codex",
                    "session_ref": session,
                    "container_ref": scope,
                },
            ).status_code
            == 200
        )
    response = client.post(
        "/relay/messages",
        json={
            "sender_runtime": "codex",
            "sender_session_ref": "sender-trace",
            "recipient": "codex:receiver-trace",
            "payload": "x",
            "container_ref": scope,
        },
    )
    message = response.json()
    assert storage.relay_record_trace_event(
        {
            "attempt_id": "relay-activation-" + "1" * 32,
            "delivery_id": message["deliveries"][0]["delivery_id"],
            "stage": "prepared",
        }
    )

    api = client.get(f"/relay/messages/{message['message_id']}/trace")
    dashboard = client.get(
        f"/dashboard/api/relay/messages/{message['message_id']}/trace"
    )
    assert api.status_code == dashboard.status_code == 200
    assert api.json() == dashboard.json()
    unknown = "relay-msg-" + "0" * 32
    assert client.get(f"/relay/messages/{unknown}/trace").status_code == 404
    assert (
        client.get(f"/dashboard/api/relay/messages/{unknown}/trace").status_code
        == 404
    )


def test_mcp_cursor_and_budget_trim_preserve_truthful_continuation():
    from app.mcp.server import _MCP_RELAY_MAX_CHARS, _relay_trace_cursor, _relay_trace_text

    assert _relay_trace_cursor(None) == (0, None)
    assert _relay_trace_cursor("12:4") == (4, 12)
    assert _relay_trace_cursor("bad") is None
    assert _relay_trace_cursor("12:-1") is None
    assert _relay_trace_cursor("4:12") is None
    assert _relay_trace_cursor("9999999999999999999:0") is None
    events = [
        {"sequence": index, "stage": "completed", "reason": "x" * 128}
        for index in range(1, 21)
    ]
    rendered = _relay_trace_text(
        {
            "contract": "relay-delivery-trace/v1",
            "events": events,
            "delivery_snapshots": [],
            "as_of_sequence": 20,
            "has_more": False,
        },
        0,
    )
    page = json.loads(rendered)
    assert len(rendered) <= _MCP_RELAY_MAX_CHARS
    assert 0 < len(page["events"]) < len(events)
    assert page["has_more"] is True
    assert page["next_cursor"] == f"20:{page['events'][-1]['sequence']}"
    assert _relay_trace_cursor(page["next_cursor"]) == (
        page["events"][-1]["sequence"],
        20,
    )


def test_cleanup_marks_every_known_associate_and_discloses_page_gap(relay):
    storage, service, _ = relay
    first = _message(service)
    second = _message(service)
    attempt = "relay-activation-" + "2" * 32
    old = datetime.now(timezone.utc) - timedelta(days=31)
    storage.relay_trace_record(
        attempt_id=attempt,
        delivery_id=first["deliveries"][0]["delivery_id"],
        stage="prepared",
        recorded_at=old,
    )
    storage.relay_trace_record(
        attempt_id=attempt,
        delivery_id=second["deliveries"][0]["delivery_id"],
        stage="associated",
        recorded_at=datetime.now(timezone.utc),
    )
    assert storage.relay_cleanup_trace(now=datetime.now(timezone.utc), limit=1) == 1

    with storage._relay_session_factory() as db:
        assert (
            db.query(RelayDeliveryTraceRecord)
            .filter(RelayDeliveryTraceRecord.stage == "prepared")
            .count()
            == 0
        )
        rows = db.query(RelayDeliveryRecord).filter(
            RelayDeliveryRecord.id.in_(
                [
                    first["deliveries"][0]["delivery_id"],
                    second["deliveries"][0]["delivery_id"],
                ]
            )
        )
        assert all(row.trace_pruned == 1 for row in rows)
    trace = service.trace_message(message_id=second["message_id"])
    assert trace["pruned"] and trace["gap"]


def test_trace_writer_failure_is_best_effort_and_releases_slot(client):
    service = client.app.state.pallium_service
    called = threading.Event()

    def fail(_event):
        called.set()
        raise RuntimeError("diagnostic storage unavailable")

    assert service.enqueue_relay_trace_event(fail, {"stage": "prepared"})
    assert called.wait(timeout=2)
    completed = threading.Event()
    assert service.enqueue_relay_trace_event(
        lambda _event: completed.set(), {"stage": "prepared"}
    )
    assert completed.wait(timeout=2)

def test_pruning_never_reuses_a_frozen_sequence(relay):
    storage, service, _ = relay
    message = _message(service)
    first = storage.relay_trace_record(
        attempt_id="relay-activation-" + "3" * 32,
        delivery_id=message["deliveries"][0]["delivery_id"],
        stage="prepared",
        recorded_at=datetime.now(timezone.utc) - timedelta(days=31),
    )
    assert storage.relay_cleanup_trace(now=datetime.now(timezone.utc), limit=64) == 1
    second = storage.relay_trace_record(
        attempt_id="relay-activation-" + "4" * 32,
        delivery_id=message["deliveries"][0]["delivery_id"],
        stage="prepared",
    )
    assert second["sequence"] > first["sequence"]
    frozen = service.trace_message(
        message_id=message["message_id"], as_of_sequence=first["sequence"]
    )
    assert frozen["events"] == [] and frozen["pruned"] and frozen["gap"]


def test_cleanup_frees_space_at_exact_global_capacity(relay, monkeypatch):
    import storage.sqlite_relay as sqlite_relay
    import storage.sqlite_retention as sqlite_retention

    storage, service, _ = relay
    monkeypatch.setattr(sqlite_relay, "RELAY_TRACE_MAX_ROWS", 1)
    monkeypatch.setattr(sqlite_retention, "RELAY_TRACE_MAX_ROWS", 1)
    first = _message(service)
    second = _message(service)
    attempt = "relay-activation-" + "5" * 32
    assert _event(storage, first, attempt, "prepared")["recorded"]
    assert _event(storage, second, "relay-activation-" + "6" * 32, "prepared")[
        "dropped"
    ]
    assert storage.relay_cleanup_trace(now=datetime.now(timezone.utc), limit=1) == 1
    assert _event(storage, second, "relay-activation-" + "6" * 32, "prepared")[
        "recorded"
    ]


def test_direct_claude_recovery_emits_persistable_trace(relay, monkeypatch):
    storage, service, _ = relay
    service.turn(
        runtime="claude-code", session_ref="recovered", container_ref="git:test"
    )
    message = _message(service, recipient="claude-code:recovered")
    registry = ClaudeWakeRegistry()
    assert registry.register(
        runtime="claude-code",
        session_ref="recovered",
        container_ref="git:test",
        socket_path="local-socket",
        token="local-token",
        idle=True,
    )
    monkeypatch.setattr(claude_wake, "claude_wake_transport", lambda *_args: "accepted")
    events = []
    completed = threading.Event()

    def trace(event):
        events.append(event)
        if event["stage"] == "completed":
            completed.set()

    claude_wake.recover_claude_relay_wakes(
        registry, service, trace_callback=trace
    )
    assert completed.wait(timeout=2)
    assert [event["stage"] for event in events] == ["prepared", "completed"]
    for event in events:
        assert storage.relay_record_trace_event(event)
    result = service.trace_message(message_id=message["message_id"])
    assert result["events"][-1]["outcome"] == "accepted"


def test_mcp_compacts_long_snapshot_without_losing_the_only_event():
    from app.mcp.server import _MCP_RELAY_MAX_CHARS, _relay_trace_text

    event = {
        "sequence": 1,
        "attempt_id": "relay-activation-" + "7" * 32,
        "delivery_id": "relay-delivery-" + "8" * 32,
        "stage": "completed",
        "outcome": "uncertain",
        "reason": "transport_uncertain",
        "evidence": ["submission_attempted"],
        "native_retry_safe": False,
        "destination_health_update": None,
        "scope_generation": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot = {
        "delivery_id": event["delivery_id"],
        "state": "pending",
        "stored_state": "pending",
        "attempts": 0,
        "claimed_at": None,
        "lease_expires_at": None,
        "delivered_at": None,
        "recipient_runtime": "codex",
        "recipient_session_ref": "s" * 255,
        "recipient_endpoint_id": "relay-session-" + "9" * 32,
        "recipient_container_ref": "git:" + "c" * 700,
        "recipient_endpoint_state": "active",
        "trace_version": 1,
        "trace_truncated": False,
        "trace_pruned": False,
    }
    result = {
        "contract": "relay-delivery-trace/v1",
        "message_id": "relay-msg-" + "a" * 32,
        "events": [event],
        "delivery_snapshots": [snapshot],
        "next_sequence": 1,
        "as_of_sequence": 1,
        "has_more": False,
        "completeness": "best_effort",
        "legacy": False,
        "absent": False,
        "truncated": False,
        "pruned": False,
        "gap": False,
        "explanation": "Native activation outcome is uncertain; do not resend.",
    }
    assert len(json.dumps(result, separators=(",", ":"))) > _MCP_RELAY_MAX_CHARS
    rendered = _relay_trace_text(result, 0)
    page = json.loads(rendered)
    assert len(rendered) <= _MCP_RELAY_MAX_CHARS
    assert page["events"] == [event]
    assert "recipient_container_ref" in page["snapshot_fields_omitted"]