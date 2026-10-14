"""Recovery after a conclusively drained retained Desktop read failure."""
import pytest
import asyncio
import json
import threading

from tests.test_codex_retained_wake import (
    SCOPE, TARGET, _hook_runner, http_wake, recover, retained as retained_fixture,
)


@pytest.mark.asyncio
async def test_actual_mcp_idle_recovers_same_epoch_enrollment_without_replay(
        retained, monkeypatch, tmp_path):
    from app import codex_bridge_pipe as bridge
    from tests.test_codex_worker_reconnect import _protocol_server, _actual_status
    from tests.test_codex_mcp_desktop_bridge import _serve_protocol

    service, request, natives = retained
    manifest = {"epoch": service.epoch}
    registrations, operations = [], []
    recovered = threading.Event()
    healthy_observed = threading.Event()
    monkeypatch.setattr(bridge, "_read_private", lambda *a: json.dumps(manifest).encode())
    native_type = bridge.NativeInventoryClient

    class IO:
        unresolved = False

        def write(self, value, deadline):
            self.request = value

        def read(self, deadline):
            value = self.request
            result = service._process(value, service.source, value["sequence"] - 1, deadline)
            if value["verb"] == "register":
                registrations.append(dict(value))
                if len(registrations) == 2:
                    recovered.set()
            elif len(registrations) == 2 and result["connected"]:
                healthy_observed.set()
            return {**result, "version": 1, "epoch": service.epoch,
                    "sequence": value["sequence"]}

        def close(self):
            pass

    def native(path, stop, *, retained):
        client = object.__new__(native_type)
        client.w, client.sid = service.w, service.sid
        client.bootstrap_path, client.manifest = path, manifest
        client.stop_event, client.retained = stop, retained
        client.peer, client.source = service.current, service.source
        client.io, client.sequence = IO(), 0
        client.continuity, client.unresolved = None, False
        return client

    server = _protocol_server(monkeypatch, native, operations)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", request["endpoint"])

    async def exercise(session):
        assert not (await _actual_status(session, "first")).isError
        assert len(registrations) == 1 and len(natives) == 1
        with service._custody_lock:
            original = service.retained_registration
            assert original is not None
            continuity = service._continuity_fingerprint()
            # Preserve the initiating failure while testing resolved enrollment loss.
            service._drop(diagnostic_failure=("owner-result", "native-tool-failed"))
            assert service.retained_registration is None and service.custody is None
        assert await asyncio.to_thread(recovered.wait, 1)
        assert await asyncio.to_thread(healthy_observed.wait, 1)
        assert len(registrations) == 2 and len(operations) == 1
        assert registrations[1]["continuity"] == continuity
        assert service.epoch == manifest["epoch"]
        assert service.retained_registration["desktop_identity"] == original["desktop_identity"]
        assert service.enrollment_diagnostics()["last_failure_reason"] == "native-tool-failed"
        assert all(not desktop.owners for desktop in natives)
        assert not (await _actual_status(session, "fresh")).isError
        assert len(operations) == 2

    await _serve_protocol(server, exercise)


