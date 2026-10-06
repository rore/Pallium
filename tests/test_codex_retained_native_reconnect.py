"""Real Windows pipe registration across a retained service process restart."""

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading

import pytest

from app import codex_bridge_pipe as bridge
from tests.test_codex_bridge_pipe import FakeDesktop

pytestmark = pytest.mark.slow
native = pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel pipe contract")

_SERVICE = r"""
import os, sys, time
from pathlib import Path
import app.codex_bridge_pipe as bridge

def fake_app_descriptor(w, source, desktop_pid, sid):
    parents, ancestors, child = bridge._parent_pids(), [], source
    for _ in range(32):
        pid = parents.get(child.pid)
        if type(pid) is not int or pid <= 0 or pid in {p.pid for p in ancestors}:
            raise bridge.ShadowUnavailable("peer-mismatch")
        peer = bridge._Peer(w, pid, sid)
        ancestors.append(peer)
        if pid == desktop_pid:
            policy = type("Policy", (), {"desktop_user_sid": sid,
                "desktop_executable": r"C:\\TestHost\\Codex.exe",
                "desktop_version": "native-fixture-v1"})()
            desktop = type("DesktopIdentity", (), {})()
            desktop.pid, desktop.creation, desktop.policy = pid, peer.creation, policy
            desktop.verify, desktop.close = peer.check, lambda: None
            return desktop, ancestors
        child = peer
    raise bridge.ShadowUnavailable("peer-mismatch")

bridge._source_desktop = fake_app_descriptor
service = bridge.RetainedService(Path(sys.argv[1]))
service.start()
try:
    deadline = time.monotonic() + 5
    while not service.stop_event.is_set() and time.monotonic() < deadline:
        try:
            manifest = bridge._json(bridge._read_private(
                bridge._native(), Path(sys.argv[1]) / "active.json", bridge._self_sid(bridge._native())))
            if manifest.get("epoch") == service.epoch and manifest.get("pid") == os.getpid():
                break
        except bridge.ShadowUnavailable:
            pass
        time.sleep(.01)
    else:
        raise RuntimeError("service failed to publish bootstrap")
    print(service.epoch, flush=True)
    if sys.stdin.readline().strip() != "stop":
        raise RuntimeError("missing bounded stop command")
    service.stop()
    if service.thread.is_alive() or service.unresolved:
        raise RuntimeError("service did not stop cleanly")
finally:
    if service.thread is not None and service.thread.is_alive():
        service.stop()
"""

_SOURCE = r"""
import json, os, sys, threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient

client, previous = None, None
for line in sys.stdin:
    request = json.loads(line)
    if request.get("stop"):
        if client:
            client.dispose()
        print("stopped", flush=True)
        break
    if client is not None and not client.service_current():
        previous = client.manifest
        client.dispose()
        client = None
    if client is None:
        client = NativeInventoryClient(Path(request["bootstrap"]), threading.Event(),
            retained=True, previous_manifest=previous)
        previous = client.manifest
    ready = {"status": "skipped"} if request.get("register_only") else client.ready()
    if request.get("legacy"):
        response = client._exchange("register", endpoint=os.environ["CODEX_APP_TOOLS_PIPE_PATH"],
            thread_ref="source-chat", turn_ref="source-turn")
        result = client._public(response)
    else:
        if request.get("continuity") is not None:
            client.continuity = request["continuity"]
        result = client.register(request.get("metadata", {"thread_ref": "source-chat", "turn_ref": "source-turn"}))
    print(json.dumps({"ready": ready, "result": result,
        "continuity": client.continuity, "wire_keys": sorted(response) if request.get("legacy") else []}),
        flush=True)
"""

_OTHER_SOURCE = r"""
import json, sys, threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient

client = NativeInventoryClient(Path(sys.argv[1]), threading.Event(), retained=True,
    previous_manifest=json.loads(sys.argv[2]))
try:
    client.ready()
    client.continuity = sys.argv[3]
    print(json.dumps(client.register({"thread_ref":"source-chat", "turn_ref":"source-turn"})), flush=True)
finally:
    client.dispose()
"""


def _response(request, value):
    if request.get("method") != "tools/list":
        return value
    value["result"]["tools"] = [
        {"namespace": "codex_app", "name": "send_message_to_thread", "inputSchema": {
            "type": "object", "required": ["threadId", "prompt"], "properties": {
                "threadId": {"type": "string"}, "prompt": {"type": "string"}}}},
        {"namespace": "codex_app", "name": "read_thread", "inputSchema": {
            "type": "object", "properties": {"threadId": {"type": "string"},
                "turnLimit": {"type": "number"}, "includeOutputs": {"type": "boolean"},
                "maxOutputCharsPerItem": {"type": "integer"}}}},
    ]
    return value


