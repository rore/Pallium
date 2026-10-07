"""Released OpenCode V2 + production plugin + real Pallium HTTP, local provider only."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

pytestmark = pytest.mark.slow


def test_released_native_idle_busy_and_reload(client, tmp_path, test_db_url):
    binary = os.environ.get("PALLIUM_OPENCODE_V2_BINARY")
    if not binary or not Path(binary).is_file():
        pytest.skip("set PALLIUM_OPENCODE_V2_BINARY to the released 2.0.22 executable")
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "remote", "add", "origin", "https://example.test/team/relay.git"], check=True)
    locations = [workspace / name for name in ("one", "two", "three")]
    for directory in locations:
        directory.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    subprocess.run(["git", "init", "-q", str(foreign)], check=True)
    subprocess.run(["git", "-C", str(foreign), "remote", "add", "origin", "https://example.test/team/foreign.git"], check=True)
    scope = {"container_ref": "git:example.test/team/relay"}
    requests = []
    release = threading.Event()
    release.set()
    entered = threading.Event()
    tool_emitted = threading.Event()
    service_unavailable = threading.Event()
    relay_client = [client]
    restored_client = []
    fail_context = threading.Event()
    failed_contexts = []
    ingested = []
    assistant_outputs = []

    class RelayHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if service_unavailable.is_set():
                self.send_error(503, "isolated test outage")
                return
            if self.path == "/relay/opencode/wake" and raw:
                body = json.loads(raw)
                if body["operation"] == "context" and fail_context.is_set():
                    fail_context.clear()
                    failed_contexts.append(body)
                    self.send_error(503, "isolated preclaim failure")
                    return
            response = relay_client[0].request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if self.path in ("/items", "/item-and-query") and response.is_success:
                body = json.loads(raw)
                result = response.json()
                ingested.extend(zip(body if isinstance(body, list) else [body], result if isinstance(result, list) else [result]))
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = forward

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            entered.set()
            assert release.wait(40), "provider not released"
            tool = "IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) and not tool_emitted.is_set()
            assistant_marker = f"NATIVE_ASSISTANT_שלום_{len(requests)}"
            if not tool:
                assistant_outputs.append((assistant_marker, body))
            if tool:
                tool_emitted.set()
                # ACK already happened before this model request. Rebuild the
                # complete Pallium app from the same SQLite database before the
                # tool resumes and the next native context hook runs.
                restarted = TestClient(create_app(AppConfig(
                    storage_backend="sqlite", sqlite_url=test_db_url,
                    default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
                    vector_index=VectorIndexConfig(enabled=False))))
                restored_client.append(restarted)
                relay_client[0] = restarted
            chunks = [
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_fixture", "type": "function", "function": {
                         "name": "execute", "arguments": '{"code":"return 1"}'}}
                 ]}, "finish_reason": None}]},
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ] if tool else [
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {
                     "role": "assistant", "content": assistant_marker}, "finish_reason": None}]},
                {"id": "local", "object": "chat.completion.chunk", "created": 1,
                 "model": "mock-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
            data = ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    relay = ThreadingHTTPServer(("localhost", 0), RelayHTTP)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    for server in (relay, provider):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("config", "data", "cache", "state", "home", "temp"):
        (tmp_path / name).mkdir()
    config = {
        "model": "mock/mock-model", "update": "disable", "share": "disabled", "snapshots": False,
        "plugins": [str(root / "integrations" / "opencode")],
        "providers": {"mock": {"package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "local-only"},
            "models": {"mock-model": {"limit": {"context": 32000, "output": 2000}}}}},
    }
    (tmp_path / "config" / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not (
        k.startswith(("PALLIUM_", "OPENCODE_")) or k.endswith("API_KEY"))}
    env.update({"PALLIUM_PORT": str(relay.server_port), "OPENCODE_CONFIG_DIR": str(tmp_path / "config"),
        "OPENCODE_CONFIG_PROJECT_DISABLE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_FILEWATCHER_DISABLE": "1", "OPENCODE_TEST_HOME": str(tmp_path / "home"),
        "OPENCODE_DB": str(tmp_path / "data" / "native.db"), "OPENCODE_PASSWORD": "local-test",
        "HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "home"),
        "TEMP": str(tmp_path / "temp"), "TMP": str(tmp_path / "temp"),
        **{"XDG_" + k + "_HOME": str(tmp_path / v) for k, v in (
            ("CONFIG", "config"), ("DATA", "data"), ("CACHE", "cache"), ("STATE", "state"))}})
    processes = []
    logs = []

    def start():
        out = queue.Queue()
        process = subprocess.Popen([binary, "serve", "--stdio", "--hostname", "127.0.0.1", "--port", "0"],
            cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)

        def read():
            for line in process.stdout:
                logs.append(line)
                out.put(line)

        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            assert process.poll() is None, logs[-15:]
            try:
                line = out.get(timeout=.2)
            except queue.Empty:
                continue
            if line.startswith('{"url":'):
                return process, json.loads(line)["url"]
        pytest.fail("native server did not start: " + str(logs[-15:]))

    def api(method, path, body=None, headers=None):
        auth = base64.b64encode(b"opencode:local-test").decode()
        request = Request(url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                          headers={"Authorization": "Basic " + auth, "Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None

    def activate_plugin(directory):
        plugins = api("GET", "/api/plugin", headers={"x-opencode-directory": str(directory).replace("\\", "/")})
        return plugins if "pallium-v2" in json.dumps(plugins).lower() else None

    def eventually(check):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            result = check()
            if result:
                return result
            time.sleep(.1)
        pytest.fail("native lifecycle condition timed out: " + str(logs[-15:]))

    def stop(process, graceful=True):
        if process.poll() is None:
            if graceful:
                process.stdin.close()
            else:
                process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(10)

    try:
        process, url = start()
        for directory in [workspace, *locations, foreign]:
            eventually(lambda: activate_plugin(directory))
        session = api("POST", "/api/session", {"location": {"directory": str(workspace).replace("\\", "/")}})["data"]["id"]
        prefix = "/api/session/" + session
        api("POST", prefix + "/prompt", {"id": "msg_natural_first", "text": "NATIVE_USER_שלום", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        listed = eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", "session_ref": session, **scope}).json())
        container = listed[0]["container_ref"]
        scope = {"container_ref": container}
        eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope}).json()[0]["activation"]["integration"] == "opencode_queue")
        assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200

        def send(payload):
            response = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
                "recipient": "opencode:" + session, "payload": payload, **scope})
            assert response.status_code == 200, response.text
            return response.json()

        def delivered(sent):
            status = client.get("/relay/messages/" + sent["message_id"], params=scope)
            assert status.status_code == 200, status.text
            return status.json()["deliveries"][0]["state"] == "delivered"

        idle = send("IDLE_PAYLOAD_שלום")
        eventually(lambda: delivered(idle))
        eventually(lambda: any("IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False) for body in requests))
        api("POST", "/api/experimental/session/" + session + "/wait")
        idle_requests = [body for body in requests if "IDLE_PAYLOAD_שלום" in json.dumps(body, ensure_ascii=False)]
        assert len(idle_requests) == 2, "Relay context must survive the second native provider/tool step"
        assert restored_client, "Pallium must restart between ACK and continuation"
        for body in idle_requests:
            provider_text = json.dumps(body, ensure_ascii=False)
            assert container in provider_text and session in provider_text and "actor_ref" in provider_text
        entered.clear()
        release.clear()
        api("POST", prefix + "/prompt", {"id": "msg_busy_user", "text": "BUSY_USER", "delivery": "queue"})
        assert entered.wait(15)
        busy = send("BUSY_PAYLOAD_é")
        time.sleep(3)
        assert not delivered(busy), "queued wake claimed before model boundary"
        release.set()
        eventually(lambda: delivered(busy))
        api("POST", "/api/experimental/session/" + session + "/wait")
        context = api("GET", prefix + "/context")
        wake_ids = [m["id"] for m in context["data"] if m.get("type") == "user" and m.get("metadata", {}).get("pallium_relay_wake")]
        assert len(wake_ids) == len(set(wake_ids)) == 2
        fail_context.set()
        failure = send("PRECLAIM_RECOVERY_PAYLOAD")
        eventually(lambda: delivered(failure))
        api("POST", "/api/experimental/session/" + session + "/wait")
        assert len(failed_contexts) == 1
        recovered_context = api("GET", prefix + "/context")["data"]
        failed_id = failed_contexts[0]["native_input_id"]
        index = next(i for i, m in enumerate(recovered_context) if m["id"] == failed_id)
        assert recovered_context[index + 1]["type"] == "idle" and recovered_context[index + 1]["outcome"] == "failed"
        assert any(m.get("type") == "user" and m.get("metadata", {}).get("delivery_id") == failed_contexts[0]["delivery_id"]
                   and m["id"] != failed_id for m in recovered_context)
        eventually(lambda: any(body.get("role") == "assistant" for body, _ in ingested))
        for role, marker in (("user", "NATIVE_USER_שלום"), ("assistant", "NATIVE_ASSISTANT_שלום")):
            body, result = next((body, result) for body, result in ingested if body.get("role") == role and marker in body["content"])
            expanded = client.get("/source/" + result["source_item_id"] + "/context", params={**scope,
                "query_actor_ref": body["actor_ref"], "before": 0, "after": 0})
            assert expanded.status_code == 200 and marker in expanded.text
        assistant_sources = [body for body, _ in ingested if body.get("role") == "assistant"]
        natural_marker = assistant_sources[0]["content"]
        automatic_marker = next(marker for marker, model_body in assistant_outputs
            if "IDLE_PAYLOAD_שלום" in json.dumps(model_body, ensure_ascii=False)
            and any(body["content"] == marker for body in assistant_sources))
        assistant_actor = assistant_sources[0]["actor_ref"]
        history_client = relay_client[0]
        history_client.app.state.pallium_service.drain_processing_queue(worker_id="opencode-native-history")
        for marker in (natural_marker, automatic_marker):
            sources = [(body, result) for body, result in ingested
                if body.get("role") == "assistant" and body["content"] == marker]
            assert len(sources) == 1, (marker, [body["content"] for body, _ in ingested if body.get("role") == "assistant"])
            body, result = sources[0]
            assert body["container_ref"] == container and body["thread_ref"] == session and body["actor_ref"] == assistant_actor
            history = history_client.post("/query", json={"text": "NATIVE", "container_ref": container,
                "active_session_ref": session, "thread_ref": session, "actor_ref": assistant_actor,
                "visibility": "private", "trigger_origin": "agent_pull", "limit": 50, "source_only": True})
            assert history.status_code == 200, history.text
            assert result["source_item_id"] in json.dumps(history.json())
            expanded = history_client.get("/source/" + result["source_item_id"] + "/context", params={**scope,
                "query_actor_ref": assistant_actor, "before": 0, "after": 0})
            assert expanded.status_code == 200 and marker in expanded.text
        foreign_history = history_client.post("/query", json={"text": "NATIVE", "container_ref": "git:example.test/team/foreign",
            "active_session_ref": session, "thread_ref": session, "visibility": "private",
            "trigger_origin": "agent_pull", "limit": 50, "source_only": True})
        assert foreign_history.status_code == 200, foreign_history.text
        assert not any(natural_marker in json.dumps(row) for row in foreign_history.json()["results"])
        assert all(not body["content"].startswith("[Pallium Relay wake:") for body, _ in ingested)
        stop(process, graceful=False)
        reload_message = send("RELOAD_PAYLOAD")
        service_unavailable.set()
        process, url = start()
        eventually(lambda: activate_plugin(workspace))
        time.sleep(3)
        service_unavailable.clear()
        eventually(lambda: delivered(reload_message))
        assert any("RELOAD_PAYLOAD" in json.dumps(body) for body in requests)
        api("DELETE", prefix)
        eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope, "include_inactive": True}).json()[0]["state"] == "closed")
    finally:
        release.set()
        for process in processes:
            stop(process)
        for server in (relay, provider):
            server.shutdown()
            server.server_close()
        for restarted in restored_client:
            restarted.close()