@pytest.mark.asyncio
@pytest.mark.parametrize("idle_result", [
    "healthy", "busy", "resolved-transport-failure", "resolved-deadline",
    "peer-mismatch", "invalid-response", "unresolved", "changed-pipe",
    "changed-bootstrap", "changed-continuity", "disposal-failure", "different-thread",
    "dispose-changed-pipe", "dispose-changed-bootstrap", "dispose-changed-continuity",
    "dispose-unresolved", "changed-source", "admission-register-failure",
])
async def test_actual_mcp_idle_ready_preserves_or_fences_source_channel(
    retained, monkeypatch, idle_result,
):
    from app import codex_bridge_pipe as bridge
    from app.mcp import codex_desktop_bridge as lifecycle
    from tests.test_codex_worker_reconnect import _protocol_server, _actual_status
    from tests.test_codex_mcp_desktop_bridge import _serve_protocol

    service, request, natives = retained
    source = service.source
    manifest = {"epoch": service.epoch}
    registrations, operations, workers, clients = [], [], [], []
    idle_observed, disposed = threading.Event(), threading.Event()
    native_type, worker_type = bridge.NativeInventoryClient, lifecycle.InventoryWorker
    monkeypatch.setattr(bridge, "_read_private", lambda *args: json.dumps(manifest).encode())

    class Worker(worker_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(lifecycle, "InventoryWorker", Worker)

    class IO:
        unresolved = False
        def write(self, value, deadline):
            self.request = value
        def read(self, deadline):
            value = self.request
            if value["verb"] == "ready" and registrations:
                idle_observed.set()
                if idle_result == "admission-register-failure":
                    service._drop()
                elif len(clients) == 1 and idle_result not in {"healthy", "busy"}:
                    if idle_result == "unresolved":
                        self.unresolved = True
                    elif idle_result == "changed-pipe":
                        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
                    elif idle_result == "changed-bootstrap":
                        manifest["epoch"] = "changed-epoch"
                    elif idle_result == "changed-continuity":
                        clients[0].continuity = "b" * 64
                    elif idle_result == "changed-source":
                        clients[0].source.gone = True
                    category = (idle_result if idle_result in {"peer-mismatch", "invalid-response"}
                                else "deadline" if idle_result == "resolved-deadline"
                                else "transport-failed")
                    raise bridge.ShadowUnavailable(category)
            if value["verb"] == "register" and registrations and idle_result == "admission-register-failure":
                raise bridge.ShadowUnavailable("transport-failed")
            result = service._process(value, service.source, value["sequence"] - 1, deadline)
            if value["verb"] == "register":
                registrations.append(dict(value))
            elif registrations and idle_result == "busy":
                result = {**result, "status": "unavailable", "reason": "busy"}
            return {**result, "version": 1, "epoch": service.epoch,
                    "sequence": value["sequence"]}
        def close(self):
            # The inherited loop EOF proof independently verifies this exact cleanup.
            service._drop()
            disposed.set()
            if idle_result == "disposal-failure":
                raise RuntimeError("controlled conclusive-disposal failure")
            if idle_result == "dispose-changed-pipe":
                monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
            elif idle_result == "dispose-changed-bootstrap":
                manifest["epoch"] = "changed-epoch"
            elif idle_result == "dispose-changed-continuity":
                clients[0].continuity = "b" * 64
            elif idle_result == "dispose-unresolved":
                self.unresolved = True

    def native(path, stop, *, retained):
        client = object.__new__(native_type)
        client.w, client.sid = service.w, service.sid
        client.bootstrap_path, client.manifest = path, dict(manifest)
        client.stop_event, client.retained = stop, retained
        from tests.test_codex_retained_wake import Peer
        client.peer = Peer(service.w, service.current.pid, creation=service.current.creation)
        client.source = Peer(service.w, source.pid, creation=source.creation)
        if clients:
            # The service's next accepted source handle names the same live process.
            service.source = Peer(service.w, source.pid, creation=source.creation)
        client.io, client.sequence = IO(), 0
        client.continuity, client.unresolved = None, False
        clients.append(client)
        return client

    server = _protocol_server(monkeypatch, native, operations)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", request["endpoint"])

    async def exercise(session):
        assert not (await _actual_status(session, "first")).isError
        assert len(registrations) == len(operations) == 1
        assert await asyncio.to_thread(idle_observed.wait, 1)
        worker, = workers
        if idle_result in {"resolved-transport-failure", "resolved-deadline", "different-thread"}:
            assert await asyncio.to_thread(disposed.wait, 1)
            assert not service.unresolved and not source.gone
            assert service.retained_registration is None and service.custody is None
            assert len(clients) == len(registrations) == 1, "idle retirement retried enrollment"
            if idle_result == "different-thread":
                fresh = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                    meta={"threadId": "different-runtime", "turnId": "fresh"})
                assert not fresh.isError
                await asyncio.to_thread(worker._thread.join, 1)
                assert not worker._thread.is_alive() and not worker._restart_allowed
                assert len(clients) == len(registrations) == 1
            else:
                assert not (await _actual_status(session, "fresh")).isError
                assert len(registrations) == 2 and len(operations) == 2
                assert registrations[1]["continuity"] == clients[0].continuity
                assert service.retained_registration is not None and service.custody is not None
        elif idle_result in {"healthy", "busy"}:
            assert worker._thread.is_alive() and worker._restart_allowed
            assert service.retained_registration is not None and service.custody is not None
            assert not disposed.is_set() and not source.gone
            assert len(registrations) == 1 and len(operations) == 1
        else:
            await asyncio.to_thread(worker._thread.join, 1)
            assert not worker._thread.is_alive() and not worker._restart_allowed
            assert not (await _actual_status(session, "fresh")).isError
            assert len(clients) == len(registrations) == 1 and len(operations) == 2
        assert all(not desktop.owners for desktop in natives)

    await _serve_protocol(server, exercise)


def test_missing_saved_registration_is_not_reported_as_peer_mismatch(retained):
    from app import codex_bridge_pipe as bridge
    service, _, _ = retained
    with pytest.raises(bridge.ShadowUnavailable) as failure:
        service._reopen_registration()
    assert failure.value.category == "registration-missing"
    assert bridge._inventory_reason(failure.value) == "native-failed"


@pytest.fixture
def retained(monkeypatch, tmp_path):
    yield from retained_fixture.__wrapped__(monkeypatch, tmp_path)


