from __future__ import annotations

import asyncio
import threading
import contextlib
import logging
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.config import AppConfig, EmbeddingProviderConfig, LLMProviderConfig, SemanticPackageConfig, SnapshotConfig
from app.main import create_app
from core.models import MemoryObject, SourceItem
from core.vector_index_holder import VectorIndexHolder
from storage.vector_index import VectorIndex, VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


def _no_vector_config(sqlite_url: str = "sqlite:///:memory:") -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=sqlite_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


async def _wait_for_health(client, predicate, *, timeout: float = 5.0):
    """Wait for an externally visible startup state, not a worker-side signal."""
    async with asyncio.timeout(timeout):
        while True:
            response = await client.get("/health")
            body = response.json()
            if predicate(body):
                return response, body
            await asyncio.sleep(.01)


@contextlib.asynccontextmanager
async def _prebuilt_production_inner(monkeypatch, builder):
    """Keep native database preparation outside the lifecycle under test."""
    from app import main

    inner = await asyncio.to_thread(builder)
    loop_thread, delegate_threads = threading.get_ident(), []

    def delegate(*_args, **_kwargs):
        delegate_threads.append(threading.get_ident())
        return inner

    monkeypatch.setattr(main, "create_app", delegate)
    try:
        yield inner
        assert len(delegate_threads) == 1 and delegate_threads[0] != loop_thread
    finally:
        await asyncio.to_thread(inner.state._close_constructed)


@pytest.mark.parametrize("metrics_failure", [False, True])
def test_app_reuses_startup_storage_and_closes_it_once(monkeypatch, test_db_url, metrics_failure):
    from app import dependencies, main

    providers, closed = [], []
    original_builder = main.build_storage_provider
    original_metrics = main.MetricsStore

    def build(config):
        storage = original_builder(config)
        original_close = storage.close

        def close():
            closed.append(storage)
            original_close()

        storage.close = close
        providers.append(storage)
        return storage

    def metrics(factory):
        if metrics_failure:
            raise RuntimeError("planned optional metrics failure")
        return original_metrics(factory)

    monkeypatch.setattr(main, "build_storage_provider", build)
    monkeypatch.setattr(dependencies, "build_storage_provider", build)
    monkeypatch.setattr(main, "MetricsStore", metrics)
    built = main.create_app(_no_vector_config(test_db_url))
    try:
        assert len(providers) == 1
        assert built.state.pallium_service._storage is providers[0]
        if metrics_failure:
            assert built.state.metrics_store is None
        else:
            assert built.state.metrics_store._session_factory is providers[0]._session_factory
        with TestClient(built) as client:
            assert client.get("/health").status_code == 200
            assert client.post("/query", json={"text": "startup ownership"}).status_code == 200
            assert client.get("/relay/sessions", params={"container_ref": "startup-ownership"}).status_code == 200
    finally:
        built.state._close_constructed()
    assert closed == providers


def test_app_falls_back_when_early_storage_creation_fails(monkeypatch, test_db_url):
    from app import dependencies, main

    providers, closed = [], []
    original_builder = dependencies.build_storage_provider

    def build(config):
        storage = original_builder(config)
        original_close = storage.close
        storage.close = lambda: closed.append(storage) or original_close()
        providers.append(storage)
        return storage

    def fail_early(_config):
        raise RuntimeError("planned early provider failure")

    monkeypatch.setattr(main, "build_storage_provider", fail_early)
    monkeypatch.setattr(dependencies, "build_storage_provider", build)
    built = main.create_app(_no_vector_config(test_db_url))
    try:
        assert providers == [built.state.pallium_service._storage]
        assert built.state.metrics_store is None
        with TestClient(built) as client:
            assert client.get("/health").status_code == 200
            assert client.post("/query", json={"text": "fallback ownership"}).status_code == 200
            assert client.get("/relay/sessions", params={"container_ref": "fallback-ownership"}).status_code == 200
    finally:
        built.state._close_constructed()
    assert closed == providers


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_service_builder_preserves_storage_ownership(monkeypatch, test_db_url, borrowed, failure):
    from app import dependencies

    config = _no_vector_config(test_db_url)
    storage = dependencies.build_storage_provider(config)
    original_close = storage.close
    close_calls, factory_calls = [], []
    storage.close = lambda: close_calls.append(storage) or original_close()

    def build(_config):
        factory_calls.append(_config)
        return storage

    monkeypatch.setattr(dependencies, "build_storage_provider", build)
    if failure:
        def fail_build(*_args, **_kwargs):
            raise RuntimeError("planned service build failure")
        monkeypatch.setattr(dependencies, "_build_service_from_storage", fail_build)
    result = None
    try:
        kwargs = {"storage": storage} if borrowed else {}
        if failure:
            with pytest.raises(RuntimeError, match="planned service build failure"):
                dependencies.build_service(config, **kwargs)
        else:
            result = dependencies.build_service(config, **kwargs)
            assert result.storage is storage and result.service._storage is storage
        assert factory_calls == ([] if borrowed else [config])
        assert close_calls == ([storage] if failure and not borrowed else [])
    finally:
        if result is not None:
            result.service.close()
        if not close_calls:
            storage.close()
    assert close_calls == [storage]


