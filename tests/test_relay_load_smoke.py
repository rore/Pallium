from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.mark.slow
@pytest.mark.parametrize("caller_count", [24, 50])
def test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
    tmp_path, monkeypatch, caller_count, _isolated=False,
) -> None:
    if not _isolated:
        # As in runtime_logging coverage, isolate process-wide logging from pytest.
        program = """
import logging.config
import sys
from pathlib import Path
import pytest
from app.runtime_logging import build_uvicorn_log_config
logging.config.dictConfig(build_uvicorn_log_config(component='api'))
from tests.test_relay_load_smoke import test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle
patch = pytest.MonkeyPatch()
try:
    test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
        Path(sys.argv[1]), patch, int(sys.argv[2]), _isolated=True)
finally:
    patch.undo()
"""
        child = subprocess.run(
            [sys.executable, "-B", "-c", program, str(tmp_path), str(caller_count)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        return
    from app import codex_bridge_pipe, codex_wake
    from core.relay_activation import ActivationAttemptResult
    from scripts.live_funnel_smoke import ScratchServer
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from tests.test_agent_relay_hooks import _load

    workers, native_attempts, statements, sqlite_errors, hook_calls = [], [], [], [], []
    phases, health_samples, emissions, results, fanout_stacks = [], [], {}, [], {}
    fanout = False
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake

    class InertRetainedTransport:
        def dispatch(self, reservation, registry):
            spent = registry.begin_native_attempt(reservation)
            if spent is None:
                return None, reservation
            native_attempts.append(spent.delivery_id)
            return ActivationAttemptResult("accepted", "submitted"), spent

        def stop(self):
            pass

    def observe_schedule(*args, **kwargs):
        worker = original_schedule(*args, **kwargs)
        if worker is not None:
            workers.append(worker)
        return worker

    def observe_sql(_connection, _cursor, statement, _parameters, _context, _many):
        if fanout:
            statements.append(statement.split()[0].upper())

    def observe_sql_error(context):
        if fanout:
            error = context.original_exception
            frame, stack = sys._getframe(), []
            while frame is not None and len(stack) < 16:
                stack.append(frame.f_code.co_name)
                frame = frame.f_back
            sqlite_errors.append({
                "type": type(error).__name__,
                "code": getattr(error, "sqlite_errorcode", None),
                "name": getattr(error, "sqlite_errorname", None),
                "statement_kind": (context.statement or "").split()[0] if context.statement else None,
                "message": str(error),
                "function_stack": stack,
            })

    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", observe_schedule)
    monkeypatch.setattr(codex_bridge_pipe, "start_shadow_service", lambda *_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_inventory_service", lambda **_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_retained_service", InertRetainedTransport)
    monkeypatch.setattr(codex_bridge_pipe, "retained_wake_enabled", lambda: True)
    # Keep actual FastMCP initialization and its logging setup in this witness.
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    assert logging.getLogger().handlers
    assert all(type(handler).__name__ != "RichHandler" for handler in logging.getLogger().handlers)
    assert app.state.codex_wake_registry.initialize(old_owner_drained=True)
    common = _load("concurrent_codex_common", "integrations/codex/hooks/common.py")
    assert common.hook_deadline() is None
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(common, "STATE_DIR", tmp_path / "hook-state")
    original_request = common.relay_request

    def observe_hook_request(method, path, *args, **kwargs):
        started = time.perf_counter()
        response = original_request(method, path, *args, **kwargs)
        hook_calls.append({
            "method": method, "path": path,
            "seconds": time.perf_counter() - started,
            "returned": response is not None,
        })
        return response

    monkeypatch.setattr(common, "relay_request", observe_hook_request)
    event.listen(Engine, "before_cursor_execute", observe_sql)
    event.listen(Engine, "handle_error", observe_sql_error)
    scope = {"container_ref": "git:example.test/concurrent-http-東京"}

    async def exercise(base_url):
        nonlocal fanout
        start, ready, stop_health = asyncio.Event(), asyncio.Event(), asyncio.Event()
        ready_count = 0
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            for runtime, session in [
                ("opencode", "mixed-sender"),
                *[("codex", f"mixed-target-{i}") for i in range(caller_count)],
            ]:
                response = await client.post("/relay/turn", json={
                    "runtime": runtime, "session_ref": session, **scope,
                })
                assert response.status_code == 200, response.text

            async def request(index, phase, method, path, **kwargs):
                began = time.perf_counter()
                response = await client.request(method, path, **kwargs)
                phases.append({"index": index, "phase": phase,
                               "seconds": time.perf_counter() - began,
                               "status": response.status_code})
                assert response.status_code == 200, (index, phase, response.status_code, response.text)
                return response.json()

            def hook_claim_emit_ack(index, message):
                began = time.perf_counter()
                delivery = message["deliveries"][0]
                claimed = common.relay_turn(
                    "codex", f"mixed-target-{index}", scope["container_ref"],
                    max_chars=1000, wake_delivery_id=delivery["delivery_id"],
                )
                phases.append({"index": index, "phase": "hook_claim",
                               "seconds": time.perf_counter() - began,
                               "status": "returned" if claimed is not None else "refused"})
                assert claimed is not None, (index, "hook claim refused")
                claimed_delivery, = claimed["deliveries"]
                assert claimed_delivery["delivery_id"] == delivery["delivery_id"]
                assert claimed_delivery["message_id"] == message["message_id"]
                assert claimed_delivery["attempts"] == 1
                rendered, emitted = common.format_relay(claimed["deliveries"])
                assert emitted == [claimed_delivery]
                assert f"message_id: {message['message_id']}" in rendered
                assert f"delivery_id: {delivery['delivery_id']}" in rendered
                # Per-caller emission is observable before the hook owns its ACK.
                emissions[index] = (message["message_id"], delivery["delivery_id"])
                began = time.perf_counter()
                confirmed = common.acknowledge_relay(emitted, container_ref=scope["container_ref"])
                phases.append({"index": index, "phase": "hook_ack",
                               "seconds": time.perf_counter() - began,
                               "status": "confirmed" if confirmed == emitted else "refused"})
                assert confirmed == emitted, (index, "hook ACK refused")

            async def journey(index):
                nonlocal ready_count
                ready_count += 1
                if ready_count == caller_count:
                    ready.set()
                await start.wait()
                message = await request(index, "send", "POST", "/relay/messages", json={
                    "sender_runtime": "opencode", "sender_session_ref": "mixed-sender",
                    "recipient": f"codex:mixed-target-{index}",
                    "payload": f"Concurrent message 東京 {index}", **scope,
                })
                message_id = message["message_id"]
                trace, status = await asyncio.gather(
                    request(index, "trace", "GET", f"/relay/messages/{message_id}/trace"),
                    request(index, "status", "GET", f"/relay/messages/{message_id}", params=scope),
                )
                assert trace["message_id"] == status["message_id"] == message_id
                assert len(status["deliveries"]) == 1
                await asyncio.to_thread(hook_claim_emit_ack, index, message)
                retained = await request(index, "readback", "GET", f"/relay/messages/{message_id}", params=scope)
                delivery, = retained["deliveries"]
                assert delivery["delivery_id"] == message["deliveries"][0]["delivery_id"]
                assert delivery["state"] == "delivered"
                assert delivery["attempts"] == 1
                assert retained["payload"] == f"Concurrent message 東京 {index}"
                return message_id, delivery["delivery_id"]

            async def monitor_health():
                await start.wait()
                while not stop_health.is_set():
                    began = time.perf_counter()
                    try:
                        response = await client.get("/health")
                        health_samples.append({"seconds": time.perf_counter() - began,
                                               "status": response.status_code})
                    except Exception as error:
                        health_samples.append({"seconds": time.perf_counter() - began,
                                               "error": type(error).__name__})
                    if not fanout_stacks and not stop_health.is_set():
                        for ident, frame in sys._current_frames().items():
                            thread = next((thread for thread in threading.enumerate() if thread.ident == ident), None)
                            if thread is None or not ("AnyIO" in thread.name or "scratch-server" == thread.name):
                                continue
                            stack = []
                            while frame is not None and len(stack) < 10:
                                stack.append((frame.f_code.co_name, frame.f_lineno))
                                frame = frame.f_back
                            fanout_stacks[thread.name + ":" + str(ident)] = stack
                    await asyncio.sleep(0.05)

            tasks = [asyncio.create_task(journey(i)) for i in range(caller_count)]
            health = asyncio.create_task(monitor_health())
            await ready.wait()
            fanout = True
            start.set()
            try:
                results.extend(await asyncio.gather(*tasks, return_exceptions=True))
            finally:
                stop_health.set()
                await health
            assert health_samples and all(sample.get("status") == 200 for sample in health_samples)
            failures = [(i, type(result).__name__, str(result))
                        for i, result in enumerate(results) if isinstance(result, BaseException)]
            assert failures == [], failures
            assert len(set(results)) == len(emissions) == caller_count
            assert set(results) == set(emissions.values())
            listed = await request(-1, "sessions", "GET", "/relay/sessions", params=scope)
            assert len(listed) == caller_count + 1
            assert common.hook_deadline() is None

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    try:
        with ScratchServer(app, "127.0.0.1", port) as server:
            monkeypatch.setattr(common, "PALLIUM_BASE_URL", server.base_url)
            try:
                asyncio.run(exercise(server.base_url))
            finally:
                for worker in workers:
                    worker.join(5)
                assert all(not worker.is_alive() for worker in workers)
                app.state.pallium_service._relay_trace_executor.submit(lambda: None).result(2)
    finally:
        fanout = False
        event.remove(Engine, "before_cursor_execute", observe_sql)
        event.remove(Engine, "handle_error", observe_sql_error)
        stacks = {}
        for ident, frame in sys._current_frames().items():
            thread = next((thread for thread in threading.enumerate() if thread.ident == ident), None)
            if thread is None or not ("AnyIO" in thread.name or "scratch-server" == thread.name):
                continue
            stack = []
            while frame is not None and len(stack) < 10:
                stack.append((frame.f_code.co_name, frame.f_lineno))
                frame = frame.f_back
            stacks[thread.name + ":" + str(ident)] = stack
        evidence = {
            "callers": caller_count, "phases": phases, "health": health_samples,
            "sql_statements": dict(Counter(statements)), "sqlite_errors": sqlite_errors,
            "hook_calls": hook_calls, "native_attempts": len(native_attempts),
            "native_workers": len(workers), "emissions": len(emissions),
            "successful_journeys": sum(not isinstance(result, BaseException) for result in results),
            "root_log_handlers": [type(handler).__name__ for handler in logging.getLogger().handlers],
            "bounded_stacks_during_fanout": fanout_stacks,
            "bounded_stacks_after_drain": stacks,
        }
        (tmp_path / "mixed-http-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print("mixed_http_summary=" + json.dumps({key: evidence[key] for key in (
            "callers", "sql_statements", "sqlite_errors", "native_attempts", "native_workers",
            "emissions", "successful_journeys", "root_log_handlers",
        )}))


