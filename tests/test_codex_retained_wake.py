"""Retained wake HTTP/MCP journeys using a local fake Desktop transport."""
from contextlib import asynccontextmanager, contextmanager
import asyncio
import json
from pathlib import Path
import threading
import time
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import codex_bridge_pipe as bridge, codex_wake, claude_wake
from app.dependencies import build_router, recover_expired_relay_wakes
from app.mcp import server as mcp_server
from app.cli import setup_codex
from core.codex_wake import CodexWakeRegistry
from core.claude_wake import ClaudeWakeRegistry
from core.errors import ImmediateTransactionBusyError
from core.relay import RelayService
from tests.test_codex_mcp_desktop_bridge import _serve_protocol
from tests.test_agent_relay_hooks import _load

SCOPE = {"container_ref": "git:example.test/retained-東京"}
TARGET = "target-session"

class Peer:
    def __init__(self, w, pid, sid=None, creation=None):
        self.w, self.pid, self.handle = w, pid, pid
        self.creation = creation or f"{pid:03}"
        self.closed = self.gone = False
    def check(self):
        if self.closed or self.gone:
            raise bridge.ShadowUnavailable("peer-gone")
    verify = check
    def close(self):
        self.closed = True

class Desktop:
    def __init__(self, w, handle, stop):
        self.handle, self.stop = handle, stop
        self.unresolved = self.closed = False
        self.writes = []
        self.state = "notLoaded"
        self.body = self.response = self.on_owner = self.on_state = None
        self.schemas = [
            {"namespace": "codex_app", "name": "send_message_to_thread", "inputSchema": {
                "type": "object", "required": ["threadId", "prompt"],
                "properties": {"threadId": {"type": "string"}, "prompt": {"type": "string"}}}},
            {"namespace": "codex_app", "name": "read_thread", "inputSchema": {
                "type": "object", "required": ["threadId"], "properties": {
                    "threadId": {"type": "string"}, "turnLimit": {"type": "number"},
                    "includeOutputs": {"type": "boolean"}, "maxOutputCharsPerItem": {"type": "integer"}}}}]
    def write(self, value, deadline):
        assert not self.closed and not self.stop.is_set()
        self.writes.append(value)
    def read(self, deadline):
        request = self.writes[-1]
        if request["method"] == "tools/list":
            result = {"tools": self.schemas}
        elif request["params"]["tool"] == "read_thread":
            body = self.body or json.dumps({"schemaVersion": 1, "thread": {
                "id": request["params"]["arguments"]["threadId"], "kind": "codex", "hostId": "local",
                "status": {"type": self.state}}, "turns": ["private-history-sentinel"]})
            if self.on_state:
                self.on_state()
            result = {"success": True, "contentItems": [{"type": "inputText", "text": body}]}
        else:
            if self.on_owner:
                self.on_owner(request)
            if self.response == "lost":
                raise bridge.ShadowUnavailable("transport-failed")
            result = {} if self.response == "malformed" else {"success": self.response != "native-error", "contentItems": [{"type": "inputText", "text": "submitted"}]}
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}
    def close(self):
        self.closed = True
    @property
    def owners(self):
        return [v for v in self.writes if v.get("params", {}).get("tool") == "send_message_to_thread"]