@pytest.mark.asyncio
async def test_production_factory_keeps_http_responsive_during_build(monkeypatch, client) -> None:
    import httpx
    from app import main
    from fastapi import FastAPI

    build_started, release_build, build_finished = threading.Event(), threading.Event(), threading.Event()
    inner_apps, inner_scope_types = [], []
    worker_threads, production_closes = [], []
    event_loop_thread = threading.get_ident()
    built = client.app  # Real construction is fixture setup, not a two-second startup SLA.
    original_close = built.state.pallium_service.close

    def observe_close():
        production_closes.append(build_finished.is_set())
        original_close()

    monkeypatch.setattr(built.state.pallium_service, "close", observe_close)
    fastapi_call = FastAPI.__call__

    async def observe_inner_scope(self, scope, receive, send):
        if inner_apps and self is inner_apps[0]:
            inner_scope_types.append(scope["type"])
        await fastapi_call(self, scope, receive, send)

    def held_builder(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        build_started.set()
        if not release_build.wait(5):
            raise AssertionError("test did not release the held app build")
        try:
            inner_apps.append(built)
            return built
        finally:
            build_finished.set()

    monkeypatch.setattr(main, "create_app", held_builder)
    monkeypatch.setattr(FastAPI, "__call__", observe_inner_scope)
    factory = asyncio.create_task(asyncio.to_thread(main.app))
    application = None
    try:
        try:
            application = await asyncio.wait_for(asyncio.shield(factory), timeout=1)
        except asyncio.TimeoutError:
            started = await asyncio.to_thread(build_started.wait, 1)
            release_build.set()
            application = await asyncio.wait_for(factory, timeout=5)
            async with application.router.lifespan_context(application):
                pass
            pytest.fail(
                f"production app factory waited for synchronous construction (builder_started={started})"
            )

        async with application.router.lifespan_context(application):
            try:
                assert await asyncio.to_thread(build_started.wait, 2), "app lifespan did not start construction"
                assert len(worker_threads) == 1
                assert worker_threads[0] != event_loop_thread
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application), base_url="http://test",
                ) as client:
                    health = await client.get("/health")
                    status = await client.get("/status")
                    assert health.json()["initialized"] is False
                    assert health.json()["ready"] is False
                    assert status.json()["initialized"] is False
                    assert status.json()["ready"] is False
                    assert not build_finished.is_set(), "health/status waited for construction"

                    query = await client.post("/query", json={"text": "startup probe"})
                    mcp = await client.post("/mcp", json={
                        "jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "startup-probe", "version": "1"}},
                    })
                    assert query.status_code == 503
                    assert mcp.status_code == 503
                    assert not build_finished.is_set(), "operational request reached the partial app"

                    websocket_messages = []

                    async def websocket_receive():
                        return {"type": "websocket.connect"}

                    async def websocket_send(message):
                        websocket_messages.append(message)

                    await application(
                        {
                            "type": "websocket",
                            "asgi": {"version": "3.0", "spec_version": "2.4"},
                            "scheme": "ws",
                            "path": "/startup-probe",
                            "raw_path": b"/startup-probe",
                            "query_string": b"",
                            "headers": [],
                            "client": ("testclient", 12345),
                            "server": ("testserver", 80),
                            "subprotocols": [],
                        },
                        websocket_receive,
                        websocket_send,
                    )
                    assert websocket_messages == [{"type": "websocket.close", "code": 1013}]
                    assert inner_scope_types == [], "uninitialized request entered the partial app"

                release_build.set()
                assert await asyncio.to_thread(build_finished.wait, 2), "app construction did not settle"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application), base_url="http://test",
                ) as client:
                    health, health_body = await _wait_for_health(
                        client, lambda body: body.get("initialized") is True,
                    )
                    status = await client.get("/status")
                    assert health.status_code == 200
                    assert health_body["ready"] is True
                    assert status.json()["initialized"] is True
                    assert status.json()["ready"] is True
                    assert (await client.post("/query", json={"text": "startup probe"})).status_code == 200
                    assert "http" in inner_scope_types, "ready request was not delegated to the built app"
            finally:
                release_build.set()
    finally:
        release_build.set()
        if application is None:
            application = await asyncio.wait_for(factory, timeout=5)
    assert production_closes == [True], "production lifespan must close before fixture cleanup"


@pytest.mark.asyncio
async def test_production_factory_keeps_mcp_lifespan_on_one_task(monkeypatch, test_db_url: str) -> None:
    import httpx
    from app import main

    manager = pytest.importorskip("mcp.server.streamable_http_manager")
    create_app = main.create_app
    lifecycle_tasks = []

    @contextlib.asynccontextmanager
    async def run(_manager):
        lifecycle_tasks.append(("enter", asyncio.current_task()))
        try:
            yield
        finally:
            lifecycle_tasks.append(("exit", asyncio.current_task()))

    monkeypatch.setattr(manager.StreamableHTTPSessionManager, "run", run)
    async with _prebuilt_production_inner(monkeypatch, lambda: create_app(_no_vector_config(test_db_url))):
        application = main.app()
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                await _wait_for_health(client, lambda body: body.get("initialized") is True)

        assert [phase for phase, _task in lifecycle_tasks] == ["enter", "exit"]
        assert lifecycle_tasks[0][1] is lifecycle_tasks[1][1]


@pytest.mark.asyncio
async def test_production_factory_rejects_second_active_lifespan_without_second_build(
    monkeypatch, client,
) -> None:
    from app import main

    build_started, release_build = threading.Event(), threading.Event()
    build_calls = []
    built = client.app

    def held_builder(*_args, **_kwargs):
        build_calls.append(True)
        build_started.set()
        if not release_build.wait(5):
            raise AssertionError("test did not release the held app build")
        return built

    monkeypatch.setattr(main, "create_app", held_builder)
    application = main.app()
    request_shutdown = asyncio.Event()
    lifespan_entered = asyncio.Event()

    async def own_lifespan():
        async with application.router.lifespan_context(application):
            lifespan_entered.set()
            await request_shutdown.wait()

    owner = asyncio.create_task(own_lifespan())
    try:
        await asyncio.wait_for(lifespan_entered.wait(), timeout=5)
        assert await asyncio.to_thread(build_started.wait, 2), "app lifespan did not start construction"
        second_lifespan = application.router.lifespan_context(application)
        with pytest.raises(RuntimeError, match="already entered"):
            await second_lifespan.__aenter__()
        assert build_calls == [True]
    finally:
        release_build.set()
        request_shutdown.set()
        await asyncio.wait_for(owner, timeout=5)
    assert build_calls == [True]


@pytest.mark.asyncio
async def test_production_factory_degraded_provider_keeps_query_operational(
    monkeypatch, test_db_url: str,
) -> None:
    import httpx
    from app import main

    create_app = main.create_app
    async with _prebuilt_production_inner(
        monkeypatch, lambda: create_app(_failed_embedding_config(test_db_url)),
    ):
        application = main.app()
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                health, body = await _wait_for_health(
                    client, lambda state: state.get("initialized") is True,
                )
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "startup probe"})

        assert health.status_code == 200
        assert body["status"] == "degraded"
        assert body["ready"] is False
        assert status.json()["initialized"] is True
        assert status.json()["ready"] is False
        assert query.status_code == 200


@pytest.mark.asyncio
async def test_production_factory_constructor_failure_closes_acquired_storage(
    monkeypatch, test_db_url: str,
) -> None:
    import httpx
    from app import dependencies, main

    config = _no_vector_config(test_db_url)
    create_app = main.create_app
    storage_builder = main.build_storage_provider
    acquired_storage, close_calls = [], []
    storage_closed = threading.Event()
    storage = await asyncio.to_thread(storage_builder, config)
    fallback_close = storage.close

    def tracked_storage_builder(_config):
        original_close = fallback_close

        def close():
            close_calls.append(storage)
            try:
                original_close()
            finally:
                storage_closed.set()

        storage.close = close
        acquired_storage.append(storage)
        return storage

    def fail_service_build(*_args, **_kwargs):
        raise RuntimeError("planned constructor failure")

    try:
        monkeypatch.setattr(main, "build_storage_provider", tracked_storage_builder)
        monkeypatch.setattr(dependencies, "_build_service_from_storage", fail_service_build)
        monkeypatch.setattr(main, "create_app", lambda *_args, **_kwargs: create_app(config))
        application = main.app()
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                assert await asyncio.to_thread(storage_closed.wait, 5), "constructor failure leaked its acquired SQLite storage"
                health, health_body = await _wait_for_health(
                    client, lambda body: bool(body.get("initialization_error")),
                )
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "after constructor failure"})

        assert len(acquired_storage) == 1
        assert close_calls == acquired_storage
        assert health.status_code == 503
        assert health_body["initialized"] is False
        assert health_body["ready"] is False
        assert status.json()["initialized"] is False
        assert status.json()["ready"] is False
        assert query.status_code == 503

    finally:
        if not storage_closed.is_set():
            await asyncio.to_thread(fallback_close)

