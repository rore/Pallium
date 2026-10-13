from __future__ import annotations

import asyncio
import itertools
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import anyio
import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@contextmanager
def _observe_setup_writer(storage, monkeypatch):
    """Attach acquisition evidence to failures in the two real-DB setup probes."""
    import json
    import time
    from sqlalchemy import event

    stages, active = [], set()
    overflow = [False]
    original_begin = storage._begin_relay_immediate
    original_lock = storage._relay_writer_lock
    engine = storage._relay_engine

    def record(stage, **values):
        if len(stages) >= 128:
            overflow[0] = True
            return
        stages.append({"stage": stage, "at": time.monotonic(),
                       "thread": threading.get_ident(), **values})

    class ObservedLock:
        def acquire(self, *args, **kwargs):
            observed = threading.get_ident() in active
            if observed:
                record("local_wait")
            result = original_lock.acquire(*args, **kwargs)
            if observed:
                record("local_result", acquired=result)
            return result

        def release(self):
            return original_lock.release()

        def locked(self):
            return original_lock.locked()

    @contextmanager
    def begin():
        ident = threading.get_ident()
        active.add(ident)
        record("helper_enter")
        try:
            with original_begin() as session:
                record("acquired")
                yield session
        except BaseException as exc:
            record("helper_error", category=type(exc).__name__)
            raise
        finally:
            record("helper_exit")
            active.discard(ident)

    def sql(stage, statement, error=None):
        if threading.get_ident() in active:
            normalized = (statement or "").strip().upper()
            if normalized == "BEGIN IMMEDIATE" or normalized.startswith("PRAGMA BUSY_TIMEOUT="):
                record(stage, statement=normalized,
                       code=getattr(error, "sqlite_errorcode", None))

    def before(_conn, _cursor, statement, _params, _context, _many):
        sql("sql_enter", statement)

    def after(_conn, _cursor, statement, _params, _context, _many):
        sql("sql_exit", statement)

    def error(context):
        sql("sql_error", context.statement, context.original_exception)

    listeners = [("before_cursor_execute", before), ("after_cursor_execute", after), ("handle_error", error)]
    with monkeypatch.context() as local:
        local.setattr(storage, "_relay_writer_lock", ObservedLock())
        local.setattr(storage, "_begin_relay_immediate", begin)
        for name, callback in listeners:
            event.listen(engine, name, callback)
        try:
            yield
        except BaseException as exc:
            exc.add_note("relay setup acquisition: " + json.dumps({
                "stages": stages, "overflow": overflow[0],
            }))
            raise
        finally:
            for name, callback in listeners:
                event.remove(engine, name, callback)


@pytest.mark.parametrize("receipt_ack", [False, True])
@pytest.mark.parametrize("callback_failure", [False, True])
def test_tcp_ack_receipt_precedes_owned_callback_and_shutdown_drains(
    tmp_path, monkeypatch, caplog, receipt_ack, callback_failure,
) -> None:
    import socket
    from contextlib import ExitStack
    from concurrent.futures import ThreadPoolExecutor
    from app import dependencies, main as app_main, codex_bridge_pipe
    from scripts.live_funnel_smoke import ScratchServer

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    closed, shutdown_started = threading.Event(), threading.Event()
    calls, dispatches, native_calls = [], [], []
    original_router = dependencies.create_router
    cleanup, original_storage = ExitStack(), app_main.build_storage_provider

    def own_storage(*args, **kwargs):
        storage = original_storage(*args, **kwargs)
        original_close = storage.close

        def close():
            closed.set()
            original_close()

        monkeypatch.setattr(storage, "close", close)
        cleanup.callback(storage.close)
        return storage

    def router(service, **kwargs):
        callback = kwargs["relay_ack_callback"]

        def held_callback(result, scope):
            calls.append((result["delivery_id"], result["state"], result["recipient_runtime"]))
            entered.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("callback gate watchdog expired")
                if callback_failure:
                    raise RuntimeError("controlled ACK cleanup failure")
                return callback(result, scope)
            finally:
                finished.set()

        kwargs["relay_ack_callback"] = held_callback
        kwargs["relay_send_callback"] = None
        return original_router(service, **kwargs)

    def schedule(result, *_args, **_kwargs):
        dispatches.extend(row["delivery_id"] for row in result["deliveries"])

    monkeypatch.setattr(dependencies, "create_router", router)
    monkeypatch.setattr(dependencies, "schedule_codex_relay_wake", schedule)
    monkeypatch.setattr(app_main, "build_storage_provider", own_storage)
    monkeypatch.setattr("app.mcp.server.create_server", lambda **_: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(codex_bridge_pipe, "start_shadow_service", lambda *_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_inventory_service", lambda **_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_retained_service", lambda **_: None)
    app = create_app(AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    cleanup.callback(app.state.pallium_service.close)
    registry = app.state.codex_wake_registry
    assert registry.initialize(old_owner_drained=True)
    scope = {"container_ref": "git:example.test/ack-response-owner"}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = ScratchServer(app, "127.0.0.1", port)
    pool = ThreadPoolExecutor(max_workers=1)
    shutdown = None
    response = None
    closed_by_lifespan = False
    try:
        server.__enter__()
        with httpx.Client(base_url=server.base_url, timeout=2) as client:
            for session in ("sender", "target"):
                registered = client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **scope})
                assert registered.status_code == 200, registered.text
            sent = []
            for payload in ("first café 東京", "next café 東京"):
                message = client.post("/relay/messages", json={
                    "sender_runtime": "codex", "sender_session_ref": "sender",
                    "recipient": "codex:target", "payload": payload, **scope,
                })
                assert message.status_code == 200, message.text
                sent.append(message.json())
            first = sent[0]["deliveries"][0]
            saved = registry.reserve(
                recipient_endpoint_id=first["recipient_endpoint_id"],
                delivery_id=first["delivery_id"], session_ref="target", **scope,
            )
            assert saved is not None
            claimed = client.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "target", "max_messages": 1,
                "wake_delivery_id": first["delivery_id"], **scope,
            })
            assert claimed.status_code == 200, claimed.text
            delivery, = claimed.json()["deliveries"]
            assert delivery["delivery_id"] == first["delivery_id"]
            assert delivery["attempts"] == 1
            path = "/relay/deliveries/mcp-ack" if receipt_ack else "/relay/deliveries/ack"
            proof = {"receipt": delivery["receipt"]} if receipt_ack else {"claim_token": delivery["claim_token"]}
            request = pool.submit(client.post, path, json={"delivery_id": delivery["delivery_id"], **proof, **scope}, timeout=0.5)
            assert entered.wait(2), "actual ACK callback did not enter"
            try:
                response = request.result(2)
            except httpx.TimeoutException:
                pass
            retained = client.get(f"/relay/messages/{sent[0]['message_id']}", params=scope)
            assert retained.status_code == 200, retained.text
            stored, = retained.json()["deliveries"]
            assert (stored["delivery_id"], stored["state"], stored["attempts"]) == (delivery["delivery_id"], "delivered", 1)
            assert registry.run_if_current(saved, lambda: native_calls.append("duplicate")) == (False, None)
            assert native_calls == []
            assert not finished.is_set() and not closed.is_set()

            def stop():
                shutdown_started.set()
                server.__exit__()

            shutdown = threading.Thread(target=stop, name="ack-owned-shutdown")
            shutdown.start()
            assert shutdown_started.wait(2)
            shutdown.join(0.1)
            assert shutdown.is_alive() and not closed.is_set(), "shutdown bypassed request-owned callback"
    finally:
        release.set()
        pool.shutdown(wait=True)
        if shutdown is not None:
            shutdown.join(10)
        server.__exit__()
        closed_by_lifespan = closed.is_set()
        cleanup.close()
    assert shutdown is not None and not shutdown.is_alive()
    assert server._thread is not None and not server._thread.is_alive()
    assert finished.is_set() and closed_by_lifespan
    assert calls == [(first["delivery_id"], "delivered", "codex")]
    assert dispatches == ([] if callback_failure else [sent[1]["deliveries"][0]["delivery_id"]])
    if callback_failure:
        assert any("Relay ACK callback failed after persistence" in record.message or
                   "Relay MCP ACK callback failed after persistence" in record.message for record in caplog.records)
    assert response is not None, "durable ACK response waited for callback cleanup"
    assert response.status_code == 200, response.text
    assert response.json()["delivery_id"] == first["delivery_id"]
    assert response.json()["state"] == "delivered"


