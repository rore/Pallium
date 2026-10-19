from __future__ import annotations

from app import run as app_run
from app.config import AppConfig
import pytest


@pytest.fixture(autouse=True)
def isolated_run_config(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    config = AppConfig(sqlite_url="sqlite:///:memory:", relay_sqlite_url="sqlite:///:memory:")
    monkeypatch.setattr(AppConfig, "from_env", staticmethod(lambda: config))


def test_run_default_invokes_supervisor_with_processors_and_cleaner(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_supervisor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_supervisor", fake_run_supervisor)

    exit_code = app_run.run(["--host", "127.0.0.1", "--port", "8010", "--processors", "2"])

    assert exit_code == 0
    assert captured["args"] == ["--host", "127.0.0.1", "--port", "8010", "--processors", "2", "--cleaners", "1"]


def test_run_processor_mode_invokes_processor(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_processor(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_processor", fake_run_processor)

    exit_code = app_run.run(["processor", "--processor-id", "proc-1", "--once"])

    assert exit_code == 0
    assert captured["args"] == ["--processor-id", "proc-1", "--poll-interval-seconds", "0.2", "--once"]


def test_run_cleaner_mode_invokes_cleaner(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run_cleaner(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(app_run, "run_cleaner", fake_run_cleaner)

    exit_code = app_run.run(["cleaner", "--cleaner-id", "cleaner-1", "--batch-size", "50", "--once"])

    assert exit_code == 0
    assert captured["args"] == ["--cleaner-id", "cleaner-1", "--batch-size", "50", "--once"]


def test_run_serve_mode_configures_timestamped_uvicorn_logging(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_server_run(server):
        captured["app"] = server.config.app
        captured.update(vars(server.config))
        server.started = True

    monkeypatch.setattr(app_run.uvicorn.Server, "run", fake_server_run)

    exit_code = app_run.run(["serve", "--host", "127.0.0.1", "--port", "8011"])

    assert exit_code == 0
    assert callable(captured["app"])
    assert captured["factory"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8011
    log_config = captured["log_config"]
    assert log_config["formatters"]["pallium_default"]["()"] == "app.runtime_logging.RuntimeLogFormatter"
    assert log_config["formatters"]["pallium_default"]["component"] == "api"
    assert log_config["loggers"]["uvicorn.error"]["handlers"] == ["default"]
    assert log_config["loggers"]["uvicorn.access"]["handlers"] == ["access"]


def test_run_snapshot_mode(monkeypatch) -> None:
    """Verify 'snapshot' is a valid CLI mode that dispatches to run_snapshot."""
    from app.run import build_parser
    parsed = build_parser().parse_args(["snapshot"])
    assert parsed.mode == "snapshot"


@pytest.mark.parametrize("reload,workers", [(True, "1"), (False, "2")])
def test_serve_preserves_unowned_reload_and_multiworker_driver(monkeypatch, reload, workers):
    calls = []
    monkeypatch.setenv("WEB_CONCURRENCY", workers)
    monkeypatch.setattr(app_run.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(app_run.uvicorn.Server, "run", lambda _: pytest.fail("unowned server driver"))
    app_run._serve(host="127.0.0.1", port=0, reload=reload)
    assert len(calls) == 1 and calls[0][0] == ("app.main:app",)
    assert calls[0][1]["factory"] is True and calls[0][1]["reload"] is reload


@pytest.mark.parametrize("interrupt", [False, True])
@pytest.mark.parametrize("started", [False, True])
def test_owned_serve_preserves_interrupt_and_startup_failure(monkeypatch, interrupt, started):
    from uvicorn.main import STARTUP_FAILURE

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    def run(server):
        server.started = started
        if interrupt:
            raise KeyboardInterrupt
    monkeypatch.setattr(app_run.uvicorn.Server, "run", run)
    if started:
        app_run._serve(host="127.0.0.1", port=0, reload=False)
    else:
        with pytest.raises(SystemExit) as caught:
            app_run._serve(host="127.0.0.1", port=0, reload=False)
        assert caught.value.code == STARTUP_FAILURE


@pytest.mark.asyncio
@pytest.mark.parametrize("early", [False, True])
async def test_owned_server_terminal_exit_runs_actual_lifespan_cleanup(
    monkeypatch, test_db_url, tmp_path, early,
):
    import asyncio
    import contextlib
    import json
    import threading
    import httpx
    from app import main, codex_bridge_pipe as bridge
    from tests.test_health import _no_vector_config, _prebuilt_production_inner

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path / "private-home"))
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "private-incarnation")
    token = tmp_path / "private-home" / "run" / "api_token"
    trigger, native_entered, notified = threading.Event(), threading.Event(), threading.Event()
    servers, listeners, callbacks, closed, loop_entries = [], [], [], [], []
    original_run = app_run.uvicorn.Server.run
    original_loop = app_run.uvicorn.Server.main_loop
    original_factory = main.app
    original_native = bridge._native
    fault = RuntimeError("private-terminal-source-fault")

    def native():
        if not listeners or threading.current_thread() is not listeners[0].thread:
            return original_native()
        native_entered.set()
        assert trigger.wait(8)
        raise fault

    def start(*, on_terminal):
        assert callable(on_terminal)
        def notify():
            on_terminal()
            notified.set()
        service = bridge.RetainedService(tmp_path / "native", on_terminal=notify)
        listeners.append(service)
        return service.start()

    monkeypatch.setattr(bridge, "native_available", lambda: True)
    monkeypatch.setattr(bridge, "_native", native)
    monkeypatch.setattr(bridge, "start_retained_service", start)

    def observe_run(server):
        servers.append(server)
        return original_run(server)

    async def observe_loop(server):
        loop_entries.append(True)
        await original_loop(server)

    def factory(*, on_retained_terminal):
        callbacks.append(on_retained_terminal)
        application = original_factory(on_retained_terminal=on_retained_terminal)
        lifespan = application.router.lifespan_context
        @contextlib.asynccontextmanager
        async def early_lifespan(app):
            async with lifespan(app):
                if early:
                    assert await asyncio.to_thread(native_entered.wait, 5)
                    trigger.set()
                    assert await asyncio.to_thread(notified.wait, 5)
                    on_retained_terminal()
                    on_retained_terminal()
                    await asyncio.sleep(0)
                    assert not servers[0].should_exit
                yield
        application.router.lifespan_context = early_lifespan
        return application

    monkeypatch.setattr(app_run.uvicorn.Server, "run", observe_run)
    monkeypatch.setattr(app_run.uvicorn.Server, "main_loop", observe_loop)
    monkeypatch.setattr(main, "app", factory)
    async with _prebuilt_production_inner(
        monkeypatch, lambda: main.create_app(_no_vector_config(test_db_url)),
    ) as inner:
        storage = inner.state.pallium_service._storage
        original_close = storage.close
        def close():
            try:
                assert listeners and not listeners[0].thread.is_alive()
                assert inner.state._wait_for_operations(timeout=0)
                closed.append(True)
            finally:
                original_close()
        monkeypatch.setattr(storage, "close", close)
        serving = asyncio.create_task(asyncio.to_thread(app_run._serve, host="127.0.0.1", port=0, reload=False))
        try:
            if not early:
                async with asyncio.timeout(8):
                    while not servers or not servers[0].started:
                        await asyncio.sleep(.01)
                    port = servers[0].servers[0].sockets[0].getsockname()[1]
                    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                        while True:
                            response = await http.get("/health")
                            if response.json().get("initialized") is True:
                                break
                            await asyncio.sleep(.01)
                        assert response.status_code == 200
                        assert json.loads(token.read_text())["nonce"] == "private-incarnation"
                assert native_entered.is_set()
                trigger.set()
            await asyncio.wait_for(asyncio.shield(serving), 8)
            assert len(servers) == len(callbacks) == len(listeners) == 1
            assert loop_entries == [True] and servers[0].exit_requested
            assert closed == [True] and not token.exists()
            assert listeners[0]._terminal_failure and not listeners[0].thread.is_alive()
        finally:
            trigger.set()
            if callbacks and not serving.done():
                callbacks[0]()
            await serving