@pytest.fixture
def retained(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_wake, "_scheduled_delivery_ids", set())
    monkeypatch.setattr(codex_wake, "_scheduled_session_generations", {})
    monkeypatch.setattr(codex_wake, "_scheduled_session_delivery_ids", {})
    monkeypatch.setattr(codex_wake, "_scheduled_session_attempt_ids", {})
    monkeypatch.setattr(bridge, "retained_wake_enabled", lambda: True)
    monkeypatch.setattr(bridge, "_native_uncertain", False)
    monkeypatch.setattr(codex_wake, "_DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr(codex_wake, "_start_launch", lambda *a: pytest.fail("retained mode used CLI"))
    w = SimpleNamespace(con=SimpleNamespace(GENERIC_READ=1, GENERIC_WRITE=2, OPEN_EXISTING=3,
            FILE_FLAG_OVERLAPPED=4, SECURITY_SQOS_PRESENT=8),
        file=SimpleNamespace(SECURITY_IDENTIFICATION=16, CreateFile=lambda *a: 90),
        pipe=SimpleNamespace(GetNamedPipeServerProcessId=lambda h: 40),
        event=SimpleNamespace(WaitForSingleObject=lambda h, t: 258, WAIT_OBJECT_0=0, WAIT_TIMEOUT=258))
    monkeypatch.setattr(bridge, "_Peer", Peer)
    monkeypatch.setattr(bridge, "_parent_pids", lambda: {42: 41, 41: 40})
    monkeypatch.setattr(bridge, "_process_image", lambda *a: (str(Path("C:/Apps") / "Codex.exe"), "1.2.3.4"))
    def desktop_peer(w, descriptor):
        peer = Peer(w, descriptor.desktop_pid)
        peer.policy = descriptor
        return peer
    monkeypatch.setattr(bridge, "_DesktopPeer", desktop_peer)
    natives = []
    def native(*args):
        value = Desktop(*args)
        natives.append(value)
        return value
    monkeypatch.setattr(bridge, "_DesktopIO", native)
    service = bridge.RetainedService(tmp_path)
    service.w, service.sid = w, "same-user"
    service.current = Peer(w, 30)
    service.source = Peer(w, 42)
    request = {"version": 1, "verb": "register", "epoch": service.epoch, "sequence": 1,
               "thread_ref": "source-α", "turn_ref": "turn-β", "endpoint": r"\\.\pipe\desktop-private"}
    yield service, request, natives
    service.stop_event.set()
    service._drop()
    assert service.custody is None or service.unresolved

def register(retained):
    service, request, natives = retained
    assert service._process(request, service.source, 0, float("inf"))["status"] == "registered"
    return service, natives[-1]


def test_enrollment_diagnostics_are_cached_defensive_and_survive_cleanup(retained, monkeypatch):
    service, request, _ = retained
    request = {**request, "continuity": None}
    result = service._process(request, service.source, 0, float("inf"))
    assert result["status"] == "registered" and len(result["continuity"]) == 64
    snapshot = service.enrollment_diagnostics()
    assert snapshot["accepted"] and snapshot["registration_remembered"]
    assert snapshot["custody_present"] and snapshot["continuity_opted_in"]
    snapshot["accepted"] = False

    service._custody_lock.acquire()
    observed, finished = [], threading.Event()
    reader = threading.Thread(target=lambda: (observed.append(service.enrollment_diagnostics()), finished.set()), daemon=True)
    reader.start()
    try:
        assert finished.wait(1), "cached diagnostics waited for the custody lock"
    finally:
        service._custody_lock.release()
        reader.join(1)
    assert not reader.is_alive() and observed[0]["accepted"]

    service._drop()
    monkeypatch.setattr(service, "_open_custody", lambda *a, **kw: (_ for _ in ()).throw(bridge.ShadowUnavailable("peer-mismatch")))
    retry = {**request, "sequence": 2}
    with pytest.raises(bridge.ShadowUnavailable):
        service._process(retry, service.source, 1, float("inf"))
    service._drop()
    service._drop()
    final = service.enrollment_diagnostics()
    assert final["accepted"] and not final["registration_remembered"] and not final["custody_present"]
    assert final["continuity_opted_in"]
    assert (final["last_failure_stage"], final["last_failure_reason"]) == ("register", "peer-mismatch")


def test_lost_enrollment_cache_stays_unavailable_after_cleanup_and_denial(client, retained, monkeypatch):
    service, request, _ = retained
    assert service._process(request, service.source, 0, float("inf"))["status"] == "registered"
    client.app.state.codex_wake_registry.retained_service = service
    service._enrollment_diagnostics = None
    service._drop()
    monkeypatch.setattr(service, "_open_custody", lambda *a, **kw: (_ for _ in ()).throw(bridge.ShadowUnavailable("peer-mismatch")))
    with pytest.raises(bridge.ShadowUnavailable):
        service._process({**request, "sequence": 2}, service.source, 1, float("inf"))
    service._drop()
    assert service.enrollment_diagnostics() is None
    for path in ("/status", "/dashboard/api/relay/summary"):
        response = client.get(path)
        assert response.status_code == 200
        enrollment = response.json()["relay_wake"]["native_enrollment"]
        assert enrollment["state"] == "unavailable" and enrollment["reason"] == "snapshot_unavailable"


def test_diagnostic_publication_failure_does_not_change_registration_result(client, retained, monkeypatch):
    service, request, _ = retained
    broken_clock = SimpleNamespace(now=lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("clock unavailable")))
    monkeypatch.setattr(bridge, "datetime", broken_clock)
    replacement = bridge.RetainedService(service.directory)
    assert replacement.enrollment_diagnostics()["observed_at"] is None
    client.app.state.codex_wake_registry.retained_service = service
    result = service._process(request, service.source, 0, float("inf"))
    assert result["status"] == "registered" and service.retained_registration is not None
    assert service.enrollment_diagnostics()["accepted"] is True
    for path in ("/status", "/dashboard/api/relay/summary"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["relay_wake"]["native_enrollment"]["state"] == "unavailable"


def test_terminal_invalidation_wins_over_inflight_diagnostic_publication(
    client, retained, monkeypatch,
):
    service, request, natives = retained
    assert service._process(request, service.source, 0, float("inf"))["status"] == "registered"
    client.app.state.codex_wake_registry.retained_service = service
    service._drop(preserve_registration=True)
    native = natives[-1]
    native_state = (len(native.writes), len(native.owners))
    entered, release, worker_release = threading.Event(), threading.Event(), threading.Event()
    clear_completed, inherited_join, stop_completed = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    original_datetime = bridge.datetime
    class PausingClock:
        @staticmethod
        def now(*_args, **_kwargs):
            if threading.current_thread().name == "diagnostic-publisher":
                entered.set()
                release.wait()
            return original_datetime.now(*_args, **_kwargs)
    monkeypatch.setattr(bridge, "datetime", PausingClock)
    worker_entered = threading.Event()
    def blocked_worker():
        worker_entered.set()
        worker_release.wait()
    class ObservableThread(threading.Thread):
        def join(self, timeout=None):
            if timeout == .5 and not inherited_join.is_set():
                inherited_join.set()
                assert entered.wait(2), "publisher did not pause before the shutdown timeout"
            return super().join(timeout)
    worker = ObservableThread(target=blocked_worker, daemon=True)
    service.thread = worker
    worker.start()
    publisher = None
    stop_thread = None
    try:
        assert worker_entered.wait(1)
        original_clear = service._clear_registration
        def clear_then_signal():
            original_clear()
            clear_completed.set()
        monkeypatch.setattr(service, "_clear_registration", clear_then_signal)
        def stop_service():
            try:
                service.stop()
            finally:
                stop_completed.set()
        stop_thread = threading.Thread(target=stop_service, daemon=True)
        stop_thread.start()
        assert clear_completed.wait(1) and inherited_join.wait(1)
        def publish():
            with service._custody_lock:
                service._publish_enrollment_diagnostics(failure=("register", "peer-mismatch"))
        publisher = threading.Thread(
            target=publish,
            name="diagnostic-publisher",
            daemon=True,
        )
        publisher.start()
        assert entered.wait(1)
        assert stop_completed.wait(1)
        assert service.unresolved and service.enrollment_diagnostics() is None
        release.set()
        publisher.join(1)
        assert not publisher.is_alive()
        stop_thread.join(1)
        assert not stop_thread.is_alive()
        for path in ("/status", "/dashboard/api/relay/summary"):
            enrollment = client.get(path).json()["relay_wake"]["native_enrollment"]
            assert enrollment["state"] == "unavailable"
        service._drop()
        for path in ("/status", "/dashboard/api/relay/summary"):
            enrollment = client.get(path).json()["relay_wake"]["native_enrollment"]
            assert enrollment["state"] == "unavailable"
        assert (len(native.writes), len(native.owners)) == native_state
    finally:
        release.set()
        worker_release.set()
        if publisher is not None:
            publisher.join(1)
        if stop_thread is not None:
            stop_thread.join(1)
        worker.join(1)
    assert not worker.is_alive()


def test_real_enrollment_lifecycle_is_visible_on_both_http_views(client, retained, monkeypatch):
    service, request, natives = retained
    registry = client.app.state.codex_wake_registry
    registry.retained_service = service
    paths = ("/status", "/dashboard/api/relay/summary")

    def snapshots():
        result = []
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, response.text
            result.append(response.json()["relay_wake"]["native_enrollment"])
        return result

    def assert_state(state):
        views = snapshots()
        assert [view["state"] for view in views] == [state, state]
        serialized = json.dumps(views, ensure_ascii=False)
        for secret in (request["endpoint"], request["thread_ref"], request["turn_ref"], service.sid):
            assert secret not in serialized
        return views

    assert_state("never_registered")
    result = service._process(request, service.source, 0, float("inf"))
    assert result["status"] == "registered"
    assert_state("registered")

    durable_before = registry.reservations()
    native_before = len(natives)
    writes_before = len(natives[-1].writes)
    owners_before = len(natives[-1].owners)
    service._custody_lock.acquire()
    results, finished = [], threading.Event()
    def read_views():
        try:
            results.extend(snapshots())
        finally:
            finished.set()
    reader = threading.Thread(target=read_views, daemon=True)
    reader.start()
    try:
        assert finished.wait(2), "HTTP diagnostics waited for the native custody lock"
    finally:
        service._custody_lock.release()
        reader.join(2)
    assert not reader.is_alive() and [value["state"] for value in results] == ["registered", "registered"]
    assert registry.reservations() == durable_before and len(natives) == native_before
    assert len(natives[-1].writes) == writes_before and len(natives[-1].owners) == owners_before

    service._drop(preserve_registration=True)
    assert_state("retained_disconnected")
    continuity = service._process({**request, "sequence": 2, "continuity": None},
                                  service.source, 1, float("inf"))
    assert continuity["status"] == "registered" and len(continuity["continuity"]) == 64
    opted_in = assert_state("registered")
    assert opted_in[0]["continuity_opted_in"] and opted_in[1]["continuity_opted_in"]

    service.source.gone = True
    service._maintain()
    maintenance = assert_state("released")
    assert [(value["last_failure_stage"], value["last_failure_reason"]) for value in maintenance] == [
        ("maintenance", "peer-mismatch"), ("maintenance", "peer-mismatch"),
    ]
    service.source.gone = False
    assert service._process({**request, "sequence": 3}, service.source, 2, float("inf"))["status"] == "registered"
    assert_state("registered")
    service._clear_registration()
    assert_state("authority_cleared")
    service._drop()
    assert_state("released")

    with monkeypatch.context() as scoped:
        scoped.setattr(service, "_open_custody", lambda *a, **kw: (_ for _ in ()).throw(bridge.ShadowUnavailable("peer-mismatch")))
        denied = {**request, "sequence": 4}
        with pytest.raises(bridge.ShadowUnavailable):
            service._process(denied, service.source, 3, float("inf"))
    after_denial = assert_state("released")
    assert after_denial[0]["accepted"] and after_denial[1]["accepted"]
    assert after_denial[0]["last_failure_reason"] == after_denial[1]["last_failure_reason"] == "peer-mismatch"

    fresh = bridge.RetainedService(service.directory)
    fresh.w, fresh.sid, fresh.current, fresh.source = service.w, service.sid, service.current, service.source
    registry.retained_service = fresh
    assert_state("never_registered")
    with monkeypatch.context() as scoped:
        scoped.setattr(fresh, "_open_custody", lambda *a, **kw: (_ for _ in ()).throw(bridge.ShadowUnavailable("peer-mismatch")))
        with pytest.raises(bridge.ShadowUnavailable):
            fresh._process({**request, "epoch": fresh.epoch}, fresh.source, 0, float("inf"))
    before_acceptance_denial = assert_state("never_registered")
    assert before_acceptance_denial[0]["last_failure_reason"] == "peer-mismatch"

    registry.retained_service = service
    stopped_request = {**request, "sequence": 5}
    assert service._process(stopped_request, service.source, 4, float("inf"))["status"] == "registered"
    service.stop()
    assert_state("authority_cleared")
    service.stop()
    assert_state("authority_cleared")
    service._drop()
    assert_state("released")
    service._drop()
    assert_state("released")

    unresolved = bridge.RetainedService(service.directory)
    unresolved.w, unresolved.sid = service.w, service.sid
    unresolved.current, unresolved.source = service.current, service.source
    registry.retained_service = unresolved
    unresolved_request = {**request, "epoch": unresolved.epoch}
    assert unresolved._process(unresolved_request, unresolved.source, 0, float("inf"))["status"] == "registered"
    unresolved.custody.unresolved = True
    unresolved._drop()
    assert_state("unresolved_handles")


def test_dispatch_reopens_retained_registration_without_http_side_effects(client, http_wake):
    http, _, registry, service, desktop, send, _ = http_wake
    main_registry = client.app.state.codex_wake_registry
    main_registry.retained_service = service
    service._drop(preserve_registration=True)
    for path in ("/status", "/dashboard/api/relay/summary"):
        assert client.get(path).json()["relay_wake"]["native_enrollment"]["state"] == "retained_disconnected"

    before = (len(desktop.writes), len(desktop.owners))
    delivery = send()
    assert delivery["state"] == "pending"
    assert service.custody is not None and service.retained_registration is not None
    assert len(service.custody.owners) == 1
    for path in ("/status", "/dashboard/api/relay/summary"):
        response = client.get(path)
        assert response.status_code == 200
        enrollment = response.json()["relay_wake"]["native_enrollment"]
        assert enrollment["state"] == "registered"
        serialized = json.dumps(enrollment, ensure_ascii=False)
        for private in (r"\\.\pipe\desktop-private", "source-α", "turn-β", service.sid, "private-payload-東京"):
            assert private not in serialized
    assert len(desktop.writes) == before[0] and len(desktop.owners) == before[1]
    after_dispatch = http.get("/relay/messages/retained-journey", params=SCOPE).json()
    writes_after_dispatch = len(service.custody.writes)
    owners_after_dispatch = len(service.custody.owners)
    durable_after_dispatch = after_dispatch
    for path in ("/status", "/dashboard/api/relay/summary"):
        assert client.get(path).status_code == 200
    assert len(service.custody.writes) == writes_after_dispatch
    assert len(service.custody.owners) == owners_after_dispatch
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json() == durable_after_dispatch


def test_inherited_stop_timeout_invalidates_enrollment_evidence(client, retained):
    service, request, _ = retained
    assert service._process(request, service.source, 0, float("inf"))["status"] == "registered"
    client.app.state.codex_wake_registry.retained_service = service
    entered, release = threading.Event(), threading.Event()
    def blocked():
        entered.set()
        release.wait()
    worker = threading.Thread(target=blocked, daemon=True)
    service.thread = worker
    worker.start()
    try:
        assert entered.wait(1)
        service.stop()
        assert service.unresolved
        assert service.enrollment_diagnostics() is None
        for path in ("/status", "/dashboard/api/relay/summary"):
            enrollment = client.get(path).json()["relay_wake"]["native_enrollment"]
            assert enrollment["state"] == "unavailable"
    finally:
        release.set()
        worker.join(1)
    assert not worker.is_alive()


def test_inherited_source_io_unresolved_invalidates_enrollment_evidence(
    client, retained, monkeypatch,
):
    service, request, _ = retained
    assert service._process(request, service.source, 0, float("inf"))["status"] == "registered"
    client.app.state.codex_wake_registry.retained_service = service
    monkeypatch.setattr(bridge, "_retained", [])
    w = SimpleNamespace(
        con=SimpleNamespace(FILE_FLAG_OVERLAPPED=4),
        pipe=SimpleNamespace(
            PIPE_ACCESS_DUPLEX=1, PIPE_TYPE_MESSAGE=2, PIPE_READMODE_MESSAGE=4,
            PIPE_WAIT=8, PIPE_REJECT_REMOTE_CLIENTS=16,
            CreateNamedPipe=lambda *args: 91,
            GetNamedPipeClientProcessId=lambda handle: 40,
            DisconnectNamedPipe=lambda handle: None,
        ),
        event=SimpleNamespace(WaitForSingleObject=lambda *args: 258,
                              WAIT_OBJECT_0=0, WAIT_TIMEOUT=258),
    )
    class BrokenIO:
        def __init__(self, *_args):
            self.unresolved = False
        def accept(self, _deadline):
            self.unresolved = True
            raise bridge.ShadowUnavailable("transport-failed")
        def close(self):
            pass
    monkeypatch.setattr(bridge, "_native", lambda: w)
    monkeypatch.setattr(bridge, "_self_sid", lambda _w: service.sid)
    monkeypatch.setattr(bridge, "_check_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge, "_lock_file", lambda *_args: 92)
    monkeypatch.setattr(bridge, "_security_attributes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge, "_atomic_private", lambda *_args: None)
    monkeypatch.setattr(bridge, "_PipeIO", BrokenIO)
    service._run()
    assert service.unresolved and service.enrollment_diagnostics() is None
    for path in ("/status", "/dashboard/api/relay/summary"):
        enrollment = client.get(path).json()["relay_wake"]["native_enrollment"]
        assert enrollment["state"] == "unavailable"

@pytest.fixture
def http_wake(client, retained, monkeypatch):
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    registry = CodexWakeRegistry(relay_service=relay)
    assert registry.initialize(old_owner_drained=True)
    service, desktop = register(retained)
    registry.retained_service = service
    workers = []
    original = codex_wake._schedule_reserved_codex_relay_wake
    def schedule(*args, **kwargs):
        worker = original(*args, **kwargs)
        if worker:
            workers.append(worker)
        return worker
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", schedule)
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)
    app = FastAPI()
    app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                   codex_wake_registry=registry))
    http = TestClient(app)
    for runtime, session in (("claude-code", "sender"), ("codex", TARGET)):
        assert http.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE}).status_code == 200
    body = {"sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": f"codex:{TARGET}",
            "message_id": "retained-journey", "payload": "private-payload-東京", **SCOPE}
    def send():
        deadline = time.monotonic() + 2.0
        response = http.post("/relay/messages", json=body)
        try:
            response_body = response.json()
        except ValueError:
            response_body = None
        detail = response_body.get("detail") if isinstance(response_body, dict) else None
        if (response.status_code == 503 and isinstance(detail, dict)
                and detail.get("code") == "relay_busy" and detail.get("retryable") is True):
            try:
                delay = int(response.headers["Retry-After"])
            except (KeyError, ValueError):
                delay = -1
            remaining = deadline - time.monotonic()
            if 0 <= delay <= remaining:
                time.sleep(delay)
                if time.monotonic() < deadline:
                    response = http.post("/relay/messages", json=body)
        assert response.status_code == 200, response.text
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive(), "native wake blocked hook/registry"
        return response.json()["deliveries"][0]
    yield http, relay, registry, service, desktop, send, workers
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    http.close()