@pytest.mark.parametrize("failure", [
    None, "snapshot", "turn_callback", "admission", "projection",
    "not_found", "conflict", "unavailable", "busy", "invalid", "runner_busy", "cancel_after_claim",
])
def test_exact_codex_turn_uses_one_admission_and_preserves_phase_failures(
    tmp_path, monkeypatch, caplog, failure,
) -> None:
    from contextlib import ExitStack
    from app import dependencies, main as app_main
    from core.errors import ImmediateTransactionBusyError
    from core.relay import (
        RelayConflictError, RelayNotFoundError, RelayService, RelayUnavailableError,
    )

    armed = False
    admissions, phases = [], []
    claimed_rows = []
    callback_entered, release_callback = threading.Event(), threading.Event()
    local = threading.local()
    original_router = dependencies.create_router
    original_turn = RelayService.turn
    durable_errors = {
        "not_found": (RelayNotFoundError, 404, "relay entity not found in the requested scope"),
        "conflict": (RelayConflictError, 409, "controlled conflict"),
        "unavailable": (RelayUnavailableError, 501, "controlled unavailable"),
        "busy": (ImmediateTransactionBusyError, 503, {"code": "relay_busy", "retryable": True}),
        "invalid": (ValueError, 422, "controlled invalid"),
        "runner_busy": (ImmediateTransactionBusyError, 503, {"code": "relay_busy", "retryable": True}),
    }

    def phase(name):
        phases.append((name, local.admission, threading.get_ident()))

    def observe_turn(self, **kwargs):
        if armed:
            phase("claim")
            if failure in durable_errors:
                error, _, _ = durable_errors[failure]
                raise error(f"controlled {failure}")
        return original_turn(self, **kwargs)

    def observe_router(service, **kwargs):
        for name in ("relay_runner", "relay_codex_runner"):
            original = kwargs[name]

            async def runner(operation, _name=name, _original=original):
                if not armed:
                    return await _original(operation)
                token = (_name, len(admissions))
                admissions.append(token)
                if failure == "runner_busy":
                    raise ImmediateTransactionBusyError("controlled runner rejection")

                def observed():
                    local.admission = token
                    try:
                        return operation()
                    finally:
                        del local.admission
                return await _original(observed)
            kwargs[name] = runner

        def snapshot(_request):
            if not armed:
                return None
            phase("snapshot")
            if failure == "snapshot":
                raise RuntimeError("controlled snapshot failure")
            return None

        def turn_callback(_request, result):
            phase("turn_callback")
            assert result["deliveries"][0]["state"] == "claimed"
            claimed_rows.append(dict(result["deliveries"][0]))
            if failure == "cancel_after_claim":
                callback_entered.set()
                assert release_callback.wait(5), "exact callback gate watchdog expired"
            if failure == "turn_callback":
                raise RuntimeError("controlled turn callback failure")

        def admission(_request, result, reservation):
            phase("admission")
            assert reservation is None
            assert result["deliveries"][0]["attempts"] == 1
            if failure == "admission":
                raise RuntimeError("controlled admission failure")

        activation = kwargs["relay_activation_callback"]
        def project(row):
            if armed:
                phase("projection")
                if failure == "projection" and "session_ref" in row:
                    raise RuntimeError("controlled projection failure")
            return activation(row)

        # Native transport is outside this caller/ordering regression.
        kwargs["relay_send_callback"] = None
        kwargs["relay_ack_callback"] = None
        kwargs["relay_turn_snapshot_callback"] = snapshot
        kwargs["relay_turn_callback"] = lambda *args: turn_callback(*args) if armed else None
        kwargs["relay_turn_admission_callback"] = lambda *args: admission(*args) if armed else None
        kwargs["relay_activation_callback"] = project
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(RelayService, "turn", observe_turn)
    monkeypatch.setattr("app.mcp.server.create_server", lambda **_: (_ for _ in ()).throw(ImportError()))
    cleanup, original_storage = ExitStack(), app_main.build_storage_provider
    def owned_storage(*args, **kwargs):
        storage = original_storage(*args, **kwargs)
        cleanup.callback(storage.close)
        return storage
    monkeypatch.setattr(app_main, "build_storage_provider", owned_storage)
    app = None

    async def exercise():
        nonlocal armed
        loop_thread = threading.get_ident()
        scope = {"container_ref": "git:example.test/exact-turn-admission"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for session in ("sender", "target"):
                response = await client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **scope})
                assert response.status_code == 200, response.text
            sent = await client.post("/relay/messages", json={
                "sender_runtime": "codex", "sender_session_ref": "sender",
                "recipient": "codex:target", "payload": "one admission café 東京", **scope,
            })
            assert sent.status_code == 200, sent.text
            delivery_id = sent.json()["deliveries"][0]["delivery_id"]
            exact_request = {
                "runtime": "codex", "session_ref": "target",
                "wake_delivery_id": delivery_id, "max_messages": 1, **scope,
            }
            armed = True
            try:
                if failure == "cancel_after_claim":
                    request = asyncio.create_task(client.post("/relay/turn", json=exact_request))
                    try:
                        assert await asyncio.to_thread(callback_entered.wait, 5)
                        request.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await request
                        assert not app.state._wait_for_operations(0)
                    finally:
                        release_callback.set()
                        if not request.done():
                            request.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await request
                        assert await asyncio.to_thread(app.state._wait_for_operations, 5)
                else:
                    response = await client.post("/relay/turn", json=exact_request)
            finally:
                armed = False
            if failure in durable_errors:
                _, status, detail = durable_errors[failure]
                assert response.status_code == status, response.text
                assert response.json() == {"detail": detail}
                if failure in {"busy", "runner_busy"}:
                    assert response.headers["Retry-After"] == "1"
                assert [p[0] for p in phases] == ([] if failure == "runner_busy" else ["snapshot", "claim"])
            else:
                if failure == "cancel_after_claim":
                    committed = await client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
                    assert committed.status_code == 200, committed.text
                    persisted, = committed.json()["deliveries"]
                    assert persisted["delivery_id"] == delivery_id
                    assert persisted["state"] == "claimed"
                    assert persisted["attempts"] == 1
                    duplicate = await client.post("/relay/turn", json=exact_request)
                    assert duplicate.status_code == 200, duplicate.text
                    assert duplicate.json()["deliveries"] == []
                    delivery, = claimed_rows
                else:
                    assert response.status_code == 200, response.text
                    delivery, = response.json()["deliveries"]
                assert delivery["delivery_id"] == delivery_id
                assert delivery["payload"] == "one admission café 東京"
                assert delivery["attempts"] == 1
                assert [p[0] for p in phases] == [
                    "snapshot", "claim", "turn_callback", "admission", "projection", "projection",
                ]
                acknowledged = await client.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery_id, "claim_token": delivery["claim_token"], **scope,
                })
                assert acknowledged.status_code == 200, acknowledged.text
            readback = await client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
            assert readback.status_code == 200, readback.text
            retained, = readback.json()["deliveries"]
            assert retained["delivery_id"] == delivery_id
            assert retained["state"] == ("pending" if failure in durable_errors else "delivered")
            assert retained["attempts"] == (0 if failure in durable_errors else 1)
            if failure in {"snapshot", "turn_callback", "admission", "projection"}:
                assert any("snapshot unavailable" in r.message or "failed" in r.message for r in caplog.records)
            assert app.state._wait_for_operations(0)
            assert admissions == [("relay_codex_runner", 0)], admissions
            assert all(p[1] == admissions[0] and p[2] != loop_thread for p in phases), phases

    try:
        app = create_app(AppConfig(
            storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
            relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
            default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        ))
        cleanup.callback(app.state.pallium_service._storage.close)
        cleanup.callback(app.state.pallium_service.close)
        asyncio.run(exercise())
    finally:
        release_callback.set()
        cleanup.close()