@pytest.mark.slow
def test_relay_control_plane_survives_reasonable_concurrent_ingest_load(
    tmp_path, monkeypatch,
) -> None:
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
    scope = {
        "container_ref": "git:example.test/load-smoke",
        "actor_ref": "load-user",
    }

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            for runtime, session_ref in (
                ("codex", "load-sender"),
                ("opencode", "load-target"),
            ):
                response = await client.post("/relay/turn", json={
                    "runtime": runtime,
                    "session_ref": session_ref,
                    **scope,
                })
                assert response.status_code == 200, response.text

            async def ingest(index: int) -> httpx.Response:
                return await client.post("/items", json=[{
                    "source_type": "chat_thread",
                    "source_id": f"load-source-{index}",
                    "content_type": "text/plain",
                    "content": f"Concurrent load item {index} with enough text to persist.",
                    "artifact_kind": "message",
                    "role": "user",
                    **scope,
                }])

            ingests = [asyncio.create_task(ingest(index)) for index in range(48)]
            relay_latencies = []
            for batch in range(8):
                for offset in range(3):
                    started = time.perf_counter()
                    sent = await client.post("/relay/messages", json={
                        "sender_runtime": "codex",
                        "sender_session_ref": "load-sender",
                        "recipient": "opencode:load-target",
                        "payload": f"load relay {batch}-{offset}",
                        **scope,
                    })
                    relay_latencies.append(time.perf_counter() - started)
                    assert sent.status_code == 200, sent.text
                turn = await client.post("/relay/turn", json={
                    "runtime": "opencode",
                    "session_ref": "load-target",
                    **scope,
                })
                assert turn.status_code == 200, turn.text
                deliveries = turn.json()["deliveries"]
                assert len(deliveries) == 3
                for delivery in deliveries:
                    acknowledged = await client.post(
                        "/relay/deliveries/ack",
                        json={
                            "delivery_id": delivery["delivery_id"],
                            "claim_token": delivery["claim_token"],
                            **scope,
                        },
                    )
                    assert acknowledged.status_code == 200, acknowledged.text

            health_started = time.perf_counter()
            health = await client.get("/health")
            health_latency = time.perf_counter() - health_started
            responses = await asyncio.gather(*ingests)
            assert all(response.status_code == 200 for response in responses)
            assert health.status_code == 200
            assert max(relay_latencies) < 2.0
            assert health_latency < 0.5

    asyncio.run(asyncio.wait_for(exercise(), timeout=20))