def recover(journey):
    _, relay, registry, _, _, _, workers = journey
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=registry)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()

@pytest.mark.parametrize("state", ["working", "unknown", "future", None, [], {}])
def test_pending_busy_or_unknown_releases_and_recovers(http_wake, state):
    http, _, registry, service, desktop, send, _ = http_wake
    desktop.state = state
    delivery = send()
    assert desktop.owners == [] and registry.reservations() == ()
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "pending"
    if service.custody is None:
        request = {"version": 1, "verb": "register", "epoch": service.epoch, "sequence": 2,
                   "thread_ref": "source-α", "turn_ref": "turn-β", "endpoint": r"\\.\pipe\desktop-private"}
        assert service._process(request, service.source, 1, float("inf"))["status"] == "registered"
        desktop = service.custody
    desktop.state = "notLoaded"
    recover(http_wake)
    assert len(desktop.owners) == 1
    assert registry.snapshot(delivery["recipient_endpoint_id"]).outcome == "uncertain"
    recover(http_wake)
    assert len(desktop.owners) == 1

@pytest.mark.parametrize("body", ["{}", "bad-json", "[]", '{"schemaVersion":1,"schemaVersion":1}',
    json.dumps({"schemaVersion": True, "thread": {"id": TARGET, "kind": "codex", "hostId": "local", "status": {"type": "notLoaded"}}}),
    *[json.dumps({"schemaVersion": 1, "thread": {"id": TARGET, "kind": "codex", "hostId": "local", "status": {"type": "notLoaded"}, **change}})
      for change in ({"id": "other"}, {"kind": "chatgpt"}, {"hostId": "remote"}, {"status": "notLoaded"})]])
