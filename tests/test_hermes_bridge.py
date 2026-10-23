"""Wire-compatibility coverage for the Hermes-owned MCP bridge."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from integrations.hermes.mcp_bridge import (
    HISTORY_TOOLS,
    MAX_RESPONSE_CHARS,
    MEMORY_TOOLS,
    TOOLS,
    _tool_catalog,
    _tool_response_text,
)


class _Wire:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *, mode, by_alias):
        assert mode == "json" and by_alias is True
        return self.data


def _catalog_wire(*, memory_enabled=False, **overrides):
    expected = TOOLS | (MEMORY_TOOLS if memory_enabled else frozenset())
    tools = [{
        "name": name,
        "description": "description",
        "inputSchema": {
            "type": "object",
            "properties": {
                "container_ref": {"type": "string"},
                "thread_ref": {"type": "string"},
                "query": {"type": "string"},
                "source_ref": {"type": "string"},
                "include_supported_memories": {"type": "boolean"},
            },
            "required": ["container_ref", "query"],
        },
    } for name in sorted(expected)]
    result = {"tools": tools, "nextCursor": None}
    result.update(overrides)
    return result


def test_catalog_reads_wire_aliases_and_hides_trusted_fields() -> None:
    catalog = _tool_catalog(_Wire(_catalog_wire(resultType="complete")))
    assert {tool["name"] for tool in catalog} == TOOLS
    history = next(tool for tool in catalog if tool["name"] in HISTORY_TOOLS)
    assert "container_ref" not in history["parameters"]["properties"]
    assert "thread_ref" not in history["parameters"]["properties"]
    assert history["parameters"]["required"] == ["query"]
    assert history["parameters"]["additionalProperties"] is False


def test_memory_catalog_is_opt_in_and_keeps_source_forget_target_visible() -> None:
    with pytest.raises(ValueError):
        _tool_catalog(_Wire(_catalog_wire(memory_enabled=True)))
    catalog = _tool_catalog(_Wire(_catalog_wire(memory_enabled=True)), memory_enabled=True)
    assert {tool["name"] for tool in catalog} == TOOLS | MEMORY_TOOLS
    remember = next(tool for tool in catalog if tool["name"] == "pallium_remember")
    assert not {"container_ref", "actor_ref", "thread_ref"} & remember["parameters"]["properties"].keys()
    forget_source = next(tool for tool in catalog if tool["name"] == "pallium_forget_source")
    assert "thread_ref" in forget_source["parameters"]["properties"]
    flag = next(tool for tool in catalog if tool["name"] == "pallium_flag_memory")
    assert "source_ref" not in flag["parameters"]["properties"]
    expand_source = next(tool for tool in catalog if tool["name"] == "pallium_expand_source")
    assert "include_supported_memories" in expand_source["parameters"]["properties"]


@pytest.mark.parametrize("wire", [
    {"tools": [], "next_cursor": None},  # SDK field names must be read from the public wire aliases.
    _catalog_wire(nextCursor="page-2"),
    _catalog_wire(resultType="partial"),
    _catalog_wire(tools=[{"name": "pallium_unapproved", "inputSchema": {"type": "object"}}]),
    _catalog_wire(tools=[{"name": "pallium_relay_address", "inputSchema": {"type": "array"}}]),
    _catalog_wire(tools=[{"name": "pallium_relay_address", "inputSchema": {
        "type": "object", "properties": {}, "required": ["missing"],
    }}]),
    _catalog_wire(tools=[
        {"name": "pallium_relay_address", "inputSchema": {"type": "object"}}
        for _ in range(len(TOOLS))
    ]),
])
def test_catalog_rejects_incomplete_or_malformed_wire_data(wire) -> None:
    with pytest.raises(ValueError):
        _tool_catalog(_Wire(wire))


def test_catalog_allows_optional_cursor_but_rejects_snake_case_alias() -> None:
    optional = _catalog_wire()
    del optional["nextCursor"]
    assert {tool["name"] for tool in _tool_catalog(_Wire(optional))} == TOOLS

    wire = _catalog_wire()
    del wire["nextCursor"]
    wire["next_cursor"] = None
    with pytest.raises(ValueError):
        _tool_catalog(_Wire(wire))


def test_tool_response_uses_wire_error_alias_and_redacts_private_error_text() -> None:
    secret = "receipt-should-never-cross-the-bridge"
    refused = _tool_response_text(_Wire({
        "content": [{"type": "text", "text": secret}],
        "isError": True,
        "resultType": "complete",
    }))
    assert "refused" in json.loads(refused)["error"]
    assert secret not in refused

    successful = _tool_response_text(_Wire({
        "content": [{"type": "text", "text": "ok"}], "isError": False,
    }))
    assert successful == "ok"


@pytest.mark.parametrize("wire", [
    {"content": [{"type": "text", "text": "ok"}], "is_error": False},
    {"content": [{"type": "image", "data": "private"}], "isError": False},
    {"content": [{"type": "text", "text": "x" * (MAX_RESPONSE_CHARS + 1)}], "isError": False},
    {"content": [{"type": "text", "text": "receipt"}], "isError": False,
     "resultType": "incomplete"},
])
def test_tool_response_rejects_wrong_alias_or_unsupported_envelope(wire) -> None:
    result = _tool_response_text(_Wire(wire))
    assert "error" in json.loads(result)


class _RelayProxy(BaseHTTPRequestHandler):
    calls: list[tuple[str, dict]] = []
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        with self.lock:
            self.calls.append((parsed.path, query))
        session = query.get("session_ref", [""])[0]
        rows = ([{
            "runtime": query.get("runtime", [""])[0],
            "session_ref": session,
            "endpoint_id": "relay-session-0123456789abcdef0123456789abcdef",
            "alias": None,
        }] if parsed.path == "/relay/sessions" and session else [])
        raw = json.dumps(rows).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        return


_BRIDGE_PROBE = r'''
import asyncio, json, sys
from importlib.metadata import version
from integrations.hermes.mcp_bridge import RelayMcpBridge

config = json.loads(sys.argv[1])
dynamic = config.get("scope_mode") == "session"
bridge = RelayMcpBridge(
    python=config["pallium_python"], repo=config["repo"],
    base_url=config["base_url"], container_ref=None if dynamic else config["container_ref"],
    actor_ref=None if dynamic else "bridge-test-actor", visibility="private",
    memory_enabled=config.get("memory_enabled", False),
)
try:
    names = sorted(tool["name"] for tool in bridge.catalog)
    scope = {"scope": {"container_ref": config["container_ref"], "actor_ref": "bridge-test-actor"}} if dynamic else {}
    address = json.loads(bridge.call("pallium_relay_address", {}, (config["session"], "turn-real"), **scope))
    missing = json.loads(bridge.call("pallium_relay_address", {}, None))
    async def refused_missing_metadata():
        return await bridge._call("pallium_relay_address", {}, {})
    refused = asyncio.run_coroutine_threadsafe(refused_missing_metadata(), bridge._loop).result(timeout=10)
    print(json.dumps({"mcp_version": version("mcp"), "names": names,
                      "catalog": bridge.catalog, "address": address,
                      "missing": missing, "refused": refused}))
finally:
    bridge.close()
'''


def _run_owned_process(command, *, cwd, env, timeout):
    process = subprocess.Popen(
        command, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=10, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=10)
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_bridge_probe(host_python: Path, config: str, repo: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH"))))
    try:
        return _run_owned_process(
            [str(host_python), "-c", _BRIDGE_PROBE, config], cwd=repo, env=env, timeout=45,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"Hermes bridge probe timed out; stdout={exc.output!r}, stderr={exc.stderr!r}"
        ) from None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup check")
@pytest.mark.slow
def test_probe_timeout_terminates_its_owned_child_group(tmp_path: Path) -> None:
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        "print(child.pid,flush=True); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired) as timeout:
        _run_owned_process([sys.executable, "-c", script], cwd=tmp_path,
                           env=os.environ.copy(), timeout=5)
    child_pid = int(timeout.value.output.strip().splitlines()[0])
    assert child_pid > 0
    # The child inherits both pipes: EOF proves it no longer holds either open.
    assert timeout.value.timeout == 5


@pytest.mark.parametrize("host_kind", ["sdk1", "sdk2"])
@pytest.mark.parametrize("memory_enabled", [False, True])
@pytest.mark.parametrize("scope_mode", ["fixed", "session"])
def test_bridge_stdio_call_on_supported_sdk(host_kind, memory_enabled, scope_mode) -> None:
    configured_host = os.environ.get("HERMES_BRIDGE_HOST_PYTHON") if host_kind == "sdk2" else None
    if host_kind == "sdk2" and not configured_host:
        pytest.skip("Set HERMES_BRIDGE_HOST_PYTHON to a disposable Hermes SDK2 interpreter")
    host_python = Path(configured_host) if configured_host else Path(sys.executable)
    if not host_python.is_file():
        pytest.fail(f"Configured bridge interpreter is missing: {host_python}")
    if host_kind == "sdk2" and not configured_host:
        pytest.skip("SDK2 bridge host was not configured")
    _RelayProxy.calls = []
    session = f"bridge-{host_kind}-session"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayProxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    repo = str(Path(__file__).resolve().parents[1])
    config = json.dumps({
        "pallium_python": sys.executable,
        "repo": repo,
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "container_ref": "git:test/hermes-bridge",
        "session": session,
        "memory_enabled": memory_enabled,
        "scope_mode": scope_mode,
    })
    try:
        completed = _run_bridge_probe(host_python, config, repo)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["mcp_version"].startswith("1." if host_kind == "sdk1" else "2.")
    assert set(result["names"]) == TOOLS | (MEMORY_TOOLS if memory_enabled else frozenset())
    assert result["address"]["session_ref"] == session
    assert result["address"]["runtime"] == "hermes"
    assert "trusted session and turn" in result["missing"]["error"]
    assert "refused" in json.loads(result["refused"])["error"]
    assert "receipt-do-not-leak" not in result["refused"]
    address_queries = [query for path, query in _RelayProxy.calls if path == "/relay/sessions"]
    assert any(query.get("session_ref") == [session] for query in address_queries)