@pytest.mark.parametrize("runtime", ["codex", "claude-code", "opencode"])
def test_ack_release_uses_durable_runtime_when_endpoint_scope_read_fails(
    client, monkeypatch, runtime,
) -> None:
    from app import dependencies
    from core.relay import RelayNotFoundError, RelayService

    calls = []
    registry = client.app.state.claude_wake_registry
    original_claude_release = registry.release_delivery
    original_codex_release = dependencies.release_codex_relay_wake

    def claude_release(*args, **kwargs):
        calls.append("claude-code")
        return original_claude_release(*args, **kwargs)

    def codex_release(*args, **kwargs):
        calls.append("codex")
        return original_codex_release(*args, **kwargs)

    monkeypatch.setattr(registry, "release_delivery", claude_release)
    monkeypatch.setattr(dependencies, "release_codex_relay_wake", codex_release)
    monkeypatch.setattr(dependencies, "schedule_codex_relay_wake", lambda *_, **__: None)
    monkeypatch.setattr(dependencies, "schedule_claude_relay_wake", lambda *_, **__: None)
    scope = {"container_ref": "git:example.test/ack-scope-fallback"}
    for session in ("sender", "target"):
        response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **scope})
        assert response.status_code == 200, response.text
    sent = client.post("/relay/messages", json={
        "sender_runtime": runtime, "sender_session_ref": "sender",
        "recipient": f"{runtime}:target", "payload": "scope fallback 東京", **scope,
    })
    assert sent.status_code == 200, sent.text
    claimed = client.post("/relay/turn", json={"runtime": runtime, "session_ref": "target", **scope})
    assert claimed.status_code == 200, claimed.text
    delivery, = claimed.json()["deliveries"]
    original_scope = RelayService.session_scope_by_endpoint

    def unavailable_scope(*_args, **_kwargs):
        raise RelayNotFoundError("endpoint scope unavailable")

    monkeypatch.setattr(RelayService, "session_scope_by_endpoint", unavailable_scope)
    acknowledged = client.post("/relay/deliveries/ack", json={
        "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **scope,
    })
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["delivery_id"] == delivery["delivery_id"]
    assert acknowledged.json()["state"] == "delivered"
    assert calls == ([] if runtime == "opencode" else [runtime])
    monkeypatch.setattr(RelayService, "session_scope_by_endpoint", original_scope)
    readback = client.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
    assert readback.status_code == 200, readback.text
    retained, = readback.json()["deliveries"]
    assert retained["delivery_id"] == delivery["delivery_id"]
    assert retained["state"] == "delivered"
    assert retained["attempts"] == 1


@pytest.mark.parametrize("outcome", ["slow", "busy"])
def test_relay_warning_sink_uses_tracked_worker_while_health_progresses(
    tmp_path, monkeypatch, outcome,
) -> None:
    from api import routes
    from core.errors import ImmediateTransactionBusyError
    from core.relay import RelayService

    entered, release = threading.Event(), threading.Event()
    warnings = []
    original_warning = routes.logger.warning
    loop_thread = threading.get_ident()
    monkeypatch.setattr(routes, "time", SimpleNamespace(**{
        **vars(routes.time), "monotonic": itertools.count(step=0.2).__next__,
    }))
    monkeypatch.setattr("app.mcp.server.create_server", lambda **_: (_ for _ in ()).throw(ImportError()))
    app = create_app(AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))

    def warning(message, *args, **kwargs):
        if args and args[0] == "message_trace":
            warnings.append((threading.get_ident(), message, args))
            entered.set()
            if threading.get_ident() != loop_thread:
                assert release.wait(5), "warning sink watchdog expired"
        return original_warning(message, *args, **kwargs)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            scope = {"container_ref": "git:example.test/log-sink"}
            for session in ("sender", "target"):
                response = await client.post("/relay/turn", json={"runtime": "opencode", "session_ref": session, **scope})
                assert response.status_code == 200, response.text
            sent = await client.post("/relay/messages", json={
                "sender_runtime": "opencode", "sender_session_ref": "sender",
                "recipient": "opencode:target", "payload": "logging 東京", **scope,
            })
            assert sent.status_code == 200, sent.text
            if outcome == "busy":
                def busy_trace(*_args, **_kwargs):
                    raise ImmediateTransactionBusyError("writer busy")
                monkeypatch.setattr(RelayService, "trace_message", busy_trace)
            monkeypatch.setattr(routes.logger, "warning", warning)
            request = asyncio.create_task(client.get(f"/relay/messages/{sent.json()['message_id']}/trace"))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                assert warnings[0][0] != loop_thread
                health = await asyncio.wait_for(client.get("/health"), 5)
                assert health.status_code in {200, 503}
                assert not request.done()
                assert not app.state._wait_for_operations(0)
            finally:
                release.set()
                response = await asyncio.wait_for(request, 5)
            assert len(warnings) == 1
            assert f"outcome={outcome}" in warnings[0][1]
            if outcome == "busy":
                assert response.status_code == 503, response.text
                assert response.headers["Retry-After"] == "1"
                assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
            else:
                assert response.status_code == 200, response.text
                assert response.json()["message_id"] == sent.json()["message_id"]
            assert app.state._wait_for_operations(0)

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        try:
            app.state.pallium_service.close()
        finally:
            app.state.pallium_service._storage.close()