def test_malformed_descriptor_never_writes_owner(http_wake, body, caplog):
    _, _, registry, _, desktop, send, _ = http_wake
    desktop.body = body
    send()
    assert desktop.owners == [] and registry.reservations() == ()
    assert "private-" not in caplog.text

@pytest.mark.parametrize("fault", ["lost", "malformed", "native-error", None])
def test_write_is_fenced_across_concurrency_recovery_restart(http_wake, fault):
    http, relay, registry, service, desktop, send, _ = http_wake
    desktop.response = fault
    errors = []
    def run():
        try:
            send()
        except Exception as error:
            errors.append(error)
    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert errors == []
    assert len(desktop.owners) == 1
    recover(http_wake)
    assert len(desktop.owners) == 1
    restarted = CodexWakeRegistry(relay_service=relay)
    restarted.retained_service = service
    assert restarted.reservations()[0].outcome == "uncertain"
    assert codex_wake.schedule_codex_relay_wake({"recipient": f"codex:{TARGET}", "deliveries": [
        {**http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0],
         "recipient_session_ref": TARGET, "recipient_runtime": "codex"}]}, SCOPE,
        relay_service=relay, registry=restarted) is None
    assert len(desktop.owners) == 1
    read = next(v for v in desktop.writes if v.get("params", {}).get("tool") == "read_thread")
    assert read["params"]["arguments"] == {"threadId": TARGET, "turnLimit": 1,
        "includeOutputs": False, "maxOutputCharsPerItem": 1}
    owner = desktop.owners[0]
    assert owner["params"]["threadId"] == "source-α" and owner["params"]["turnId"] == "turn-β"
    assert set(owner["params"]["arguments"]) == {"threadId", "prompt"}

def test_http_retryable_busy_once_keeps_one_delivery_and_owner(http_wake, monkeypatch):
    http, relay, registry, _, desktop, send, _ = http_wake
    storage = relay._store
    original = storage._begin_relay_immediate
    attempts = 0

    @contextmanager
    def busy_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ImmediateTransactionBusyError("database is locked")
        with original() as db:
            yield db

    monkeypatch.setattr(storage, "_begin_relay_immediate", busy_once)
    delivery = send()

    status = http.get("/relay/messages/retained-journey", params=SCOPE)
    assert status.status_code == 200
    assert attempts >= 2
    assert len(status.json()["deliveries"]) == 1
    assert status.json()["deliveries"][0]["delivery_id"] == delivery["delivery_id"]
    assert len(desktop.owners) == 1
    reservations = registry.reservations()
    assert len(reservations) == 1 and reservations[0].outcome == "uncertain"

def test_http_retryable_busy_exhaustion_stays_closed(http_wake, monkeypatch):
    http, relay, registry, _, desktop, send, _ = http_wake
    original = relay._store._begin_relay_immediate
    attempts = 0

    @contextmanager
    def always_busy():
        nonlocal attempts
        attempts += 1
        raise ImmediateTransactionBusyError("database is locked")
        yield  # pragma: no cover

    monkeypatch.setattr(relay._store, "_begin_relay_immediate", always_busy)
    with pytest.raises(AssertionError, match="relay_busy"):
        send()

    assert attempts == 2
    monkeypatch.setattr(relay._store, "_begin_relay_immediate", original)
    assert http.get("/relay/messages/retained-journey", params=SCOPE).status_code == 404
    assert desktop.owners == [] and registry.reservations() == ()

def test_http_nonbusy_error_is_not_retried(http_wake, monkeypatch):
    http, relay, registry, _, desktop, send, _ = http_wake
    attempts = 0

    @contextmanager
    def invalid_request():
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid request")
        yield  # pragma: no cover

    monkeypatch.setattr(relay._store, "_begin_relay_immediate", invalid_request)
    with pytest.raises(AssertionError, match="422"):
        send()

    assert attempts == 1
    assert desktop.owners == [] and registry.reservations() == ()

@pytest.mark.parametrize("body, retry_after", [
    (b"not-json", "1"),
    (b'{"detail":"malformed"}', "1"),
    (b'{"detail":{"code":"other","retryable":true}}', "1"),
    (b'{"detail":{"code":"relay_busy","retryable":false}}', "1"),
    (b'{"detail":{"code":"relay_busy","retryable":true}}', "3"),
])
def test_http_send_rejects_malformed_or_out_of_budget_busy(http_wake, monkeypatch, body, retry_after):
    _, _, registry, _, desktop, send, _ = http_wake
    requests = []

    def post(*args, **kwargs):
        requests.append(kwargs["json"])
        return httpx.Response(503, headers={"Retry-After": retry_after}, content=body)

    monkeypatch.setattr(http_wake[0], "post", post)
    with pytest.raises(AssertionError, match="503"):
        send()

    assert len(requests) == 1
    assert desktop.owners == [] and registry.reservations() == ()

def test_failed_spend_has_zero_owner_calls(http_wake, monkeypatch):
    _, _, registry, _, desktop, send, _ = http_wake
    monkeypatch.setattr(registry, "begin_native_attempt", lambda *a: None)
    send()
    assert desktop.owners == [] and registry.reservations() == ()

def test_owner_response_allows_hook_claim_ack_before_return(http_wake):
    http, _, registry, _, desktop, send, _ = http_wake
    received, errors = [], []
    def on_owner(request):
        def hook():
            try:
                delivery_id = request["params"]["arguments"]["prompt"].split()[4].rstrip(".")
                response = http.post("/relay/turn", json={"runtime": "codex", "session_ref": TARGET,
                    "wake_delivery_id": delivery_id, **SCOPE})
                assert response.status_code == 200
                claimed = response.json()["deliveries"][0]
                received.append(claimed["payload"])
                assert http.post("/relay/deliveries/ack", json={"delivery_id": delivery_id,
                    "claim_token": claimed["claim_token"], **SCOPE}).status_code == 200
            except Exception as error:
                errors.append(error)
        callback = threading.Thread(target=hook)
        callback.start()
        callback.join(1)
        assert not callback.is_alive(), "registry lock held across native response"
    desktop.on_owner = on_owner
    send()
    assert errors == [] and received == ["private-payload-東京"]
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"
    assert registry.reservations() == ()

@pytest.mark.parametrize("loss", ["source", "desktop", "channel", "epoch", "unresolved"])
def test_connection_loss_defers_without_owner(http_wake, loss):
    _, _, registry, service, desktop, send, _ = http_wake
    if loss == "source":
        service.source.gone = True
    elif loss == "desktop":
        service.desktop.gone = True
    elif loss == "channel":
        service._drop()
    elif loss == "epoch":
        registry.retained_service = bridge.RetainedService(Path("new-epoch"))
    else:
        desktop.unresolved = True
    send()
    assert desktop.owners == [] and registry.reservations() == ()

@pytest.mark.parametrize("change", [{"epoch": "wrong"}, {"sequence": True}, {"thread_ref": ""},
    {"turn_ref": "x" * 256}, {"endpoint": "not-a-pipe"}, {"extra": "data"}])
def test_registration_invalid_context_never_opens_desktop(retained, change):
    service, request, natives = retained
    with pytest.raises(bridge.ShadowUnavailable):
        service._process({**request, **change}, service.source, 0, float("inf"))
    assert natives == []

@pytest.mark.parametrize("image", ["Codex.exe", "ChatGPT.exe"])
def test_registration_rejects_unrelated_same_user_desktop_and_closes(retained, monkeypatch, image):
    service, request, natives = retained
    monkeypatch.setattr(bridge, "_process_image", lambda *args: (str(Path("C:/Apps") / image), "1.2.3.4"))
    monkeypatch.setattr(bridge, "_parent_pids", lambda: {42: 41, 41: 39})
    with pytest.raises(bridge.ShadowUnavailable):
        service._process(request, service.source, 0, float("inf"))
    assert natives[0].closed and service.custody is None and service.ancestors == []
    assert natives[0].owners == []

