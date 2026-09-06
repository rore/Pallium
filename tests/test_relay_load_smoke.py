from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


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