def test_independent_relay_operations_progress_with_all_codex_callbacks_waiting(
    tmp_path, monkeypatch,
) -> None:
    from app import dependencies
    from core.relay import RelayService

    held, release, sends_persisted = (
        threading.Event(), threading.Event(), threading.Event()
    )
    callback_threads, admissions, gate_errors, native_schedules, persisted = [], [], [], [], []
    codex_requests = []
    armed = False
    original_router = dependencies.create_router

    def observe_router(service, **kwargs):
        callback = kwargs["relay_send_callback"]
        codex_runner = kwargs.get("relay_codex_runner")
        if codex_runner is not None:
            async def observe_codex_runner(operation):
                if armed:
                    codex_requests.append(operation)
                return await codex_runner(operation)
            kwargs["relay_codex_runner"] = observe_codex_runner

        def observe_send(result, scope):
            if armed and result["deliveries"][0]["recipient_runtime"] == "codex":
                callback_threads.append(threading.get_ident())
            return callback(result, scope)

        kwargs["relay_send_callback"] = observe_send
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    # Keep durable reserve/reconcile intact; stop before the native worker starts.
    monkeypatch.setattr(
        "app.codex_wake._schedule_reserved_codex_relay_wake",
        lambda reservation, *_args, **_kwargs: native_schedules.append(reservation),
    )
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    for name in ("trace_message", "message_status", "turn", "send"):
        original = getattr(RelayService, name)

        def observe_entry(self, *args, _name=name, _original=original, **kwargs):
            if armed and _name != "send":
                admissions.append((_name, kwargs.get("message_id", kwargs.get("session_ref"))))
            result = _original(self, *args, **kwargs)
            if armed and _name == "send" and result["deliveries"][0]["recipient_runtime"] == "codex":
                persisted.append(result["message_id"])
                if len(persisted) == 4:
                    sends_persisted.set()
            return result

        monkeypatch.setattr(RelayService, name, observe_entry)

    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    scope = {"container_ref": "git:example.test/mixed-capacity"}
    # These databases are freshly created under tmp_path; no prior owner exists.
    assert app.state.codex_wake_registry.initialize(old_owner_drained=True)

    def hold_registry():
        with app.state.codex_wake_registry._lock:
            held.set()
            if not release.wait(15):
                gate_errors.append("registry gate watchdog expired")

    holder = threading.Thread(target=hold_registry, name="test-codex-registry-holder")

    async def exercise():
        nonlocal armed
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for runtime, session in [
                ("opencode", "sender"),
                *[("codex", f"blocked-{i}") for i in range(4)],
                *[("opencode", f"passive-{i}") for i in range(8)],
                *[("opencode", f"ack-passive-{i}") for i in range(8)],
            ]:
                registered = await client.post("/relay/turn", json={
                    "runtime": runtime, "session_ref": session, **scope,
                })
                assert registered.status_code == 200, registered.text
            messages = []
            for i in range(8):
                sent = await client.post("/relay/messages", json={
                    "sender_runtime": "opencode", "sender_session_ref": "sender",
                    "recipient": f"opencode:passive-{i}", "payload": f"mixed 東京 {i}", **scope,
                })
                assert sent.status_code == 200, sent.text
                messages.append(sent.json())

            acknowledgments = []
            for i in range(8):
                sent = await client.post("/relay/messages", json={
                    "sender_runtime": "opencode", "sender_session_ref": "sender",
                    "recipient": f"opencode:ack-passive-{i}", "payload": f"ACK {i}", **scope,
                })
                assert sent.status_code == 200, sent.text
                claimed = await client.post("/relay/turn", json={
                    "runtime": "opencode", "session_ref": f"ack-passive-{i}", **scope,
                })
                assert claimed.status_code == 200, claimed.text
                delivery, = claimed.json()["deliveries"]
                assert delivery["delivery_id"] == sent.json()["deliveries"][0]["delivery_id"]
                acknowledgments.append(delivery)

            holder.start()
            assert await asyncio.to_thread(held.wait, 5)
            armed = True
            sends = [asyncio.create_task(client.post("/relay/messages", json={
                "sender_runtime": "opencode", "sender_session_ref": "sender",
                "recipient": f"codex:blocked-{i}", "payload": f"blocked {i}", **scope,
            })) for i in range(4)]
            probes = []
            ack_probes = []
            progressed = False
            evidence = {}
            try:
                assert await asyncio.to_thread(sends_persisted.wait, 5)
                stacks = {}
                deadline = asyncio.get_running_loop().time() + 5
                while True:
                    for ident in callback_threads:
                        frame, stack = sys._current_frames().get(ident), []
                        while frame is not None:
                            stack.append((frame.f_code.co_name, frame.f_lineno))
                            frame = frame.f_back
                        stacks[ident] = stack[:12]
                    if len(stacks) == 3 and len(codex_requests) == 4 and all(any(name == "dispatch_relay_wake" for name, _ in stack)
                           for stack in stacks.values()):
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0)
                assert len(stacks) == 3 and len(codex_requests) == 4, (stacks, len(codex_requests))
                assert all(any(name == "dispatch_relay_wake" for name, _ in stack)
                           for stack in stacks.values()), stacks
                for i, message in enumerate(messages):
                    message_id = message["message_id"]
                    probes.extend([
                        asyncio.create_task(client.get(f"/relay/messages/{message_id}/trace")),
                        asyncio.create_task(client.get(f"/relay/messages/{message_id}", params=scope)),
                        asyncio.create_task(client.post("/relay/turn", json={
                            "runtime": "opencode", "session_ref": f"passive-{i}",
                            "max_chars": 1000, **scope,
                        })),
                    ])
                for index, delivery in enumerate(acknowledgments):
                    if index % 3 == 0:
                        path, arguments = "/relay/deliveries/ack", {"claim_token": delivery["claim_token"]}
                    elif index % 3 == 1:
                        path, arguments = "/relay/deliveries/mcp-ack", {"receipt": delivery["receipt"]}
                    else:
                        path, arguments = "/relay/replies", {
                            "receipt": delivery["receipt"], "payload": f"Reply 東京 {index}",
                        }
                    ack_probes.append(asyncio.create_task(client.post(path, json={
                        "delivery_id": delivery["delivery_id"], **arguments, **scope,
                    })))
                health = await asyncio.wait_for(client.get("/health"), 5)
                assert health.status_code in {200, 503}
                combined = asyncio.gather(*probes, *ack_probes)
                try:
                    await asyncio.wait_for(asyncio.shield(combined), 5)
                    progressed = True
                except asyncio.TimeoutError:
                    pass
                evidence = {
                    "callback_threads": callback_threads,
                    "blocked_stacks": stacks,
                    "storage_admissions_while_held": list(admissions),
                    "completed_independent_requests": sum(task.done() for task in probes),
                    "completed_independent_acks": sum(task.done() for task in ack_probes),
                    "persisted_sends_waiting_for_callbacks": len(persisted),
                    "codex_callbacks_inside": len(stacks),
                    "codex_callbacks_queued_before_total_capacity": len(codex_requests) - len(stacks),
                    "health_status": health.status_code,
                    "native_schedules_while_held": len(native_schedules),
                }
            finally:
                release.set()
                await asyncio.to_thread(holder.join, 5)
                assert not holder.is_alive()
                send_results = await asyncio.wait_for(asyncio.gather(*sends), 5)
                probe_results = await asyncio.wait_for(asyncio.gather(*probes), 5)
                ack_results = await asyncio.wait_for(asyncio.gather(*ack_probes), 5)
                armed = False
            assert gate_errors == [], gate_errors
            assert len(native_schedules) == 4
            assert all(response.status_code == 200 for response in send_results), [
                (response.status_code, response.text) for response in send_results
            ]
            assert all(response.status_code == 200 for response in probe_results), [
                (response.status_code, response.text) for response in probe_results
            ]
            assert all(response.status_code == 200 for response in ack_results), [
                (response.status_code, response.text) for response in ack_results
            ]
            replies = []
            for index, (expected, acknowledged) in enumerate(zip(acknowledgments, ack_results)):
                if index % 3 == 2:
                    reply = acknowledged.json()
                    assert reply["in_reply_to"] == expected["message_id"]
                    assert reply["payload"] == f"Reply 東京 {index}"
                    reply_delivery, = reply["deliveries"]
                    assert reply_delivery["recipient_runtime"] == "opencode"
                    assert reply_delivery["recipient_session_ref"] == "sender"
                    assert reply_delivery["state"] == "pending"
                    replies.append(reply)
                else:
                    assert acknowledged.json()["delivery_id"] == expected["delivery_id"]
                    assert acknowledged.json()["state"] == "delivered"
                state = await client.get(f"/relay/messages/{expected['message_id']}", params=scope)
                assert state.status_code == 200, state.text
                retained, = state.json()["deliveries"]
                assert retained["delivery_id"] == expected["delivery_id"]
                assert retained["state"] == "delivered"
                assert retained["attempts"] == 1
            sender_turn = await client.post("/relay/turn", json={
                "runtime": "opencode", "session_ref": "sender", **scope,
            })
            assert sender_turn.status_code == 200, sender_turn.text
            assert {delivery["delivery_id"] for delivery in sender_turn.json()["deliveries"]} == {
                reply["deliveries"][0]["delivery_id"] for reply in replies
            }
            for delivery in sender_turn.json()["deliveries"]:
                acknowledged = await client.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **scope,
                })
                assert acknowledged.status_code == 200, acknowledged.text
            for i, message in enumerate(messages):
                trace, status, claimed = probe_results[i * 3:i * 3 + 3]
                assert trace.json()["message_id"] == status.json()["message_id"] == message["message_id"]
                delivery, = claimed.json()["deliveries"]
                assert delivery["delivery_id"] == message["deliveries"][0]["delivery_id"]
                assert delivery["attempts"] == 1
                acknowledged = await client.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **scope,
                })
                assert acknowledged.status_code == 200, acknowledged.text
                readback = await client.get(f"/relay/messages/{message['message_id']}", params=scope)
                assert readback.status_code == 200, readback.text
                retained, = readback.json()["deliveries"]
                assert retained["delivery_id"] == delivery["delivery_id"]
                assert retained["state"] == "delivered"
                assert retained["attempts"] == 1
            assert app.state._wait_for_operations(0)
            assert progressed, evidence

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        if holder.ident is not None:
            holder.join(5)
        try:
            app.state.pallium_service.close()
        finally:
            app.state.pallium_service._storage.close()