@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"threadId": "runtime-α", "turnId": "turn-β"}, None,
    {"threadId": "runtime-α", "turnId": "turn-β", "x-codex-turn-metadata": {"session_id": "other"}}])
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("worker_present", [False, True])
async def test_ordinary_mcp_relay_captures_context_without_new_tool(monkeypatch, metadata, failed, worker_present, capsys):
    calls = []
    class Worker:
        async def register(self, caller):
            calls.append(caller)
            if failed:
                raise RuntimeError("private-capability-sentinel")
            return {"status": "registered", "reason": "ok", "endpoint": "private-capability-sentinel"}
    @asynccontextmanager
    async def lifespan(server):
        yield {"codex_retained": Worker()} if worker_present else {}
    class Client:
        def __init__(self, ctx):
            pass
        async def relay_status(self, *args, **kwargs):
            return {"message_id": "message", "payload": "", "deliveries": [], "payload_offset": 0,
                    "next_offset": None, "payload_total_chars": 0, "content_truncated": False}
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:19836")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", SCOPE["container_ref"])
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", Client)
    server = mcp_server.create_server(lifespan=lifespan, codex_retained=True)
    assert [t.model_dump() for t in await server.list_tools()] == [t.model_dump() for t in await mcp_server.create_server().list_tools()]
    async def call(session):
        result = await session.call_tool("pallium_relay_status", {"message_id": "message"}, meta=metadata)
        assert not result.isError, result
    await _serve_protocol(server, call)
    valid = bool(metadata) and "x-codex-turn-metadata" not in metadata
    assert calls == ([{"thread_ref": "runtime-α", "turn_ref": "turn-β"}] if valid and worker_present else [])
    diagnostic = capsys.readouterr().err
    expected = ("retained-register-exception" if metadata is None else
                "retained-caller-absent" if not valid else
                "retained-worker-absent" if not worker_present else
                "retained-register-exception" if failed else "retained-register-registered-ok")
    assert expected in diagnostic
    assert all(secret not in diagnostic for secret in ("private-capability-sentinel", "runtime-α", "turn-β", "message"))

def test_default_setup_and_http_transport_isolation(monkeypatch):
    assert "PALLIUM_CODEX_AUTOMATIC_WAKE" not in setup_codex._mcp_env_toml(19836)
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private")
    assert not mcp_server._codex_retained_enabled("streamable-http")
    assert not mcp_server._codex_retained_enabled("sse")



def _hook_runner(http, monkeypatch, state, events, tmp_path):
    script = "user_prompt_submit" if state == "idle" else "session_start"
    # Restore the previous alias (including absence) for existing hook state isolation.
    monkeypatch.setitem(sys.modules, "codex_common", sys.modules.get("codex_common"))
    hook = _load("retained_" + script, "integrations/codex/hooks/" + script + ".py")
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *a: "actor")
    if state == "idle":
        monkeypatch.setattr(hook, "resolve_container_ref", lambda *a: SCOPE["container_ref"])
        monkeypatch.setattr(hook, "discover_work_refs", lambda *a: hook._common.WorkRefDiscovery())
        monkeypatch.setattr(hook, "record_codex_hook_execution", lambda **k: None)
        monkeypatch.setattr(hook, "record_codex_wake_event", lambda **k: None)
    else:
        monkeypatch.setattr(hook, "derive_container_ref", lambda *a: SCOPE["container_ref"])
        monkeypatch.setattr(hook, "pin_container", lambda *a, **k: None)
        monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *a: [])
    def relay(method, path, body, **kwargs):
        response = http.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()
    monkeypatch.setattr(hook, "relay_request", relay)
    original_emit = hook.emit_context
    def emit(text, event):
        original_emit(text, event)
        events.append(("emit", event, text))
    monkeypatch.setattr(hook, "emit_context", emit)
    def ack(deliveries, *, container_ref):
        assert events and events[-1][0] == "emit"
        for delivery in deliveries:
            response = http.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"], "container_ref": container_ref})
            assert response.status_code == 200
        events.append(("ack",))
        return deliveries
    monkeypatch.setattr(hook, "acknowledge_relay", ack)
    def run(prompt="natural resume"):
        monkeypatch.setattr(hook, "read_hook_input", lambda: {
            "cwd": ".", "session_id": TARGET, "source": "resume", "prompt": prompt})
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0
    return run


@pytest.mark.parametrize("state,event", [("idle", "UserPromptSubmit"), ("notLoaded", "SessionStart")])
def test_selected_transport_actual_hook_emits_then_acks(http_wake, monkeypatch, capsys, state, event, tmp_path):
    http, _, registry, _, desktop, send, _ = http_wake
    desktop.state = state
    events, queues = [], []
    hook = _hook_runner(http, monkeypatch, state, events, tmp_path)
    if state == "idle":
        class Process:
            returncode = 0
            def communicate(self, **kwargs):
                hook(queues[-1][1])
                return None, ""
        def launch(session, prompt):
            queues.append((session, prompt))
            return Process(), None
        monkeypatch.setattr(codex_wake, "_start_launch", launch)
    else:
        desktop.on_owner = lambda request: hook(request["params"]["arguments"]["prompt"])
    send()
    assert [e[0] for e in events] == ["emit", "ack"]
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["hookEventName"] == event
    assert "private-payload-東京" in output["hookSpecificOutput"]["additionalContext"]
    assert len(queues) == (state == "idle") and len(desktop.owners) == (state == "notLoaded")
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"
    assert registry.reservations() == ()
    send()
    assert len(events) == 2


