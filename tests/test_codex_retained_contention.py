"""Real source-pipe contention preserves retained registration during dispatch."""

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app import codex_bridge_pipe as bridge
from tests.test_codex_bridge_pipe import FakeDesktop, wait_until
from tests.test_codex_retained_native_reconnect import _SOURCE, _response, _source_call

pytestmark = pytest.mark.slow


@pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel pipe contract")
def test_retained_register_returns_busy_during_serialized_dispatch_and_keeps_source(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    temp_parent = repo / "tmp"
    temp_parent.mkdir(exist_ok=True)
    test_root = temp_parent / f"native-retained-contention-{secrets.token_hex(16)}"
    assert not test_root.exists()
    bridge._secure_directory(bridge._native(), test_root, bridge._self_sid(bridge._native()))

    first_exchange, second_exchange = threading.Event(), threading.Event()
    first_finished, second_finished = threading.Event(), threading.Event()
    exchange_durations = []

    def desktop_response(request, value):
        if request.get("method") != "tools/call":
            return _response(request, value)
        tool = request["params"]["tool"]
        if tool == "read_thread":
            first_exchange.set()
            started = time.monotonic()
            time.sleep(2)
            exchange_durations.append(time.monotonic() - started)
            first_finished.set()
            body = {"schemaVersion": 1, "thread": {"id": "target-session", "kind": "codex",
                "hostId": "local", "status": {"type": "notLoaded"}}}
            return {"jsonrpc": "2.0", "id": request["id"], "result": {
                "success": True, "isError": False,
                "contentItems": [{"type": "inputText", "text": json.dumps(body)}]}}
        assert tool == "send_message_to_thread"
        second_exchange.set()
        started = time.monotonic()
        time.sleep(2)
        exchange_durations.append(time.monotonic() - started)
        second_finished.set()
        return {"jsonrpc": "2.0", "id": request["id"], "result": {"success": True, "isError": False}}

    desktop = FakeDesktop(desktop_response, allow_call=True)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", desktop.endpoint)
    monkeypatch.setattr(bridge, "_source_desktop", _fake_app_descriptor)
    directory = bridge.prepare_inventory_service(test_root / "home")
    service = bridge.RetainedService(directory).start()
    source = None
    dispatch_thread = registration_thread = None
    dispatch_results, dispatch_errors, registration_results, registration_errors = [], [], [], []
    registration_done = threading.Event()
    try:
        wait_until(lambda: (directory / "active.json").exists() or service.stop_event.is_set())
        assert not service.stop_event.is_set()
        env = os.environ.copy()
        env["CODEX_APP_TOOLS_PIPE_PATH"] = desktop.endpoint
        source = subprocess.Popen([sys.executable, "-c", _SOURCE], cwd=repo, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8")
        first = _source_call(source, {"bootstrap": str(directory / "active.json"), "continuity": None})
        proof = first["continuity"]
        assert first["ready"]["status"] == "ready" and first["result"]["status"] == "registered"
        assert isinstance(proof, str) and len(proof) == 64
        admitted = service.retained_registration
        old_caller = service.caller
        old_source = service.source
        assert admitted is not None and admitted["caller"] == old_caller

        class Registry:
            _relay = None

            def __init__(self):
                self.attempts = self.fences = 0

            def begin_native_attempt(self, _reservation):
                self.attempts += 1
                return object()

            def run_if_current(self, _reservation, operation):
                self.fences += 1
                return True, operation()

        reservation = SimpleNamespace(outcome="pending", session_ref="target-session",
            container_ref="target-container", delivery_id="delivery", recipient_endpoint_id="endpoint",
            generation=1, retry_not_before=None)
        registry = Registry()
        dispatch_started = time.monotonic()
        def dispatch():
            try:
                dispatch_results.append(service.dispatch(reservation, registry))
            except Exception as exc:
                dispatch_errors.append(exc)
        dispatch_thread = threading.Thread(target=dispatch, daemon=True)
        dispatch_thread.start()
        assert first_exchange.wait(2), "dispatch did not reach its first real Desktop response"

        def register_during_dispatch():
            try:
                registration_results.append(_source_call(source, {"bootstrap": str(directory / "active.json"),
                    "continuity": proof, "register_only": True,
                    "metadata": {"thread_ref": "source-chat", "turn_ref": "turn-busy"}}))
            except Exception as exc:
                registration_errors.append(exc)
            finally:
                registration_done.set()

        registration_thread = threading.Thread(target=register_during_dispatch, daemon=True)
        registration_thread.start()
        assert registration_done.wait(2), "registration did not promptly return busy during dispatch"
        assert not registration_errors, registration_errors
        busy = registration_results[0]
        assert busy["result"]["status"] == "unavailable" and busy["result"]["reason"] == "busy"
        assert busy["continuity"] == proof
        assert service.source is old_source and service.retained_registration is admitted
        assert service.caller == old_caller and admitted["caller"] == old_caller
        assert dispatch_thread.is_alive(), "dispatch ended while its first Desktop response remained pending"

        assert second_exchange.wait(3), "dispatch did not reach its second real Desktop response"
        assert dispatch_thread.is_alive() and first_finished.is_set()
        dispatch_thread.join(3)
        assert not dispatch_thread.is_alive() and second_finished.is_set()
        assert time.monotonic() - dispatch_started > 3
        assert len(exchange_durations) == 2 and all(duration < 3 for duration in exchange_durations)
        assert not dispatch_errors, dispatch_errors
        assert len(dispatch_results) == 1
        assert dispatch_results[0][0].outcome == "uncertain"
        assert dispatch_results[0][0].reason == "native_submitted"
        assert registry.attempts == registry.fences == 1
        assert len(desktop.requests) == 3
        assert [item["params"]["tool"] for item in desktop.requests[1:]] == ["read_thread", "send_message_to_thread"]

        updated = _source_call(source, {"bootstrap": str(directory / "active.json"), "continuity": proof,
            "register_only": True,
            "metadata": {"thread_ref": "source-chat", "turn_ref": "turn-after-busy"}})
        assert updated["result"]["status"] == "registered" and updated["continuity"] == proof
        assert service.source is old_source and service.caller == ("source-chat", "turn-after-busy")
        assert service.retained_registration["caller"] == service.caller
    finally:
        if dispatch_thread is not None and dispatch_thread.is_alive():
            dispatch_thread.join(4)
        if registration_thread is not None and registration_thread.is_alive():
            registration_thread.join(4)
        if source is not None and source.poll() is None:
            try:
                source.stdin.write(json.dumps({"stop": True}) + "\n")
                source.stdin.flush()
                source.wait(timeout=3)
            except Exception:
                source.terminate()
                source.wait(timeout=5)
        if source is not None:
            for stream in (source.stdin, source.stdout, source.stderr):
                if stream:
                    stream.close()
        service.stop()
        desktop.close()
        assert not service.unresolved and service.custody is None
        assert test_root.resolve().parent == temp_parent.resolve()
        assert test_root.name.startswith("native-retained-contention-")
        if test_root.exists():
            shutil.rmtree(test_root)


def _fake_app_descriptor(w, source, desktop_pid, sid):
    parents, ancestors, child = bridge._parent_pids(), [], source
    for _ in range(32):
        pid = parents.get(child.pid)
        if type(pid) is not int or pid <= 0 or pid in {peer.pid for peer in ancestors}:
            raise bridge.ShadowUnavailable("peer-mismatch")
        peer = bridge._Peer(w, pid, sid)
        ancestors.append(peer)
        if pid == desktop_pid:
            policy = SimpleNamespace(desktop_user_sid=sid, desktop_executable=r"C:\TestHost\Codex.exe",
                desktop_version="native-fixture-v1")
            desktop = SimpleNamespace(pid=pid, creation=peer.creation, policy=policy,
                verify=peer.check, close=lambda: None)
            return desktop, ancestors
        child = peer
    raise bridge.ShadowUnavailable("peer-mismatch")
