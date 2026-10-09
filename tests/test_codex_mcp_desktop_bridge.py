"""Inert Codex MCP bridge eligibility and lifecycle coverage."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import anyio
import httpx
import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.mcp import codex_desktop_bridge, server as mcp_server

INVENTORY_META = {"threadId": "source-chat", "turnId": "source-turn"}
INVENTORY_CALLER = {"thread_ref": "source-chat", "turn_ref": "source-turn"}


class _FakeStatusClient:
    def __init__(self, _ctx):
        pass

    async def get_status(self):
        return {"status": "healthy"}


def test_bridge_is_opt_in_codex_stdio_and_checks_capability_presence_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALLIUM_CODEX_BRIDGE_MODE", raising=False)
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "secret-capability-path")
    assert not mcp_server._codex_bridge_enabled("stdio")

    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "inert")
    assert mcp_server._codex_bridge_enabled("stdio")
    assert not mcp_server._codex_bridge_enabled("streamable-http")
    assert not mcp_server._codex_bridge_enabled("sse")

    monkeypatch.setenv("PALLIUM_AGENT_REF", "claude")
    assert not mcp_server._codex_bridge_enabled("stdio")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
    assert not mcp_server._codex_bridge_enabled("stdio")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "invalid")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "secret-capability-path")
    assert not mcp_server._codex_bridge_enabled("stdio")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "inert")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "")
    assert not mcp_server._codex_bridge_enabled("stdio")


def test_main_only_passes_lifespan_for_explicit_eligible_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    fake_server = MagicMock()

    def create_server(**kwargs):
        captured.update(kwargs)
        return fake_server

    monkeypatch.setattr(mcp_server, "create_server", create_server)
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "inert")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "secret-capability-path")

    mcp_server.main()
    assert captured["lifespan"] is mcp_server._codex_bridge_lifespan
    assert len(fake_server.run.call_args_list) == 1
    assert fake_server.run.call_args.kwargs == {"transport": "stdio"}
    assert "secret-capability-path" not in repr(captured)

    captured.clear()
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "streamable-http")
    mcp_server.main()
    assert "lifespan" not in captured

    captured.clear()
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "other")
    mcp_server.main()
    assert "lifespan" not in captured


_STDIO_CHILD = dedent(
    r'''
    import asyncio
    import os
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from app.mcp import server as m

    # This harness exercises the legacy inert lifecycle; retained mode has its own journeys.
    m._codex_retained_enabled = lambda transport: False

    failure = os.environ["TEST_BRIDGE_FAILURE"]
    shutdown_entered = asyncio.Event()
    shutdown_cancelled = asyncio.Event()
    if failure == "shutdown-timeout":
        original_wait_for = asyncio.wait_for
        lifespan_waits = [0]
        async def controlled_wait_for(awaitable, timeout):
            lifespan_waits[0] += 1
            if lifespan_waits[0] != 2:
                return await original_wait_for(awaitable, timeout=timeout)
            assert timeout == 1.0
            shutdown = asyncio.create_task(awaitable)
            await shutdown_entered.wait()
            shutdown.cancel()
            try:
                await shutdown
            except asyncio.CancelledError:
                pass
            assert shutdown_cancelled.is_set()
            print("inert-test-shutdown-manager-cancelled", file=__import__("sys").stderr, flush=True)
            raise TimeoutError
        # Drive the fault without competing with the SDK's separate process-exit deadline.
        local_asyncio = SimpleNamespace(**vars(asyncio))
        local_asyncio.wait_for = controlled_wait_for
        m.asyncio = local_asyncio
    if failure == "import":
        original_import = m.importlib.import_module
        def injected_import(name, package=None):
            if name == "app.mcp.codex_desktop_bridge":
                raise RuntimeError("secret import failure")
            return original_import(name, package)
        m.importlib = SimpleNamespace(import_module=injected_import)
    else:
        from app.mcp import codex_desktop_bridge as bridge
        if failure == "task":
            async def idle():
                raise RuntimeError("secret task failure")
            bridge._idle = idle
        elif failure in ("startup", "startup-timeout"):
            @asynccontextmanager
            async def injected(server):
                if failure == "startup-timeout":
                    await asyncio.Future()
                raise RuntimeError("secret startup failure")
                yield {}
            bridge.lifespan = injected
        elif failure in ("shutdown", "shutdown-timeout"):
            @asynccontextmanager
            async def injected(server):
                yield {}
                if failure == "shutdown-timeout":
                    shutdown_entered.set()
                    try:
                        await asyncio.Future()
                    finally:
                        shutdown_cancelled.set()
                raise RuntimeError("secret shutdown failure")
            bridge.lifespan = injected

    class FakeClient:
        def __init__(self, _ctx):
            pass
        async def get_status(self):
            return {"status": "healthy"}
        async def query(self, text, limit=5):
            return {"query": text, "limit": limit, "results": []}

    m.PalliumMcpClient = FakeClient
    create = m.create_server
    def checked_create(**kwargs):
        server = create(**kwargs)
        reference = create()
        async def same_catalog():
            actual = await server.list_tools()
            baseline = await reference.list_tools()
            assert [x.model_dump() for x in actual] == [x.model_dump() for x in baseline]
        asyncio.run(same_catalog())
        return server
    m.create_server = checked_create
    m.main()
    if failure == "shutdown-timeout":
        assert asyncio.wait_for is original_wait_for
    print("inert-test-launcher-returned", file=__import__("sys").stderr, flush=True)
    '''
)


@contextmanager
def _stdio_error_log():
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as log:
        try:
            yield log
        except BaseException as error:
            log.seek(0)
            text = log.read(8192)
            frames = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', text)
            kinds = re.findall(r'^([\w.]+(?:Error|Exception)):', text, re.MULTILINE)
            error.add_note(json.dumps({
                "child_exception_classes": kinds,
                "child_frames": [(Path(path).name, line, function)
                                 for path, line, function in frames],
            }))
            raise


def test_stdio_failure_note_omits_raw_text_paths_and_capabilities():
    with pytest.raises(RuntimeError) as caught:
        with _stdio_error_log() as log:
            log.write('File "private/user.py", line 3, in fake_entry\n'
                      'TypeError: private-capability-sentinel\n')
            raise RuntimeError("test parent failure")
    note = caught.value.__notes__[0]
    assert "TypeError" in note and "fake_entry" in note
    assert "private/" not in note and "private-capability-sentinel" not in note


def _stdio_params(
    failure: str,
    *,
    agent: str = "codex",
    mode: str = "inert",
    capability: str | None = "private-capability-sentinel",
) -> StdioServerParameters:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH")))),
        "PALLIUM_MCP_TRANSPORT": "stdio",
        "PALLIUM_AGENT_REF": agent,
        "PALLIUM_CODEX_BRIDGE_MODE": mode,
        "PALLIUM_BASE_URL": "http://127.0.0.1:1",
        "PALLIUM_CONTAINER_REF": "test/codex-bridge",
        "PALLIUM_VISIBILITY": "private",
        "TEST_BRIDGE_FAILURE": failure,
    })
    if capability is None:
        env.pop("CODEX_APP_TOOLS_PIPE_PATH", None)
    else:
        env["CODEX_APP_TOOLS_PIPE_PATH"] = capability
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", _STDIO_CHILD],
        cwd=repo,
        env=env,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "diagnostic"),
    [
        ("import", "import-failed"),
        ("startup", "startup-failed"),
        ("startup-timeout", "startup-failed"),
        ("task", "task-failed"),
        ("shutdown", "shutdown-failed"),
        ("shutdown-timeout", "shutdown-failed"),
    ],
)
async def test_real_stdio_keeps_concurrent_normal_tools_live_on_bridge_fault(
    failure: str,
    diagnostic: str,
) -> None:
    with _stdio_error_log() as error_log:
        async with stdio_client(_stdio_params(failure), errlog=error_log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()
                query_tool = next(tool for tool in catalog.tools if tool.name == "pallium_query")
                assert {"query", "limit"} <= set(query_tool.inputSchema["properties"])
                assert "CODEX_APP_TOOLS_PIPE_PATH" not in repr(query_tool.inputSchema)
                status, query = await asyncio.gather(
                    session.call_tool("pallium_status", {}),
                    session.call_tool("pallium_query", {"query": "inert bridge", "limit": 4,
                        "container_ref": "test/codex-bridge", "visibility": "private"}),
                )
                assert not status.isError and json.loads(status.content[0].text) == {"status": "healthy"}
                assert not query.isError and json.loads(query.content[0].text) == {
                    "query": "inert bridge", "limit": 4, "results": []
                }
        error_log.seek(0)
        output = error_log.read()
    assert f"Pallium Codex bridge inert: {diagnostic}" in output
    if failure == "shutdown-timeout":
        assert "inert-test-shutdown-manager-cancelled" in output
    assert "inert-test-launcher-returned" in output
    assert "secret " not in output
    assert "private-capability-sentinel" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent", "mode", "capability"),
    [
        ("codex", "off", "private-capability-sentinel"),
        ("other", "inert", "private-capability-sentinel"),
        ("codex", "inert", None),
        ("codex", "invalid", "private-capability-sentinel"),
        ("codex", "inert", ""),
    ],
)
async def test_real_stdio_ineligible_child_never_imports_bridge(
    agent: str,
    mode: str,
    capability: str | None,
) -> None:
    params = _stdio_params(
        "import", agent=agent, mode=mode, capability=capability
    )
    with _stdio_error_log() as error_log:
        async with stdio_client(params, errlog=error_log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert any(tool.name == "pallium_status" for tool in catalog.tools)
                result = await session.call_tool("pallium_status", {})
                assert not result.isError and json.loads(result.content[0].text) == {"status": "healthy"}
        error_log.seek(0)
        output = error_log.read()
        diagnostics = [line for line in output.splitlines() if line.startswith("Pallium Codex bridge inert:")]
        assert set(diagnostics) <= {
            "Pallium Codex bridge inert: retained-disabled",
            "Pallium Codex bridge inert: retained-no-host-pipe",
            "Pallium Codex bridge inert: retained-platform-disabled",
        }
        assert "inert-test-launcher-returned" in output


@pytest.mark.asyncio
async def test_outer_server_exception_is_not_suppressed_by_bridge_lifespan() -> None:
    server = MagicMock()
    with pytest.raises(RuntimeError, match="normal server failure"):
        async with mcp_server._codex_bridge_lifespan(server):
            raise RuntimeError("normal server failure")


def test_diagnostic_sink_errors_are_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    class ClosedSink:
        def write(self, _value: str) -> None:
            raise OSError("closed")

        def flush(self) -> None:
            raise ValueError("closed")

    monkeypatch.setattr(sys, "stderr", ClosedSink())
    mcp_server._bridge_diagnostic("test")
    codex_desktop_bridge._diagnostic("test")


async def _serve_protocol(server, action) -> None:
    client_to_server, server_input = anyio.create_memory_object_stream(0)
    server_to_client, client_input = anyio.create_memory_object_stream(0)
    server_task = asyncio.create_task(server._mcp_server.run(
        server_input,
        server_to_client,
        server._mcp_server.create_initialization_options(),
    ))
    try:
        async with ClientSession(client_input, client_to_server) as session:
            await session.initialize()
            await action(session)
    finally:
        await client_to_server.aclose()
        await asyncio.wait_for(server_task, timeout=2)




@pytest.mark.asyncio
async def test_protocol_eof_cancels_idle_task_without_capability_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def tracked_idle() -> None:
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(codex_desktop_bridge, "_idle", tracked_idle)
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", _FakeStatusClient)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "secret-capability-path")
    server = mcp_server.create_server(lifespan=mcp_server._codex_bridge_lifespan)

    async def call_status(session: ClientSession) -> None:
        await started.wait()
        response = await session.call_tool("pallium_status", {})
        assert not response.isError and json.loads(response.content[0].text) == {"status": "healthy"}

    await _serve_protocol(server, call_status)
    await asyncio.wait_for(stopped.wait(), timeout=1)
    assert "secret-capability-path" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_outer_cancellation_releases_cooperative_inert_task(monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def tracked_idle():
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(codex_desktop_bridge, "_idle", tracked_idle)

    async def server_lifetime():
        async with mcp_server._codex_bridge_lifespan(None):
            await asyncio.Future()

    task = asyncio.create_task(server_lifetime())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["inert", "inventory"])
async def test_http_mcp_keeps_catalog_and_tools_bridge_free(monkeypatch, mode):
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", mode)
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private-capability-sentinel")
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", _FakeStatusClient)
    original_import = mcp_server.importlib.import_module

    def deny_bridge_import(name, *args, **kwargs):
        assert name != "app.mcp.codex_desktop_bridge"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(mcp_server.importlib, "import_module", deny_bridge_import)
    server = mcp_server.create_server(host="localhost")
    assert server.settings.lifespan is None
    # Keep ASGI tests independent of the SSE dependency's process-wide shutdown watcher.
    server.settings.json_response = True
    app = server.streamable_http_app()
    expected = [tool.model_dump() for tool in await server.list_tools()]

    with anyio.fail_after(5):
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                async with streamable_http_client("http://localhost:8001/mcp",
                        http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        actual = await session.list_tools()
                        assert [tool.model_dump() for tool in actual.tools] == expected
                        result = await session.call_tool("pallium_status", {})
                        assert not result.isError
                        assert json.loads(result.content[0].text) == {"status": "healthy"}


def _shadow_native(monkeypatch, *, fault=False, block=None):
    calls = []
    closed = threading.Event()

    class NativeClient:
        def __init__(self, path, stop_event):
            assert threading.current_thread() is not threading.main_thread()
            calls.append(("connect", str(path)))
            self.stop_event = stop_event

        def enroll(self, metadata):
            calls.append(("enroll", metadata))
            if block is not None:
                block.wait(5)
            if fault:
                raise RuntimeError("private-native-fault")
            return {"mode": "shadow", "status": "enrolled", "reason": "ok", "ttl_seconds": 15,
                    "policy": "private-policy", "handle": "private-handle"}

        def status(self):
            calls.append(("status", None))
            return {"status": "eligible", "reason": "observed", "ttl_seconds": 10}

        def renew(self):
            calls.append(("renew", None))
            return {"status": "held", "reason": "observed", "ttl_seconds": 15}

        def close(self):
            calls.append(("close", None))
            closed.set()

    monkeypatch.setitem(sys.modules, "app.codex_bridge_pipe", SimpleNamespace(
        native_available=lambda: True, NativeShadowClient=NativeClient))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private-desktop-capability")
    monkeypatch.setenv("PALLIUM_CODEX_SHADOW_BOOTSTRAP_FILE", "private-bootstrap")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", _FakeStatusClient)
    return calls, closed


def test_shadow_eligibility_requires_explicit_windows_stdio_native(monkeypatch):
    _shadow_native(monkeypatch)
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "shadow")
    monkeypatch.setattr(mcp_server.sys, "platform", "linux")
    assert not mcp_server._codex_shadow_enabled("stdio")
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    assert mcp_server._codex_shadow_enabled("stdio")
    assert not mcp_server._codex_shadow_enabled("streamable-http")
    assert not mcp_server._codex_shadow_enabled("sse")
    for variable in ("PALLIUM_CODEX_SHADOW_BOOTSTRAP_FILE", "CODEX_APP_TOOLS_PIPE_PATH",
                     "PALLIUM_AGENT_REF", "PALLIUM_CODEX_BRIDGE_MODE"):
        with monkeypatch.context() as context:
            context.delenv(variable)
            assert not mcp_server._codex_shadow_enabled("stdio")
    monkeypatch.setitem(sys.modules, "app.codex_bridge_pipe", SimpleNamespace(native_available=lambda: False))
    assert not mcp_server._codex_shadow_enabled("stdio")


def test_main_passes_explicit_shadow_flag_only_when_eligible(monkeypatch):
    _shadow_native(monkeypatch)
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "shadow")
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    captured = {}
    fake = MagicMock()
    def create(**kwargs):
        captured.update(kwargs)
        return fake
    monkeypatch.setattr(mcp_server, "create_server", create)
    mcp_server.main()
    assert captured["codex_shadow"] is True
    assert captured["lifespan"] is mcp_server._codex_shadow_lifespan
    captured.clear()
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "streamable-http")
    mcp_server.main()
    assert "codex_shadow" not in captured and "lifespan" not in captured


@pytest.mark.asyncio
async def test_shadow_protocol_catalog_current_controller_and_eof(monkeypatch):
    calls, closed = _shadow_native(monkeypatch)
    server = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)
    baseline = mcp_server.create_server()
    expected = [tool.model_dump() for tool in await baseline.list_tools()]
    pair = {"threadId": "任务-α", "turnId": "turn-1"}

    async def exercise(session):
        tools = (await session.list_tools()).tools
        optional = [tool for tool in tools if tool.name.startswith("pallium_codex_bridge_shadow_")]
        assert len(optional) == 2
        assert all(tool.inputSchema.get("properties", {}) == {} for tool in optional)
        assert [tool.model_dump() for tool in tools if tool not in optional] == expected
        async def invoke(operation, meta):
            reply = await session.call_tool("pallium_codex_bridge_shadow_" + operation, {}, meta=meta)
            assert not reply.isError
            return json.loads(reply.content[0].text)
        assert (await invoke("status", pair))["reason"] == "not-enrolled"
        assert calls == []
        assert (await invoke("enroll", pair))["status"] == "enrolled"
        assert calls[1] == ("enroll", {"thread_ref": "任务-α", "turn_ref": "turn-1"})
        assert (await invoke("status", {"threadId": "other", "turnId": "turn-1"}))["reason"] == "wrong-controller"
        assert (await invoke("status", {"threadId": "任务-α", "turnId": "turn-2"}))["status"] == "eligible"
        assert (await invoke("status", None))["reason"] == "invalid-metadata"
        result = await invoke("status", {"x-codex-turn-metadata": {
            "thread_id": "任务-α", "session_id": "任务-α", "turn_id": "turn-1"}})
        assert result == {"mode": "shadow", "status": "eligible", "reason": "observed", "ttl_seconds": 10}
        assert not (await session.call_tool("pallium_status", {})).isError
    await _serve_protocol(server, exercise)
    assert closed.is_set()
    assert calls[-1] == ("close", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {}, {"threadId": "t"}, {"turnId": "u"},
    {"threadId": "t", "turnId": ""}, {"threadId": "t", "turnId": " u"},
    {"threadId": "t", "turnId": "\n"}, {"threadId": "t", "turnId": "u" * 256},
    {"threadId": "t", "turnId": 1}, {"threadId": "t", "turnId": []},
    {"threadId": "t", "turnId": "u", "x-codex-turn-metadata": {"turn_id": "v"}},
    {"threadId": "t", "turnId": "u", "x-codex-turn-metadata": {"session_id": "other"}},
    {"threadId": "t", "turnId": "u", "x-codex-turn-metadata": []}])
async def test_shadow_protocol_metadata_denies_without_native_access(monkeypatch, meta):
    calls, _ = _shadow_native(monkeypatch)
    monkeypatch.setenv("PALLIUM_THREAD_REF", "t")
    monkeypatch.setenv("CODEX_THREAD_ID", "t")
    server = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)
    async def exercise(session):
        for operation in ("enroll", "status"):
            response = await session.call_tool("pallium_codex_bridge_shadow_" + operation, {}, meta=meta)
            assert json.loads(response.content[0].text)["reason"] == "invalid-metadata"
        assert calls == []
    await _serve_protocol(server, exercise)


@pytest.mark.asyncio
async def test_shadow_protocol_native_fault_is_terminal_and_normal_tools_live(monkeypatch):
    calls, closed = _shadow_native(monkeypatch, fault=True)
    server = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)
    async def exercise(session):
        meta = {"threadId": "t", "turnId": "u"}
        normal, shadow = await asyncio.gather(session.call_tool("pallium_status", {}),
            session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta))
        assert not normal.isError and json.loads(normal.content[0].text)["status"] == "healthy"
        assert json.loads(shadow.content[0].text)["reason"] == "native-failed"
        again = await session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta)
        assert json.loads(again.content[0].text)["reason"] == "stopped"
        assert sum(operation == "enroll" for operation, _ in calls) == 1
    await _serve_protocol(server, exercise)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_shadow_native_cancellation_and_shutdown_are_bounded(monkeypatch):
    release = threading.Event()
    calls, closed = _shadow_native(monkeypatch, block=release)
    worker = codex_desktop_bridge.ShadowWorker(Path("private-bootstrap"))
    task = asyncio.create_task(worker.request("enroll", {"thread_ref": "t", "turn_ref": "u"}))
    try:
        while len(calls) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        before = time.monotonic()
        await worker.stop()
        assert time.monotonic() - before < 0.75
        assert not closed.is_set()
        assert (await worker.request("enroll", {"thread_ref": "t", "turn_ref": "u"}))["reason"] == "stopped"
    finally:
        release.set()
        await worker.stop()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_shadow_protocol_max_identity_and_capability_removal_stop(monkeypatch):
    calls, closed = _shadow_native(monkeypatch)
    server = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)
    meta = {"threadId": "t" * 255, "turnId": "u" * 255}
    async def exercise(session):
        enrolled = await session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta)
        assert json.loads(enrolled.content[0].text)["status"] == "enrolled"
        monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
        status = await session.call_tool("pallium_codex_bridge_shadow_status", {}, meta=meta)
        assert json.loads(status.content[0].text)["reason"] == "stopped"
        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "returned-capability")
        again = await session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta)
        assert json.loads(again.content[0].text)["reason"] == "stopped"
        assert sum(operation == "enroll" for operation, _ in calls) == 1
    await _serve_protocol(server, exercise)
    assert closed.is_set()


def test_shadow_public_output_never_exposes_private_native_fields():
    assert codex_desktop_bridge.public_status({"mode": "private-mode", "status": "private-status",
        "reason": "private-policy-token", "ttl_seconds": 301, "policy": "private-policy",
        "handle": "private-handle", "path": "private-path"}) == {"mode": "shadow", "status": "unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "renew"])
async def test_shadow_unavailable_evidence_ends_authority_without_rearming(monkeypatch, operation):
    calls, closed = _shadow_native(monkeypatch)
    native_client = sys.modules["app.codex_bridge_pipe"].NativeShadowClient
    now = [0.0]
    monkeypatch.setattr(codex_desktop_bridge, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def unavailable(_self):
        calls.append((operation, None))
        return {"status": "unavailable", "reason": "evidence-unavailable", "ttl_seconds": 10}

    monkeypatch.setattr(native_client, operation, unavailable)
    server = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)
    meta = {"threadId": "controller", "turnId": "current-turn"}

    async def exercise(session):
        enrolled = await session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta)
        assert json.loads(enrolled.content[0].text)["status"] == "enrolled"
        if operation == "status":
            response = await session.call_tool("pallium_codex_bridge_shadow_status", {}, meta=meta)
            assert json.loads(response.content[0].text)["reason"] == "evidence-unavailable"
        else:
            now[0] = 6.0
        with anyio.fail_after(1):
            while not closed.is_set():
                await asyncio.sleep(.01)
        status = await session.call_tool("pallium_codex_bridge_shadow_status", {}, meta=meta)
        again = await session.call_tool("pallium_codex_bridge_shadow_enroll", {}, meta=meta)
        assert json.loads(status.content[0].text)["reason"] == "stopped"
        assert json.loads(again.content[0].text)["reason"] == "stopped"
        assert sum(call == "enroll" for call, _ in calls) == 1
        assert not (await session.call_tool("pallium_status", {})).isError

    await _serve_protocol(server, exercise)
    fresh = mcp_server.create_server(codex_shadow=True, lifespan=mcp_server._codex_shadow_lifespan)

    async def reenroll(session):
        reply = await session.call_tool("pallium_codex_bridge_shadow_enroll", {},
            meta={"threadId": "controller", "turnId": "fresh-turn"})
        assert json.loads(reply.content[0].text)["status"] == "enrolled"
        assert sum(call == "enroll" for call, _ in calls) == 2

    await _serve_protocol(fresh, reenroll)


@pytest.mark.parametrize("status", ["enrolled", "eligible", "held", "inactive", "unavailable"])
@pytest.mark.parametrize("reason", ["ok", "observed", "evidence-unavailable", "closed", "not-enrolled"])
def test_shadow_public_output_preserves_exact_native_vocabulary(status, reason):
    assert codex_desktop_bridge.public_status({"status": status, "reason": reason, "ttl_seconds": 15}) == {
        "mode": "shadow", "status": status, "reason": reason, "ttl_seconds": 15}


def _inventory_native(monkeypatch, *, fault=None, block=None):
    calls = []
    disposed = threading.Event()

    class NativeClient:
        def __init__(self, path, stop):
            assert threading.current_thread() is not threading.main_thread()
            calls.append("connect")
            self.stop = stop

        def ready(self):
            calls.append("ready")
            if fault == "ready":
                raise RuntimeError("private-native-sentinel")
            return {"status": "ready", "reason": "ready"}

        def register(self, metadata):
            assert metadata == INVENTORY_CALLER
            calls.append("register")
            if block is not None:
                block.wait(5)
            if fault == "register":
                raise RuntimeError("private-native-sentinel")
            return {"status": "registered", "reason": "ok", "ttl_seconds": 12,
                    "connected": True, "endpoint": "private-capability-sentinel",
                    "inventory": "private-inventory-sentinel"}

        def dispose(self):
            calls.append("dispose")
            disposed.set()

    monkeypatch.setitem(sys.modules, "app.codex_bridge_pipe", SimpleNamespace(
        native_available=lambda: True, NativeInventoryClient=NativeClient))
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "inventory")
    monkeypatch.setenv("PALLIUM_CODEX_INVENTORY_BOOTSTRAP_FILE", "private-bootstrap")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private-capability-sentinel")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", _FakeStatusClient)
    return calls, disposed


def test_inventory_gate_is_separate_and_only_eligible_stdio(monkeypatch):
    _inventory_native(monkeypatch)
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    assert mcp_server._codex_inventory_enabled("stdio")
    assert not mcp_server._codex_shadow_enabled("stdio")
    for transport in ("sse", "streamable-http"):
        assert not mcp_server._codex_inventory_enabled(transport)
    for name, value in (
        ("PALLIUM_CODEX_BRIDGE_MODE", "off"), ("PALLIUM_CODEX_BRIDGE_MODE", "shadow"),
        ("PALLIUM_CODEX_BRIDGE_MODE", "inert"), ("PALLIUM_AGENT_REF", "claude"),
        ("PALLIUM_CODEX_INVENTORY_BOOTSTRAP_FILE", ""),
    ):
        with monkeypatch.context() as context:
            context.setenv(name, value)
            assert not mcp_server._codex_inventory_enabled("stdio")
    with monkeypatch.context() as context:
        context.delenv("CODEX_APP_TOOLS_PIPE_PATH")
        assert not mcp_server._codex_inventory_enabled("stdio")
    monkeypatch.setattr(mcp_server.sys, "platform", "linux")
    assert not mcp_server._codex_inventory_enabled("stdio")
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "app.codex_bridge_pipe", SimpleNamespace(native_available=lambda: False))
    assert not mcp_server._codex_inventory_enabled("stdio")


@pytest.mark.asyncio
async def test_inventory_gate_checks_presence_without_reading_capability(monkeypatch):
    _inventory_native(monkeypatch)
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")

    class PresenceOnly(dict):
        def get(self, key, *args):
            assert key != "CODEX_APP_TOOLS_PIPE_PATH"
            return super().get(key, *args)

        def __getitem__(self, key):
            assert key != "CODEX_APP_TOOLS_PIPE_PATH"
            return super().__getitem__(key)

    environment = PresenceOnly(mcp_server.os.environ)
    environment["CODEX_APP_TOOLS_PIPE_PATH"] = ""
    monkeypatch.setattr(mcp_server.os, "environ", environment)
    assert mcp_server._codex_inventory_enabled("stdio")
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)

    async def exercise(session):
        reply = await session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META)
        assert json.loads(reply.content[0].text)["status"] == "registered"

    await _serve_protocol(server, exercise)


def test_inventory_main_catalog_flag_is_not_forwarded_to_http(monkeypatch):
    _inventory_native(monkeypatch)
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    captured = {}
    monkeypatch.setattr(mcp_server, "create_server", lambda **options: (
        captured.update(options) or MagicMock()))
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    mcp_server.main()
    assert captured["codex_inventory"] is True
    assert captured["lifespan"] is mcp_server._codex_inventory_lifespan
    assert "private-capability-sentinel" not in repr(captured)
    captured.clear()
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "streamable-http")
    mcp_server.main()
    assert "codex_inventory" not in captured and "lifespan" not in captured


@pytest.mark.asyncio
async def test_inventory_caller_catalog_ready_register_and_eof(monkeypatch):
    calls, disposed = _inventory_native(monkeypatch)
    baseline = [tool.model_dump() for tool in await mcp_server.create_server().list_tools()]
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)

    async def exercise(session):
        tools = (await session.list_tools()).tools
        optional = [tool for tool in tools if tool.name == "pallium_codex_bridge_inventory_register"]
        assert len(optional) == 1 and optional[0].inputSchema.get("properties", {}) == {}
        assert [tool.model_dump() for tool in tools if tool not in optional] == baseline
        with anyio.fail_after(1):
            while "ready" not in calls:
                await asyncio.sleep(.01)
        assert "register" not in calls
        # Runtime-owned caller metadata does not grant recipient or action authority.
        for _ in range(3):
            reply = await session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META)
            assert not reply.isError
            assert json.loads(reply.content[0].text) == {
                "mode": "inventory", "status": "registered", "reason": "ok",
                "ttl_seconds": 12, "connected": True}
        assert not (await session.call_tool("pallium_status", {})).isError
    await _serve_protocol(server, exercise)
    assert disposed.is_set() and calls == ["connect", "ready", "register", "register", "register", "dispose"]


@pytest.mark.asyncio
async def test_inventory_register_binds_runtime_owned_caller_pair(monkeypatch):
    calls, _ = _inventory_native(monkeypatch)
    native = sys.modules["app.codex_bridge_pipe"].NativeInventoryClient
    captured = []

    def register(self, metadata):
        captured.append(metadata)
        calls.append("register")
        return {"status": "registered", "reason": "ok", "ttl_seconds": 12,
                "connected": True}

    monkeypatch.setattr(native, "register", register)
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)

    async def exercise(session):
        reply = await session.call_tool("pallium_codex_bridge_inventory_register", {},
                                        meta={"threadId": "source-chat", "turnId": "source-turn"})
        assert json.loads(reply.content[0].text)["status"] == "registered"

    await _serve_protocol(server, exercise)
    assert captured == [{"thread_ref": "source-chat", "turn_ref": "source-turn"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {}, {"threadId": "source-chat"},
    {"turnId": "source-turn"}, {"threadId": "source-chat", "turnId": ""},
    {"threadId": "source-chat", "turnId": " source-turn"},
    {"threadId": "source-chat", "turnId": "source-turn\n"},
    {"threadId": "source-chat", "turnId": "x" * 256},
    {"threadId": "source-chat", "turnId": 1},
    {"threadId": "source-chat", "turnId": "source-turn",
     "x-codex-turn-metadata": {"turn_id": "other-turn"}},
    {"threadId": "source-chat", "turnId": "source-turn",
     "x-codex-turn-metadata": {"session_id": "other-chat"}}])
async def test_inventory_register_without_runtime_turn_denies_before_private_transfer(monkeypatch, meta):
    calls, _ = _inventory_native(monkeypatch)
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)

    async def exercise(session):
        reply = await session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=meta)
        result = json.loads(reply.content[0].text)
        assert result["status"] == "unavailable"
        assert result["reason"] == ("native-failed" if meta is None else "stopped")

    await _serve_protocol(server, exercise)
    assert "register" not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["ready", "register"])
async def test_inventory_native_failure_keeps_caller_tools_live_and_no_reconnect(monkeypatch, capsys, fault):
    calls, disposed = _inventory_native(monkeypatch, fault=fault)
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)
    async def exercise(session):
        if fault == "ready":
            with anyio.fail_after(1):
                while not disposed.is_set():
                    await asyncio.sleep(.01)
        normal, optional = await asyncio.gather(
            session.call_tool("pallium_status", {}),
            session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META))
        assert not normal.isError and json.loads(normal.content[0].text)["status"] == "healthy"
        assert json.loads(optional.content[0].text)["status"] == "unavailable"
        again = await session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META)
        assert json.loads(again.content[0].text)["reason"] == "stopped"
        assert calls.count("connect") == 1
    await _serve_protocol(server, exercise)
    assert disposed.is_set()
    assert "private-" not in repr(capsys.readouterr())


@pytest.mark.asyncio
async def test_inventory_concurrent_caller_is_busy_without_blocking_normal_tool(monkeypatch):
    release = threading.Event()
    calls, disposed = _inventory_native(monkeypatch, block=release)
    server = mcp_server.create_server(codex_inventory=True, lifespan=mcp_server._codex_inventory_lifespan)
    async def exercise(session):
        first = asyncio.create_task(session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META))
        try:
            with anyio.fail_after(1):
                while "register" not in calls:
                    await asyncio.sleep(.01)
            normal, second = await asyncio.gather(
                session.call_tool("pallium_status", {}),
                session.call_tool("pallium_codex_bridge_inventory_register", {}, meta=INVENTORY_META))
            assert not normal.isError
            assert json.loads(second.content[0].text)["reason"] == "busy"
            assert calls.count("register") == 1
        finally:
            release.set()
            await first
    await _serve_protocol(server, exercise)
    assert disposed.is_set()


@pytest.mark.asyncio
async def test_inventory_cancellation_shutdown_and_capability_loss_are_terminal(monkeypatch):
    release = threading.Event()
    calls, disposed = _inventory_native(monkeypatch, block=release)
    worker = codex_desktop_bridge.InventoryWorker(Path("private-bootstrap"))
    task = asyncio.create_task(worker.register(INVENTORY_CALLER))
    try:
        with anyio.fail_after(1):
            while "register" not in calls:
                await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        before = time.monotonic()
        await worker.stop()
        assert time.monotonic() - before < .75 and not disposed.is_set()
        assert (await worker.register(INVENTORY_CALLER))["reason"] == "stopped"
    finally:
        release.set()
        await worker.stop()
    assert disposed.is_set() and calls.count("connect") == 1
    calls, disposed = _inventory_native(monkeypatch)
    fresh = codex_desktop_bridge.InventoryWorker(Path("private-bootstrap"))
    try:
        assert (await fresh.register(INVENTORY_CALLER))["status"] == "registered"
        monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
        assert (await fresh.register(INVENTORY_CALLER))["reason"] == "stopped"
        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "returned-capability")
        assert (await fresh.register(INVENTORY_CALLER))["reason"] == "stopped"
    finally:
        await fresh.stop()
    assert disposed.is_set() and calls.count("register") == 1


@pytest.mark.parametrize("value", [None, [], {"status": [], "reason": {}, "ttl_seconds": True},
    {"status": "private", "reason": "private", "ttl_seconds": 301, "connected": "yes",
     "endpoint": "private", "tools": ["private"]}])
def test_inventory_redaction_rejects_partial_invalid_and_private_values(value):
    assert codex_desktop_bridge.inventory_status(value) == {"mode": "inventory", "status": "unavailable"}


_INVENTORY_STDIO_CHILD = dedent(r'''
    import asyncio
    import os
    import sys
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from app.mcp import server as m
    class NativeClient:
        def __init__(self, path, stop): pass
        def ready(self): return {"status": "ready", "reason": "ready"}
        def register(self, metadata):
            assert metadata == {"thread_ref": "source-chat", "turn_ref": "source-turn"}
            if os.environ["TEST_BRIDGE_FAILURE"] == "register":
                raise RuntimeError("private-native-sentinel")
            return {"status": "registered", "reason": "ok", "connected": True,
                    "endpoint": "private-capability-sentinel"}
        def dispose(self): pass
    sys.modules["app.codex_bridge_pipe"] = SimpleNamespace(
        native_available=lambda: True, NativeInventoryClient=NativeClient)
    failure = os.environ["TEST_BRIDGE_FAILURE"]
    if failure == "import":
        original_import = m.importlib.import_module
        def injected_import(name, package=None):
            if name == "app.mcp.codex_desktop_bridge":
                raise RuntimeError("private-import-sentinel")
            return original_import(name, package)
        m.importlib = SimpleNamespace(import_module=injected_import)
    elif failure in ("startup", "startup-timeout", "shutdown", "shutdown-timeout"):
        from app.mcp import codex_desktop_bridge as bridge
        @asynccontextmanager
        async def injected(server):
            if failure.startswith("startup"):
                if failure.endswith("timeout"):
                    await asyncio.Future()
                raise RuntimeError("private-startup-sentinel")
            yield {}
            if failure.endswith("timeout"):
                await asyncio.Future()
            raise RuntimeError("private-shutdown-sentinel")
        bridge.inventory_lifespan = injected
    class FakeClient:
        def __init__(self, ctx): pass
        async def get_status(self): return {"status": "healthy"}
    m.PalliumMcpClient = FakeClient
    m.main()
    print("inventory-test-launcher-returned", file=sys.stderr, flush=True)
''')


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="Windows inventory stdio mode")
@pytest.mark.parametrize("failure", ["none", "register", "import", "startup", "startup-timeout",
    "shutdown", "shutdown-timeout"])
async def test_inventory_real_stdio_caller_and_eof_do_not_leak_native_capability(failure):
    params = _stdio_params(failure, mode="inventory")
    params.args = ["-c", _INVENTORY_STDIO_CHILD]
    params.env["PALLIUM_CODEX_INVENTORY_BOOTSTRAP_FILE"] = "private-bootstrap"
    with _stdio_error_log() as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                optional = [tool for tool in (await session.list_tools()).tools
                    if tool.name.startswith("pallium_codex_bridge_")]
                assert [tool.name for tool in optional] == ["pallium_codex_bridge_inventory_register"]
                assert optional[0].inputSchema.get("properties", {}) == {}
                normal, registered = await asyncio.gather(
                    session.call_tool("pallium_status", {}),
                    session.call_tool(optional[0].name, {}, meta=INVENTORY_META))
                assert not normal.isError and not registered.isError
                body = json.loads(registered.content[0].text)
                assert body["status"] == ("registered" if failure == "none" else "unavailable")
                assert "private-" not in registered.content[0].text
        log.seek(0)
        output = log.read()
    assert "inventory-test-launcher-returned" in output and "private-" not in output


@pytest.mark.parametrize("fault", ["start", "stop", None])
def test_optional_inventory_service_lifecycle_keeps_normal_http_healthy(monkeypatch, request, caplog, fault):
    from app import codex_bridge_pipe
    calls = []

    class Worker:
        def stop(self):
            calls.append("stop")
            if fault == "stop":
                raise RuntimeError("private-shutdown-sentinel")

    def start(*, trial_relay, trial_registry):
        assert trial_relay is not None and trial_registry is not None
        calls.append("start")
        if fault == "start":
            raise RuntimeError("private-startup-sentinel")
        return Worker()

    monkeypatch.setattr(codex_bridge_pipe, "start_inventory_service", start)
    with request.getfixturevalue("client") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/status").status_code == 200
        assert client.get("/debug/queue/health").status_code == 200
    assert calls == (["start"] if fault == "start" else ["start", "stop"])
    assert "private-" not in caplog.text