@pytest.mark.asyncio
async def test_production_factory_runtime_setup_failure_closes_app_resources(
    monkeypatch, test_db_url: str,
) -> None:
    import httpx
    from app import main

    config = _no_vector_config(test_db_url)
    create_app = main.create_app
    storage_builder = main.build_storage_provider
    acquired_storage, storage_close_calls, service_close_calls = [], [], []
    resources_closed = threading.Event()
    inner_apps = []

    def tracked_storage_builder(storage_config):
        storage = storage_builder(storage_config)
        original_close = storage.close

        def close():
            storage_close_calls.append(storage)
            try:
                original_close()
            finally:
                if len(storage_close_calls) == 1:
                    resources_closed.set()

        storage.close = close
        acquired_storage.append(storage)
        return storage

    def capture_created_app(*_args, **_kwargs):
        built = create_app(config)
        service = built.state.pallium_service
        original_close = service.close

        def close_service():
            service_close_calls.append(service)
            original_close()

        service.close = close_service
        inner_apps.append(built)
        return built

    def fail_runtime_setup(*_args, **_kwargs):
        raise RuntimeError("planned runtime setup failure")

    monkeypatch.setattr(main, "build_storage_provider", tracked_storage_builder)
    monkeypatch.setattr("app.dependencies.build_storage_provider", tracked_storage_builder)
    # Exclude database construction from the runtime-cleanup watchdog.
    inner = await asyncio.to_thread(capture_created_app)
    loop_thread = threading.get_ident()
    builder_threads = []

    def delegate_inner(*_args, **_kwargs):
        builder_threads.append(threading.get_ident())
        return inner

    monkeypatch.setattr(main, "create_app", delegate_inner)
    monkeypatch.setattr(main, "start_claude_wake_reconciler", fail_runtime_setup)
    application = main.app()
    try:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                assert await asyncio.to_thread(resources_closed.wait, 5), "runtime setup failure did not close all acquired SQLite storage"
                health, health_body = await _wait_for_health(
                    client, lambda body: bool(body.get("initialization_error")),
                )
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "after runtime failure"})

        assert len(builder_threads) == 1
        assert builder_threads[0] != loop_thread
        assert len(inner_apps) == 1
        assert len(acquired_storage) == 1
        assert sorted(map(id, storage_close_calls)) == sorted(map(id, acquired_storage))
        assert len(service_close_calls) == 1
        assert health.status_code == 503
        assert health_body["initialized"] is False
        assert health_body["ready"] is False
        assert status.json()["initialized"] is False
        assert status.json()["ready"] is False
        assert query.status_code == 503

    finally:
        await asyncio.to_thread(inner.state._close_constructed)