@pytest.mark.parametrize("first_outcome", ["accepted", "uncertain"])
@pytest.mark.parametrize("restart", [False, True])
def test_spent_wake_retries_after_cooldown_and_real_hook_acks_backlog(
    client, http_wake, monkeypatch, capsys, tmp_path, first_outcome, restart,
):
    from datetime import datetime, timedelta, timezone

    import storage.sqlite_relay as sqlite_relay

    http, relay, registry, service, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or now[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    desktop.state = "idle"
    events, prompts = [], []
    hook = _hook_runner(http, monkeypatch, "idle", events, tmp_path)

    class Process:
        returncode = 0

        def communicate(self, **kwargs):
            hook(prompts[-1])
            return None, ""

    def launch(session, prompt):
        prompts.append(prompt)
        if len(prompts) == 1 and first_outcome == "uncertain":
            return None, ("ambiguous", "timeout", None)
        if len(prompts) == 1:
            process = type("Accepted", (), {
                "returncode": 0,
                "communicate": lambda self, **kwargs: (None, ""),
            })()
            return process, None
        return Process(), None

    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    first = send()
    first_fence = registry.snapshot(first["recipient_endpoint_id"])
    assert first_fence is not None and first_fence.outcome == first_outcome
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "pending"

    response = http.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": f"codex:{TARGET}", "message_id": "retained-followup",
        "payload": "later-payload-東京", **SCOPE,
    })
    assert response.status_code == 200, response.text
    later = response.json()
    now[0] += timedelta(seconds=59)

    restarted = registry
    if restart:
        restarted = CodexWakeRegistry(relay_service=relay)
        assert restarted.initialize(old_owner_drained=True)
        restarted.retained_service = service
        app = FastAPI()
        app.include_router(build_router(
            client.app.state.pallium_service,
            relay_storage=client.app.state.pallium_service._storage,
            codex_wake_registry=restarted,
        ))
        http.close()
        http = TestClient(app)
        events.clear()
        hook = _hook_runner(http, monkeypatch, "idle", events, tmp_path)

    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=restarted)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert len(prompts) == 1
    now[0] += timedelta(seconds=2)
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=restarted)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()

    assert len(prompts) == 3  # Initial wake, recovered wake, then the next hook batch.
    assert [event[0] for event in events] == ["emit", "ack", "emit", "ack"]
    assert "private-payload-東京" in events[0][2]
    assert "later-payload-東京" in events[2][2]
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"
    assert http.get(f"/relay/messages/{later['message_id']}", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"
    assert restarted.reservations() == ()
    assert not codex_wake._scheduled_delivery_ids
    assert not codex_wake._scheduled_session_generations
    assert not codex_wake._scheduled_session_delivery_ids
    assert not codex_wake._scheduled_session_attempt_ids
    capsys.readouterr()


def test_busy_target_does_not_slide_due_retry_deadline(http_wake, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import storage.sqlite_relay as sqlite_relay

    http, relay, registry, _, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or now[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    launches = []
    def launch(*args):
        launches.append(args)
        return SimpleNamespace(returncode=0, communicate=lambda **_kwargs: (None, "")), None
    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    desktop.state = "idle"
    delivery = send()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    initial = registry.snapshot(delivery["recipient_endpoint_id"])
    assert initial is not None and initial.outcome == "accepted"
    original_deadline = initial.retry_not_before
    assert original_deadline is not None
    assert len(launches) == 1

    now[0] += timedelta(seconds=61)
    desktop.state = "working"
    recover(http_wake)
    assert len(launches) == 1
    busy = registry.snapshot(delivery["recipient_endpoint_id"])
    assert busy is not None and busy.generation == initial.generation
    assert busy.outcome == "accepted" and busy.retry_not_before == original_deadline

    desktop.state = "idle"
    recover(http_wake)
    recovered = registry.snapshot(delivery["recipient_endpoint_id"])
    assert recovered is not None and recovered.generation > initial.generation
    assert recovered.outcome == "accepted" and recovered.retry_not_before > original_deadline
    assert len(launches) == 2

    now[0] += timedelta(seconds=61)
    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    assert claim.json()["deliveries"][0]["delivery_id"] == delivery["delivery_id"]
    recover(http_wake)
    active = registry.snapshot(delivery["recipient_endpoint_id"])
    assert active == recovered and len(launches) == 2


@pytest.mark.parametrize("claim_mode", ["active", "acked"])
def test_retry_cas_loses_to_hook_claim_after_fresh_native_read(http_wake, monkeypatch, claim_mode):
    from datetime import datetime, timedelta, timezone

    import storage.sqlite_relay as sqlite_relay

    http, _, registry, _, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or now[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    launches = []
    monkeypatch.setattr(codex_wake, "_start_launch", lambda *args: (
        launches.append(args) or SimpleNamespace(
            returncode=0, communicate=lambda **_kwargs: (None, ""),
        ), None,
    ))
    desktop.state = "idle"
    delivery = send()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    spent = registry.snapshot(delivery["recipient_endpoint_id"])
    assert spent is not None and spent.outcome == "accepted"
    now[0] += timedelta(seconds=61)

    def claim_before_rearm():
        desktop.on_state = None
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": TARGET, **SCOPE,
        })
        assert response.status_code == 200, response.text
        claimed = response.json()["deliveries"][0]
        assert claimed["delivery_id"] == delivery["delivery_id"]
        if claim_mode == "acked":
            ack = http.post("/relay/deliveries/ack", json={
                "delivery_id": claimed["delivery_id"],
                "claim_token": claimed["claim_token"], **SCOPE,
            })
            assert ack.status_code == 200, ack.text

    desktop.on_state = claim_before_rearm
    recover(http_wake)
    assert len(launches) == 1
    if claim_mode == "active":
        current = registry.snapshot(delivery["recipient_endpoint_id"])
        assert current == spent
        assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "claimed"
    else:
        assert registry.snapshot(delivery["recipient_endpoint_id"]) is None
        assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"


def test_concurrent_spent_retry_rearm_spends_one_new_generation(http_wake, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.claude_wake import ClaudeWakeRegistry
    import storage.sqlite_relay as sqlite_relay

    _, relay, registry, _, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or now[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    launches = []
    def launch(*args):
        launches.append(args)
        return SimpleNamespace(returncode=0, communicate=lambda **_kwargs: (None, "")), None
    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    desktop.state = "idle"
    delivery = send()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    spent = registry.snapshot(delivery["recipient_endpoint_id"])
    assert spent is not None and spent.outcome == "accepted"
    now[0] += timedelta(seconds=61)
    start = threading.Barrier(3)
    errors = []
    def recover_concurrently():
        start.wait(timeout=2)
        try:
            recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=registry)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=recover_concurrently) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2)
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()

    assert errors == []
    assert len(launches) == 2  # One initial notification and exactly one concurrent recovery write.
    replacement = registry.snapshot(delivery["recipient_endpoint_id"])
    assert replacement is not None and replacement.generation > spent.generation
    assert replacement.outcome == "accepted"
    assert registry.begin_native_attempt(spent) is None
    assert registry.run_if_current(spent, lambda: pytest.fail("stale spent generation submitted")) == (False, None)


@pytest.mark.parametrize("contention", ["released", "held", "exhausted"])
@pytest.mark.parametrize("script", ["session_start", "user_prompt_submit"])
def test_session_start_lock_budget_claims_emits_and_acks_once(
    http_wake, monkeypatch, capsys, tmp_path, contention, script,
):
    http, _, _, _, desktop, send, _ = http_wake
    desktop.state = "working"  # Enqueue without a native wake in this hook test.
    sent = send()
    monkeypatch.setitem(sys.modules, "codex_common", sys.modules.get("codex_common"))
    hook = _load("lock_budget_" + script, "integrations/codex/hooks/" + script + ".py")
    common = hook._common
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "lock-budget-sessions")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": ".", "session_id": TARGET, "source": "resume",
        "prompt": codex_wake._wake_prompt(sent["delivery_id"])})
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *a: "actor")
    if script == "session_start":
        monkeypatch.setattr(hook, "derive_container_ref", lambda *a: SCOPE["container_ref"])
        monkeypatch.setattr(hook, "pin_container", lambda *a, **k: None)
        monkeypatch.setattr(hook, "_fetch_retrieval_fallback", lambda *a: [])
    else:
        monkeypatch.setattr(hook, "resolve_container_ref", lambda *a: SCOPE["container_ref"])
        monkeypatch.setattr(hook, "discover_work_refs", lambda *a: common.WorkRefDiscovery())
        monkeypatch.setattr(hook, "record_codex_hook_execution", lambda **k: None)
        monkeypatch.setattr(hook, "record_codex_wake_event", lambda **k: None)
    calls = []
    timeouts = []

    def request(method, path, body, **kwargs):
        calls.append(path)
        if path == "/relay/turn":
            timeouts.append(kwargs["timeout"])
        response = http.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(hook, "relay_request", request)
    monkeypatch.setattr(common, "relay_request", request)  # Real ACK helper.
    if contention != "released":
        # Exhaust the request allowance, not the independent suppression output.
        clock = (lambda: 10.0) if contention == "exhausted" else time.monotonic
        monkeypatch.setattr(hook, "start_hook_deadline", lambda *a, **k:
            common.start_hook_deadline(1.4 if contention == "held" else 0.5, clock=clock))
    lock = common._acquire_session_lock(TARGET)
    assert lock is not None
    release = threading.Timer(0.3, common._release_session_lock, args=(lock,))
    if contention == "released":
        acquire = common._acquire_session_lock
        def start_release_on_wait(*args, **kwargs):
            if kwargs.get("deadline") is not None and release.ident is None:
                release.start()
            return acquire(*args, **kwargs)
        monkeypatch.setattr(common, "_acquire_session_lock", start_release_on_wait)
    started = time.monotonic()
    try:
        with pytest.raises(SystemExit) as exited:
            hook.main()
        assert exited.value.code == 0
    finally:
        if contention == "released":
            release.join(2)
            assert not release.is_alive()
        else:
            common._release_session_lock(lock)
    assert time.monotonic() - started < 2
    if contention == "held":
        assert time.monotonic() - started >= 0.3  # Actually waited on the held lock.
    emitted = json.loads(capsys.readouterr().out)
    if script == "user_prompt_submit" and contention != "released":
        assert emitted["decision"] == "block"
        output = ""
    else:
        output = emitted["hookSpecificOutput"]["additionalContext"]
        assert SCOPE["container_ref"] in output
    delivery = http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]
    if contention == "released":
        assert "private-payload-東京" in output
        assert calls == ["/relay/turn", "/relay/deliveries/ack"]
        if script == "user_prompt_submit":
            assert 0 < timeouts[0] <= 1.8  # The lock wait consumes the existing 2s cap.
        assert delivery["state"] == "delivered" and delivery["attempts"] == 1
        with pytest.raises(SystemExit):
            hook.main()
        assert "private-payload-東京" not in capsys.readouterr().out
        assert calls == ["/relay/turn", "/relay/deliveries/ack", "/relay/turn"]
        assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["attempts"] == 1
    else:
        assert calls == [] and "private-payload-東京" not in output
        assert delivery["state"] == "pending" and delivery["attempts"] == 0