def _defer_on_state_timeout(http_wake, retained, bridge, *, unresolved=False, native_failure=False):
    http, _, _, service, first, send, _ = http_wake
    _, _, natives = retained
    first.state = "notLoaded"
    original_read = first.read

    def timeout_read(deadline):
        request = first.writes[-1]
        if request.get("params", {}).get("tool") == "read_thread":
            if native_failure:
                envelope = original_read(deadline)
                envelope["result"] = {"success": False, "contentItems": [
                    {"type": "inputText", "text": "private native failure sentinel"}]}
                first.unresolved = unresolved
                return envelope
            first.unresolved = unresolved
            raise bridge.ShadowUnavailable("deadline")
        return original_read(deadline)

    first.read = timeout_read
    send()
    return http, service, first, natives


def test_native_tool_failure_reopens_same_registration_for_hook_delivery(
        http_wake, retained, monkeypatch, capsys, tmp_path, client):
    from app import codex_bridge_pipe as bridge
    http, _, registry, service, first, send, _ = http_wake
    _, _, natives = retained
    events = []
    hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    original_read = first.read

    def unavailable_read(deadline):
        envelope = original_read(deadline)
        if first.writes[-1].get("params", {}).get("tool") == "read_thread":
            envelope["result"] = {"success": False, "contentItems": [
                {"type": "inputText", "text": "private native failure sentinel"}]}
        return envelope

    first.read = unavailable_read
    delivery = send()
    assert first.owners == [] and registry.reservations() == ()
    assert service.retained_registration is not None
    trace_executor = client.app.state.pallium_service._relay_trace_executor
    # Native-worker completion does not drain diagnostic writes.
    trace_executor.submit(lambda: None).result(timeout=2)
    pending = http.get("/relay/messages/retained-journey", params=SCOPE)
    assert pending.status_code == 200, pending.text
    pending_delivery = pending.json()["deliveries"][0]
    for field in ("delivery_id", "message_id", "recipient_endpoint_id"):
        assert pending_delivery[field] == delivery[field]
    assert pending_delivery["state"] == "pending" and pending_delivery["attempts"] == 0
    failure_log = capsys.readouterr().err
    assert "category=native-tool-failed" in failure_log
    assert "stage=state-read" in failure_log
    from app.codex_wake import relay_wake_log_refs
    delivery_ref, _, _ = relay_wake_log_refs(
        delivery["delivery_id"], TARGET, SCOPE["container_ref"])
    assert f"delivery_ref={delivery_ref}" in failure_log and "generation=1" in failure_log
    assert "timestamp=20" in failure_log and "+00:00" in failure_log
    assert "private native failure sentinel" not in failure_log

    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        desktop.on_owner = lambda request: hook(request["params"]["arguments"]["prompt"])
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", reconnect)
    recover(http_wake)

    assert len(natives) == 2 and natives[0].closed and len(natives[1].owners) == 1
    assert sum(w.get("params", {}).get("tool") == "read_thread" for w in first.writes) == 1
    assert sum(w.get("params", {}).get("tool") == "read_thread" for w in natives[1].writes) == 1
    assert [event[0] for event in events] == ["emit", "ack"]
    assert registry.reservations() == ()
    trace_executor.submit(lambda: None).result(timeout=2)
    delivered = http.get("/relay/messages/retained-journey", params=SCOPE)
    assert delivered.status_code == 200, delivered.text
    delivered_delivery = delivered.json()["deliveries"][0]
    for field in ("delivery_id", "message_id", "recipient_endpoint_id"):
        assert delivered_delivery[field] == delivery[field]
    assert delivered_delivery["state"] == "delivered" and delivered_delivery["attempts"] == 1


