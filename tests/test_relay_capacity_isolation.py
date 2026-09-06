from __future__ import annotations

import asyncio
import threading

import anyio
import httpx

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def test_relay_and_health_survive_saturated_memory_worker_capacity(tmp_path, monkeypatch) -> None:
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
                health, turn = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/health"),
                        client.post("/relay/turn", json={
                            "runtime": "codex",
                            "session_ref": "capacity-target",
                            "container_ref": "git:example.test/capacity",
                            "actor_ref": "capacity-user",
                        }),
                    ),
                    timeout=0.5,
                )
                assert health.status_code in {200, 503}
                assert turn.status_code == 200
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
            shutdown_barrier = asyncio.create_task(
                asyncio.to_thread(app.state._wait_for_relay_operations)
            )
            await asyncio.sleep(0)
            assert not shutdown_barrier.done()
            relay_release.set()
            assert await asyncio.to_thread(relay_finished.wait, 0.5)
            await asyncio.wait_for(shutdown_barrier, 0.5)

    try:
        asyncio.run(exercise())
    finally:
        app.state.pallium_service._storage.close()