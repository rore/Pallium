from __future__ import annotations

from tests.test_windows_service import guard_selected_mock

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


def test_cooperative_windows_owned_exit_latches_before_main_loop(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app import windows_service
    servers, closed = [], []
    channel = SimpleNamespace(requested=lambda: True, close=lambda: closed.append(True))
    class Loop:
        def call_soon_threadsafe(self, callback):
            callback()
        def create_task(self, coroutine):
            with pytest.raises(StopIteration):
                coroutine.send(None)
            class Task:
                def add_done_callback(self, callback):
                    callback(self)
            return Task()
    class Server:
        def __init__(self, config):
            self.config, self.should_exit, self.started = config, False, False
            servers.append(self)
        def run(self):
            self.started = True
            self.config.app()
        async def main_loop(self):
            assert self.should_exit
    monkeypatch.setattr(app_run.secrets, "token_hex", lambda _: "independent-public-entropy")
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: channel)
    monkeypatch.setattr(app_run.uvicorn, "Config", lambda *_, **__: SimpleNamespace(workers=1, app=None))
    monkeypatch.setattr(app_run.uvicorn, "Server", Server)
    monkeypatch.setattr(app_run.asyncio, "get_running_loop", lambda: Loop())
    monkeypatch.setitem(sys.modules, "app.main", SimpleNamespace(app=lambda **_: object()))
    app_run._serve(host="127.0.0.1", port=21987, reload=False)
    server = servers[0]
    assert server.exit_requested and not server.should_exit and closed == [True]
    coroutine = server.main_loop()
    with pytest.raises(StopIteration):
        coroutine.send(None)
    assert server.main_loop_entered and server.should_exit


@pytest.mark.parametrize("bind_succeeds", [True, False], ids=["bound", "bind-failed"])
def test_cooperative_windows_postbind_lifecycle_proof_tracks_listener(monkeypatch, bind_succeeds):
    from types import SimpleNamespace
    from app import windows_service
    trace = []
    def bound(port, listeners, instance):
        assert instance == "instance-independent-public-entropy"
        assert port == 21987 and listeners == ["owned-listener"]
        trace.append("bound")
        return True
    channel = SimpleNamespace(requested=lambda: False, publish_bound=bound,
                              clear_bound=lambda: trace.append("clear"), close=lambda: trace.append("close"))
    class Server:
        def __init__(self, config):
            self.config, self.started, self.should_exit = config, False, False
        def run(self):
            if bind_succeeds:
                self.started = True
                self.servers = ["owned-listener"]
                coroutine = self.main_loop()
                with pytest.raises(StopIteration):
                    coroutine.send(None)
        async def main_loop(self):
            assert trace == ["bound"]
            trace.append("loop")
    monkeypatch.setattr(app_run.secrets, "token_hex", lambda _: "independent-public-entropy")
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: channel)
    monkeypatch.setattr(app_run.uvicorn, "Config", lambda *_, **__: SimpleNamespace(workers=1, app=None))
    monkeypatch.setattr(app_run.uvicorn, "Server", Server)
    if bind_succeeds:
        app_run._serve(host="127.0.0.1", port=21987, reload=False)
        assert trace == ["bound", "loop", "clear", "close"]
    else:
        with pytest.raises(SystemExit):
            app_run._serve(host="127.0.0.1", port=21987, reload=False)
        assert trace == ["close"]


def test_cooperative_windows_managed_header_is_public_and_unmanaged_config_unchanged(monkeypatch):
    from types import SimpleNamespace
    from app import windows_service
    options, entropy = [], []
    public_values = iter(("fresh-public-random", "second-public-random"))
    channel = SimpleNamespace(close=lambda: None)
    def public_entropy(size):
        entropy.append(size)
        return next(public_values)
    def config(*_, **kwargs):
        options.append(kwargs)
        return SimpleNamespace(workers=1, app=None)
    class Server:
        def __init__(self, config):
            self.config, self.started = config, False
        def run(self):
            self.started = True
    monkeypatch.setenv("PALLIUM_API_LAUNCH_TOKEN", "private-startup-nonce")
    monkeypatch.setattr(app_run.secrets, "token_hex", public_entropy)
    monkeypatch.setattr(app_run.uvicorn, "Config", config)
    monkeypatch.setattr(app_run.uvicorn, "Server", Server)
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: channel)
    app_run._serve(host="127.0.0.1", port=21987, reload=False)
    assert options[-1]["headers"] == [("X-Pallium-Service-Instance", "instance-fresh-public-random")]
    assert "private-startup-nonce" not in repr(options[-1]) and entropy == [16]
    app_run._serve(host="127.0.0.1", port=21987, reload=False)
    assert options[-1]["headers"] == [("X-Pallium-Service-Instance", "instance-second-public-random")]
    assert options[-1]["headers"] != options[-2]["headers"] and entropy == [16, 16]
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: None)
    app_run._serve(host="127.0.0.1", port=21987, reload=False)
    assert "headers" not in options[-1] and entropy == [16, 16]