@pytest.mark.asyncio
async def test_production_factory_serves_lexical_and_relay_before_vector_ready(
    monkeypatch, tmp_path: Path, test_db_url: str,
) -> None:
    import httpx
    from app import main

    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(
            enabled=True,
            index_path=str(tmp_path / "startup.index"),
            embedding_provider="local",
        ),
        embedding_providers={
            "local": EmbeddingProviderConfig(name="local", kind="fastembed", model="startup-test"),
        },
    )
    provider = MagicMock()
    provider.model_name.return_value = "startup-test"
    provider.dimensions.return_value = 4
    index = MagicMock(spec=VectorIndex)
    index.model_name = "startup-test"
    index.entry_count.return_value = 0
    monkeypatch.setattr("app.dependencies.build_embedding_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("app.dependencies._load_or_create_vector_index", lambda *_args, **_kwargs: index)

    reconcile_started, release_reconcile, reconcile_finished = threading.Event(), threading.Event(), threading.Event()
    reconcile_done_events = []

    def gated_reconcile(_service, *, reconcile_done=None, **_kwargs):
        stop = threading.Event()
        reconcile_done_events.append(reconcile_done)

        def run():
            reconcile_started.set()
            try:
                release_reconcile.wait(5)
                if reconcile_done is not None and not stop.is_set():
                    reconcile_done.set()
            finally:
                reconcile_finished.set()

        threading.Thread(target=run, daemon=True, name="test-vector-reconcile").start()
        return stop

    create_app = main.create_app
    monkeypatch.setattr(main, "_start_reconcile_thread", gated_reconcile)
    monkeypatch.setattr(main, "create_app", lambda *_args, **_kwargs: create_app(config))
    application = main.app()
    try:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                _health, health_body = await _wait_for_health(
                    client, lambda body: body.get("initialized") is True,
                )
                assert await asyncio.to_thread(reconcile_started.wait, 2), "vector reconciliation did not start"
                assert len(reconcile_done_events) == 1 and not reconcile_done_events[0].is_set()
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "startup probe"})
                relay = await client.get("/relay/sessions", params={"container_ref": "startup-probe"})
                assert health_body["ready"] is False
                assert status.json()["initialized"] is True
                assert status.json()["ready"] is False
                assert query.status_code == 200
                assert relay.status_code == 200

                release_reconcile.set()
                assert await asyncio.to_thread(reconcile_finished.wait, 2), "vector reconciliation did not settle"
                _health, health_body = await _wait_for_health(
                    client, lambda body: body.get("ready") is True,
                )
                status = await client.get("/status")
                assert health_body["initialized"] is True
                assert status.json()["initialized"] is True
                assert status.json()["ready"] is True
    finally:
        release_reconcile.set()
        if reconcile_started.is_set():
            assert await asyncio.to_thread(reconcile_finished.wait, 2), "test reconcile worker did not settle"


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_failure", [None, "rebuild", "claude_reconciler", "held_claude"])
async def test_production_factory_drains_real_rebuild_inventory_before_storage_close(
    monkeypatch, tmp_path: Path, stop_failure: str | None,
) -> None:
    import httpx
    from app import main
    from core.rebuild_coordinator import RebuildCoordinator
    from sqlalchemy import text

    index_path = tmp_path / "live.index"
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'startup.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(
            enabled=True,
            index_path=str(index_path),
            embedding_provider="local",
        ),
        embedding_providers={
            "local": EmbeddingProviderConfig(name="local", kind="fastembed", model="startup-test"),
        },
    )
    provider = MagicMock()
    provider.model_name.return_value = "startup-test"
    provider.dimensions.return_value = 4
    provider.recommended_min_similarity.return_value = 0.1
    index = MagicMock(spec=VectorIndex)
    index.model_name = "prior-test-model"
    index.entry_count.return_value = 1
    index.search.return_value = []
    monkeypatch.setattr("app.dependencies.build_embedding_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("app.dependencies._load_or_create_vector_index", lambda *_args, **_kwargs: index)

    inventory_started, release_inventory, inventory_finished = threading.Event(), threading.Event(), threading.Event()
    worker_threads, pre_checkpoint = [], []
    storage_close_after_worker = []
    drain_started = threading.Event()
    real_drain = main.drain_claude_relay_wakes
    real_inventory = RebuildCoordinator._inventory_raw_source_vectors
    create_shadow = threading.Event()

    def held_inventory(coordinator):
        worker_threads.append(threading.current_thread())
        pre_checkpoint.append(
            coordinator._checkpoint is None and not coordinator._state_path.exists()
        )
        inventory_started.set()
        if not release_inventory.wait(10):
            raise AssertionError("test did not release rebuild inventory")
        try:
            return real_inventory(coordinator)
        finally:
            inventory_finished.set()

    def no_native_shadow_index(_coordinator):
        create_shadow.set()

    monkeypatch.setattr(RebuildCoordinator, "_inventory_raw_source_vectors", held_inventory)
    monkeypatch.setattr(RebuildCoordinator, "_create_shadow_index", no_native_shadow_index)

    if stop_failure == "rebuild":
        def fail_rebuild_stop(coordinator, *_args, **_kwargs):
            coordinator._stop_event.set()
            raise RuntimeError("planned rebuild stop failure")

        monkeypatch.setattr(RebuildCoordinator, "stop", fail_rebuild_stop)
    elif stop_failure == "claude_reconciler":
        monkeypatch.setattr(RebuildCoordinator, "stop", lambda coordinator, **_kwargs: coordinator._stop_event.set())

    def observe_drain(registry):
        drain_started.set()
        return real_drain(registry)

    monkeypatch.setattr(main, "drain_claude_relay_wakes", observe_drain)

    real_start_wake_reconciler = main.start_claude_wake_reconciler
    wake_reconcilers = []
    claude_stop_started, release_claude_stop = threading.Event(), threading.Event()

    def start_wake_reconciler(
        registry, relay_service, *, claim_recovery=None, trace_callback=None, **kwargs,
    ):
        reconciler = real_start_wake_reconciler(
            registry, relay_service, claim_recovery=None, trace_callback=trace_callback, **kwargs,
        )
        wake_reconcilers.append(reconciler)
        if stop_failure == "held_claude":
            original_stop = reconciler.stop

            def held_stop():
                claude_stop_started.set()
                if not release_claude_stop.wait(5):
                    raise AssertionError("test did not release Claude stop")
                original_stop()

            reconciler.stop = held_stop
        if stop_failure == "claude_reconciler":
            original_stop = reconciler.stop

            def stop_then_raise():
                original_stop()
                raise RuntimeError("planned Claude reconciler stop failure")

            reconciler.stop = stop_then_raise
        return reconciler

    monkeypatch.setattr(main, "start_claude_wake_reconciler", start_wake_reconciler)

    def reconciled_without_thread(_service, *, reconcile_done=None, **_kwargs):
        if reconcile_done is not None:
            reconcile_done.set()
        return threading.Event()

    monkeypatch.setattr(main, "_start_reconcile_thread", reconciled_without_thread)
    create_app = main.create_app
    inner_apps = []

    def build_inner(*_args, **_kwargs):
        built = create_app(config)
        storage = built.state.pallium_service._storage
        original_close = storage.close

        def close_storage():
            storage_close_after_worker.append(
                inventory_finished.is_set() and worker_threads and not worker_threads[0].is_alive()
                and wake_reconcilers and not wake_reconcilers[0]._thread.is_alive()
                and drain_started.is_set()
            )
            original_close()

        storage.close = close_storage
        inner_apps.append(built)
        return built

    def sqlite_select_one(storage):
        with storage._session_factory() as session:
            return session.execute(text("SELECT 1")).scalar_one()

    # Exclude database construction from the inventory-arrival watchdog.
    inner = await asyncio.to_thread(build_inner)
    loop_thread = threading.get_ident()
    builder_threads = []

    def delegate_inner(*_args, **_kwargs):
        builder_threads.append(threading.get_ident())
        return inner

    monkeypatch.setattr(main, "create_app", delegate_inner)
    application = main.app()
    owner = None
    request_shutdown = asyncio.Event()
    lifespan_entered = asyncio.Event()

    async def own_lifespan():
        async with application.router.lifespan_context(application):
            lifespan_entered.set()
            await request_shutdown.wait()

    try:
        owner = asyncio.create_task(own_lifespan())
        await asyncio.wait_for(lifespan_entered.wait(), timeout=5)
        assert await asyncio.to_thread(inventory_started.wait, 3), "real rebuild inventory did not start"
        assert builder_threads and builder_threads[0] != loop_thread
        assert len(builder_threads) == 1
        assert pre_checkpoint == [True]
        assert worker_threads[0].name == "vector-rebuild"
        assert worker_threads[0].is_alive()
        assert not create_shadow.is_set()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test",
        ) as client:
            _health, health_body = await _wait_for_health(
                client, lambda body: body.get("initialized") is True,
            )
            status = await client.get("/status")
            query = await client.post("/query", json={"text": "startup probe"})
            relay = await client.get("/relay/sessions", params={"container_ref": "startup-probe"})
            assert health_body["ready"] is False
            assert status.json()["initialized"] is True
            assert status.json()["ready"] is False
            assert query.status_code == 200
            assert relay.status_code == 200

            request_shutdown.set()
            health, health_body = await _wait_for_health(
                client, lambda body: body.get("initialized") is False,
            )
            loop_pulse = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_pulse.set)
            await asyncio.wait_for(loop_pulse.wait(), timeout=1)
            assert not owner.done(), "shutdown abandoned the active rebuild inventory"
            assert worker_threads[0].is_alive()
            assert storage_close_after_worker == []
            assert not drain_started.is_set(), "cleanup advanced past the held rebuild before it settled"
            assert await asyncio.to_thread(
                sqlite_select_one, inner_apps[0].state.pallium_service._storage
            ) == 1

            status = await client.get("/status")
            query = await client.post("/query", json={"text": "during shutdown"})
            assert health_body["ready"] is False
            assert status.json()["initialized"] is False
            assert status.json()["ready"] is False
            assert query.status_code == 503

            rebuild = inner_apps[0].state._rebuild_coordinator
            if stop_failure == "held_claude":
                assert await asyncio.to_thread(claude_stop_started.wait, 2)
                assert rebuild._stop_event.is_set(), "rebuild cancellation waited behind another worker"
                release_claude_stop.set()
            else:
                assert await asyncio.to_thread(rebuild._stop_event.wait, 2)
            release_inventory.set()
            await asyncio.wait_for(owner, timeout=5)
            assert await asyncio.to_thread(inventory_finished.wait, 1)
            assert not create_shadow.is_set()
            assert not worker_threads[0].is_alive()
            assert len(wake_reconcilers) == 1
            assert not wake_reconcilers[0]._thread.is_alive()
            assert drain_started.is_set()
            assert storage_close_after_worker == [True]

            health = await client.get("/health")
            status = await client.get("/status")
            assert health.json()["initialized"] is False
            assert health.json()["ready"] is False
            assert status.json()["initialized"] is False
            assert status.json()["ready"] is False
    finally:
        release_claude_stop.set()
        release_inventory.set()
        request_shutdown.set()
        if owner is not None:
            await asyncio.wait_for(owner, timeout=5)
        if (not any(worker.is_alive() for worker in worker_threads)
                and not any(reconciler._thread.is_alive() for reconciler in wake_reconcilers)):
            await asyncio.to_thread(inner.state._close_constructed)


