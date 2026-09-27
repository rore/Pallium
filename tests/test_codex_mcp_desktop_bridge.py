"""Inert Codex MCP bridge eligibility and lifecycle coverage."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
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
    from app.mcp import server as m

    failure = os.environ["TEST_BRIDGE_FAILURE"]
    if failure == "import":
        original_import = m.importlib.import_module
        def injected_import(name):
            if name == "app.mcp.codex_desktop_bridge":
                raise RuntimeError("secret import failure")
            return original_import(name)
        m.importlib.import_module = injected_import
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
                    await asyncio.Future()
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
    print("inert-test-launcher-returned", file=__import__("sys").stderr, flush=True)
    '''
)


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
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as error_log:
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
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as error_log:
        async with stdio_client(params, errlog=error_log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert any(tool.name == "pallium_status" for tool in catalog.tools)
                result = await session.call_tool("pallium_status", {})
                assert not result.isError and json.loads(result.content[0].text) == {"status": "healthy"}
        error_log.seek(0)
        output = error_log.read()
        assert "Pallium Codex bridge inert:" not in output
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
async def test_http_mcp_keeps_catalog_and_tools_bridge_free(monkeypatch):
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", "inert")
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
