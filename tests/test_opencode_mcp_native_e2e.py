"""Opt-in official 2.2.7 witness; no plugin, shared service or external provider."""

from __future__ import annotations

import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlparse

import pytest

pytest.importorskip("mcp")
from tests.test_opencode_mcp_e2e import (
    CONTAINER, WORK, _environment, _read_refs, _register, _remote_mcp, relay_http,
)

pytestmark = pytest.mark.slow


def _stop_process(process):
    if process.poll() is not None:
        return
    process.stdin.close()  # --stdio owns only this isolated server's lifetime.
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("codemode", [False, True], ids=["direct", "code-mode"])
def test_released_227_remote_mcp_identity(client, relay_http, tmp_path, monkeypatch, codemode):
    binary = os.environ.get("PALLIUM_OPENCODE_V2_BINARY")
    if not binary or not Path(binary).is_file():
        pytest.skip("set PALLIUM_OPENCODE_V2_BINARY to official 2.2.7; native acceptance remains unqualified")
    # Never let repo/parent policies or plugin discovery enter this native profile.
    scratch = tmp_path.resolve()
    assert not scratch.is_relative_to(Path("C:/Dev/rore").resolve()), "use an external --basetemp"
    assert not scratch.is_relative_to(Path(__file__).resolve().parents[1])
    workspace = scratch / "workspace"
    workspace.mkdir()
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
           if key in os.environ}
    for variable, name in {
        "HOME": "home", "USERPROFILE": "home", "APPDATA": "appdata",
        "LOCALAPPDATA": "localappdata", "PROGRAMDATA": "system",
        "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data", "XDG_CACHE_HOME": "cache",
        "XDG_STATE_HOME": "state", "TEMP": "temp", "TMP": "temp", "TMPDIR": "temp",
    }.items():
        path = scratch / name
        path.mkdir(exist_ok=True)
        env[variable] = str(path)
    env.update(OPENCODE_CONFIG_DIR=str(scratch / "config"),
               OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_MODELS_FETCH="1",
               OPENCODE_TEST_HOME=str(scratch / "home"), OPENCODE_DB=str(scratch / "data/native.db"),
               OPENCODE_PASSWORD="isolated-mcp-test")

    def cli(*args):
        result = subprocess.run([binary, *args], cwd=workspace, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    version = cli("--version")
    assert version == "opencode v2.2.7", f"native acceptance is release-specific, got {version!r}"
    # This command does not discover/start a service or open the database.
    paths = {name: cli("debug", "paths", name)
             for name in ("db", "home", "data", "config", "cache", "state", "tmp")}
    assert all(Path(path).resolve().is_relative_to(scratch) for path in paths.values()), paths

    provider_requests, provider_errors, emitted = [], [], threading.Event()
    provider_stage = [0]
    mcp_requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider_requests.append(body)
                assert body["model"] == "mock-model"
                names = {tool["function"]["name"] for tool in body.get("tools", [])}
                tool_calls = []
                if names and provider_stage[0] < (2 if codemode else 1):
                    provider_stage[0] += 1
                    emitted.set()
                    if codemode:
                        assert "execute" in names, names
                        code = ("return await search({namespace:'pallium',query:'relay',limit:100})"
                                if provider_stage[0] == 1 else
                                "return {address: await tools.pallium.pallium_relay_address({}), "
                                "attached: await tools.pallium.pallium_relay_attach_work_ref("
                                + json.dumps(WORK, ensure_ascii=False) + ")}")
                        requested = [("execute", {"code": code})]
                    else:
                        requested = [("pallium_pallium_relay_address", {}),
                                     ("pallium_pallium_relay_attach_work_ref", WORK)]
                        assert all(name in names for name, _ in requested), names
                    tool_calls = [{"index": i, "id": f"call_mcp_{provider_stage[0]}_{i}", "type": "function",
                                   "function": {"name": name, "arguments": json.dumps(args)}}
                                  for i, (name, args) in enumerate(requested)]
                delta = {"role": "assistant", **({"tool_calls": tool_calls} if tool_calls
                         else {"content": "isolated native MCP complete"})}
                chunks = [
                    {"id": "local", "object": "chat.completion.chunk", "created": 1,
                     "model": "mock-model", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"id": "local", "object": "chat.completion.chunk", "created": 1,
                     "model": "mock-model", "choices": [{"index": 0, "delta": {},
                         "finish_reason": "tool_calls" if tool_calls else "stop"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                ]
                raw = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                       + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except Exception as error:
                provider_errors.append(repr(error))
                self.send_error(500, "isolated provider assertion failed")

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    process = None
    logs = []
    base, backend_calls, _ = relay_http
    try:
        with ExitStack() as resources:
            mcp_url = resources.enter_context(_remote_mcp(monkeypatch, _environment(base), mcp_requests))
            config = {
                "$schema": "https://opencode.ai/config.json", "model": "mock/mock-model",
                "update": "disable", "share": "disabled", "snapshots": False, "plugins": [],
                "policies": [{"action": "provider.use", "resource": "*", "effect": "deny"},
                             {"action": "provider.use", "resource": "mock", "effect": "allow"}],
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
                "providers": {"mock": {"package": "@opencode/ai/providers/openai-compatible",
                    "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "local-only"},
                    "models": {"mock-model": {"limit": {"context": 32000, "output": 2000}}}}},
                "mcp": {"servers": {"pallium": {"type": "remote", "url": mcp_url,
                                               "oauth": False, "codemode": codemode}}},
            }
            config_path = scratch / "config/opencode.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            process = subprocess.Popen([binary, "serve", "--stdio", "--hostname", "127.0.0.1", "--port", "0"],
                cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            # Disconnect native clients before shutting down the MCP listener.
            resources.callback(_stop_process, process)
            output = queue.Queue()

            def read():
                for line in process.stdout:
                    logs.append(line)
                    output.put(line)

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            deadline = time.monotonic() + 40
            url = None
            while time.monotonic() < deadline:
                assert process.poll() is None, logs[-15:]
                try:
                    line = output.get(timeout=.2)
                except queue.Empty:
                    continue
                if line.startswith('{"url":'):
                    url = json.loads(line)["url"]
                    break
            assert url and url.startswith("http://127.0.0.1:"), logs[-15:]
            assert urlparse(url).port not in (19836, 28894)

            def api(method, path, body=None):
                auth = base64.b64encode(b"opencode:isolated-mcp-test").decode()
                request = Request(url + path, method=method,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={"Authorization": "Basic " + auth, "Content-Type": "application/json",
                             "x-opencode-directory": workspace.as_posix()})
                with urlopen(request, timeout=45) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None

            # Fail before any prompt if the released binary ignores isolation settings.
            info = api("GET", "/api/info")
            assert info["version"] == "2.2.7" and info["pid"] == process.pid, info
            entries = api("GET", "/api/config")
            assert entries and all(Path(entry["path"]).resolve().is_relative_to(scratch)
                                   for entry in entries if "path" in entry), entries
            documents = [entry["info"] for entry in entries if entry["type"] == "document"]
            assert any(document.get("model") == {"providerID": "mock", "model": "mock-model"}
                       for document in documents), entries
            assert all(not document.get("plugins") for document in documents), entries
            plugins = api("GET", "/api/plugin")["data"]
            assert all(plugin["source"]["type"] == "builtin" for plugin in plugins), plugins
            # Catalog listing settles provider initialization; an immediate exact
            # lookup can return 404 while the location's built-ins are starting.
            actual_providers = api("GET", "/api/provider")["data"]
            assert [entry["id"] for entry in actual_providers] == ["mock"], actual_providers
            actual_provider = actual_providers[0]
            assert actual_provider["package"] == config["providers"]["mock"]["package"]
            assert actual_provider["settings"]["baseURL"] == config["providers"]["mock"]["settings"]["baseURL"]
            assert not provider_requests, "preflight must happen before any model request"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                mcp_state = api("GET", "/api/mcp")["data"]
                if any(server["name"] == "pallium" and server["status"]["status"] == "connected"
                       for server in mcp_state):
                    break
                time.sleep(.05)
            else:
                pytest.fail(f"isolated MCP connection did not become ready: {mcp_state}")
            plugins = api("GET", "/api/plugin")["data"]
            assert all(plugin["source"]["type"] == "builtin" for plugin in plugins), plugins
            created = api("POST", "/api/session", {"location": {"directory": workspace.as_posix()},
                "title": "Isolated MCP witness"})["data"]
            session_id = created["id"]
            endpoint = _register(client, session_id)["endpoint_id"]
            api("POST", f"/api/session/{session_id}/prompt", {"text": "Check the isolated fixture.", "delivery": "queue"})
            api("POST", f"/api/experimental/session/{session_id}/wait")
            assert not provider_errors, provider_errors
            assert emitted.is_set(), "native host did not expose the expected tool surface"
            calls = [request["params"] for request in mcp_requests if request.get("method") == "tools/call"]
            assert {call["name"] for call in calls} == {"pallium_relay_address", "pallium_relay_attach_work_ref"}, calls
            assert all(call.get("_meta", {}).get("ai.opencode/sessionID") == session_id for call in calls), calls
            assert all(not {"session_ref", "thread_ref", "runtime"} & set(call.get("arguments", {})) for call in calls)
            rows = _read_refs(client, session_id)
            assert len(rows) == 1 and rows[0]["local_ref"] == WORK["local_ref"], rows
            identity_calls = [value for _, path, value in backend_calls if path == "/relay/sessions/work-refs/attach"]
            assert len(identity_calls) == 1
            assert identity_calls[0]["runtime"] == "opencode" and identity_calls[0]["session_ref"] == session_id
            context = api("GET", f"/api/session/{session_id}/context")["data"]
            assert endpoint in json.dumps(context), "native tool output must contain the exact backend address"
            assert any(endpoint in json.dumps(body) for body in provider_requests), "tool result never reached native continuation"
            (scratch / "native-mcp-evidence.json").write_text(json.dumps({"version": version,
                "codemode": codemode, "paths": paths, "config_entries": entries, "plugins": plugins,
                "provider": actual_provider, "session_id": session_id, "endpoint": endpoint,
                "mcp_calls": calls, "work_refs": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if process is not None:
            _stop_process(process)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=5)
        (scratch / "native-mcp.log").write_text("".join(logs), encoding="utf-8")