@pytest.mark.parametrize("limit", ["timeout", "global", "provided"])
@pytest.mark.parametrize("exhausted_at", [None, "lock", "bootstrap"])
def test_relay_lock_and_scope_recovery_share_one_deadline(
    monkeypatch, tmp_path, limit, exhausted_at,
):
    common = _load("lock_budget_common", "integrations/codex/hooks/common.py")
    monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path)
    now = [10.0]
    clock = lambda: now[0]
    common.start_hook_deadline(1 if limit == "global" else 5, clock=clock)
    deadline = common.HookDeadline(11, clock=clock) if limit == "provided" else None
    (tmp_path / (TARGET + ".json")).write_text(json.dumps({
        "container_ref": "git:example.test/old"}), encoding="utf-8")
    acquire = common._acquire_session_lock

    def acquire_after_wait(*args, **kwargs):
        lock = acquire(*args, **kwargs)
        now[0] += 1 if exhausted_at == "lock" else 0.25
        return lock

    monkeypatch.setattr(common, "_acquire_session_lock", acquire_after_wait)
    calls = []

    def request(method, path, body, *, timeout, **kwargs):
        calls.append((body, timeout))
        now[0] += 1 if exhausted_at == "bootstrap" else 0.25
        return {"session": {"endpoint_id": "relay-session-budget",
            "container_ref": body["container_ref"],
            "scope_generation": 0 if len(calls) == 1 else 1}, "deliveries": []}

    result = common.relay_turn("codex", TARGET, SCOPE["container_ref"],
        timeout=1 if limit == "timeout" else 5, deadline=deadline, request=request)
    assert len(calls) == (0 if exhausted_at == "lock" else 1 if exhausted_at == "bootstrap" else 2)
    if calls:
        assert calls[0][1] == pytest.approx(0.75)
        assert calls[0][0]["register_session"] is False
    if exhausted_at is None:
        assert calls[1][1] == pytest.approx(0.5)
        assert result["session"]["container_ref"] == SCOPE["container_ref"]
    else:
        assert result is None
    # Even exhausted paths release the file lock.
    common.start_hook_deadline(1, clock=clock)
    lock = acquire(TARGET)
    assert lock is not None
    common._release_session_lock(lock)


def test_natural_hook_overtakes_state_check_without_owner_attempt(http_wake, monkeypatch, capsys, tmp_path):
    http, _, registry, _, desktop, send, _ = http_wake
    events = []
    desktop.on_state = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    send()
    assert [e[0] for e in events] == ["emit", "ack"]
    assert desktop.owners == [] and registry.reservations() == ()
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"
    capsys.readouterr()


def test_queue_wait_allows_fresh_registration_and_disconnect(http_wake, retained, monkeypatch):
    _, _, registry, service, desktop, send, _ = http_wake
    desktop.state = "idle"
    entered, release = threading.Event(), threading.Event()
    queues = []
    class Process:
        returncode = 0
        def communicate(self, **kwargs):
            entered.set()
            assert release.wait(2)
            return None, ""
    def launch(*args):
        queues.append(args)
        return Process(), None
    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert entered.wait(1)
        request = {**retained[1], "sequence": 2, "turn_ref": "fresh-turn"}
        registered = []
        check = threading.Thread(target=lambda: registered.append(service._process(request, service.source, 1, float("inf"))))
        check.start()
        check.join(.5)
        assert not check.is_alive() and registered[0]["status"] == "registered"
        service._drop()
        assert service.custody is None
        assert registry.reservations()[0].outcome == "uncertain"
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and len(queues) == 1 and desktop.owners == []


@pytest.mark.parametrize("result", [("ambiguous", "timeout", None), ("failed", "os_error", None)])
def test_idle_queue_uncertainty_never_falls_back(http_wake, monkeypatch, result):
    _, _, registry, _, desktop, send, _ = http_wake
    desktop.state = "idle"
    queues = []
    def launch(*args):
        queues.append(args)
        return None, result
    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    send()
    recover(http_wake)
    assert len(queues) == 1 and desktop.owners == [] and registry.reservations()[0].outcome == "uncertain"


@pytest.mark.asyncio
async def test_fresh_runtime_request_reenrolls_after_service_epoch_change(monkeypatch, tmp_path):
    from app.mcp import codex_desktop_bridge as lifecycle
    epoch = [1]
    calls, disposed = [], threading.Event()
    class Native:
        def __init__(self, path, stop, *, retained):
            assert retained
            self.epoch = epoch[0]
            calls.append(("connect", self.epoch))
        def ready(self):
            return {"status": "ready", "reason": "ready"}
        def register(self, metadata):
            if self.epoch != epoch[0]:
                return {"status": "unavailable", "reason": "closed"}
            calls.append(("register", dict(metadata)))
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            disposed.set()
    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    monkeypatch.setattr(bridge, "retained_directory", lambda **kwargs: tmp_path)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:19836")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", SCOPE["container_ref"])
    class Client:
        def __init__(self, ctx): pass
        async def relay_status(self, *args, **kwargs):
            return {"payload": "", "deliveries": [], "payload_offset": 0,
                    "payload_total_chars": 0, "content_truncated": False, "next_offset": None}
    monkeypatch.setattr(mcp_server, "PalliumMcpClient", Client)
    server = mcp_server.create_server(lifespan=mcp_server._codex_retained_lifespan, codex_retained=True)
    async def exercise(session):
        async def call(turn):
            result = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                meta={"threadId": "actual-runtime", "turnId": turn})
            assert not result.isError
        await call("first")
        epoch[0] = 2
        await call("expired")
        for _ in range(100):
            if disposed.is_set(): break
            await asyncio.sleep(.01)
        assert disposed.is_set()
        await call("fresh")
    await _serve_protocol(server, exercise)
    assert calls == [("connect", 1), ("register", {"thread_ref": "actual-runtime", "turn_ref": "first"}),
                     ("connect", 2), ("register", {"thread_ref": "actual-runtime", "turn_ref": "fresh"})]
    assert disposed.is_set()

@pytest.mark.parametrize("fault", ["start", "stop", None])
def test_retained_service_failure_keeps_existing_http_lifecycle_live(monkeypatch, request, caplog, fault):
    calls = []
    class Worker:
        def stop(self):
            calls.append("stop")
            if fault == "stop":
                raise RuntimeError("private-shutdown-sentinel")
    def start():
        calls.append("start")
        if fault == "start":
            raise RuntimeError("private-startup-sentinel")
        return Worker()
    monkeypatch.setattr(bridge, "start_retained_service", start)
    with request.getfixturevalue("client") as http:
        for path in ("/health", "/status", "/debug/queue/health"):
            assert http.get(path).status_code == 200
        registry = http.app.state.codex_wake_registry
    assert registry.retained_service is None
    assert calls == (["start"] if fault == "start" else ["start", "stop"])
    assert "private-" not in caplog.text



@pytest.mark.parametrize("base_url,port", [("http://localhost:19836", 19836),
    ("http://127.0.0.1:19837/", 19837), ("http://[::1]:24680", 24680)])
def test_configured_local_port_selects_exact_private_service(base_url, port):
    path = bridge.retained_bootstrap_path(base_url)
    assert path == bridge.retained_directory(port=port) / "active.json"
    assert path != bridge.retained_directory(port=port + 1) / "active.json"


@pytest.mark.parametrize("base_url", [None, "", "http://localhost", "https://localhost:19836",
    "http://remote.example:19836", "http://localhost.remote.example:19836",
    "http://user@localhost:19836", "http://localhost:19836/api", "http://localhost:19836?x=1",
    "http://localhost:19836#x", "http://localhost:0", "http://localhost:65536",
    " http://localhost:19836", "http://localhost:invalid",
    "http://local\nhost:19836", "http://local\thost:19836", "http://local\rhost:19836"])
def test_unbound_or_remote_mcp_cannot_enroll_local_custody(base_url):
    with pytest.raises(bridge.ShadowUnavailable):
        bridge.retained_bootstrap_path(base_url)


@pytest.mark.parametrize("port", [None, True, 0, 65536, "19836"])
def test_invalid_actual_service_port_never_publishes_custody(port):
    with pytest.raises(bridge.ShadowUnavailable):
        bridge.retained_directory(port=port)