def _start_service(root, log_path):
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-c", _SERVICE, str(root)],
        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8")
    log.close()
    output = []
    reader = threading.Thread(target=lambda: output.append(process.stdout.readline()), daemon=True)
    reader.start()
    reader.join(8)
    if reader.is_alive():
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        raise AssertionError("retained service did not publish readiness within 8 seconds")
    epoch = output[0].strip() if output else ""
    if not epoch or process.poll() is not None:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        raise AssertionError(log_path.read_text(encoding="utf-8"))
    return process, epoch


def _stop(process):
    if process.poll() is None:
        process.stdin.write("stop\n")
        process.stdin.flush()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    if process.stdin:
        process.stdin.close()
    if process.stdout:
        process.stdout.close()
    assert process.returncode == 0


def _source_call(process, request):
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    result = []
    reader = threading.Thread(target=lambda: result.append(process.stdout.readline()), daemon=True)
    reader.start()
    reader.join(8)
    details = process.stderr.read() if result and not result[0] and process.poll() is not None else ""
    assert not reader.is_alive() and result and result[0], f"source client did not answer: {details}"
    return json.loads(result[0])


@native
def test_retained_registration_continues_across_real_service_epoch(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    temp_parent = repo / "tmp"
    temp_parent.mkdir(exist_ok=True)
    test_root = temp_parent / f"native-retained-reconnect-{secrets.token_hex(16)}"
    assert not test_root.exists()
    service_processes, desktops = [], []
    source = None
    try:
        w = bridge._native()
        bridge._secure_directory(w, test_root, bridge._self_sid(w))
        directory = bridge.prepare_inventory_service(test_root / "home")
        endpoint = rf"\\.\pipe\inventory-test-{secrets.token_hex(16)}"
        env = os.environ.copy()
        env["CODEX_APP_TOOLS_PIPE_PATH"] = endpoint
        desktop_module = sys.modules[FakeDesktop.__module__]

        def start_desktop():
            with monkeypatch.context() as patch:
                patch.setattr(desktop_module.secrets, "token_hex", lambda *_: endpoint.rsplit("-", 1)[-1])
                desktop = FakeDesktop(_response)
            assert desktop.endpoint == endpoint
            desktops.append(desktop)
            return desktop

        source = subprocess.Popen([sys.executable, "-c", _SOURCE], cwd=repo, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8")
        desktop = start_desktop()
        first_service, first_epoch = _start_service(directory, test_root / "service-1.log")
        service_processes.append(first_service)
        first = _source_call(source, {"bootstrap": str(directory / "active.json"), "legacy": True})
        assert first["ready"]["status"] == "ready" and first["result"]["status"] == "registered"
        assert set(first["wire_keys"]) == {
            "mode", "status", "reason", "ttl_seconds", "connected", "inventory_ok", "source_exited",
            "version", "epoch", "sequence",
        }
        assert first["continuity"] is None
        registered = _source_call(source, {"bootstrap": str(directory / "active.json"), "continuity": None})
        proof = registered["continuity"]
        assert registered["result"]["status"] == "registered" and len(proof) == 64
        assert first_service.poll() is None

        old_manifest = bridge._json(bridge._read_private(w, directory / "active.json", bridge._self_sid(w)))
        _stop(first_service)
        assert not desktop.thread.is_alive()
        desktops.remove(desktop)
        desktop.close()

        desktop = start_desktop()
        second_service, second_epoch = _start_service(directory, test_root / "service-2.log")
        service_processes.append(second_service)
        assert second_epoch != first_epoch
        old_requests = len(desktop.requests)
        denied_run = subprocess.run([sys.executable, "-c", _OTHER_SOURCE,
            str(directory / "active.json"), json.dumps(old_manifest), proof], cwd=repo, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=8)
        denied = json.loads(denied_run.stdout)
        assert denied["status"] == "unavailable"
        assert denied_run.returncode == 0 and len(desktop.requests) == old_requests
        assert not desktop.thread.is_alive()
        desktops.remove(desktop)
        desktop.close()

        desktop = start_desktop()
        resumed = _source_call(source, {"bootstrap": str(directory / "active.json"), "continuity": proof})
        assert resumed["result"]["status"] == "registered"
        assert resumed["continuity"] == proof
        assert len(desktop.requests) == old_requests + 1
    finally:
        for process in reversed(service_processes):
            if process.poll() is None:
                try:
                    _stop(process)
                except Exception:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
        for process in (source,):
            if process is not None and process.poll() is None:
                try:
                    process.stdin.write(json.dumps({"stop": True}) + "\n")
                    process.stdin.flush()
                    process.wait(timeout=3)
                except Exception:
                    process.terminate()
                    process.wait(timeout=5)
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
        for desktop in desktops:
            desktop.close()
        assert test_root.resolve().parent == temp_parent.resolve()
        assert test_root.resolve().is_relative_to(repo.resolve())
        assert test_root.name.startswith("native-retained-reconnect-")
        if test_root.exists():
            shutil.rmtree(test_root)