@pytest.mark.parametrize("phase", ["publish", "revoke"], ids=["publish-failure", "revoke-failure"])
@pytest.mark.parametrize("error_kind", ["os", "metadata", "unknown"], ids=["filesystem", "malformed-metadata", "unknown"])
def test_cooperative_windows_marker_error_drains_lifespan_once_then_fails(monkeypatch, phase, error_kind):
    from types import SimpleNamespace
    from app import windows_service
    trace, servers, returned = [], [], []
    stopped = [False]
    error = {"os": OSError, "metadata": ValueError, "unknown": windows_service.Unknown}[error_kind]("marker bookkeeping failed")
    def publish(*_):
        trace.append("publish")
        if phase == "publish":
            raise error
        return True
    def revoke():
        trace.append("revoke")
        if phase == "revoke":
            raise error
    def request():
        trace.append("request-stop")
        stopped[0] = True
    channel = SimpleNamespace(requested=lambda: stopped[0], publish_bound=publish,
                              clear_bound=revoke, request=request, close=lambda: trace.append("close"))
    class Server:
        def __init__(self, config):
            self.config, self.started, self.should_exit = config, False, False
            self.shutdown_calls = 0
            servers.append(self)
        def run(self):
            self.started, self.servers = True, ["owned-listener"]
            coroutine = self.main_loop()
            # Mirror Uvicorn: an escaped main_loop error would bypass these finalizers.
            with pytest.raises(StopIteration):
                coroutine.send(None)
            self.shutdown_calls += 1
            trace.extend(("listener-shutdown", "lifespan-drained"))
        async def main_loop(self):
            trace.append("base-loop")
            if phase == "publish":
                assert self.should_exit and stopped[0]
            self.request_exit()
    monkeypatch.setattr(app_run.secrets, "token_hex", lambda _: "independent-public-entropy")
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: channel)
    monkeypatch.setattr(app_run.uvicorn, "Config", lambda *_, **__: SimpleNamespace(workers=1, app=None))
    monkeypatch.setattr(app_run.uvicorn, "Server", Server)
    with pytest.raises(RuntimeError, match="binding marker failed") as failure:
        app_run._serve(host="127.0.0.1", port=21987, reload=False)
        returned.append("success")
    assert failure.value.__cause__ is error and returned == []
    assert servers[0].shutdown_calls == 1 and stopped[0]
    assert trace.count("listener-shutdown") == trace.count("lifespan-drained") == trace.count("request-stop") == 1
    assert trace.index("lifespan-drained") < trace.index("close")


