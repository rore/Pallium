"""Released OpenCode V2 + production plugin + real Pallium HTTP, local provider only."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

pytestmark = pytest.mark.slow


def test_released_native_idle_busy_and_reload(client, tmp_path, test_db_url, monkeypatch):
    binary = os.environ.get("PALLIUM_OPENCODE_V2_BINARY")
    if not binary or not Path(binary).is_file():
        pytest.skip("set PALLIUM_OPENCODE_V2_BINARY to the released 2.0.22 executable")
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "remote", "add", "origin", "https://example.test/team/relay.git"], check=True)
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
    capture_reply_lost = threading.Event()
    capture_reply_lost.set()
    lost_captures = []
    retirement_armed = threading.Event()
    retirement_blocked = threading.Event()
    retirement_release = threading.Event()
    retirement_resumed = threading.Event()
    retirement_acks = []

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
            if self.path == "/relay/deliveries/ack":
                retirement_acks.append(json.loads(raw))
            response = relay_client[0].request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if self.path in ("/items", "/item-and-query") and response.is_success:
                body = json.loads(raw)
                result = response.json()
                ingested.extend(zip(body if isinstance(body, list) else [body], result if isinstance(result, list) else [result]))
                if self.path == "/items" and capture_reply_lost.is_set() and body[0].get("role") == "assistant":
                    capture_reply_lost.clear()
                    lost_captures.append((body[0], result[0]))
                    self.close_connection = True
                    return  # native capture committed; its caller receives no receipt
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            hold = self.path == "/relay/turn" and retirement_armed.is_set() and response.is_success and bool(response.json().get("deliveries"))
            if hold:
                retirement_armed.clear()
                retirement_blocked.set()
                assert retirement_release.wait(30), "retired context response body not released"
            try:
                self.wfile.write(response.content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                if hold:
                    retirement_resumed.set()

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
            compacting = "<template>" in json.dumps(body)
            summary = """## Objective
- Continue the generic fixture.
## Requirements
- (none)
## Decisions
- (none)
## Work State
### Completed
- Initial fixture response.
### Active
- (none)
### Blocked
- (none)
## Next Move
1. Continue the fixture.
## Relevant Files
- (none)
## Important Context
- (none)
"""
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
                     "role": "assistant", "content": summary if compacting else "NATIVE_ASSISTANT_שלום"}, "finish_reason": None}]},
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
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    source = Path(os.environ.get("PALLIUM_OPENCODE_NATIVE_PLUGIN_DIR",
                                root / "integrations" / "opencode" / ".opencode" / "plugins"))
    for name in ("pallium-v2.mjs", "pallium-common.mjs"):
        shutil.copy2(source / name, plugin / name)
    lifecycle = tmp_path / "lifecycle.jsonl"
    wrapper = plugin / "index.js"
    wrapper.write_text("""import production from './pallium-v2.mjs';
