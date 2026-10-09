from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

import anyio
import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


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
            for role in ("sender", "target"):
                response = await client.post("/relay/turn", json={
                    "runtime": runtime, "session_ref": role, **scope,
                })
                assert response.status_code == 200
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

def test_operation_tracking_covers_cancellation_and_failure_boundaries(tmp_path, monkeypatch) -> None:
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