async def _start_operation_barrier(app):
    entered = threading.Event()

    def wait_for_operations() -> bool:
        entered.set()
        return app.state._wait_for_operations(2)

    barrier = asyncio.create_task(asyncio.to_thread(wait_for_operations))
    assert await asyncio.to_thread(entered.wait, 1)
    return barrier


async def _assert_barrier_waiting(barrier) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(barrier), 0.05)


@pytest.mark.parametrize("projection_fails", [False, True])
def test_activation_projection_uses_tracked_relay_runner_after_admission(
    tmp_path, monkeypatch, projection_fails,
) -> None:
    from app import dependencies

    original_create_router = dependencies.create_router
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    events, runner_calls, projection_threads, projections = [], [], [], []
    loop_thread = threading.get_ident()

    def observe_router(service, **kwargs):
        runner = kwargs["relay_runner"]
        project = kwargs["relay_activation_callback"]
        admit = kwargs["relay_turn_admission_callback"]

        async def observed_runner(operation):
            runner_calls.append(operation)
            return await runner(operation)

        codex_runner = kwargs.get("relay_codex_runner")
        if codex_runner is not None:
            async def observed_codex_runner(operation):
                runner_calls.append(operation)
                return await codex_runner(operation)
            kwargs["relay_codex_runner"] = observed_codex_runner

        def observed_admission(*args):
            events.append("admission")
            return admit(*args)

        def observed_projection(row):
            events.append("projection")
            projection_threads.append(threading.get_ident())
            entered.set()
            try:
                # Avoid hanging the regression on the broken event-loop path.
                if threading.get_ident() != loop_thread:
                    assert release.wait(10), "projection release watchdog expired"
                if projection_fails:
                    raise RuntimeError("activation read unavailable")
                projection = project(row)
                projections.append(projection)
                return projection
            finally:
                finished.set()

        kwargs.update(
            relay_runner=observed_runner,
            relay_turn_callback=lambda *_: events.append("turn_callback"),
            relay_turn_admission_callback=observed_admission,
            relay_activation_callback=observed_projection,
        )
        return original_create_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    scope = {"container_ref": "git:example.test/activation-projection"}

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            turn = asyncio.create_task(client.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "projection-東京", **scope,
            }))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                assert len(projection_threads) == 1
                assert projection_threads[0] != loop_thread
                assert events == ["turn_callback", "admission", "projection"]
                assert len(runner_calls) == 4
                health = await asyncio.wait_for(client.get("/health"), 5)
                assert health.status_code in {200, 503}
                assert not finished.is_set()
                assert not turn.done()
                assert not app.state._wait_for_operations(0)
            finally:
                release.set()
                response = await asyncio.wait_for(turn, 5)
            assert response.status_code == 200
            result = response.json()
            assert result["session"]["session_ref"] == "projection-東京"
            assert result["deliveries"] == []
            assert result["session"]["activation"] == (
                None if projection_fails else projections[0]
            )
            assert app.state._wait_for_operations(0)
            listed = await client.get("/relay/sessions", params=scope)
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            listed_session = listed.json()[0]
            for field in ("first_seen_at", "last_seen_at"):
                assert datetime.fromisoformat(listed_session.pop(field)).replace(tzinfo=timezone.utc) == (
                    datetime.fromisoformat(result["session"].pop(field)).replace(tzinfo=timezone.utc)
                )
            assert listed_session == result["session"]
            assert len(runner_calls) == 6

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        app.state.pallium_service._storage.close()