@pytest.mark.asyncio
async def test_production_factory_closes_resources_after_rebuild_thread_start_failure(
    monkeypatch, tmp_path: Path,
) -> None:
    import httpx
    import app.dependencies as dependencies
    from app import main
    from storage.sqlite import SQLiteStorageProvider

    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'start-failure.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(
            enabled=True, index_path=str(tmp_path / "live.index"), embedding_provider="local",
        ),
        embedding_providers={
            "local": EmbeddingProviderConfig(name="local", kind="fastembed", model="startup-test"),
        },
    )
    provider = MagicMock()
    provider.model_name.return_value = "startup-test"
    provider.dimensions.return_value = 4
    provider.recommended_min_similarity.return_value = 0.1
    index = MagicMock(spec=VectorIndex)
    index.model_name = "prior-test-model"
    index.entry_count.return_value = 1
    index.search.return_value = []
    monkeypatch.setattr("app.dependencies.build_embedding_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("app.dependencies._load_or_create_vector_index", lambda *_args, **_kwargs: index)

    storage_close_calls: dict[int, int] = {}
    storages: list[SQLiteStorageProvider] = []

    def instrument_storage_builder(builder):
        def build_storage(*args, **kwargs):
            storage = builder(*args, **kwargs)
            if isinstance(storage, SQLiteStorageProvider):
                storages.append(storage)
                original_close = storage.close

                def counted_close():
                    storage_close_calls[id(storage)] = storage_close_calls.get(id(storage), 0) + 1
                    original_close()

                storage.close = counted_close
            return storage

        return build_storage

    monkeypatch.setattr(main, "build_storage_provider", instrument_storage_builder(main.build_storage_provider))
    monkeypatch.setattr(
        dependencies, "build_storage_provider",
        instrument_storage_builder(dependencies.build_storage_provider),
    )
    service_close_calls = []
    built_apps = []
    create_app = main.create_app

    def build_inner(*_args, **_kwargs):
        built = create_app(config)
        service = built.state.pallium_service
        original_close = service.close

        def counted_service_close():
            service_close_calls.append(service)
            original_close()

        service.close = counted_service_close
        built_apps.append(built)
        return built

    async with _prebuilt_production_inner(monkeypatch, build_inner):
        thread_starts = []
        real_thread_start = threading.Thread.start

        def fail_rebuild_start(thread):
            if thread.name == "vector-rebuild":
                thread_starts.append(thread)
                raise RuntimeError("planned vector rebuild thread start failure")
            return real_thread_start(thread)

        monkeypatch.setattr(threading.Thread, "start", fail_rebuild_start)
        application = main.app()
        owner = None
        request_shutdown = asyncio.Event()
        lifespan_entered = asyncio.Event()

        async def own_lifespan():
            async with application.router.lifespan_context(application):
                lifespan_entered.set()
                await request_shutdown.wait()

        try:
            owner = asyncio.create_task(own_lifespan())
            await asyncio.wait_for(lifespan_entered.wait(), timeout=5)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                health, body = await _wait_for_health(
                    client, lambda value: value.get("initialization_error") == "service_initialization_failed",
                )
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "failed startup probe"})
                assert health.status_code == 503
                assert body["status"] == "failed"
                assert body["initialized"] is False and body["ready"] is False
                assert status.status_code == 503
                assert status.json()["initialized"] is False and status.json()["ready"] is False
                assert query.status_code == 503

                assert len(thread_starts) == 1
                assert thread_starts[0].name == "vector-rebuild"
                assert thread_starts[0].ident is None and not thread_starts[0].is_alive()
                assert len(built_apps) == 1
                assert len(service_close_calls) == 1
                assert service_close_calls == [built_apps[0].state.pallium_service]
                assert len(storages) == 1
                assert set(storage_close_calls) == {id(storage) for storage in storages}
                assert all(storage_close_calls[id(storage)] == 1 for storage in storages)

            request_shutdown.set()
            await asyncio.wait_for(asyncio.shield(owner), timeout=5)
        finally:
            request_shutdown.set()
            if owner is not None:
                await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.asyncio
