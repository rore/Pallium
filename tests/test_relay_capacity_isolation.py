from __future__ import annotations

import asyncio
import threading

import anyio
import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


async def _start_operation_barrier(app):
    entered = threading.Event()

    def wait_for_operations() -> None:
        entered.set()
        app.state._wait_for_operations()

    barrier = asyncio.create_task(asyncio.to_thread(wait_for_operations))
    assert await asyncio.to_thread(entered.wait, 1)
    return barrier


async def _assert_barrier_waiting(barrier) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(barrier), 0.05)

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
        release.wait(2)
        return {"released": True}

    async def exercise() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            blocked = asyncio.create_task(client.get("/_test/block-memory-worker"))
            try:
                assert await asyncio.to_thread(started.wait, 0.5)
                health, status, queue, turn = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/health"), client.get("/status"),
                        client.get("/debug/queue/health"),
                        client.post("/relay/turn", json={
                            "runtime": "codex", "session_ref": "capacity-target",
                            "container_ref": "git:example.test/capacity",
                            "actor_ref": "capacity-user",
                        }),
                    ), timeout=1.0,
                )
                assert health.status_code in {200, 503} and turn.status_code == 200
                assert set(status.json()) == {
                    "pending_items", "oldest_pending_age_seconds",
                    "total_source_items", "total_memory_objects",
                    "active_memory_objects", "snapshot", "storage",
                    "vector_index_ready", "embedding_provider_ok", "ingestion",
                    "vector_expected", "vector_rebuild", "uptime_seconds",
                    "query", "metrics_summary", "historical_lookup_funnel",
                    "derived_memory",
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
            await asyncio.wait_for(shutdown_barrier, 0.5)

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
            await asyncio.wait_for(diagnostic_barrier, 0.5)
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
            await asyncio.wait_for(
                asyncio.to_thread(app.state._wait_for_operations), 1,
            )

            async def fail_dispatch(*_args, **_kwargs):
                raise RuntimeError("dispatch failed")

            monkeypatch.setattr("app.main.anyio.to_thread.run_sync", fail_dispatch)
            with pytest.raises(RuntimeError, match="dispatch failed"):
                await client.post("/relay/turn", json=payload("dispatch-failure"))
            await asyncio.wait_for(
                asyncio.to_thread(app.state._wait_for_operations), 1,
            )

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
            await asyncio.wait_for(queued_barrier, 1)
            assert started_count == 4

            def fail_worker(**_kwargs):
                raise RuntimeError("worker failed")

            monkeypatch.setattr(storage, "relay_turn", fail_worker)
            with pytest.raises(RuntimeError, match="worker failed"):
                await client.post("/relay/turn", json=payload("worker-failure"))
            await asyncio.wait_for(
                asyncio.to_thread(app.state._wait_for_operations), 1,
            )

            monkeypatch.setattr(storage, "relay_turn", original_relay_turn)
            response = await client.post(
                "/relay/turn", json=payload("success-after-failures"),
            )
            assert response.status_code == 200
            await asyncio.wait_for(
                asyncio.to_thread(app.state._wait_for_operations), 1,
            )

    try:
        asyncio.run(exercise())
    finally:
        app.state.pallium_service._storage.close()