@pytest.mark.parametrize("phase,outcome", [
    (phase, outcome)
    for phase in (
        "snapshot", "turn", "admission", "send", "reply_ack", "reply_send",
        "ack", "mcp_ack", "register", "close",
    )
    for outcome in ("success", "error")
] + [("register", "refused"), ("close", "refused")])
def test_relay_callbacks_use_tracked_runner_without_blocking_health(
    tmp_path, monkeypatch, phase, outcome,
) -> None:
    from app import dependencies
    from core.claude_wake import ClaudeWakeRegistry

    entered, release = threading.Event(), threading.Event()
    events, callback_threads, gate_errors = [], [], []
    sent_message_ids = []
    loop_thread = threading.get_ident()
    armed = False
    selected = {"reply_ack": "ack", "reply_send": "send", "mcp_ack": "ack"}.get(phase, phase)

    def observe(name, callback):
        def call(*args, **kwargs):
            if armed:
                events.append(name)
                if name == "send":
                    sent_message_ids.append(args[0]["message_id"])
                if name == selected:
                    callback_threads.append(threading.get_ident())
                    entered.set()
                    # Broken synchronous dispatch must fail without hanging the loop.
                    if threading.get_ident() != loop_thread and not release.wait(10):
                        gate_errors.append("callback release watchdog expired")
                    if outcome == "error":
                        if name in {"register", "close"}:
                            raise ValueError("invalid registration")
                        raise RuntimeError("callback unavailable")
                    if outcome == "refused":
                        return False
            return callback(*args, **kwargs) if callback is not None else None
        return call

    original_create_router = dependencies.create_router

    def observe_router(service, **kwargs):
        for name, key in (
            ("snapshot", "relay_turn_snapshot_callback"),
            ("turn", "relay_turn_callback"),
            ("admission", "relay_turn_admission_callback"),
            ("send", "relay_send_callback"),
            ("ack", "relay_ack_callback"),
        ):
            kwargs[key] = observe(name, kwargs.get(key))
        return original_create_router(service, **kwargs)

    registry = ClaudeWakeRegistry()
    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr("app.main.build_claude_wake_registry", lambda *_: registry)
    # The callback contract ends at scheduling, before external native transport.
    monkeypatch.setattr(dependencies, "schedule_codex_relay_wake", lambda *_, **__: None)
    monkeypatch.setattr(dependencies, "schedule_claude_relay_wake", lambda *_, **__: None)
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    monkeypatch.setattr(registry, "register", observe("register", registry.register))
    monkeypatch.setattr(registry, "close", observe("close", registry.close))
    scope = {"container_ref": "git:example.test/callbacks-東京"}
    runtime = "claude-code" if phase in {"register", "close"} else "codex"
    registration = {
        "runtime": "claude-code", "session_ref": "target", **scope,
        "socket_path": "/tmp/callback.sock", "token": "callback-token",
        "idle": True, "intent_id": "callback-intent",
    }

    async def exercise():
        nonlocal armed
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with _observe_setup_writer(app.state.pallium_service._storage, monkeypatch):
                for role in ("sender", "target"):
                    response = await client.post("/relay/turn", json={
                        "runtime": runtime, "session_ref": role, **scope,
                    })
                    assert response.status_code == 200, response.text
            message = await client.post("/relay/messages", json={
                "sender_runtime": runtime, "sender_session_ref": "sender",
                "recipient": f"{runtime}:target",
                "payload": "callback payload 東京", **scope,
            })
            assert message.status_code == 200
            message_id = message.json()["message_id"]
            delivery_id = message.json()["deliveries"][0]["delivery_id"]
            turn_payload = {"runtime": runtime, "session_ref": "target", "max_chars": 1000, **scope}
            if phase in {"snapshot", "turn", "admission"}:
                path, payload = "/relay/turn", {**turn_payload, "wake_delivery_id": delivery_id}
                expected_events = ["snapshot", "turn", "admission"]
            elif phase == "send":
                path, payload = "/relay/messages", {
                    "sender_runtime": runtime, "sender_session_ref": "sender",
                    "recipient": f"{runtime}:target",
                    "payload": "second payload", **scope,
                }
                expected_events = ["send"]
            elif phase in {"register", "close"}:
                if phase == "close":
                    assert (await client.post("/internal/claude-wake/register", json=registration)).status_code == 204
                path = f"/internal/claude-wake/{phase}"
                payload = registration if phase == "register" else {
                    "runtime": runtime, "session_ref": "target", **scope,
                    "intent_id": "callback-intent",
                }
                expected_events = [phase]
            else:
                claimed = await client.post("/relay/turn", json=turn_payload)
                assert claimed.status_code == 200
                delivery = claimed.json()["deliveries"][0]
                payload = {"delivery_id": delivery_id, **scope}
                if phase == "ack":
                    path = "/relay/deliveries/ack"
                    payload["claim_token"] = delivery["claim_token"]
                else:
                    payload["receipt"] = delivery["receipt"]
                    path = "/relay/deliveries/mcp-ack"
                expected_events = ["ack"]
                if phase.startswith("reply_"):
                    path = "/relay/replies"
                    payload["payload"] = "reply 東京"
                    expected_events = ["ack", "send"]
            armed = True
            request = asyncio.create_task(client.post(path, json=payload))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                assert len(callback_threads) == 1
                assert callback_threads[0] != loop_thread
                health = await asyncio.wait_for(client.get("/health"), 5)
                assert health.status_code in {200, 503}
                assert not request.done()
                assert not app.state._wait_for_operations(0)
                # Persistence precedes callbacks; snapshot precedes the exact claim.
                persisted_message_id = sent_message_ids[0] if phase == "send" else message_id
                state = await client.get(f"/relay/messages/{persisted_message_id}", params=scope)
                assert state.status_code == 200
                if phase == "send":
                    assert persisted_message_id != message_id
                    assert state.json()["payload"] == payload["payload"]
                expected_state = (
                    "pending" if phase in {"snapshot", "send", "register", "close"}
                    else "claimed" if phase in {"turn", "admission"} else "delivered"
                )
                assert state.json()["deliveries"][0]["state"] == expected_state
            finally:
                release.set()
                response = await asyncio.wait_for(request, 5)
                armed = False
            assert gate_errors == []
            assert events == expected_events
            assert app.state._wait_for_operations(0)
            expected_status = 200
            if phase in {"register", "close"}:
                expected_status = 204 if outcome == "success" else (
                    409 if phase == "register" and outcome == "refused" else 400
                )
            assert response.status_code == expected_status, response.text
            if phase == "send" or phase.startswith("reply_"):
                assert sent_message_ids == [response.json()["message_id"]]
                sent = await client.get(f"/relay/messages/{sent_message_ids[0]}", params=scope)
                assert sent.status_code == 200
                assert sent.json()["payload"] == payload["payload"]
                assert sent.json()["deliveries"][0]["state"] == "pending"
                if phase.startswith("reply_"):
                    assert response.json()["in_reply_to"] == message_id
                    assert sent.json()["in_reply_to"] == message_id
                    assert sent.json()["deliveries"][0]["recipient_session_ref"] == "sender"
            if expected_status == 400:
                assert response.json()["detail"] == "invalid registration"
            elif expected_status == 409:
                assert response.json()["detail"] == "registration rejected"
            if phase in {"snapshot", "turn", "admission"}:
                claimed = response.json()["deliveries"]
                assert len(claimed) == 1
                assert claimed[0]["delivery_id"] == delivery_id
                ack = await client.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery_id, "claim_token": claimed[0]["claim_token"], **scope,
                })
                assert ack.status_code == 200
            if phase not in {"send", "register", "close"}:
                state = await client.get(f"/relay/messages/{message_id}", params=scope)
                assert state.status_code == 200
                assert state.json()["deliveries"][0]["state"] == "delivered"
            if phase in {"register", "close"}:
                listed = await client.get("/relay/sessions", params=scope)
                assert listed.status_code == 200
                target = next(row for row in listed.json() if row["session_ref"] == "target")
                registered = (phase == "register" and outcome == "success") or (phase == "close" and outcome != "success")
                assert target["activation"]["availability"] == ("ready" if registered else "unknown")

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        try:
            app.state.pallium_service.close()
        finally:
            app.state.pallium_service._storage.close()


@pytest.mark.parametrize("runtime", ["claude-code", "opencode"])
def test_non_codex_http_activation_does_not_read_codex_authority(
    tmp_path, monkeypatch, runtime,
) -> None:
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    monkeypatch.setattr("app.dependencies.schedule_claude_relay_wake", lambda *_, **__: None)
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    reads = []

    def unexpected_authority_read(_registry):
        reads.append("usable")
        raise AssertionError("non-Codex projection consulted Codex authority")

    scope = {"container_ref": "git:example.test/runtime-isolation"}

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for session in ("sender", "target"):
                response = await client.post("/relay/turn", json={
                    "runtime": runtime, "session_ref": session, **scope,
                })
                assert response.status_code == 200
            message = await client.post("/relay/messages", json={
                "sender_runtime": runtime, "sender_session_ref": "sender",
                "recipient": f"{runtime}:target", "payload": "runtime isolation", **scope,
            })
            assert message.status_code == 200
            monkeypatch.setattr(
                type(app.state.codex_wake_registry), "usable", property(unexpected_authority_read),
            )
            sessions = await client.get("/relay/sessions", params=scope)
            assert sessions.status_code == 200
            assert len(sessions.json()) == 2
            assert all(row["activation"]["runtime"] == runtime for row in sessions.json())
            status = await client.get(f"/relay/messages/{message.json()['message_id']}", params=scope)
            assert status.status_code == 200
            assert status.json()["deliveries"][0]["activation"]["runtime"] == runtime
            assert reads == []

    try:
        asyncio.run(exercise())
    finally:
        try:
            app.state.pallium_service.close()
        finally:
            app.state.pallium_service._storage.close()