async def test_production_factory_shutdown_settles_held_build_before_close(
    monkeypatch, test_db_url: str,
) -> None:
    import httpx
    from app import main
    from fastapi import FastAPI

    build_started, release_build, build_finished = threading.Event(), threading.Event(), threading.Event()
    create_app = main.create_app
    built_apps, close_after_build = [], []
    inner_scope_types = []
    fastapi_call = FastAPI.__call__

    async def observe_inner_scope(self, scope, receive, send):
        if built_apps and self is built_apps[0]:
            inner_scope_types.append(scope["type"])
        await fastapi_call(self, scope, receive, send)

    def held_builder(*_args, **_kwargs):
        try:
            build_started.set()
            if not release_build.wait(5):
                raise AssertionError("test did not release the held app build")
            built = delegate(*_args, **_kwargs)
            original_close = built.state.pallium_service.close

            def counted_close():
                close_after_build.append(build_finished.is_set())
                original_close()

            built.state.pallium_service.close = counted_close
            built_apps.append(built)
            return built
        finally:
            build_finished.set()

    async with _prebuilt_production_inner(monkeypatch, lambda: create_app(_no_vector_config(test_db_url))):
        delegate = main.create_app
        monkeypatch.setattr(main, "create_app", held_builder)
        monkeypatch.setattr(FastAPI, "__call__", observe_inner_scope)
        application = main.app()
        owner = None
        request_shutdown = asyncio.Event()
        lifespan_entered = asyncio.Event()

        async def own_lifespan():
            async with application.router.lifespan_context(application):
                lifespan_entered.set()
                await request_shutdown.wait()

        try:
            owner = asyncio.create_task(own_lifespan())
            await asyncio.wait_for(lifespan_entered.wait(), timeout=5)
            assert await asyncio.to_thread(build_started.wait, 2), "app lifespan did not start construction"
            request_shutdown.set()
            loop_pulse = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_pulse.set)
            await asyncio.wait_for(loop_pulse.wait(), timeout=1)
            assert not owner.done(), "shutdown abandoned or bypassed the held build"
            assert not build_finished.is_set()
            assert close_after_build == [], "shutdown closed resources while construction was still held"

            release_build.set()
            await asyncio.wait_for(asyncio.shield(owner), timeout=5)
            assert build_finished.is_set()
            assert len(built_apps) == 1
            assert close_after_build == [True]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://test",
            ) as client:
                health = await client.get("/health")
                status = await client.get("/status")
                query = await client.post("/query", json={"text": "after shutdown"})
            assert health.json()["initialized"] is False
            assert health.json()["ready"] is False
            assert status.json()["initialized"] is False
            assert status.json()["ready"] is False
            assert query.status_code == 503
            assert inner_scope_types == [], "post-shutdown request was delegated to the settled app"
        finally:
            release_build.set()
            request_shutdown.set()
            if owner is not None:
                await asyncio.gather(owner, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("held_stage", ["transport", "completed_trace"])
async def test_production_factory_drains_claude_wake_thread_before_storage_close(
    monkeypatch, test_db_url: str, held_stage: str,
) -> None:
    import httpx
    import app.main as main
    from app.claude_wake_binding import write_json_atomic
    from core.service import PalliumService
    from sqlalchemy import text

    gate_started, release_gate, trace_finished = threading.Event(), threading.Event(), threading.Event()
    producers_settled, drain_started, service_close_started = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    scheduled_threads = []
    direct_producer_threads = []
    storage_close_calls, service_close_calls = [], []
    close_order_witnesses = []
    created_apps = []
    create_app = main.create_app
    original_enqueue = PalliumService.enqueue_relay_trace_event

    def build_inner(*_args, **_kwargs):
        built = create_app(_no_vector_config(test_db_url))
        service = built.state.pallium_service
        storage = service._storage
        original_storage_close = storage.close
        original_service_close = service.close

        def close_storage():
            storage_close_calls.append(storage)
            close_order_witnesses.append((
                "storage", tuple(worker.is_alive() for worker in scheduled_threads),
                trace_finished.is_set(),
            ))
            original_storage_close()

        def close_service():
            service_close_started.set()
            service_close_calls.append(service)
            close_order_witnesses.append((
                "service", tuple(worker.is_alive() for worker in scheduled_threads),
                trace_finished.is_set(),
            ))
            original_service_close()

        storage.close = close_storage
        service.close = close_service
        created_apps.append(built)
        return built

    def gated_enqueue(service, writer, event):
        if event.get("stage") == "completed":
            try:
                if held_stage == "completed_trace":
                    gate_started.set()
                    if not release_gate.wait(8):
                        raise AssertionError("test did not release the completed trace callback")
                return original_enqueue(service, writer, event)
            finally:
                trace_finished.set()
        return original_enqueue(service, writer, event)

    def fake_transport(*_args):
        scheduled_threads.append(threading.current_thread())
        if held_stage == "transport":
            gate_started.set()
            if not release_gate.wait(8):
                raise AssertionError("test did not release the held wake transport")
        return "accepted"

    import app.claude_wake as claude_wake
    original_start_reconciler = main.start_claude_wake_reconciler
    actual_drain = getattr(main, "drain_claude_relay_wakes", None)

    def start_reconciler(registry, relay_service, *, trace_callback=None, **_kwargs):
        reconciler = original_start_reconciler(
            registry, relay_service, claim_recovery=None, trace_callback=trace_callback,
        )
        original_stop = reconciler.stop

        def stop_and_settle_producers():
            original_stop()
            state = created_apps[0].state
            for name in (
                "_claude_wake_reconciler", "_codex_retained_service",
                "_codex_inventory_service", "_codex_shadow_service",
            ):
                producer = getattr(state, name, None)
                if producer is None:
                    continue
                thread = getattr(producer, "thread", None) or getattr(producer, "_thread", None)
                if thread is None:
                    continue
                assert thread not in scheduled_threads
                if thread not in direct_producer_threads:
                    direct_producer_threads.append(thread)
                if thread.ident is not None:
                    thread.join()
            assert state._wait_for_operations(timeout=0)
            producers_settled.set()

        reconciler.stop = stop_and_settle_producers
        return reconciler

    def observe_actual_drain(registry):
        drain_started.set()
        return actual_drain(registry)

    def unexpected_missing_drain(_registry):
        raise AssertionError("old source unexpectedly called a drain helper it does not own")

    async with _prebuilt_production_inner(monkeypatch, build_inner):
        monkeypatch.setattr(main, "start_claude_wake_reconciler", start_reconciler)
        monkeypatch.setattr(claude_wake, "recover_claude_relay_wakes", lambda *_args, **_kwargs: None)
        if actual_drain is None:
            monkeypatch.setattr(main, "drain_claude_relay_wakes", unexpected_missing_drain, raising=False)
        else:
            monkeypatch.setattr(main, "drain_claude_relay_wakes", observe_actual_drain)
        monkeypatch.setattr(PalliumService, "enqueue_relay_trace_event", gated_enqueue)
        monkeypatch.setattr("app.claude_wake.claude_wake_transport", fake_transport)
        application = main.app()
        owner = None
        request_shutdown = asyncio.Event()
        lifespan_entered = asyncio.Event()

        async def own_lifespan():
            async with application.router.lifespan_context(application):
                lifespan_entered.set()
                await request_shutdown.wait()

        try:
            owner = asyncio.create_task(own_lifespan())
            await asyncio.wait_for(lifespan_entered.wait(), timeout=5)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application, client=("127.0.0.1", 50000)),
                base_url="http://test",
            ) as client:
                _health, health_body = await _wait_for_health(
                    client, lambda body: body.get("initialized") is True,
                )
                assert health_body["ready"] is True
                scope = {"container_ref": "git:example/repo"}
                for runtime, session_ref in (("codex", "startup-sender"), ("claude-code", "startup-target")):
                    response = await client.post("/relay/turn", json={
                        "runtime": runtime, "session_ref": session_ref, **scope,
                    })
                    assert response.status_code == 200, response.text
                registry = created_apps[0].state.claude_wake_registry
                assert registry is not None and registry._state_dir is not None
                registration = {
                    "runtime": "claude-code", "session_ref": "startup-target",
                    "container_ref": scope["container_ref"], "socket_path": "fake-native-endpoint",
                    "token": "test-only-token", "idle": True, "intent_id": "test-only-registration",
                }
                registration_path = registry._intent_path(
                    registration["runtime"], registration["session_ref"], registration["container_ref"],
                )
                assert registration_path is not None
                assert registration_path.parent == registry._state_dir / "intents"
                write_json_atomic(registration_path, registration)
                assert registration_path.is_file()
                registered = await client.post("/internal/claude-wake/register", json=registration)
                assert registered.status_code == 204, registered.text
                sent = await client.post("/relay/messages", json={
                    "sender_runtime": "codex", "sender_session_ref": "startup-sender",
                    "recipient": "claude-code:startup-target", "payload": "test-only wake", **scope,
                })
                assert sent.status_code == 200, sent.text
                message_id = sent.json()["message_id"]
                delivery_id = sent.json()["deliveries"][0]["delivery_id"]
                assert await asyncio.to_thread(gate_started.wait, 5), "Relay HTTP did not schedule the held Claude wake"
                assert len(created_apps) == 1
                assert len(scheduled_threads) == 1
                wake_thread = scheduled_threads[0]
                assert wake_thread.name == "pallium-claude-wake" and wake_thread.is_alive()
                readback = await client.get(f"/relay/messages/{message_id}", params=scope)
                assert readback.status_code == 200
                assert readback.json()["deliveries"][0]["delivery_id"] == delivery_id
                assert readback.json()["deliveries"][0]["state"] == "pending"

                request_shutdown.set()
                _health, health_body = await _wait_for_health(
                    client, lambda body: body.get("initialized") is False,
                )
                assert await asyncio.to_thread(producers_settled.wait, 5), "direct producer threads did not settle"
                async with asyncio.timeout(5):
                    while not (drain_started.is_set() or service_close_started.is_set()):
                        await asyncio.sleep(0)
                assert direct_producer_threads
                assert all(not thread.is_alive() for thread in direct_producer_threads)
                assert scheduled_threads[0] not in direct_producer_threads
                assert scheduled_threads[0].is_alive(), "held wake thread settled before the drain boundary"
                assert not service_close_started.is_set(), "service close began before wake drainage completed"
                assert storage_close_calls == []
                assert service_close_calls == []

                status = await client.get("/status")
                query = await client.post("/query", json={"text": "during wake drainage"})
                assert health_body["ready"] is False
                assert status.json()["initialized"] is False
                assert status.json()["ready"] is False
                assert query.status_code == 503
                assert not owner.done(), "shutdown returned before the scheduled wake thread settled"
                assert wake_thread.is_alive()
                assert storage_close_calls == []
                assert service_close_calls == []
                with created_apps[0].state.pallium_service._storage._session_factory() as session:
                    assert session.execute(text("SELECT 1")).scalar_one() == 1

                release_gate.set()
                await asyncio.wait_for(asyncio.shield(owner), timeout=8)
                await asyncio.to_thread(wake_thread.join, 2)
                assert not wake_thread.is_alive()
                assert trace_finished.wait(1)
                assert storage_close_calls == [created_apps[0].state.pallium_service._storage]
                assert service_close_calls == [created_apps[0].state.pallium_service]
                assert close_order_witnesses == [
                    ("service", (False,), True),
                    ("storage", (False,), True),
                ]
                health = await client.get("/health")
                status = await client.get("/status")
                assert health.json()["initialized"] is False
                assert health.json()["ready"] is False
                assert status.json()["initialized"] is False
                assert status.json()["ready"] is False
        finally:
            release_gate.set()
            request_shutdown.set()
            try:
                if owner is not None:
                    await asyncio.gather(owner, return_exceptions=True)
            finally:
                for worker in dict.fromkeys(scheduled_threads):
                    await asyncio.to_thread(worker.join, 3)
                    assert not worker.is_alive(), "test-owned Claude wake thread did not settle"