def test_drained_read_timeout_reopens_same_registration_for_hook_delivery(
        http_wake, retained, monkeypatch, capsys, tmp_path):
    from app import codex_bridge_pipe as bridge
    http, relay, registry, service, first, send, workers = http_wake
    _, _, natives = retained
    events = []
    hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)

    # Keep the initial prepared fence so the first recovery must resume it.
    release = registry.release_generation
    monkeypatch.setattr(registry, "release_generation", lambda reservation: False)
    _defer_on_state_timeout(http_wake, retained, bridge)
    monkeypatch.setattr(registry, "release_generation", release)
    reservations = registry.reservations()
    assert len(reservations) == 1 and reservations[0].outcome == "prepared"
    assert first.owners == []
    assert http.get("/relay/messages/retained-journey", params={"container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"

    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        desktop.on_owner = lambda request: hook(request["params"]["arguments"]["prompt"])
        if len(natives) == 2:
            original_read = desktop.read

            def timeout_read(deadline):
                request = desktop.writes[-1]
                if request.get("params", {}).get("tool") == "read_thread":
                    raise bridge.ShadowUnavailable("deadline")
                return original_read(deadline)

            desktop.read = timeout_read
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", reconnect)

    candidates = relay.wake_candidates
    worker_count = len(workers)

    def candidates_after_resume(*args, **kwargs):
        if kwargs.get("include_coalesced"):
            assert len(workers) == worker_count + 1
            workers[-1].join(2)
            assert not workers[-1].is_alive()
        return candidates(*args, **kwargs)

    monkeypatch.setattr(relay, "wake_candidates", candidates_after_resume)
    recover(http_wake)
    assert len(natives) == 2 and service.retained_registration is not None
    monkeypatch.setattr(relay, "wake_candidates", candidates)
    recover(http_wake)

    assert len(natives) == 3
    assert natives[0].closed and natives[1].closed and natives[2].owners
    assert [event[0] for event in events] == ["emit", "ack"]
    assert registry.reservations() == ()
    assert http.get("/relay/messages/retained-journey", params={"container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "delivered"
    assert "private-payload-東京" in capsys.readouterr().out


def test_reconnect_catalog_timeout_preserves_authority_for_next_recovery(http_wake, retained, monkeypatch):
    from app import codex_bridge_pipe as bridge
    _, service, _, natives = _defer_on_state_timeout(http_wake, retained, bridge)
    original_connect = bridge._DesktopIO

    def timeout_catalog(*args):
        desktop = original_connect(*args)
        original_read = desktop.read

        def read(deadline):
            if desktop.writes[-1].get("method") == "tools/list":
                raise bridge.ShadowUnavailable("deadline")
            return original_read(deadline)

        desktop.read = read
        return desktop

    monkeypatch.setattr(bridge, "_DesktopIO", timeout_catalog)
    recover(http_wake)
    assert len(natives) == 2 and service.retained_registration is not None

    monkeypatch.setattr(bridge, "_DesktopIO", original_connect)
    recover(http_wake)
    assert len(natives) == 3 and len(natives[2].owners) == 1


@pytest.mark.parametrize("initial_fault", ["timeout", "native-failure"])
@pytest.mark.parametrize("change", ["source", "epoch", "server", "schema", "unresolved"])
def test_reopen_denies_changed_registration_authority(
        http_wake, retained, monkeypatch, change, initial_fault):
    from app import codex_bridge_pipe as bridge

    http, service, _, natives = _defer_on_state_timeout(
        http_wake, retained, bridge, native_failure=initial_fault == "native-failure")
    original_connect = bridge._DesktopIO

    def reconnect(*args):
        desktop = original_connect(*args)
        if change == "schema":
            desktop.schemas = desktop.schemas[:1]
        return desktop

    if change == "source":
        service.source.gone = True
    elif change == "epoch":
        service.epoch = "changed-epoch"
    elif change == "unresolved":
        service.unresolved = True
    elif change == "server":
        monkeypatch.setattr(bridge, "_DesktopIO", reconnect)
        service.w.pipe.GetNamedPipeServerProcessId = lambda handle: 41
    elif change == "schema":
        monkeypatch.setattr(bridge, "_DesktopIO", reconnect)

    recover(http_wake)

    assert service.retained_registration is None
    assert not any(desktop.owners for desktop in natives)
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"


@pytest.mark.parametrize("native_failure", [False, True])
def test_unresolved_read_cancellation_clears_reopen_authority(http_wake, retained, native_failure):
    from app import codex_bridge_pipe as bridge

    _, service, _, natives = _defer_on_state_timeout(
        http_wake, retained, bridge, unresolved=True, native_failure=native_failure)
    assert service.unresolved and service.retained_registration is None
    assert len(natives) == 1


def test_stop_and_source_disconnect_clear_reopen_authority(http_wake, retained):
    from app import codex_bridge_pipe as bridge_module

    _, service, _, _ = _defer_on_state_timeout(http_wake, retained, bridge_module)
    service._drop()  # The retained source channel's EOF path uses the ordinary drop.
    assert service.retained_registration is None

    _, service, _, _ = _defer_on_state_timeout(http_wake, retained, bridge_module)
    service.stop()
    assert service.retained_registration is None and service.stop_event.is_set()


@pytest.mark.parametrize("response", ["lost", "native-error"])
def test_post_owner_failure_keeps_spent_delivery_fenced(http_wake, response, capsys):
    http, _, registry, _, desktop, send, _ = http_wake
    desktop.response = response
    send()
    assert len(desktop.owners) == 1
    assert registry.reservations()[0].outcome == "uncertain"
    recover(http_wake)
    assert len(desktop.owners) == 1
    if response == "native-error":
        failure_log = capsys.readouterr().err
        assert "category=native-tool-failed" in failure_log and "stage=owner-result" in failure_log
    assert http.get("/relay/messages/retained-journey", params={
        "container_ref": "git:example.test/retained-東京"}).json()["deliveries"][0]["state"] == "pending"