def test_relay_and_diagnostics_survive_saturated_memory_worker_capacity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    started = threading.Event()
    release = threading.Event()

    @app.get("/_test/block-memory-worker")
    def block_memory_worker():
        started.set()
        release.wait(10)
        return {"released": True}

    async def exercise() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            blocked = asyncio.create_task(client.get("/_test/block-memory-worker"))
            try:
                assert await asyncio.to_thread(started.wait, 5.0)
                health, status, queue, turn = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/health"), client.get("/status"),
                        client.get("/debug/queue/health"),
                        client.post("/relay/turn", json={
                            "runtime": "codex", "session_ref": "capacity-target",
                            "container_ref": "git:example.test/capacity",
                            "actor_ref": "capacity-user",
                        }),
                    ), timeout=5.0,
                )
                assert health.status_code in {200, 503} and turn.status_code == 200
                assert set(status.json()) == {
                    "pending_items", "oldest_pending_age_seconds",
                    "total_source_items", "total_memory_objects",
                    "active_memory_objects", "snapshot", "storage",
                    "vector_index_ready", "embedding_provider_ok", "ingestion",
                    "vector_expected", "vector_rebuild", "uptime_seconds",
                    "query", "metrics_summary", "historical_lookup_funnel",
                    "derived_memory", "relay_wake",
                }
                assert set(queue.json()) == {
                    "status_counts", "status_counts_24h",
                    "oldest_pending_age_seconds", "pending_without_use_case_count",
                    "unclaimable_pending_counts", "leased_source_items",
                    "leased_thread_scopes", "recent_failures", "retention",
                }
            finally:
                release.set()
                await blocked
                limiter.total_tokens = original_tokens

            relay_started = threading.Event()
            relay_release = threading.Event()
            relay_finished = threading.Event()
            storage = app.state.pallium_service._storage
            original_relay_turn = storage.relay_turn

            def block_relay_operation(**kwargs):
                relay_started.set()
                assert relay_release.wait(2)
                try:
                    return original_relay_turn(**kwargs)
                finally:
                    relay_finished.set()

            monkeypatch.setattr(storage, "relay_turn", block_relay_operation)
            cancelled = asyncio.create_task(client.post("/relay/turn", json={
                "runtime": "codex",
                "session_ref": "cancelled-request-target",
                "container_ref": "git:example.test/capacity",
                "actor_ref": "capacity-user",
            }))
            assert await asyncio.to_thread(relay_started.wait, 0.5)
            cancelled.cancel()
            try:
                await cancelled
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled Relay request must stay cancelled")
            assert not relay_finished.is_set()
            shutdown_barrier = await _start_operation_barrier(app)
            await _assert_barrier_waiting(shutdown_barrier)
            relay_release.set()
            assert await asyncio.to_thread(relay_finished.wait, 0.5)
            assert await asyncio.wait_for(shutdown_barrier, 1)

            monkeypatch.setattr(storage, "relay_turn", original_relay_turn)
            diagnostic_slots_full = threading.Event()
            diagnostic_release = threading.Event()
            diagnostic_finished = threading.Event()
            diagnostic_lock = threading.Lock()
            diagnostic_started = 0
            diagnostic_completed = 0
            original_queue_health = storage.get_queue_health_snapshot

            def block_diagnostic_operation(**kwargs):
                nonlocal diagnostic_started, diagnostic_completed
                with diagnostic_lock:
                    diagnostic_started += 1
                    if diagnostic_started == 2:
                        diagnostic_slots_full.set()
                assert diagnostic_release.wait(2)
                try:
                    return original_queue_health(**kwargs)
                finally:
                    with diagnostic_lock:
                        diagnostic_completed += 1
                        if diagnostic_completed == 3:
                            diagnostic_finished.set()

            monkeypatch.setattr(
                storage, "get_queue_health_snapshot", block_diagnostic_operation,
            )
            diagnostics = [
                asyncio.create_task(client.get("/debug/queue/health"))
                for _ in range(3)
            ]
            assert await asyncio.to_thread(diagnostic_slots_full.wait, 0.5)
            with diagnostic_lock:
                assert diagnostic_started == 2
            relay_during_diagnostic = await asyncio.wait_for(
                client.post("/relay/turn", json={
                    "runtime": "codex",
                    "session_ref": "diagnostic-isolation-target",
                    "container_ref": "git:example.test/capacity",
                    "actor_ref": "capacity-user",
                }),
                timeout=1.0,
            )
            assert relay_during_diagnostic.status_code == 200
            diagnostic_barrier = await _start_operation_barrier(app)
            await _assert_barrier_waiting(diagnostic_barrier)
            diagnostic_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*diagnostics), 1.0)
            assert all(response.status_code == 200 for response in responses)
            assert await asyncio.to_thread(diagnostic_finished.wait, 0.5)
            assert await asyncio.wait_for(diagnostic_barrier, 1)
    try:
        asyncio.run(exercise())
    finally:
        app.state.pallium_service._storage.close()

@pytest.mark.parametrize("failure", [None, "callback", "schedule"])
def test_codex_operation_tracking_settles_after_event_loop_closes(tmp_path, monkeypatch, failure):
    from contextlib import ExitStack
    import json
    import time
    from app import dependencies, main as app_main

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    worker_threads, outcomes = [], []
    readiness = {}
    original_router, original_dispatch = dependencies.create_router, anyio.to_thread.run_sync
    callback_error = ValueError("controlled callback failure")
    schedule_error = RuntimeError("controlled open-loop scheduling failure")
    callback_result = object()

    def callback(*_args):
        worker_threads.append(threading.current_thread())
        started.set()
        assert release.wait(5), "callback gate watchdog expired"
        if failure == "callback":
            raise callback_error
        return callback_result

    def observe_router(service, **kwargs):
        kwargs["relay_turn_callback"] = callback
        return original_router(service, **kwargs)

    async def observe_dispatch(operation, **kwargs):
        def observe_completion():
            try:
                result = operation()
                if worker_threads and threading.current_thread() is worker_threads[0]:
                    outcomes.append(result)
                return result
            except BaseException as error:
                if worker_threads and threading.current_thread() is worker_threads[0]:
                    outcomes.append(error)
                raise
            finally:
                if worker_threads and threading.current_thread() is worker_threads[0]:
                    finished.set()
        return await original_dispatch(observe_completion, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr("app.main.anyio.to_thread.run_sync", observe_dispatch)
    monkeypatch.setattr("app.mcp.server.create_server", lambda **_: (_ for _ in ()).throw(ImportError()))
    cleanup, original_storage = ExitStack(), app_main.build_storage_provider

    def owned_storage(*args, **kwargs):
        storage = original_storage(*args, **kwargs)
        cleanup.callback(storage.close)
        return storage

    monkeypatch.setattr(app_main, "build_storage_provider", owned_storage)
    try:
        app = create_app(AppConfig(
            storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
            relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
            default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        ))
    except BaseException:
        cleanup.close()
        raise
    cleanup.callback(app.state.pallium_service._storage.close)
    cleanup.callback(app.state.pallium_service.close)
    loop = asyncio.new_event_loop()
    if failure == "schedule":
        original_schedule = loop.call_soon_threadsafe

        def fail_permit_schedule(callback, *args, **kwargs):
            if getattr(callback, "__name__", None) == "release_on_behalf_of":
                assert not loop.is_closed()
                raise schedule_error
            return original_schedule(callback, *args, **kwargs)

        monkeypatch.setattr(loop, "call_soon_threadsafe", fail_permit_schedule)

    async def cancel_http_request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # Qualify steady-state worker settlement separately from first-route setup.
            began = time.monotonic()
            warmup = await client.post("/relay/turn", json={})
            readiness["warmup_seconds"] = time.monotonic() - began
            assert warmup.status_code == 422, warmup.text
            assert not started.is_set() and not finished.is_set()
            assert worker_threads == [] and outcomes == []
            assert app.state._wait_for_operations(0)
            request = asyncio.create_task(client.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "loop-close-target",
                "container_ref": "git:example.test/loop-close", "actor_ref": "capacity-user",
            }))
            try:
                assert await asyncio.to_thread(started.wait, 1)
            finally:
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request

    try:
        loop.run_until_complete(cancel_http_request())
        if failure != "schedule":
            loop.close()
        assert not finished.is_set()
        assert not app.state._wait_for_operations(0)
        release.set()
        assert finished.wait(1)
        worker_threads[0].join(5)
        assert not worker_threads[0].is_alive()
        assert app.state._wait_for_operations(1)
        expected = {None: callback_result, "callback": callback_error, "schedule": schedule_error}
        assert outcomes == [expected[failure]]
    finally:
        release.set()
        if not loop.is_closed():
            loop.close()
        for worker in worker_threads:
            worker.join(5)
        cleanup.close()
        print("pallium closed-loop readiness: " + json.dumps(readiness), file=sys.stderr)
        (tmp_path / "closed-loop-readiness.json").write_text(
            json.dumps(readiness), encoding="utf-8",
        )