class TestHealthNoVector:

    def test_health_returns_200_when_no_vector_index(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["vector_index_ready"] is True

    def test_health_json_body_shape(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert set(body.keys()) == {"status", "vector_index_ready", "embedding_provider_ok"}


def _failed_embedding_config(sqlite_url: str = "sqlite:///:memory:") -> AppConfig:
    """Vector is EXPECTED (enabled) but the embedding provider can't build
    (empty provider name) → index stays None. Simulates the silent-degrade
    scenario without needing a real ONNX model."""
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=sqlite_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=True, embedding_provider=""),
    )


class TestHealthDegradedEmbeddings:

    def test_health_degraded_when_vector_expected_but_provider_failed(self) -> None:
        app = create_app(_failed_embedding_config())
        with TestClient(app) as client:
            response = client.get("/health")
        # Impaired but reachable → 200 with a degraded signal, not 503.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["embedding_provider_ok"] is False
        assert body["vector_index_ready"] is False
        assert body["degraded_reasons"] == ["vector_embedding_provider_unavailable"]

    def test_health_ok_when_vector_disabled(self) -> None:
        # Vector intentionally off is NOT a failure.
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["embedding_provider_ok"] is True


class TestHealthLifecycle:

    @pytest.mark.parametrize("failed", [False, True])
    def test_lifespan_completion_waits_for_mcp(self, monkeypatch, caplog, failed):
        manager = pytest.importorskip("mcp.server.streamable_http_manager")
        caplog.set_level(logging.INFO, logger="app.main")

        @contextlib.asynccontextmanager
        async def run(_manager):
            assert app.state._lifespan_complete is False
            assert "startup stage=lifespan outcome=complete" not in caplog.text
            if failed:
                raise RuntimeError("MCP startup failed")
            yield

        monkeypatch.setattr(manager.StreamableHTTPSessionManager, "run", run)
        app = create_app(_no_vector_config())
        if failed:
            with pytest.raises(RuntimeError, match="MCP startup failed"):
                with TestClient(app):
                    pass
            assert app.state._lifespan_complete is False
            assert "startup stage=lifespan outcome=complete" not in caplog.text
        else:
            with TestClient(app) as client:
                assert client.get("/health").status_code == 200
                assert app.state._lifespan_complete is True
                assert "startup stage=lifespan outcome=complete" in caplog.text

    def test_lifespan_flag_starts_false(self) -> None:
        app = create_app(_no_vector_config())
        assert app.state._lifespan_complete is False
        assert app.state._reconcile_done is None

    def test_health_returns_503_before_lifespan(self) -> None:
        app = create_app(_no_vector_config())
        # Do NOT use context manager — lifespan will not run.
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "initializing"

    def test_health_returns_200_after_lifespan(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestHealthWithVectorIndex:

    def test_health_503_when_vector_configured_but_reconcile_not_done(self) -> None:
        app = create_app(_no_vector_config())
        # Simulate: lifespan has run, vector index is configured, but reconcile
        # has not completed yet.
        app.state._lifespan_complete = True
        app.state._reconcile_done = threading.Event()  # not set
        service = app.state.pallium_service
        # Swap in a truthy sentinel via the holder so _vector_index is not None
        service._index_holder.swap(MagicMock())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "initializing"
        assert body["vector_index_ready"] is False

    def test_health_200_when_vector_configured_and_reconcile_done(self) -> None:
        app = create_app(_no_vector_config())
        # Simulate: lifespan has run, vector index configured, reconcile done.
        app.state._lifespan_complete = True
        reconcile_done = threading.Event()
        reconcile_done.set()
        app.state._reconcile_done = reconcile_done
        service = app.state.pallium_service
        service._index_holder.swap(MagicMock())

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["vector_index_ready"] is True

    def test_vector_index_ready_true_when_no_vector_configured(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert body["vector_index_ready"] is True


class TestHealthEndpointLocation:

    def test_old_router_health_removed(self) -> None:
        from api.routes import create_router
        from app.dependencies import build_service

        config = _no_vector_config()
        service = build_service(config).service
        router = create_router(service)
        route_paths = [route.path for route in router.routes]
        assert "/health" not in route_paths


# ── /status endpoint tests ──────────────────────────────────────────────


def _file_db_config(tmp_path: Path, **overrides) -> AppConfig:
    """Create an AppConfig with a file-based temporary SQLite database.

    Using :memory: with SQLAlchemy's default pool can create separate
    in-memory databases per connection, which breaks direct SQL queries
    in the /status endpoint.
    """
    db_path = tmp_path / "test-status.db"
    defaults = dict(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestStatusResponseShape:

    def test_status_returns_200_always(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            response = client.get("/status")
        assert response.status_code == 200

    def test_status_response_has_all_top_level_keys(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        expected_keys = {
            "pending_items",
            "oldest_pending_age_seconds",
            "total_source_items",
            "total_memory_objects",
            "active_memory_objects",
            "snapshot",
            "storage",
            "vector_index_ready",
            "embedding_provider_ok",
            "ingestion",
            "vector_expected",
            "vector_rebuild",
            "uptime_seconds",
            "query",
            "derived_memory",
            "metrics_summary",
            "historical_lookup_funnel",
            "relay_wake",
        }
        assert set(body.keys()) == expected_keys

    def test_status_reports_funnel_armed(self, tmp_path: Path) -> None:
        """The reuse funnel is armed by default → status reports armed=True with
        a computed events count."""
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        funnel = body["historical_lookup_funnel"]
        assert set(funnel.keys()) == {"armed", "events_recorded"}
        assert funnel["armed"] is True
        assert funnel["events_recorded"] == 0

    def test_status_reports_funnel_not_armed_when_disabled(self, tmp_path: Path) -> None:
        from app.config import ObservabilityConfig

        app = create_app(
            _file_db_config(
                tmp_path,
                observability=ObservabilityConfig(historical_lookup_funnel=False),
            )
        )
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["historical_lookup_funnel"]["armed"] is False

    def test_status_snapshot_sub_keys(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        snapshot = body["snapshot"]
        assert set(snapshot.keys()) == {"enabled", "last_snapshot_at", "snapshot_count"}

    def test_status_storage_sub_keys(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        storage = body["storage"]
        assert set(storage.keys()) == {"sqlite_mb", "relay_sqlite_mb", "vector_index_mb"}
        # Both SQLite files exist after DB init.
        assert isinstance(storage["sqlite_mb"], float)
        assert isinstance(storage["relay_sqlite_mb"], float)


class TestStatusIngestionProviderSignal:

    def test_status_reports_missing_llm_credential_without_exposing_secrets(self, tmp_path: Path) -> None:
        packages = {
            "memory": SemanticPackageConfig(
                name="memory",
                implementation="agent_conversation_memory",
                enabled=True,
                llm_provider="remote",
                model="test-model",
            )
        }
        providers = {
            "remote": LLMProviderConfig(
                name="remote",
                kind="anthropic_claude",
                base_url="https://example.test",
                api_key_env="TEST_MISSING_KEY",
            )
        }
        app = create_app(_file_db_config(
            tmp_path,
            default_use_case="memory",
            semantic_packages=packages,
            llm_providers=providers,
        ))
        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["ingestion"] == {
            "status": "degraded",
            "issues": [{
                "package": "memory",
                "provider": "remote",
                "reason": "missing_api_key",
                "api_key_env": "TEST_MISSING_KEY",
            }],
        }
        assert "secret" not in str(body["ingestion"])

class TestStatusEmbeddingProviderSignal:

    def test_status_embedding_ok_when_vector_disabled(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["vector_expected"] is False
        assert body["embedding_provider_ok"] is True

    def test_status_embedding_not_ok_when_provider_failed(self, tmp_path: Path) -> None:
        app = create_app(
            _file_db_config(
                tmp_path,
                vector_index=VectorIndexConfig(enabled=True, embedding_provider=""),
            )
        )
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["vector_expected"] is True
        assert body["embedding_provider_ok"] is False
        assert body["vector_index_ready"] is False


class TestStatusEmptyDatabase:

    def test_counts_are_zero_on_empty_db(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["pending_items"] == 0
        assert body["oldest_pending_age_seconds"] is None
        assert body["total_source_items"] == 0
        assert body["total_memory_objects"] == 0

    def test_snapshot_disabled_by_default(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["snapshot"]["enabled"] is False
        assert body["snapshot"]["last_snapshot_at"] is None
        assert body["snapshot"]["snapshot_count"] == 0

    def test_uptime_is_positive(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["uptime_seconds"] >= 0

    def test_vector_index_ready_when_not_configured(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["vector_index_ready"] is True


class TestStatusWithData:

    def test_counts_after_ingesting_source_items(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        # Create two source items: one pending, one completed
        pending_item = SourceItem(
            source_type="chat_message",
            source_id="status-test-1",
            content_type="text/plain",
            content="hello",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
        )
        completed_item = SourceItem(
            source_type="chat_message",
            source_id="status-test-2",
            content_type="text/plain",
            content="world",
            role="assistant",
            container_ref="c1",
            thread_ref="t1",
            processing_status="completed",
        )
        storage.create_source_item(pending_item)
        storage.create_source_item(completed_item)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["pending_items"] == 1
        assert body["total_source_items"] == 2
        assert body["oldest_pending_age_seconds"] is not None
        assert body["oldest_pending_age_seconds"] >= 0

    def test_counts_after_creating_memory_objects(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        storage.create_source_item(SourceItem(
            source_type="chat_message",
            source_id="status-mo-test",
            content_type="text/plain",
            content="test",
            role="user",
            container_ref="c1",
            thread_ref="t1",
        ))

        mo = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={"summary": "test decision"},
            container_ref="c1",
        )
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["total_source_items"] == 1
        assert body["total_memory_objects"] == 1

    def test_multiple_pending_reports_oldest_age(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        # Create an item with an older timestamp
        old_item = SourceItem(
            source_type="chat_message",
            source_id="status-old-1",
            content_type="text/plain",
            content="old",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new_item = SourceItem(
            source_type="chat_message",
            source_id="status-new-1",
            content_type="text/plain",
            content="new",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
        )
        storage.create_source_item(old_item)
        storage.create_source_item(new_item)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["pending_items"] == 2
        # The oldest is from Jan 2026, should be many seconds old
        assert body["oldest_pending_age_seconds"] > 0


class TestStatusSnapshot:

    def test_snapshot_enabled_with_files(self, tmp_path: Path) -> None:
        # Create fake snapshot files in a subdirectory
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()
        (snapshot_dir / "pallium-20260414T100000Z.manifest.json").write_text("{}")
        (snapshot_dir / "pallium-20260414T103000Z.manifest.json").write_text("{}")

        config = _file_db_config(
            tmp_path,
            snapshot=SnapshotConfig(
                enabled=True,
                snapshot_path=str(snapshot_dir),
            ),
        )
        app = create_app(config)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["snapshot"]["enabled"] is True
        assert body["snapshot"]["snapshot_count"] == 2
        assert body["snapshot"]["last_snapshot_at"] is not None

    def test_snapshot_enabled_no_files(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()

        config = _file_db_config(
            tmp_path,
            snapshot=SnapshotConfig(
                enabled=True,
                snapshot_path=str(snapshot_dir),
            ),
        )
        app = create_app(config)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["snapshot"]["enabled"] is True
        assert body["snapshot"]["snapshot_count"] == 0
        assert body["snapshot"]["last_snapshot_at"] is None