@pytest.mark.parametrize("managed", [True, False], ids=["managed", "unmanaged"])
def test_owned_server_http_stop_drains_real_lifespan(request, tmp_path, test_db_url, managed):
    import contextlib
    import json
    import threading
    import time
    import httpx
    from app import main, windows_service, codex_bridge_pipe as bridge
    from tests.test_health import _no_vector_config

    # These patches outlive an unresolved owned thread; fixture teardown must not
    # restore native entry points or close its storage while it is still running.
    patches = pytest.MonkeyPatch()
    stop, bound = threading.Event(), threading.Event()
    trace, servers, applications, callbacks, errors, native_calls = [], [], [], [], [], []
    delegates = []
    inner = serving = None
    token = tmp_path / "private-home" / "run" / "api_token"
    startup_nonce = "private-http-startup-nonce"

    def deny_native(*args, **kwargs):
        native_calls.append((args, kwargs))
        raise AssertionError("HTTP lifecycle test must not enter service native backends")

    class Channel:
        marker = None
        port = None

        def requested(self):
            return stop.is_set()

        def request(self):
            stop.set()

        def publish_bound(self, configured_port, listeners, public_instance):
            assert configured_port == 0 and servers[0].started
            self.port = listeners[0].sockets[0].getsockname()[1]
            assert self.port > 0
            self.marker = public_instance
            trace.append("publish")
            bound.set()
            return True

        def clear_bound(self):
            self.marker = None
            trace.append("revoke")

        def close(self):
            assert "lifespan-exit" in trace
            assert all(not listener.is_serving() for listener in servers[0].servers)
            trace.append("channel-close")

    channel = Channel()
    original_run, original_factory = app_run.uvicorn.Server.run, main.app

    def observe_run(server):
        servers.append(server)
        return original_run(server)

    def factory(*, on_retained_terminal):
        callbacks.append(on_retained_terminal)
        application = original_factory(on_retained_terminal=on_retained_terminal)
        applications.append(application)
        lifespan = application.router.lifespan_context

        @contextlib.asynccontextmanager
        async def observe_lifespan(app):
            trace.append("lifespan-enter")
            async with lifespan(app):
                yield
            trace.append("lifespan-exit")

        application.router.lifespan_context = observe_lifespan
        return application

    def serve():
        try:
            app_run._serve(host="127.0.0.1", port=0, reload=False)
        except BaseException as error:
            errors.append(error)
        finally:
            trace.append("serve-return")

    try:
        patches.setenv("PALLIUM_HOME", str(tmp_path / "private-home"))
        patches.setenv("PALLIUM_API_LAUNCH_TOKEN", startup_nonce)
        patches.delenv("WEB_CONCURRENCY", raising=False)
        for name in ("WindowsAPI", "native", "_task_info", "_start_task"):
            patches.setattr(windows_service, name, deny_native)
        patches.setattr(bridge, "_native", deny_native)
        for name in ("start_shadow_service", "start_inventory_service", "start_retained_service"):
            patches.setattr(bridge, name, lambda *args, **kwargs: None)
        patches.setattr(windows_service, "inherited_stop", lambda: channel if managed else None)
        inner = main.create_app(_no_vector_config(test_db_url))
        storage = inner.state.pallium_service._storage
        original_close = storage.close

        def close_storage():
            trace.append("storage-close")
            return original_close()

        def delegate(*args, **kwargs):
            delegates.append(threading.get_ident())
            return inner

        patches.setattr(storage, "close", close_storage)
        patches.setattr(main, "create_app", delegate)
        patches.setattr(main, "app", factory)
        patches.setattr(app_run.uvicorn.Server, "run", observe_run)
        serving = threading.Thread(target=serve, name="private-http-lifecycle", daemon=True)
        serving.start()
        deadline = time.monotonic() + 10
        while not servers or not servers[0].started:
            assert serving.is_alive() and time.monotonic() < deadline, (trace, errors)
            time.sleep(.01)
        port = servers[0].servers[0].sockets[0].getsockname()[1]
        assert port > 0
        if managed:
            assert bound.wait(max(0, deadline - time.monotonic())) and channel.port == port
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                          follow_redirects=False, timeout=1) as client:
            while True:
                response = client.get("/health")
                if response.status_code == 200 and response.json().get("initialized") is True:
                    break
                assert time.monotonic() < deadline, response.text
                time.sleep(.01)
            assert json.loads(token.read_text())["nonce"] == startup_nonce
            for path in ("/health", "/status", "/debug/queue/health"):
                response = client.get(path)
                assert response.status_code == 200, (path, response.text)
                marker = response.headers.get(windows_service.SERVICE_INSTANCE_HEADER)
                if managed:
                    assert marker == channel.marker and marker.startswith("instance-")
                    assert marker != startup_nonce and startup_nonce not in marker
                else:
                    assert marker is None
        if managed:
            stop.set()
        else:
            callbacks[0]()
        serving.join(timeout=10)
        assert not serving.is_alive(), "owned HTTP thread did not settle"
        assert errors == [] and native_calls == []
        assert len(servers) == len(applications) == len(callbacks) == len(delegates) == 1
        assert delegates[0] != threading.get_ident()
        assert applications[0].state._owner.done()
        assert trace.count("lifespan-enter") == trace.count("lifespan-exit") == trace.count("storage-close") == 1
        assert trace.index("storage-close") < trace.index("lifespan-exit") < trace.index("serve-return")
        assert not token.exists()
        if managed:
            assert trace.count("publish") == trace.count("revoke") == trace.count("channel-close") == 1
            assert trace.index("revoke") < trace.index("storage-close")
            assert trace.index("lifespan-exit") < trace.index("channel-close") < trace.index("serve-return")
            assert channel.marker is None
        else:
            assert not any(item in trace for item in ("publish", "revoke", "channel-close"))
    finally:
        stop.set()
        if serving is not None and serving.is_alive():
            if callbacks:
                try:
                    callbacks[0]()
                except BaseException as error:
                    errors.append(error)
            serving.join(timeout=10)
        if serving is not None and serving.is_alive():
            request.node._unsettled_http_owner = (serving, inner, patches)
            request.node.add_report_section("call", "owned HTTP thread", repr((serving.ident, trace, errors)))
            pytest.fail("owned HTTP thread remains unresolved; storage and native guards retained")
        try:
            if inner is not None:
                inner.state._close_constructed()
        finally:
            patches.undo()
