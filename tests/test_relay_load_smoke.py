from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
from tests.relay_hook_journey import hook_claim_emit_ack as _hook_claim_emit_ack


@pytest.mark.slow
@pytest.mark.parametrize("caller_count", [24, 50])
def test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
    tmp_path, monkeypatch, caller_count, _isolated=False, _synchronized_hooks=False, _diagnostics=None, _timing_only=False,
    _process_hooks=False, _server_only=False, _external_base_url=None,
) -> None:
    if _diagnostics is None:
        mode = os.environ.get('PALLIUM_RELAY_LOAD_DIAGNOSTICS')
        _diagnostics = mode == '1'
        _timing_only = _timing_only or mode == 'timing'
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
        Path(sys.argv[1]), patch, int(sys.argv[2]), _isolated=True,
        _synchronized_hooks=sys.argv[3] == '1', _diagnostics=sys.argv[4] == '1', _timing_only=sys.argv[5] == '1', _process_hooks=sys.argv[6] == '1')
finally:
    patch.undo()
"""
        child = subprocess.run(
            [sys.executable, "-B", "-c", program, str(tmp_path), str(caller_count), str(int(_synchronized_hooks)), str(int(_diagnostics)), str(int(_timing_only)), str(int(_process_hooks))],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", timeout=300 if _process_hooks else 120,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        return
    if (_process_hooks
            and not _server_only and _external_base_url is None):
        program = """
import logging.config
import sys
from pathlib import Path
import pytest
from app.runtime_logging import build_uvicorn_log_config
from tests.test_relay_load_smoke import test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle
logging.config.dictConfig(build_uvicorn_log_config(component='api'))
patch = pytest.MonkeyPatch()
try:
    test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
        Path(sys.argv[1]), patch, int(sys.argv[2]), _isolated=True,
        _synchronized_hooks=True, _diagnostics=False, _server_only=True)
finally:
    patch.undo()
