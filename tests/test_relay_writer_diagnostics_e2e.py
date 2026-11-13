"""Caller-visible diagnostics: real storage settlement and bounded HTTP metadata.

These observations describe one provider/process. They are not authenticated
cross-process identity, filesystem identity, or transaction authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import re

import pytest
from sqlalchemy import event

from tests.test_retention import _make_source, _TEST_RETENTION_POLICY


@pytest.mark.parametrize("outcome", ("commit", "rollback"))
def test_retention_real_binding_chain_logs_after_settlement_and_listener_cleanup(
    client, monkeypatch, caplog, outcome,
):
    import storage.sqlite_retention as retention_module
    from storage.sqlite_queue import SQLiteQueueMixin

    storage = client.app.state.pallium_service._storage
    # Do not replace the producer: this is the real provider/MRO consumer chain.
    producer = getattr(type(storage), "_main_db_diagnostic_binding", None)
    assert producer is not None, "retention requires its genuine production binding producer"
    assert producer is SQLiteQueueMixin._main_db_diagnostic_binding
    binding = storage._main_db_diagnostic_binding()
    assert re.fullmatch(r"db-[0-9a-f]{64}", binding)
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    source = _make_source(storage, source_id="settlement-東京", occurred_at=now-timedelta(days=90))
    installed, removed, calls, checked_in = [], [], [], []
    native_warning = retention_module.logger.warning
    failure = RuntimeError("controlled failure after source mutation")
    native_cascade = storage._delete_source_item_cascade_in_session

    def listen(target, name, callback, **kwargs):
        installed.append((target, name, callback))
        event.listen(target, name, callback, **kwargs)

    def remove(target, name, callback):
        event.remove(target, name, callback)
        removed.append((target, name, callback))

    def checkin(connection, _record):
        if connection is not None:
            checked_in.append(connection.in_transaction)

    def warning(message, *args):
        # Capture outside assertions: the production diagnostic correctly contains failures.
        calls.append({"message": message, "args": args,
                      "transactions": [s.in_transaction() for s, _, _ in installed],
                      "listeners": [event.contains(*item) for item in installed],
                      "removed": list(removed), "checked_in": list(checked_in)})
        native_warning(message, *args)

    def fail_after_mutation(*args, **kwargs):
        native_cascade(*args, **kwargs)
        raise failure

    event.listen(storage._engine.pool, "checkin", checkin)
    try:
        monkeypatch.setattr(retention_module, "event", SimpleNamespace(listen=listen, remove=remove))
        monkeypatch.setattr(retention_module.logger, "warning", warning)
        if outcome == "rollback":
            monkeypatch.setattr(storage, "_delete_source_item_cascade_in_session", fail_after_mutation)
        with caplog.at_level("WARNING", logger="storage.sqlite_retention"):
            if outcome == "rollback":
                with pytest.raises(RuntimeError) as raised:
                    storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
                assert raised.value is failure
            else:
                result = storage.run_retention_pass(now=now, batch_size=1, retention_policy=_TEST_RETENTION_POLICY)
                assert result.deleted_source_items == 1
        assert len(calls) == 1 and len(installed) == 2
        call = calls[0]
        assert call["transactions"] == [False, False]
        assert call["listeners"] == [False, False] and call["removed"] == installed
        assert call["checked_in"] and not any(call["checked_in"])
        assert call["args"][1] == binding and call["args"][5] == outcome
        assert storage._main_db_diagnostic_binding.__func__ is producer
        assert storage._main_db_diagnostic_binding() == binding
        emitted = [r.getMessage() for r in caplog.records if "sqlite_main_writer role=source_retention" in r.getMessage()]
        assert len(emitted) == 1 and binding in emitted[0]
        assert str(storage._engine.url.database) not in emitted[0]
        assert source.content not in emitted[0] and source.source_id not in emitted[0]
        assert removed == installed and all(not event.contains(*item) for item in installed)
        if outcome == "rollback":
            assert storage.get_source_item(source.id).id == source.id
            assert any(hit.target_id == source.id for hit in storage.search_index_entries(["content"], limit=10).hits)
        else:
            with pytest.raises(KeyError):
                storage.get_source_item(source.id)
            assert not storage.search_index_entries(["content"], limit=10).hits
    finally:
        event.remove(storage._engine.pool, "checkin", checkin)
        for item in installed:
            if event.contains(*item):
                event.remove(*item)


@pytest.mark.parametrize("url", (
    "sqlite:///:memory:", "sqlite://", "sqlite:///file:private.db",
    "sqlite:///opaque.db?uri=true", "postgresql://localhost/example",
))
def test_real_binding_producer_declines_unsupported_bindings_without_identity_probes(url):
    from sqlalchemy.engine import make_url
    from storage.sqlite_queue import SQLiteQueueMixin

    owner = SimpleNamespace(_engine=SimpleNamespace(url=make_url(url)))
    assert SQLiteQueueMixin._main_db_diagnostic_binding(owner) == "unknown"


def test_writer_context_restores_nested_frames_and_never_revives_closed_copies():
    from contextvars import copy_context
    from core.errors import _relay_writer_context, _relay_writer_operation, _relay_writer_operation_name

    failure = RuntimeError("controlled nested failure")
    with _relay_writer_context("turn"):
        parent = _relay_writer_operation.get()
        assert _relay_writer_operation_name() == "turn"
        copied = copy_context()
        with pytest.raises(RuntimeError) as raised:
            with _relay_writer_context("ack"):
                child = _relay_writer_operation.get()
                assert _relay_writer_operation_name() == "ack" and parent["active"] is False
                raise failure
        assert raised.value is failure
        assert child["active"] is False and child["open"] is False
        assert _relay_writer_operation.get() is parent and _relay_writer_operation_name() == "turn"
    assert parent["active"] is False and parent["open"] is False
    assert copied.run(_relay_writer_operation_name) == "unknown"
    assert _relay_writer_operation_name() == "unknown"


@pytest.mark.parametrize("field,value", (
    ("owner_id", True), ("owner_id", 0), ("owner_id", 2**53),
    ("operation", "private-東京"), ("phase", "private-phase"),
    ("held_ms_lower_bound", -1), ("held_ms_lower_bound", 604_800_001),
    ("held_ms_lower_bound", True), ("phase_ms_lower_bound", 2),
    ("extra", "unbounded-private-value"),
))
def test_writer_observation_rejects_malformed_or_out_of_range_fields(field, value):
    from core.errors import ImmediateTransactionBusyError, _relay_writer_observation

    error = ImmediateTransactionBusyError("controlled primary", acquisition_stage="local_gate")
    error.observed_relay_writer = {"owner_id": 1, "operation": "turn", "phase": "transaction",
                                   "held_ms_lower_bound": 1, "phase_ms_lower_bound": 1}
    error.observed_relay_writer[field] = value
    assert _relay_writer_observation(error) == "unknown"


@pytest.mark.parametrize("owner,age", ((1, 0), (2**53-1, 604_800_000), (1, "over_limit")))
def test_writer_observation_accepts_bounded_edges_only_at_local_gate(owner, age):
    from core.errors import ImmediateTransactionBusyError, _relay_writer_observation

    view = {"owner_id": owner, "operation": "turn", "phase": "transaction",
            "held_ms_lower_bound": age, "phase_ms_lower_bound": age}
    error = ImmediateTransactionBusyError("controlled primary", acquisition_stage="local_gate")
    error.observed_relay_writer = view
    assert _relay_writer_observation(error) == view
    for stage in (None, "retry_exhausted", "private-東京"):
        error.acquisition_stage = stage
        assert _relay_writer_observation(error) == "unknown"


@pytest.mark.parametrize("value", (True, -1, 604_800_001, 1.5, "private-東京", None))
def test_turn_body_projection_does_not_publish_invalid_intervals(value):
    from core.errors import _relay_turn_body_fields

    body = {"state": "inflight", "current_site": "candidate_fetch", "slowest_site": "none",
            "current_site_ms_lower_bound": 0, "body_ms_lower_bound": 0,
            "holder_cpu_ms_through_sample": "unknown", "cpu_sample_age_ms_lower_bound": 0,
            "slowest_site_ms_lower_bound": 0, "slowest_site_cpu_ms_between_samples": "unknown"}
    body["body_ms_lower_bound"] = value
    assert _relay_turn_body_fields(body) == "unknown"


@pytest.mark.parametrize("flags", (
    {"flush_entered": False, "flush_returned": True, "cursor_entered": False, "cursor_returned": False},
    {"flush_entered": False, "flush_returned": False, "cursor_entered": False, "cursor_returned": True},
    {"flush_entered": 1, "flush_returned": False, "cursor_entered": False, "cursor_returned": False},
))
def test_owner_detail_rejects_impossible_sql_observation_boundaries(flags):
    from core.errors import _relay_owner_detail_fields

    detail = {"body_hook_state": "valid", "expiry": {"span": "unknown", **flags}, "settlement": "unknown"}
    assert _relay_owner_detail_fields(detail) == "unknown"


@pytest.mark.parametrize("outcome", ("commit", "rollback"))
def test_http_busy_writer_observation_and_completion_follow_real_transaction(
    client, caplog, outcome,
):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    storage = client.app.state.pallium_service._storage
    entered, release = threading.Event(), threading.Event()
    scope = {"container_ref": "git:example.test/diagnostics-東京"}
    failure = RuntimeError("controlled writer body failure")

    def park_count(_connection, _cursor, statement, _parameters, _context, _many):
        sql = statement.upper()
        if "SELECT COUNT(" in sql and "RELAY_DELIVERIES" in sql:
            entered.set()
            assert release.wait(10), "test did not release the writer"
            if outcome == "rollback":
                raise failure

    event.listen(storage._relay_engine, "before_cursor_execute", park_count)
    try:
        with caplog.at_level("WARNING"), ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(client.post, "/relay/turn", json={
                "runtime": "codex", "session_ref": "held-writer", **scope,
            })
            try:
                assert entered.wait(10), "real Relay turn did not reach COUNT"
                response = client.post("/relay/deliveries/ack", json={
                    "delivery_id": "relay-delivery-" + "a" * 32,
                    "claim_token": "opaque-receipt", **scope,
                })
                assert response.status_code == 503 and response.headers["retry-after"] == "1"
                busy = [r for r in caplog.records if r.getMessage().startswith("relay operation=ack outcome=busy")]
                assert len(busy) == 1
                observed = next(v for v in busy[0].args if type(v) is dict and "owner_id" in v)
                assert observed["operation"] == "turn" and observed["phase"] == "transaction"
                assert observed["owner_id"] >= 1 and observed["held_ms_lower_bound"] >= 0
                assert type(observed["turn_body"]) is dict
                assert scope["container_ref"] not in busy[0].getMessage()
                assert not any(r.getMessage().startswith("relay_writer_contention_completed") for r in caplog.records)
            finally:
                release.set()
            if outcome == "rollback":
                with pytest.raises(RuntimeError) as raised:
                    writer.result(timeout=10)
                assert raised.value is failure
            else:
                completed = writer.result(timeout=10)
                assert completed.status_code == 200, completed.text
        assert not storage._relay_writer_lock.locked() and storage._relay_writer_diagnostic is None
        completion = [r for r in caplog.records if r.getMessage().startswith("relay_writer_contention_completed")]
        assert len(completion) == 1 and completion[0].args[0] == observed["owner_id"]
        assert completion[0].args[2] == ("returned" if outcome == "commit" else "exception")
        request_owner = completion[0].args[-1]
        assert request_owner["owner_id"] == observed["owner_id"]
        assert request_owner["detail"]["settlement"]["state"] == "settled"
        sessions = client.get("/relay/sessions", params=scope)
        assert sessions.status_code == 200
        assert len(sessions.json()) == (1 if outcome == "commit" else 0)
        retried = client.post("/relay/deliveries/ack", json={
            "delivery_id": "relay-delivery-" + "a" * 32, "claim_token": "opaque-receipt", **scope,
        })
        assert retried.status_code == 404
    finally:
        release.set()
        event.remove(storage._relay_engine, "before_cursor_execute", park_count)


@pytest.mark.parametrize("delivery_ref", ("relay-delivery-" + "b" * 32, "private-東京"))
@pytest.mark.parametrize("logging_fails", (False, True))
def test_http_ack_busy_context_and_allowlisted_reference_preserve_primary_error(
    client, monkeypatch, caplog, delivery_ref, logging_fails,
):
    from api import routes
    from core.errors import ImmediateTransactionBusyError, _relay_writer_operation, _relay_writer_operation_name

    storage = client.app.state.pallium_service._storage
    frames = []
    error = ImmediateTransactionBusyError("private primary text", acquisition_stage="local_gate")
    error.observed_relay_writer = {"private": "must not be emitted"}

    def busy(**_kwargs):
        assert _relay_writer_operation_name() == "ack"
        frames.append(_relay_writer_operation.get())
        raise error

    def failed_warning(*_args, **_kwargs):
        raise RuntimeError("controlled secondary logging failure")

    monkeypatch.setattr(storage, "relay_ack", busy)
    if logging_fails:
        monkeypatch.setattr(routes.logger, "warning", failed_warning)
    with caplog.at_level("WARNING", logger="api.routes"):
        response = client.post("/relay/deliveries/ack", json={
            "delivery_id": delivery_ref, "claim_token": "opaque-receipt",
            "container_ref": "git:example.test/diagnostics",
        })
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert len(frames) == 1 and frames[0]["active"] is False and frames[0]["open"] is False
    assert "private primary" not in response.text and "observed_relay_writer" not in response.text
    if not logging_fails:
        records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("relay operation=ack outcome=busy")]
        assert len(records) == 1 and "observed_relay_writer=unknown" in records[0]
        expected = delivery_ref if delivery_ref.startswith("relay-delivery-") else "unknown"
        assert records[0].endswith(" delivery_ref=" + expected)
        assert "private" not in records[0] and "must not be emitted" not in records[0]


@pytest.mark.parametrize("fault", (None, "clock", "aggregate", "json-fallback", "decode"))
def test_wake_snapshot_real_read_preserves_result_or_error_and_settlement(
    client, monkeypatch, fault,
):
    import sqlite3
    import storage.sqlite_relay as relay_module
    from core.codex_wake import _relay_snapshot_timings

    storage = client.app.state.pallium_service._storage
    before = storage.relay_codex_wake_snapshot()
    checked_out, checked_in = [], []

    def checkout(connection, _record, _proxy):
        checked_out.append(connection)

    def checkin(connection, _record):
        checked_in.append(connection)

    failure = RuntimeError("controlled snapshot decode failure")

    def fail_clock():
        raise RuntimeError("controlled diagnostic clock failure")

    def fail_json(_cursor):
        raise sqlite3.OperationalError("no such function: json_group_array")

    def fail_decode(_encoded):
        raise failure

    if fault == "clock":
        clock = SimpleNamespace(**vars(relay_module.time))
        clock.perf_counter_ns = fail_clock
        monkeypatch.setattr(relay_module, "time", clock)
    elif fault == "json-fallback":
        monkeypatch.setattr(relay_module, "_wake_snapshot_envelope", fail_json)
    elif fault == "decode":
        monkeypatch.setattr(relay_module, "_decode_wake_snapshot_rows", fail_decode)
    timings = {"connection": True} if fault == "aggregate" else {}
    previous = _relay_snapshot_timings.get()
    token = _relay_snapshot_timings.set(timings)
    event.listen(storage._relay_engine.pool, "checkout", checkout)
    event.listen(storage._relay_engine.pool, "checkin", checkin)
    try:
        if fault == "decode":
            with pytest.raises(RuntimeError) as raised:
                storage.relay_codex_wake_snapshot()
            assert raised.value is failure
        else:
            assert storage.relay_codex_wake_snapshot() == before
        assert checked_out and checked_in == checked_out
        if fault in {"clock", "aggregate"}:
            assert timings["timing_invalid"] == 1
        else:
            assert all(type(timings[key]) is int and timings[key] >= 0
                       for key in ("connection", "sql", "settlement"))
        if fault == "json-fallback":
            assert timings["sql_fallback"] == 1
    finally:
        _relay_snapshot_timings.reset(token)
        event.remove(storage._relay_engine.pool, "checkout", checkout)
        event.remove(storage._relay_engine.pool, "checkin", checkin)
    assert _relay_snapshot_timings.get() is previous


@pytest.mark.parametrize("runtime", ("hermes", "codex"))
def test_exact_route_diagnostics_preserve_main_callback_authority(client, runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.codex_wake import _relay_snapshot_timings

    calls, requests, timing_scopes = [], [], []

    def turn(**kwargs):
        calls.append("turn")
        requests.append(kwargs)
        return {"session": None, "deliveries": [], "has_more": False, "remaining_count": 0}

    def snapshot(_request):
        calls.append("snapshot")
        timing_scopes.append(_relay_snapshot_timings.get())

    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service, relay_service=SimpleNamespace(turn=turn),
        relay_turn_snapshot_callback=snapshot,
        relay_turn_callback=lambda *_: calls.append("callback"),
        relay_turn_admission_callback=lambda *_: calls.append("admission"),
    ))
    with TestClient(app) as route:
        body = {
            "runtime": runtime, "session_ref": "exact-target",
            "container_ref": "git:example.test/diagnostics-東京",
            "wake_delivery_id": "relay-delivery-" + "c" * 32, "register_session": False,
        }
        if runtime == "hermes":
            body.update(max_chars=20_000, max_response_chars=48_000)
        response = route.post("/relay/turn", json=body)
    assert response.status_code == 200, response.text
    assert calls == (["turn"] if runtime == "hermes" else ["snapshot", "turn", "callback", "admission"])
    assert requests[0]["exact_delivery_id"] == "relay-delivery-" + "c" * 32
    assert requests[0]["register_session"] is False
    assert requests[0]["max_chars"] == (20_000 if runtime == "hermes" else 0)
    assert requests[0]["max_response_chars"] == (48_000 if runtime == "hermes" else 0)
    assert requests[0]["max_messages"] == 3
    assert timing_scopes == [] if runtime == "hermes" else len(timing_scopes) == 1 and type(timing_scopes[0]) is dict
    assert _relay_snapshot_timings.get() is None


@pytest.mark.parametrize("explicit,value", ((False, 1), (True, 1), (True, 3)))
def test_opencode_route_keeps_omission_aware_max_messages(client, explicit, value):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.relay import RelayConflictError

    requests = []

    def wake(**kwargs):
        requests.append(kwargs)
        raise RelayConflictError("controlled route boundary")

    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service,
                                    relay_service=SimpleNamespace(opencode_wake=wake)))
    body = {"operation": "context", "session_ref": "native-target",
            "container_ref": "git:example.test/diagnostics", "endpoint_id": "relay-session-" + "d" * 32,
            "scope_generation": 1, "native_location": "relative/native-session.json",
            "owner_id": "opencode-owner-" + "e" * 32, "generation": 1,
            "delivery_id": "relay-delivery-" + "f" * 32, "native_input_id": "msg_generic"}
    if explicit:
        body["max_messages"] = value
    with TestClient(app) as route:
        response = route.post("/relay/opencode/wake", json=body)
    assert response.status_code == 409 and len(requests) == 1
    assert ("max_messages" in requests[0]) is explicit
    if explicit:
        assert requests[0]["max_messages"] == value


@pytest.mark.parametrize("logging_fails", (False, True))
def test_registry_reserve_busy_diagnostics_keep_fail_closed_result(client, monkeypatch, caplog, logging_fails):
    import core.codex_wake as wake_module
    from core.errors import ImmediateTransactionBusyError, _relay_writer_operation, _relay_writer_operation_name

    frames = []
    error = ImmediateTransactionBusyError("private busy error", acquisition_stage="retry_exhausted",
                                          acquisition_phase_ms={"session_factory": 0, "begin_immediate": 60_000})

    def transition(operation, **_kwargs):
        assert operation == _relay_writer_operation_name() == "reserve"
        frames.append(_relay_writer_operation.get())
        raise error

    relay = SimpleNamespace(codex_wake_snapshot=lambda: (True, ()), codex_wake_transition=transition)
    registry = wake_module.CodexWakeRegistry(relay_service=relay)

    def failed_warning(*_args, **_kwargs):
        raise RuntimeError("controlled secondary warning failure")

    if logging_fails:
        monkeypatch.setattr(wake_module.logger, "warning", failed_warning)
    endpoint, delivery = "relay-session-" + "a" * 32, "relay-delivery-" + "b" * 32
    with caplog.at_level("WARNING", logger="core.codex_wake"):
        result = registry.reserve(recipient_endpoint_id=endpoint, delivery_id=delivery,
                                  session_ref="private-session-東京", container_ref="git:example.test/private-scope")
    assert result is None and len(frames) == 1
    assert frames[0]["active"] is False and frames[0]["open"] is False
    if not logging_fails:
        messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith("codex_wake_transition_failed")]
        assert len(messages) == 1
        assert "acquisition_stage=retry_exhausted" in messages[0]
        assert "delivery_ref=" + delivery in messages[0] and "recipient_endpoint_id=" + endpoint in messages[0]
        assert "begin_immediate': 60000" in messages[0] and "generation=unknown" in messages[0]
        assert "private" not in messages[0] and "東京" not in messages[0]


def test_registry_initialization_context_closes_after_refresh():
    from core.codex_wake import CodexWakeRegistry
    from core.errors import _relay_writer_operation, _relay_writer_operation_name

    initialized, frames = [False], []

    def initialize(reservations):
        assert reservations == () and _relay_writer_operation_name() == "initialize"
        frames.append(_relay_writer_operation.get())
        initialized[0] = True

    registry = CodexWakeRegistry(relay_service=SimpleNamespace(
        codex_wake_snapshot=lambda: (initialized[0], ()), codex_wake_initialize=initialize,
    ))
    assert registry.initialize(old_owner_drained=True) is True
    assert len(frames) == 1 and frames[0]["open"] is False and frames[0]["active"] is False
    assert _relay_writer_operation_name() == "unknown"


@pytest.mark.parametrize("fault", (None, "partial-install", "remove-after-cleanup"))
def test_sql_observer_attributes_only_its_tag_and_cleans_listeners(client, monkeypatch, fault):
    import storage.sqlite_queue as queue_module
    from sqlalchemy import text
    from core.errors import _relay_writer_context

    storage = client.app.state.pallium_service._storage
    installed, removed = [], []

    def listen(target, name, callback):
        installed.append((target, name, callback))
        event.listen(target, name, callback)
        if fault == "partial-install" and len(installed) == 2:
            raise RuntimeError("controlled partial listener installation")

    def remove(target, name, callback):
        event.remove(target, name, callback)
        removed.append((target, name, callback))
        if fault == "remove-after-cleanup":
            raise RuntimeError("controlled observer cleanup diagnostic")

    monkeypatch.setattr(queue_module, "event", SimpleNamespace(listen=listen, remove=remove))
    try:
        with _relay_writer_context("turn"), storage._begin_relay_immediate() as session:
            owner = storage._relay_writer_diagnostic
            with storage._observe_relay_expiry(session, owner, count=True) as tag:
                assert session.execute(text("SELECT 1")).scalar_one() == 1
                assert session.execute(text("SELECT 2").execution_options(_pallium_relay_count=object())).scalar_one() == 2
                if fault is None:
                    assert not any(owner["count_boundaries"].values())
                assert session.execute(text("SELECT 3").execution_options(_pallium_relay_count=tag)).scalar_one() == 3
            assert len(removed) == len(installed) and all(not event.contains(*item) for item in installed)
            if fault is None:
                assert owner["count_boundaries"]["cursor_entered"] is True
                assert owner["count_boundaries"]["cursor_returned"] is True
                assert owner["count_hook_state"] == "valid"
            else:
                assert owner["count_hook_state"] == "invalid"
        assert owner["active"] is False and storage._relay_writer_diagnostic is None
        assert not storage._relay_writer_lock.locked()
    finally:
        for item in installed:
            if event.contains(*item):
                event.remove(*item)


@pytest.mark.parametrize("checkpoint", (
    "before_acquisition", "after_acquisition", "pre_claim_mutation", "post_flush_precommit", "private-東京", None,
))
def test_exact_expiry_log_validates_checkpoint_without_changing_http_error(client, caplog, checkpoint):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.relay import RelayConflictError

    error = RelayConflictError("Relay claim request expired")
    error.expiry_detected_at = checkpoint

    def turn(**_kwargs):
        raise error

    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service, relay_service=SimpleNamespace(turn=turn)))
    with caplog.at_level("INFO", logger="api.routes"), TestClient(app) as route:
        response = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "exact-target",
            "container_ref": "git:example.test/private-scope",
            "wake_delivery_id": "relay-delivery-" + "c" * 32,
        })
    assert response.status_code == 409 and response.json() == {"detail": "Relay claim request expired"}
    records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("relay_turn_timing")]
    assert len(records) == 1 and "error_status=409 error_category=claim_expired" in records[0]
    expected = checkpoint if checkpoint is not None and not checkpoint.startswith("private") else "unknown"
    assert "expiry_detected_at=" + expected in records[0]
    assert "request_owner=unknown blocking_owner=unknown" in records[0]
    assert "private" not in records[0] and "exact-target" not in records[0] and "東京" not in records[0]


@pytest.mark.parametrize("fault", (None, "legacy-sql", "invalid-clock", "malformed-fields"))
def test_route_snapshot_phase_projection_is_bounded_and_does_not_leak_context(client, caplog, fault):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.codex_wake import _relay_snapshot_timings
    from core.relay import RelayConflictError

    scopes = []

    def snapshot(_request):
        timings = _relay_snapshot_timings.get()
        scopes.append(timings)
        timings.update(connection=1_000_000, sql=2_000_000, decode_validation=3_000_000,
                       settlement=4_000_000, pool_size=1_000_000, pool_overflow=-1_000_000)
        if fault == "legacy-sql":
            timings["sql_fallback"] = 1
        elif fault == "invalid-clock":
            timings["timing_invalid"] = 1
        elif fault == "malformed-fields":
            timings.update(connection=True, sql=60_000_000_001, decode_validation="private-東京",
                           settlement=-1, pool_size=True, pool_overflow=-1_000_001)

    def turn(**_kwargs):
        raise RelayConflictError("Relay claim request expired")

    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service,
                                    relay_service=SimpleNamespace(turn=turn), relay_turn_snapshot_callback=snapshot))
    with caplog.at_level("INFO", logger="api.routes"), TestClient(app) as route:
        response = route.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "private-target", "container_ref": "git:example.test/private-scope",
            "wake_delivery_id": "relay-delivery-" + "d" * 32,
        })
    assert response.status_code == 409 and len(scopes) == 1
    assert _relay_snapshot_timings.get() is None
    records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("relay_turn_timing")]
    assert len(records) == 1
    phases = {"connection": 1, "sql": 2, "decode_validation": 3, "settlement": 4}
    if fault == "legacy-sql":
        phases.update(sql="unknown", decode_validation="unknown")
    elif fault in {"invalid-clock", "malformed-fields"}:
        phases = dict.fromkeys(phases, "unknown")
    pool = {"pool_size": 1_000_000, "pool_overflow": -1_000_000}
    if fault == "malformed-fields":
        pool = dict.fromkeys(pool, "unknown")
    assert " snapshot_phase_ms=" + str(phases) + " snapshot_pool=" + str(pool) in records[0]
    assert "private" not in records[0] and "東京" not in records[0]