def test_capacity_limiter_reserves_released_token_for_waiting_borrower() -> None:
    import anyio

    async def exercise():
        limiter = anyio.CapacityLimiter(4)
        held = []
        newcomer, waiting_borrower = object(), object()
        started, awakened, settle = asyncio.Event(), asyncio.Event(), asyncio.Event()
        newcomer_acquired = False
        task = None

        async def waiter():
            started.set()
            await limiter.acquire_on_behalf_of(waiting_borrower)
            try:
                awakened.set()
                await settle.wait()
            finally:
                limiter.release_on_behalf_of(waiting_borrower)

        try:
            for _ in range(4):
                borrower = object()
                await limiter.acquire_on_behalf_of(borrower)
                held.append(borrower)
            task = asyncio.create_task(waiter())
            await started.wait()
            assert limiter.statistics().tasks_waiting == 1
            limiter.release_on_behalf_of(held.pop())
            newcomer_refused = False
            try:
                limiter.acquire_on_behalf_of_nowait(newcomer)
            except anyio.WouldBlock:
                newcomer_refused = True
            else:
                newcomer_acquired = True
            await awakened.wait()
            assert limiter.borrowed_tokens == limiter.total_tokens == 4
            assert newcomer_refused
            assert limiter.statistics().tasks_waiting == 0
        finally:
            settle.set()
            if newcomer_acquired:
                limiter.release_on_behalf_of(newcomer)
            for borrower in held:
                limiter.release_on_behalf_of(borrower)
            if task is not None:
                await task
            assert limiter.borrowed_tokens == 0
            assert limiter.statistics().tasks_waiting == 0

    anyio.run(exercise, backend="asyncio")


def test_operation_tracking_covers_cancellation_and_failure_boundaries(tmp_path, monkeypatch) -> None:
    from app import dependencies

    captured_runners = {}
    original_router = dependencies.create_router

    def observe_router(service, **kwargs):
        captured_runners["codex"] = kwargs["relay_codex_runner"]
        captured_runners["ordinary"] = kwargs["relay_runner"]
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(
        "app.mcp.server.create_server",
        lambda **_: (_ for _ in ()).throw(ImportError()),
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    storage = app.state.pallium_service._storage
    original_relay_turn = storage.relay_turn
    original_dispatch = anyio.to_thread.run_sync

    def payload(session_ref: str) -> dict[str, str]:
        return {
            "runtime": "codex",
            "session_ref": session_ref,
            "container_ref": "git:example.test/operation-tracking",
            "actor_ref": "capacity-user",
        }

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            captured = []
            dispatched = asyncio.Event()
            storage_calls = 0

            def observe_relay_turn(**kwargs):
                nonlocal storage_calls
                storage_calls += 1
                return original_relay_turn(**kwargs)

            async def hold_before_worker_claim(operation, **_kwargs):
                captured.append(operation)
                dispatched.set()
                await asyncio.Future()

            monkeypatch.setattr(storage, "relay_turn", observe_relay_turn)
            monkeypatch.setattr("app.main.anyio.to_thread.run_sync", hold_before_worker_claim)
            cancelled_after_dispatch = asyncio.create_task(
                client.post("/relay/turn", json=payload("cancelled-after-dispatch"))
            )
            await asyncio.wait_for(dispatched.wait(), 1)
            cancelled_after_dispatch.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled_after_dispatch
            assert len(captured) == 1
            assert captured[0]() is None
            assert storage_calls == 0
            assert await asyncio.to_thread(app.state._wait_for_operations, 1)

            async def fail_dispatch(*_args, **_kwargs):
                raise RuntimeError("dispatch failed")

            monkeypatch.setattr("app.main.anyio.to_thread.run_sync", fail_dispatch)
            with pytest.raises(RuntimeError, match="dispatch failed"):
                await client.post("/relay/turn", json=payload("dispatch-failure"))
            assert await asyncio.to_thread(app.state._wait_for_operations, 1)

            monkeypatch.setattr("app.main.anyio.to_thread.run_sync", original_dispatch)
            relay_release = threading.Event()
            four_started = threading.Event()
            started_count = 0
            started_lock = threading.Lock()

            def block_four_relay_workers(**kwargs):
                nonlocal started_count
                with started_lock:
                    started_count += 1
                    if started_count == 4:
                        four_started.set()
                assert relay_release.wait(3)
                return original_relay_turn(**kwargs)

            monkeypatch.setattr(storage, "relay_turn", block_four_relay_workers)
            active = [
                asyncio.create_task(client.post("/relay/turn", json=payload(f"active-{index}")))
                for index in range(4)
            ]
            assert await asyncio.to_thread(four_started.wait, 1)
            queued = asyncio.create_task(
                client.post("/relay/turn", json=payload("cancelled-while-queued"))
            )
            await asyncio.sleep(0.05)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            queued_barrier = await _start_operation_barrier(app)
            await _assert_barrier_waiting(queued_barrier)
            relay_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*active), 3)
            assert all(response.status_code == 200 for response in responses)
            assert await asyncio.wait_for(queued_barrier, 1)
            assert started_count == 4

            native_release, three_native_started = threading.Event(), threading.Event()
            native_calls = []

            def block_codex_operation():
                native_calls.append(threading.get_ident())
                if len(native_calls) == 3:
                    three_native_started.set()
                assert native_release.wait(3)

            active_native = [asyncio.create_task(captured_runners["codex"](block_codex_operation))
                             for _ in range(3)]
            queued_at_gate = asyncio.Event()

            async def queue_codex_operation():
                queued_at_gate.set()
                return await captured_runners["codex"](lambda: native_calls.append("cancelled"))

            try:
                assert await asyncio.to_thread(three_native_started.wait, 1)
                queued_native = asyncio.create_task(queue_codex_operation())
                await asyncio.wait_for(queued_at_gate.wait(), 1)
                queued_native.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued_native
                native_barrier = await _start_operation_barrier(app)
                await _assert_barrier_waiting(native_barrier)
            finally:
                native_release.set()
                await asyncio.wait_for(asyncio.gather(*active_native), 3)
            assert await asyncio.wait_for(native_barrier, 1)
            assert len(native_calls) == 3
            assert "cancelled" not in native_calls

            native_release.clear()
            three_native_started.clear()
            native_calls.clear()
            running_native = [asyncio.create_task(captured_runners["codex"](block_codex_operation))
                              for _ in range(3)]
            replacement_started = threading.Event()
            replacement = None
            try:
                assert await asyncio.to_thread(three_native_started.wait, 1)
                for task in running_native:
                    task.cancel()
                for task in running_native:
                    with pytest.raises(asyncio.CancelledError):
                        await task
                replacement = asyncio.create_task(captured_runners["codex"](replacement_started.set))
                # An ordinary operation can complete, while a fourth Codex worker cannot.
                assert await asyncio.wait_for(captured_runners["ordinary"](lambda: "ordinary"), 1) == "ordinary"
                await _assert_barrier_waiting(replacement)
                assert not replacement_started.is_set()
                assert len(native_calls) == 3
                assert not app.state._wait_for_operations(0)
                running_barrier = await _start_operation_barrier(app)
                await _assert_barrier_waiting(running_barrier)
            finally:
                native_release.set()
                if replacement is not None:
                    await asyncio.wait_for(replacement, 3)
                assert await asyncio.to_thread(app.state._wait_for_operations, 3)
            assert replacement_started.is_set()
            assert await asyncio.wait_for(running_barrier, 1)

            def fail_worker(**_kwargs):
                raise RuntimeError("worker failed")

            monkeypatch.setattr(storage, "relay_turn", fail_worker)
            with pytest.raises(RuntimeError, match="worker failed"):
                await client.post("/relay/turn", json=payload("worker-failure"))
            assert await asyncio.to_thread(app.state._wait_for_operations, 1)

            monkeypatch.setattr(storage, "relay_turn", original_relay_turn)
            response = await client.post(
                "/relay/turn", json=payload("success-after-failures"),
            )
            assert response.status_code == 200
            assert await asyncio.to_thread(app.state._wait_for_operations, 1)

    try:
        asyncio.run(exercise())
    finally:
        app.state.pallium_service._storage.close()