"""
        ready_path = tmp_path / "server-ready.json"
        with (tmp_path / "server.stdout.log").open("w", encoding="utf-8") as stdout, \
                (tmp_path / "server.stderr.log").open("w", encoding="utf-8") as stderr:
            server_process = subprocess.Popen(
                [sys.executable, "-B", "-c", program, str(tmp_path), str(caller_count)],
                stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True, encoding="utf-8",
            )
            try:
                deadline = time.monotonic() + 35
                while not ready_path.exists():
                    assert server_process.poll() is None, "private server exited before readiness"
                    assert time.monotonic() < deadline, "private server did not become ready"
                    time.sleep(0.01)
                base_url = json.loads(ready_path.read_text(encoding="utf-8"))["base_url"]
                test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
                    tmp_path, monkeypatch, caller_count, _isolated=True,
                    _synchronized_hooks=_synchronized_hooks, _diagnostics=False, _process_hooks=True,
                    _external_base_url=base_url,
                )
            finally:
                try:
                    if server_process.poll() is None:
                        assert server_process.stdin is not None
                        server_process.stdin.write("stop\n")
                        server_process.stdin.flush()
                except BrokenPipeError:
                    pass  # The exit status below still rejects an abnormal server exit.
                finally:
                    try:
                        server_process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        server_process.kill()
                        server_process.wait(timeout=5)
                        raise
                assert server_process.returncode == 0, (tmp_path / "server.stderr.log").read_text(encoding="utf-8")
                server_evidence = json.loads((tmp_path / "server-http-evidence.json").read_text(encoding="utf-8"))
                assert server_evidence["server_settled"] and server_evidence["native_workers_settled"]
                evidence_path = tmp_path / "mixed-http-evidence.json"
                if evidence_path.exists():
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                    evidence["separate_server"] = server_evidence
                    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return
    from app import codex_bridge_pipe, codex_wake, dependencies
    from core.relay_activation import ActivationAttemptResult
    from scripts.live_funnel_smoke import ScratchServer
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from httpcore._async.connection_pool import AsyncPoolRequest
    from tests.test_agent_relay_hooks import _load

    workers, native_attempts, statements, sqlite_errors, hook_calls = [], [], [], [], []
    phases, health_samples, emissions, results, fanout_stacks = [], [], {}, [], {}
    process_entries, process_release = [], []
    operation_spans, stage_spans, writer_spans = [], [], []
    sql_spans, transaction_spans = [], []
    active_operations, active_stages, active_transactions = {}, {}, {}
    transport_events, server_spans, pool_spans = [], [], []
    fanout = False
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake
    original_router = dependencies.create_router

    def observe_router(service, **kwargs):
        def measure_stage(operation, label):
            def measured(*args, **kw):
                if not fanout:
                    return operation(*args, **kw)
                span = {"stage": label, "entered": time.perf_counter(),
                        "thread_id": threading.get_ident()}
                stage_spans.append(span)
                previous_stage = active_stages.get(span["thread_id"])
                active_stages[span["thread_id"]] = label
                try:
                    return operation(*args, **kw)
                except BaseException as error:
                    span["error_type"] = type(error).__name__
                    raise
                finally:
                    span["finished"] = time.perf_counter()
                    if previous_stage is None:
                        active_stages.pop(span["thread_id"], None)
                    else:
                        active_stages[span["thread_id"]] = previous_stage
            return measured

        for key in (("relay_turn_snapshot_callback", "relay_turn_callback",
                     "relay_turn_admission_callback") if _diagnostics else ()):
            if kwargs.get(key) is not None:
                kwargs[key] = measure_stage(kwargs[key], key)
        factory = kwargs.get("relay_activation_callback_factory")
        if _diagnostics and factory is not None:
            measured_factory = measure_stage(factory, "relay_activation_callback_factory")

            def prepare_projection(callback):
                prepared = measured_factory(callback)
                return measure_stage(prepared, "relay_activation_callback") if callable(prepared) else prepared

            # The factory uses default-callback identity to select its optimized path.
            kwargs["relay_activation_callback_factory"] = prepare_projection
        elif _diagnostics and kwargs.get("relay_activation_callback") is not None:
            kwargs["relay_activation_callback"] = measure_stage(
                kwargs["relay_activation_callback"], "relay_activation_callback")
        relay = kwargs.get("relay_service")
        if _diagnostics and relay is not None:
            monkeypatch.setattr(relay, "turn", measure_stage(relay.turn, "durable_turn"))
        if _timing_only and relay is not None:
            original_begin = relay._store._begin_relay_immediate

            @contextmanager
            def timed_writer():
                if not fanout:
                    with original_begin() as db:
                        yield db
                    return
                thread_id = threading.get_ident()
                span = {"operation": active_operations.get(thread_id), "thread_id": thread_id,
                        "entered": time.perf_counter()}
                writer_spans.append(span)
                try:
                    with original_begin() as db:
                        span["acquired"] = time.perf_counter()
                        yield db
                except BaseException as error:
                    span["error_type"] = type(error).__name__
                    raise
                finally:
                    span["finished"] = time.perf_counter()

            monkeypatch.setattr(relay._store, "_begin_relay_immediate", timed_writer)

        def measure_runner(runner, lane):
            async def measured(operation):
                if not fanout:
                    return await runner(operation)
                # Record only static route labels, never closure payload/scope values.
                code = getattr(operation, "__code__", None)
                names = code.co_freevars if code is not None else ()
                label = next((name for name in names if name.endswith("_callback")), "unlabelled")
                if "operation_name" in names:
                    label = operation.__closure__[names.index("operation_name")].cell_contents
                elif "relay_request" in names:
                    label = "exact_turn_composite"
                span = {"lane": lane, "operation": label, "submitted": time.perf_counter()}
                operation_spans.append(span)

                def observed_worker():
                    span["worker_entered"] = time.perf_counter()
                    span["thread_id"] = threading.get_ident()
                    active_operations[span["thread_id"]] = label
                    try:
                        return operation()
                    except BaseException as error:
                        span["error_type"] = type(error).__name__
                        raise
                    finally:
                        span["worker_finished"] = time.perf_counter()
                        active_operations.pop(span["thread_id"], None)

                try:
                    return await runner(observed_worker)
                finally:
                    span["await_finished"] = time.perf_counter()
            return measured

        for key, lane in (("relay_runner", "ordinary"), ("relay_wake_runner", "codex")):
            kwargs[key] = measure_runner(kwargs[key], lane)
        return original_router(service, **kwargs)

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
            words = statement.split()
            kind = words[0].upper()
            statements.append(kind)
            thread_id = threading.get_ident()
            frame, owner = sys._getframe(), "untracked"
            for _ in range(32):
                if frame is None:
                    break
                if frame.f_code.co_name.startswith("relay_"):
                    owner = frame.f_code.co_name
                    break
                frame = frame.f_back
            span = {"kind": kind, "entered": time.perf_counter(), "thread_id": thread_id,
                    "connection_id": id(_connection), "owner": owner,
                    "operation": active_operations.get(thread_id), "stage": active_stages.get(thread_id)}
            if kind == "BEGIN" and len(words) > 1:
                span["mode"] = words[1].upper()
            sql_spans.append(span)
            _context.pallium_sql_span = span

    def finish_sql(connection, context, error=None):
        span = getattr(context, "pallium_sql_span", None)
        if span is None:
            return
        span["finished"] = time.perf_counter()
        if error is not None:
            span["error_type"] = type(error).__name__
        connection_id = id(connection)
        if span["kind"] == "BEGIN" and span.get("mode") in {"IMMEDIATE", "DEFERRED"} and error is None:
            transaction = {"connection_id": connection_id, "thread_id": span["thread_id"],
                           "owner": span["owner"], "mode": span["mode"],
                           "entered": span["entered"], "began": span["finished"], "settlements": []}
            transaction_spans.append(transaction)
            active_transactions[connection_id] = transaction
        elif span["kind"] in {"COMMIT", "ROLLBACK"}:
            transaction = active_transactions.get(connection_id)
            if transaction is not None:
                transaction["settlements"].append(span)
                if error is None or span["kind"] == "ROLLBACK":
                    transaction["finished"] = span["finished"]
                    active_transactions.pop(connection_id, None)

    def after_sql(connection, _cursor, _statement, _parameters, context, _many):
        finish_sql(connection, context)

    def observe_sql_error(context):
        if fanout:
            error = context.original_exception
            finish_sql(context.connection, context.execution_context, error)
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
    if _diagnostics or _timing_only:
        monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(codex_bridge_pipe, "start_shadow_service", lambda *_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_inventory_service", lambda **_: None)
    monkeypatch.setattr(codex_bridge_pipe, "start_retained_service", InertRetainedTransport)
    monkeypatch.setattr(codex_bridge_pipe, "retained_wake_enabled", lambda: True)
    # Keep actual FastMCP initialization and its logging setup in this witness.
    app = None if _external_base_url is not None else create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    assert logging.getLogger().handlers
    assert all(type(handler).__name__ != "RichHandler" for handler in logging.getLogger().handlers)
    if app is not None:
        assert app.state.codex_wake_registry.initialize(old_owner_drained=True)

    async def observed_app(scope, receive, send):
        if not _diagnostics:
            return await app(scope, receive, send)
        reference = dict(scope.get("headers", ())).get(b"x-pallium-performance")
        if scope["type"] != "http" or reference is None:
            return await app(scope, receive, send)
        span = {"request": reference.decode("ascii"), "entered": time.perf_counter()}
        server_spans.append(span)

        async def observed_send(message):
            await send(message)
            if message["type"] == "http.response.start":
                span["response_started"] = time.perf_counter()
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                span["body_sent"] = time.perf_counter()

        return await app(scope, receive, observed_send)

    def transport_options(reference):
        if not _diagnostics:
            return {}
        async def trace_event(name, _info):
            # Discard connection objects, headers and all other trace contents.
            transport_events.append({"request": reference, "event": name, "at": time.perf_counter()})
        return {"headers": {"x-pallium-performance": reference}, "extensions": {"trace": trace_event}}

    async def observe_request(request):
        reference = request.headers.get("x-pallium-performance")
        if reference is not None:
            transport_events.append({"request": reference, "event": "httpx.request_ready", "at": time.perf_counter()})

    original_pool_wait = AsyncPoolRequest.wait_for_connection

    async def observe_pool_wait(pool_request, *args, **kwargs):
        reference = dict(pool_request.request.headers).get(b"x-pallium-performance")
        if reference is None:
            return await original_pool_wait(pool_request, *args, **kwargs)
        span = {"request": reference.decode("ascii"), "started": time.perf_counter()}
        pool_spans.append(span)
        try:
            return await original_pool_wait(pool_request, *args, **kwargs)
        except BaseException as error:
            span["error_type"] = type(error).__name__
            raise
        finally:
            span["finished"] = time.perf_counter()

    if _diagnostics:
        monkeypatch.setattr(AsyncPoolRequest, "wait_for_connection", observe_pool_wait)

    common = _load("concurrent_codex_common", "integrations/codex/hooks/common.py")
    assert common.hook_deadline() is None
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(common, "STATE_DIR", tmp_path / "hook-state")
    original_request = common.relay_request
    original_urlopen = common._urlopen

    def hook_reference(path, payload):
        identity = payload.get("session_ref") if path == "/relay/turn" else payload.get("delivery_id")
        return f"hook:{path}:{identity}" if identity is not None else None

    def observe_urlopen(request, *args, **kwargs):
        if isinstance(request, common.urllib.request.Request) and request.data is not None:
            path = common.urllib.parse.urlparse(request.full_url).path
            if path in ("/relay/turn", "/relay/deliveries/ack"):
                reference = hook_reference(path, json.loads(request.data))
                if reference is not None:
                    request.add_header("x-pallium-performance", reference)
        return original_urlopen(request, *args, **kwargs)

    def observe_hook_request(method, path, *args, **kwargs):
        started = time.perf_counter()
        span = {"method": method, "path": path, "started": started,
                "request": hook_reference(path, args[0]), "returned": False}
        hook_calls.append(span)
        try:
            response = original_request(method, path, *args, **kwargs)
            span["returned"] = response is not None
            return response
        except BaseException as error:
            span["error_type"] = type(error).__name__
            raise
        finally:
            span["finished"] = time.perf_counter()
            span["seconds"] = span["finished"] - started

    if _diagnostics:
        monkeypatch.setattr(common, "relay_request", observe_hook_request)
        monkeypatch.setattr(common, "_urlopen", observe_urlopen)
        event.listen(Engine, "before_cursor_execute", observe_sql)
        event.listen(Engine, "after_cursor_execute", after_sql)
        event.listen(Engine, "handle_error", observe_sql_error)
    scope = {"container_ref": "git:example.test/concurrent-http-東京"}

    async def exercise(base_url):
        nonlocal fanout
        start, ready, stop_health = asyncio.Event(), asyncio.Event(), asyncio.Event()
        ready_count = 0
        # Health must not queue behind the journeys' client-side connection pool.
        async with (
            httpx.AsyncClient(base_url=base_url, timeout=30, event_hooks={"request": [observe_request]} if _diagnostics else None) as client,
            httpx.AsyncClient(base_url=base_url, timeout=30, event_hooks={"request": [observe_request]} if _diagnostics else None) as health_client,
        ):
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
                reference = f"{index}:{phase}"
                options = transport_options(reference)
                kwargs["headers"] = {**kwargs.get("headers", {}), **options.get("headers", {})}
                kwargs["extensions"] = {**kwargs.get("extensions", {}), **options.get("extensions", {})}
                response = await client.request(method, path, **kwargs)
                phases.append({"index": index, "phase": phase,
                               "request": reference, "started": began, "finished": time.perf_counter(),
                               "seconds": time.perf_counter() - began,
                               "status": response.status_code})
                assert response.status_code == 200, (index, phase, response.status_code, response.text)
                return response.json()

            def hook_claim_emit_ack(index, message):
                return _hook_claim_emit_ack(common, index, message, scope, phases, emissions)

            async def prepare_message(index):
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
                return message

            async def readback(index, message):
                message_id = message["message_id"]
                retained = await request(index, "readback", "GET", f"/relay/messages/{message_id}", params=scope)
                delivery, = retained["deliveries"]
                assert delivery["delivery_id"] == message["deliveries"][0]["delivery_id"]
                assert delivery["state"] == "delivered"
                assert delivery["attempts"] == 1
                assert retained["payload"] == f"Concurrent message 東京 {index}"
                return message_id, delivery["delivery_id"]

            async def journey(index):
                nonlocal ready_count
                ready_count += 1
                if ready_count == caller_count:
                    ready.set()
                await start.wait()
                message = await prepare_message(index)
                await asyncio.to_thread(hook_claim_emit_ack, index, message)
                return await readback(index, message)

            async def synchronized_burst():
                if _process_hooks:
                    assert _external_base_url is not None and not (_diagnostics or _timing_only)
                    directory = tmp_path / "hook-processes"
                    directory.mkdir()
                    release_path = directory / "release.json"
                    children, streams = [], []
                    try:
                        ready_deadline = time.monotonic() + 60
                        for index in range(caller_count):
                            assert time.monotonic() < ready_deadline, "hook startup allowance exhausted"
                            stdout = (directory / f"{index}.stdout.log").open("w", encoding="utf-8")
                            stderr = (directory / f"{index}.stderr.log").open("w", encoding="utf-8")
                            streams.extend((stdout, stderr))
                            children.append(subprocess.Popen([
                                sys.executable, "-B", str(Path(__file__).with_name("relay_hook_journey.py")), str(index), str(directory),
                                str(Path(__file__).resolve().parents[1] / "integrations/codex/hooks/common.py"),
                                base_url, str(common.SESSIONS_DIR), str(common.STATE_DIR),
                            ], stdout=stdout, stderr=stderr))
                        while not all((directory / f"{i}.ready").exists() for i in range(caller_count)):
                            assert all(child.poll() is None for child in children), "hook child exited before readiness"
                            assert time.monotonic() < ready_deadline, "hook children did not become ready"
                            await asyncio.sleep(.01)
                        assert all(child.poll() is None for child in children)
                        messages = await asyncio.gather(
                            *(prepare_message(i) for i in range(caller_count)), return_exceptions=True)
                        assert not any(isinstance(message, BaseException) for message in messages), messages
                        for index, message in enumerate(messages):
                            assignment_path = directory / f"{index}.assignment.json"
                            pending_assignment = assignment_path.with_suffix('.tmp')
                            pending_assignment.write_text(
                                json.dumps({"scope": scope, "message": message}), encoding="utf-8")
                            pending_assignment.replace(assignment_path)
                        assignment_deadline = time.monotonic() + 10
                        while not all((directory / f"{i}.assignment-ready").exists() for i in range(caller_count)):
                            assert all(child.poll() is None for child in children), "hook child exited before assignment readiness"
                            assert time.monotonic() < assignment_deadline, "hook assignments did not become ready"
                            await asyncio.sleep(.01)
                        pending = release_path.with_suffix('.tmp')
                        released = time.perf_counter()
                        pending.write_text(json.dumps({"released": released}), encoding="utf-8")
                        pending.replace(release_path)
                        process_release.append(released)
                        result_deadline = time.monotonic() + 30
                        while not all((directory / f"{i}.result.json").exists() for i in range(caller_count)):
                            assert all(child.poll() in (None, 0) for child in children), "hook child exited abnormally"
                            assert time.monotonic() < result_deadline, "hook children did not report results"
                            await asyncio.sleep(.01)
                        completed = []
                        for index, message in enumerate(messages):
                            result = json.loads((directory / f"{index}.result.json").read_text(encoding="utf-8"))
                            process_entries.append(result["entered"])
                            phases.extend(result["phases"])
                            emissions.update({int(key): tuple(value) for key, value in result["emissions"].items()})
                            completed.append(await readback(index, message) if result["success"] else
                                AssertionError((index, result["error_type"], result["error"])))
                        return completed
                    finally:
                        teardown_deadline = time.monotonic() + 30
                        while any(child.poll() is None for child in children) and time.monotonic() < teardown_deadline:
                            await asyncio.sleep(.01)
                        unsettled = [child for child in children if child.poll() is None]
                        kill_errors = []
                        for child in unsettled:
                            try:
                                child.kill()
                            except OSError as error:
                                kill_errors.append((child.pid, type(error).__name__))
                        kill_deadline, wait_errors = time.monotonic() + 5, []
                        try:
                            for child in children:
                                try:
                                    child.wait(timeout=max(0, kill_deadline - time.monotonic()))
                                except subprocess.TimeoutExpired:
                                    wait_errors.append(child.pid)
                        finally:
                            for stream in streams:
                                stream.close()
                        assert not unsettled and not kill_errors and not wait_errors and all(
                            child.returncode == 0 for child in children), (
                                "hook children failed settlement", kill_errors, wait_errors)
                messages = await asyncio.gather(
                    *(prepare_message(i) for i in range(caller_count)), return_exceptions=True,
                )
                if any(isinstance(message, BaseException) for message in messages):
                    return messages
                barrier = threading.Barrier(caller_count + 1, timeout=10)
                pool = ThreadPoolExecutor(max_workers=caller_count)
                futures = []

                def gated_hook(index, message):
                    # All callers reach this gate before their real hook deadline starts.
                    barrier.wait()
                    hook_claim_emit_ack(index, message)

                async def finish(index, message, future):
                    await future
                    return await readback(index, message)

                try:
                    loop = asyncio.get_running_loop()
                    for i, message in enumerate(messages):
                        futures.append(loop.run_in_executor(pool, gated_hook, i, message))
                    await asyncio.to_thread(barrier.wait)
                    return await asyncio.gather(
                        *(finish(i, message, future) for i, (message, future) in enumerate(zip(messages, futures))),
                        return_exceptions=True,
                    )
                finally:
                    barrier.abort()
                    try:
                        await asyncio.gather(*futures, return_exceptions=True)
                    finally:
                        await asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=True)

            async def monitor_health():
                await start.wait()
                while not stop_health.is_set():
                    began = time.perf_counter()
                    try:
                        reference = f"health:{len(health_samples)}"
                        response = await health_client.get("/health", **transport_options(reference))
                        health_samples.append({"seconds": time.perf_counter() - began,
                                               "request": reference, "started": began, "finished": time.perf_counter(),
                                               "status": response.status_code})
                    except Exception as error:
                        health_samples.append({"seconds": time.perf_counter() - began,
                                               "error": type(error).__name__})
                    if _diagnostics and not fanout_stacks and not stop_health.is_set():
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

            tasks = [] if _synchronized_hooks else [asyncio.create_task(journey(i)) for i in range(caller_count)]
            health = asyncio.create_task(monitor_health())
            if not _synchronized_hooks:
                await ready.wait()
            fanout = True
            start.set()
            try:
                results.extend(await synchronized_burst() if _synchronized_hooks else
                               await asyncio.gather(*tasks, return_exceptions=True))
            finally:
                stop_health.set()
                await health
            assert health_samples and all(sample.get("status") == 200 for sample in health_samples)
            failures = [(i, type(result).__name__, str(result))
                        for i, result in enumerate(results) if isinstance(result, BaseException)]
            assert failures == [], failures
            assert len(set(results)) == len(emissions) == caller_count
            assert set(results) == set(emissions.values())
            if _diagnostics:
                assert operation_spans and all(
                    span["submitted"] <= span["worker_entered"] <= span["worker_finished"] <= span["await_finished"]
                    for span in operation_spans
                )
                assert {"send", "activation_projection"} <= {span["operation"] for span in operation_spans}
                assert server_spans and all(
                    span["entered"] <= span["response_started"] <= span["body_sent"]
                    for span in server_spans
                )
                assert {phase["request"] for phase in phases if "request" in phase} <= {
                    span["request"] for span in server_spans
                }
            listed = await request(-1, "sessions", "GET", "/relay/sessions", params=scope)
            assert len(listed) == caller_count + 1
            assert common.hook_deadline() is None

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server_settled = False
    try:
        owner = (ScratchServer(observed_app, "127.0.0.1", port) if app is not None
                 else nullcontext(SimpleNamespace(base_url=_external_base_url)))
        with owner as server:
            monkeypatch.setattr(common, "PALLIUM_BASE_URL", server.base_url)
            try:
                if _server_only:
                    ready_path = tmp_path / "server-ready.json"
                    ready_path.with_suffix(".tmp").write_text(
                        json.dumps({"base_url": server.base_url}), encoding="utf-8")
                    ready_path.with_suffix(".tmp").replace(ready_path)
                    assert sys.stdin.readline().strip() == "stop"
                else:
                    asyncio.run(exercise(server.base_url))
            finally:
                for worker in workers:
                    worker.join(5)
                assert all(not worker.is_alive() for worker in workers)
                if app is not None:
                    app.state.pallium_service._relay_trace_executor.submit(lambda: None).result(2)
        if _server_only:
            assert server._thread is not None and not server._thread.is_alive()
            assert app.state._wait_for_operations(0)
            server_settled = True
    finally:
        fanout = False
        if _diagnostics:
            event.remove(Engine, "before_cursor_execute", observe_sql)
            event.remove(Engine, "after_cursor_execute", after_sql)
            event.remove(Engine, "handle_error", observe_sql_error)
        stacks = {}
        for ident, frame in (sys._current_frames().items() if _diagnostics else ()):
            thread = next((thread for thread in threading.enumerate() if thread.ident == ident), None)
            if thread is None or not ("AnyIO" in thread.name or "scratch-server" == thread.name):
                continue
            stack = []
            while frame is not None and len(stack) < 10:
                stack.append((frame.f_code.co_name, frame.f_lineno))
                frame = frame.f_back
            stacks[thread.name + ":" + str(ident)] = stack
        evidence = {
            "callers": caller_count, "synchronized_hooks": _synchronized_hooks, "diagnostics": _diagnostics, "timing_only": _timing_only,
            "phases": phases, "health": health_samples,
            "operation_spans": operation_spans,
            "stage_spans": stage_spans,
            "writer_spans": writer_spans,
            "sql_spans": sql_spans, "transaction_spans": transaction_spans,
            "transport_events": transport_events, "server_spans": server_spans,
            "pool_spans": pool_spans,
            "sql_statements": dict(Counter(statements)), "sqlite_errors": sqlite_errors,
            "hook_calls": hook_calls, "native_attempts": len(native_attempts),
            "native_workers": len(workers), "emissions": len(emissions),
            "successful_journeys": sum(not isinstance(result, BaseException) for result in results),
            "root_log_handlers": [type(handler).__name__ for handler in logging.getLogger().handlers],
            "server_settled": server_settled,
            "native_workers_settled": all(not worker.is_alive() for worker in workers),
            "hook_process_release": process_release[0] if process_release else None,
            "hook_process_entry_spread_ms": 1000 * (max(process_entries) - min(process_entries)) if process_entries else None,
            "bounded_stacks_during_fanout": fanout_stacks,
            "bounded_stacks_after_drain": stacks,
        }
        (tmp_path / ("server-http-evidence.json" if _server_only else "mixed-http-evidence.json")).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print("mixed_http_summary=" + json.dumps({key: evidence[key] for key in (
            "callers", "sql_statements", "sqlite_errors", "native_attempts", "native_workers",
            "emissions", "successful_journeys", "root_log_handlers",
        )}))


@pytest.mark.slow
@pytest.mark.parametrize("caller_count", [24, 50])
def test_synchronized_http_hook_burst_keeps_exact_delivery_lifecycle(
    tmp_path, monkeypatch, caller_count,
) -> None:
    test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
        tmp_path, monkeypatch, caller_count, _synchronized_hooks=True,
    )


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


@pytest.mark.slow
def test_synchronized_hook_processes_keep_exact_delivery_lifecycle(tmp_path, monkeypatch):
    test_concurrent_http_hook_journeys_keep_exact_delivery_lifecycle(
        tmp_path, monkeypatch, 50, _synchronized_hooks=True, _process_hooks=True, _diagnostics=False,
    )