@pytest.mark.asyncio
@pytest.mark.parametrize("request_metadata", [False, True])
async def test_retained_lifespan_waits_for_fresh_caller_before_acquiring_source_slot(monkeypatch, tmp_path, request_metadata):
    from app.mcp import codex_desktop_bridge as lifecycle
    calls = []
    connected = threading.Event()
    class Native:
        def __init__(self, path, stop, *, retained):
            assert retained
            calls.append("connect")
            connected.set()
        def ready(self):
            calls.append("ready")
            return {"status": "ready", "reason": "ready"}
        def register(self, metadata):
            calls.append(("register", dict(metadata)))
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            calls.append("dispose")
    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(bridge, "retained_directory", lambda **kwargs: tmp_path)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:19836")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private")
    metadata = {"thread_ref": "actual-source", "turn_ref": "fresh-turn"}
    async with lifecycle.retained_lifespan(None) as state:
        worker = state["codex_retained"]
        assert not await asyncio.to_thread(connected.wait, .15)
        assert calls == []
        if request_metadata:
            result = await asyncio.wait_for(worker.register(metadata), .5)
            assert result["status"] == "registered"
            assert calls == ["connect", "ready", ("register", metadata)]
    assert not worker._thread.is_alive()
    assert calls == (["connect", "ready", ("register", metadata), "dispose"] if request_metadata else [])

@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["open", "ready"])
async def test_retained_first_caller_completes_when_native_startup_fails(monkeypatch, failure):
    from app.mcp import codex_desktop_bridge as lifecycle
    calls = []
    class Native:
        def __init__(self, path, stop, *, retained):
            calls.append("connect")
            if failure == "open":
                raise RuntimeError("private-native-failure")
        def ready(self):
            return {"status": "unavailable"}
        def register(self, metadata):
            pytest.fail("failed startup must not register")
        def dispose(self):
            calls.append("dispose")
    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private")
    worker = lifecycle.InventoryWorker(Path("private-bootstrap"), retained=True)
    try:
        result = await asyncio.wait_for(worker.register({"thread_ref": "source", "turn_ref": "actual-turn"}), .5)
        assert result["status"] == "unavailable"
    finally:
        await worker.stop()
    assert not worker._thread.is_alive()
    assert calls == (["connect"] if failure == "open" else ["connect", "dispose"])

@pytest.mark.parametrize("wake", [None, "1"])
@pytest.mark.parametrize("capability", [False, True])
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
def test_retained_startup_diagnostic_reports_gate_without_private_values(monkeypatch, capsys, wake, capability, transport):
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", transport)
    monkeypatch.delenv("PALLIUM_CODEX_BRIDGE_MODE", raising=False)
    if wake:
        monkeypatch.setenv("PALLIUM_CODEX_AUTOMATIC_WAKE", wake)
    else:
        monkeypatch.delenv("PALLIUM_CODEX_AUTOMATIC_WAKE", raising=False)
    if capability:
        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private-capability-sentinel")
    else:
        monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH", raising=False)
    options = {}
    monkeypatch.setattr(mcp_server, "create_server", lambda **kwargs: (
        options.update(kwargs) or SimpleNamespace(run=lambda **kwargs: None)))
    mcp_server.main()
    diagnostic = capsys.readouterr().err
    enabled = transport == "stdio" and capability
    assert options.get("codex_retained", False) == enabled
    expected = (f"Pallium Codex bridge inert: retained-{'enabled' if enabled else 'disabled'}\n" if transport == "stdio" else "")
    if transport == "stdio" and not capability:
        expected += "Pallium Codex bridge inert: retained-no-host-pipe\n"
    assert diagnostic == expected
    assert "private-capability-sentinel" not in diagnostic


@pytest.mark.parametrize("mode", ["inert", "shadow", "inventory"])
def test_default_retained_detection_preserves_explicit_finite_modes(monkeypatch, mode):
    monkeypatch.setattr(mcp_server.sys, "platform", "win32")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "private-capability-sentinel")
    monkeypatch.setenv("PALLIUM_CODEX_BRIDGE_MODE", mode)
    assert not mcp_server._codex_retained_enabled("stdio")


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_retained_service_default_is_windows_only_without_enablement_flag(monkeypatch, platform):
    monkeypatch.setattr(bridge.sys, "platform", platform)
    monkeypatch.delenv("PALLIUM_CODEX_AUTOMATIC_WAKE", raising=False)
    assert bridge.retained_wake_enabled() == (platform == "win32")


@pytest.mark.parametrize("image", ["Codex.exe", "ChatGPT.exe"])
def test_registration_accepts_supported_actual_pipe_server_ancestor_image(retained, monkeypatch, image):
    checked = []
    def process_image(w, handle):
        checked.append(handle)
        return str(Path("C:/Apps") / image), "1.2.3.4"
    monkeypatch.setattr(bridge, "_process_image", process_image)
    service, desktop = register(retained)
    assert service.custody is desktop and service.read_tool and service.owner_tool_before
    assert checked == [40]
    assert desktop.owners == []


@pytest.mark.parametrize("image", ["Other.exe", "Codex.exe.bak", "ChatGPT.exe.bak"])
def test_registration_rejects_wrong_or_spoofed_pipe_server_image(retained, monkeypatch, image):
    service, request, natives = retained
    monkeypatch.setattr(bridge, "_process_image", lambda *args: (str(Path("C:/Apps") / image), "1.2.3.4"))
    with pytest.raises(bridge.ShadowUnavailable):
        service._process(request, service.source, 0, float("inf"))
    assert service.custody is None and service.ancestors == []
    assert natives[0].closed and natives[0].owners == []


@pytest.mark.parametrize("fault", ["success-int", "missing-success", "old-mcp", "old-mcp-error",
    "failed-missing-items", "failed-empty-items", "failed-extra-items", "failed-wrong-item",
    "failed-nonstring-text", "failed-public-content", "failed-public-iserror-false",
    "failed-wrong-id", "failed-wrong-version", "empty-items",
    "extra-items", "wrong-item", "nonstring-text", "rpc-error", "wrong-id", "wrong-version"])
def test_native_state_read_contract_failure_releases_without_transport(http_wake, monkeypatch, fault):
    http, _, registry, service, desktop, send, _ = http_wake
    original_read = desktop.read
    def read(deadline):
        envelope = original_read(deadline)
        if desktop.writes[-1].get("params", {}).get("tool") != "read_thread":
            return envelope
        result = envelope["result"]
        item = result["contentItems"][0]
        results = {
            "success-int": {**result, "success": 1},
            "missing-success": {"contentItems": [item]},
            "old-mcp": {"success": True, "content": [{"type": "text", "text": item["text"]}]},
            "old-mcp-error": {"success": False, "isError": True,
                              "content": [{"type": "text", "text": "private native failure"}]},
            "failed-missing-items": {"success": False},
            "failed-empty-items": {"success": False, "contentItems": []},
            "failed-extra-items": {"success": False, "contentItems": [item, item]},
            "failed-wrong-item": {"success": False, "contentItems": [{**item, "type": "text"}]},
            "failed-nonstring-text": {"success": False, "contentItems": [{**item, "text": {}}]},
            "failed-public-content": {"success": False, "contentItems": [item], "content": []},
            "failed-public-iserror-false": {"success": False, "contentItems": [item], "isError": False},
            "empty-items": {"success": True, "contentItems": []},
            "extra-items": {"success": True, "contentItems": [item, item]},
            "wrong-item": {"success": True, "contentItems": [{**item, "type": "text"}]},
            "nonstring-text": {"success": True, "contentItems": [{**item, "text": {}}]},
        }
        if fault in {"wrong-id", "failed-wrong-id"}:
            if fault == "failed-wrong-id":
                envelope["result"] = {**result, "success": False}
            envelope["id"] += 1
        elif fault in {"wrong-version", "failed-wrong-version"}:
            if fault == "failed-wrong-version":
                envelope["result"] = {**result, "success": False}
            envelope["jsonrpc"] = "1.0"
        elif fault in results:
            envelope["result"] = results[fault]
        elif fault == "rpc-error":
            envelope["error"] = {"code": -1}
        elif fault == "wrong-id":
            envelope["id"] += 1
        else:
            envelope["jsonrpc"] = "1.0"
        return envelope
    monkeypatch.setattr(desktop, "read", read)
    send()
    assert desktop.owners == [] and registry.reservations() == ()
    assert service.retained_registration is None
    delivery = http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]
    assert delivery["state"] == "pending" and delivery["attempts"] == 0