import {appendFileSync} from 'node:fs';
const log=kind=>appendFileSync(process.env.PALLIUM_NATIVE_LIFECYCLE,JSON.stringify({kind,time:Date.now()})+'\\n');
export default {...production,setup:async ctx=>{
 log('setup');
 const session={...ctx.session,hook:(name,callback)=>ctx.session.hook(name,async event=>{
  try{return await callback(event)}finally{log(name+'.done')}
 })};
 const cleanup=await production.setup({...ctx,session});
 return async()=>{log('cleanup.enter');await cleanup();log('cleanup.done')};
}};
""", encoding="utf-8")
    (plugin / "package.json").write_text('{"type":"module","main":"index.js"}')
    config = {
        "model": "mock/mock-model", "update": "disable", "share": "disabled", "snapshots": False,
        "plugins": [str(plugin)],
        "providers": {"mock": {"package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1", "apiKey": "local-only"},
            "models": {"mock-model": {"limit": {"context": 32000, "output": 2000}}}}},
    }
    (tmp_path / "config" / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not (
        k.startswith(("PALLIUM_", "OPENCODE_")) or k.endswith("API_KEY"))}
    env.update({"PALLIUM_PORT": str(relay.server_port), "PALLIUM_NATIVE_LIFECYCLE": str(lifecycle), "OPENCODE_CONFIG_DIR": str(tmp_path / "config"),
        "OPENCODE_CONFIG_PROJECT_DISABLE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_TEST_HOME": str(tmp_path / "home"),
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

    def api(method, path, body=None):
        auth = base64.b64encode(b"opencode:local-test").decode()
        request = Request(url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                          headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"})
        with urlopen(request, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

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
        session = api("POST", "/api/session", {})["data"]["id"]
        prefix = "/api/session/" + session
        api("POST", prefix + "/prompt", {"id": "msg_natural_first", "text": "NATIVE_USER_שלום", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        eventually(lambda: lost_captures)
        initial_history = api("GET", prefix + "/context")["data"]
        initial_assistant = next(message for message in reversed(initial_history) if message.get("type") == "assistant")
        assert isinstance(initial_assistant["time"]["completed"], (int, float))
        # A normal native compaction hook retries the already-committed capture.
        # It uses the native summary model; no result override or host mutation.
        api("POST", prefix + "/compact", {"id": "msg_capture_compaction", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        compacted_history = api("GET", prefix + "/context")["data"]
        assert any(message.get("id") == "msg_capture_compaction" and message.get("status") == "completed"
                   for message in compacted_history)
        original_capture, original_receipt = lost_captures[0]
        native_retries = [(body, receipt) for body, receipt in ingested
                          if body.get("role") == "assistant" and body["content"] == original_capture["content"]]
        assert len(native_retries) == 2
        assert {receipt["source_item_id"] for _, receipt in native_retries} == {original_receipt["source_item_id"]}
        assert {body["source_id"] for body, _ in native_retries} == {original_capture["source_id"]}
        assert original_capture["source_id"].startswith("oc-assistant-")
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
        # Native source reload invokes production cleanup with the HTTP response
        # body still withheld. A process restart cannot establish this ordering.
        retirement_acks.clear()
        retired = send("RETIRED_BODY_שלום")
        retirement_armed.set()
        api("POST", prefix + "/prompt", {"id": "msg_retirement_pending", "text": "NATIVE_RETIREMENT", "delivery": "queue"})
        assert retirement_blocked.wait(15), "production context never entered the blocked response body"
        before_events = [json.loads(line) for line in lifecycle.read_text().splitlines()]
        before_setup = sum(e["kind"] == "setup" for e in before_events)
        before_context_done = sum(e["kind"] == "context.done" for e in before_events)
        with wrapper.open("a", encoding="utf-8") as stream:
            stream.write("\n// supported native source reload\n")
        eventually(lambda: sum(json.loads(line)["kind"] == "setup" for line in lifecycle.read_text().splitlines()) == before_setup + 1)
        lifecycle_events = [json.loads(line) for line in lifecycle.read_text().splitlines()]
        cleanup = next(e for e in lifecycle_events if e["kind"] == "cleanup.done")
        cleanup_enter = next(e for e in lifecycle_events if e["kind"] == "cleanup.enter")
        assert 0 <= cleanup["time"] - cleanup_enter["time"] < 2000
        assert not retirement_release.is_set()
        assert not retirement_acks
        retirement_release.set()
        assert retirement_resumed.wait(5)
        eventually(lambda: sum(json.loads(line)["kind"] == "context.done" for line in lifecycle.read_text().splitlines()) > before_context_done)
        api("POST", "/api/experimental/session/" + session + "/wait")
        assert not retirement_acks, "retired callback initiated ACK after native cleanup"
        assert all("RETIRED_BODY_שלום" not in json.dumps(body, ensure_ascii=False) for body in requests)
        assert not delivered(retired), "unattached context must remain lease-recoverable"
        # Exercise the real lease expiry/read paths with the same isolated clock
        # seam as the HTTP wake E2E suite, without a minute-long wall-clock wait.
        import storage.sqlite_relay as sqlite_relay
        original_now = sqlite_relay._now
        monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: original_now(value) if value else original_now() + timedelta(seconds=61))
        api("POST", prefix + "/prompt", {"id": "msg_retirement_successor", "text": "NATIVE_RECOVERY", "delivery": "queue"})
        api("POST", "/api/experimental/session/" + session + "/wait")
        eventually(lambda: delivered(retired))
        assert any("RETIRED_BODY_שלום" in json.dumps(body, ensure_ascii=False) for body in requests)
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
        assert all(not body["content"].startswith("[Pallium Relay wake:") for body, _ in ingested)
        stop(process, graceful=False)
        reload_message = send("RELOAD_PAYLOAD")
        service_unavailable.set()
        process, url = start()
        api("GET", "/api/plugin?directory=" + str(workspace).replace("\\", "/"))
        time.sleep(3)
        service_unavailable.clear()
        eventually(lambda: delivered(reload_message))
        assert any("RELOAD_PAYLOAD" in json.dumps(body) for body in requests)
        api("DELETE", prefix)
        eventually(lambda: client.get("/relay/sessions", params={"runtime": "opencode", **scope, "include_inactive": True}).json()[0]["state"] == "closed")
    finally:
        release.set()
        retirement_release.set()
        (tmp_path / "native.log").write_text("".join(logs), encoding="utf-8")
        for process in processes:
            stop(process)
        for server in (relay, provider):
            server.shutdown()
            server.server_close()
        for restarted in restored_client:
            restarted.close()


def test_capture_callbacks_retry_through_real_http_and_history(client, tmp_path):
    """Production hook + HTTP writes: count persisted receipts, including lost replies."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the production OpenCode caller")
    attempts, ingested = {}, []
    held, release = threading.Event(), threading.Event()

    class CaptureHTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            payload = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/fixture/held":
                return self.reply(200, held.is_set())
            if self.path == "/fixture/release":
                release.set()
                return self.reply(200, True)
            body = json.loads(raw) if self.path == "/items" else None
            marker = body[0]["content"] if body else None
            if marker:
                attempts[marker] = attempts.get(marker, 0) + 1
                attempt = attempts[marker]
                if marker == "REJECT_שלום" and attempt == 1:
                    return self.reply(503, {"detail": "isolated precommit rejection"})
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            if body and response.is_success:
                ingested.extend(zip(body, response.json()))
                if marker == "CONCURRENT_שלום" and attempt == 1:
                    held.set()
                    assert release.wait(15), "capture reply was not released"
                if marker == "LOST_שלום" and attempt == 1:
                    self.close_connection = True  # committed source, no receipt delivered
                    return
                if marker == "MALFORMED_שלום" and attempt == 1:
                    return self.reply(200, {})
            self.reply(response.status_code, response.json())

        do_GET = do_POST = forward

    server = ThreadingHTTPServer(("localhost", 0), CaptureHTTP)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = Path(__file__).resolve().parents[1]
    plugin_dir = Path(os.environ.get("PALLIUM_OPENCODE_NATIVE_PLUGIN_DIR",
                                    root / "integrations/opencode/.opencode/plugins"))
    program = tmp_path / "capture-caller.mjs"
    program.write_text("""import assert from 'node:assert/strict';
const {default:production}=await import(process.env.CAPTURE_PLUGIN);
const cwd=process.env.CAPTURE_DIRECTORY, sessionID='ses_capture_http';
let history=[], hooks={}, cleanup;
const ctx={location:{directory:cwd},app:{log(){}},session:{
 hook:async(name,callback)=>{hooks[name]=callback;return{dispose:async()=>{}}},
 get:async()=>({location:{directory:cwd}}),context:async()=>({data:history}),
},event:{subscribe:async function*({signal}){
 if(!signal.aborted)await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
}}};
const capture=()=>hooks.compaction({sessionID});
const rows=(name,id='msg_'+name)=>history=[
 {type:'user',id:'msg_user_'+name,text:'generic fixture'},
 {type:'assistant',id,time:{created:0,completed:1},content:[{type:'text',text:name+'_שלום'}]},
];
const control=async(path)=>(await fetch('http://localhost:'+process.env.PALLIUM_PORT+'/fixture/'+path)).json();
try{
 cleanup=await production.setup(ctx);
 rows('CONCURRENT');const first=capture();
 const until=Date.now()+5000;while(!await control('held')){
  assert.ok(Date.now()<until,'capture request did not reach the HTTP barrier');
  await new Promise(resolve=>setTimeout(resolve,5));
 }
 await capture();await control('release');await first;await capture();
 rows('REJECT');await capture();await capture();await capture();
 rows('MALFORMED');await capture();await capture();await capture();
 rows('LOST');await capture();await cleanup();cleanup=await production.setup(ctx);
 await capture();await capture();
 rows('SAME_TEXT','msg_same_a');await capture();
 rows('SAME_TEXT','msg_same_b');await capture();
}finally{await control('release');await cleanup?.()}
""", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not (
        key.startswith(("PALLIUM_", "OPENCODE_")) or key.endswith("API_KEY"))}
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                "XDG_STATE_HOME", "TEMP", "TMP"):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    env.update({"PALLIUM_PORT": str(server.server_port), "PALLIUM_HOOK_ACTOR_REF": "fixture-actor",
                "CAPTURE_PLUGIN": (plugin_dir / "pallium-v2.mjs").as_uri(),
                "CAPTURE_DIRECTORY": str(tmp_path)})
    try:
        result = subprocess.run([node, str(program)], env=env, cwd=tmp_path,
                                capture_output=True, text=True, timeout=40)
        (tmp_path / "capture-caller.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        assert attempts == {"CONCURRENT_שלום": 1, "REJECT_שלום": 2, "MALFORMED_שלום": 2,
                            "LOST_שלום": 2, "SAME_TEXT_שלום": 2}
        for marker in ("CONCURRENT", "REJECT", "MALFORMED", "LOST", "SAME_TEXT"):
            receipts = [(body, reply) for body, reply in ingested if body["content"] == marker + "_שלום"]
            unique = {reply["source_item_id"] for _, reply in receipts}
            assert len(unique) == (2 if marker == "SAME_TEXT" else 1)
            for receipt in unique:
                body = next(body for body, reply in receipts if reply["source_item_id"] == receipt)
                expanded = client.get("/source/" + receipt + "/context", params={
                    "container_ref": body["container_ref"], "query_actor_ref": body["actor_ref"],
                    "before": 0, "after": 0})
                assert expanded.status_code == 200
                assert [item["content"] for item in expanded.json()["items"]] == [marker + "_שלום"]
                assert expanded.json()["items"][0]["source_id"] == body["source_id"]
    finally:
        release.set()
        server.shutdown()
        server.server_close()
