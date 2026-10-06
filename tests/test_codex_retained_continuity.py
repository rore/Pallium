"""Retained registration continuity stays private and identity-bound."""

import hashlib
import json
import re
import threading
from copy import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import codex_bridge_pipe as bridge
from tests.test_codex_retained_wake import retained as _retained_fixture


@pytest.fixture
def retained(monkeypatch, tmp_path):
    yield from _retained_fixture.__wrapped__(monkeypatch, tmp_path)


CALLER = {"thread_ref": "source-α", "turn_ref": "turn-β"}
CONTINUITY = "continuity"
FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


def _register(retained, continuity=..., *, caller=CALLER):
    service, request, _ = retained
    request = {**request, **caller}
    if continuity is not ...:
        request[CONTINUITY] = continuity
    return service._process(request, service.source, 0, float("inf"))


def test_legacy_registration_keeps_response_shape_and_inventory(retained):
    response = _register(retained)
    assert set(response) == {
        "mode", "status", "reason", "ttl_seconds", "connected", "inventory_ok", "source_exited",
    }
    assert response["status"] == "registered" and response["inventory_ok"] is True
    assert retained[0].read_tool and retained[0].owner_tool_before


def test_opted_in_registration_returns_one_private_fingerprint(retained):
    response = _register(retained, None)
    assert response["status"] == "registered"
    assert set(response) == {
        "mode", "status", "reason", "ttl_seconds", "connected", "inventory_ok", "source_exited", CONTINUITY,
    }
    assert isinstance(response[CONTINUITY], str) and FINGERPRINT.fullmatch(response[CONTINUITY])
    expected = hashlib.sha256(json.dumps(
        (retained[0].source.pid, retained[0].source.creation,
         retained[0]._registration_identity(retained[0].desktop, retained[0].ancestors)),
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert response[CONTINUITY] == expected
    assert CONTINUITY not in bridge.NativeInventoryClient._public(response)


def test_original_fingerprint_registers_again_in_new_service_epoch(retained):
    service, request, _ = retained
    first = _register(retained, None)
    replacement = bridge.RetainedService(service.directory)
    replacement.w, replacement.sid = service.w, service.sid
    replacement.current, replacement.source = service.current, service.source
    try:
        resumed = replacement._process(
            {**request, "epoch": replacement.epoch, CONTINUITY: first[CONTINUITY]},
            replacement.source, 0, float("inf"))
        assert resumed["status"] == "registered"
        assert resumed[CONTINUITY] == first[CONTINUITY]
        assert replacement.retained_registration["source"] is replacement.source
    finally:
        replacement.stop_event.set()
        replacement._drop()


@pytest.mark.parametrize("component", [
    "source-pid", "source-creation", "desktop-pid", "desktop-creation", "desktop-sid",
    "desktop-image", "desktop-version", "ancestor-order", "ancestor-creation",
])
def test_new_epoch_identity_change_denies_before_catalog_read(retained, monkeypatch, component):
    service, request, _ = retained
    first = _register(retained, None)
    replacement = bridge.RetainedService(service.directory)
    replacement.w, replacement.sid = service.w, service.sid
    replacement.current, replacement.source = service.current, copy(service.source)
    if component == "source-pid":
        replacement.source.pid += 1
        monkeypatch.setattr(bridge, "_parent_pids", lambda: {43: 41, 41: 40})
    elif component == "source-creation":
        replacement.source.creation += "changed"
    else:
        original_identity = replacement._registration_identity
        replacement._registration_identity = lambda desktop, ancestors: _changed_identity(
            original_identity(desktop, ancestors), component)

    catalog_reads = []
    original_io = bridge._DesktopIO

    def track_catalog(*args):
        io = original_io(*args)
        read = io.read
        io.read = lambda deadline: (catalog_reads.append(True), read(deadline))[1]
        return io

    monkeypatch.setattr(bridge, "_DesktopIO", track_catalog)
    try:
        with pytest.raises(bridge.ShadowUnavailable):
            replacement._process(
                {**request, "epoch": replacement.epoch, CONTINUITY: first[CONTINUITY]},
                replacement.source, 0, float("inf"))
        assert catalog_reads == []
        assert replacement.caller is None and replacement.custody is None
    finally:
        replacement.stop_event.set()
        replacement._drop()


def _changed_identity(identity, component):
    changed = list(identity)
    if component == "desktop-pid":
        changed[0] += 1
    elif component == "desktop-creation":
        changed[1] += "changed"
    elif component == "desktop-sid":
        changed[2] += "-changed"
    elif component == "desktop-image":
        changed[3] += ".changed"
    elif component == "desktop-version":
        changed[4] += ".changed"
    else:
        ancestors = list(changed[5])
        if component == "ancestor-order":
            ancestors = list(reversed(ancestors))
            if len(ancestors) == 1:
                ancestors = [(999, "extra"), *ancestors]
            changed[5] = tuple(ancestors)
        else:
            pid, creation = ancestors[0]
            ancestors[0] = (pid, creation + "changed")
            changed[5] = tuple(ancestors)
    return tuple(changed)


@pytest.mark.parametrize("component", [
    "source-pid", "source-creation", "desktop-pid", "desktop-creation", "desktop-sid",
    "desktop-image", "desktop-version", "ancestor-order", "ancestor-creation",
])
def test_open_custody_identity_change_cannot_update_caller_or_remain_accepted(retained, component):
    service, _, _ = retained
    registered = _register(retained, None)
    original_caller = service.caller
    assert registered["status"] == "registered"
    if component == "source-pid":
        service.source.pid += 1
    elif component == "source-creation":
        service.source.creation += "changed"
    else:
        identity = service._registration_identity(service.desktop, service.ancestors)
        service._registration_identity = lambda desktop, ancestors: _changed_identity(identity, component)

    with pytest.raises(bridge.ShadowUnavailable):
        _register(retained, registered[CONTINUITY], caller={**CALLER, "turn_ref": "different-turn"})
    assert service.caller != {**CALLER, "turn_ref": "different-turn"}
    assert service.custody is None


@pytest.mark.parametrize("proof", ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65, 17, False, [], {}])
def test_invalid_opt_in_proof_denies_before_catalog_or_caller_update(retained, proof):
    service, request, natives = retained
    read_calls = []
    original_open = service._open_custody

    def open_custody(*args, **kwargs):
        read_calls.append("catalog")
        return original_open(*args, **kwargs)

    service._open_custody = open_custody
    with pytest.raises(bridge.ShadowUnavailable):
        _register(retained, proof)
    assert read_calls == [] and service.caller is None and service.custody is None
    assert natives == []


def _fake_client(monkeypatch, response):
    client = bridge.NativeInventoryClient.__new__(bridge.NativeInventoryClient)
    client.stop_event = threading.Event()
    client.w = SimpleNamespace()
    client.writes = []
    client.io = SimpleNamespace(
        write=lambda request, deadline: client.writes.append(request),
        read=lambda deadline: dict(response), unresolved=False)
    client.bootstrap_path = Path("private-bootstrap")
    client.sid = "same-user"
    client.manifest = {"version": 1, "pid": 1, "creation": "service", "epoch": "epoch", "pipe": "private"}
    client.peer = SimpleNamespace(check=lambda: None, handle=1)
    client.source = SimpleNamespace(check=lambda: None)
    client.sequence = 0
    client.retained = True
    client.continuity = None
    client.unresolved = False
    monkeypatch.setattr(bridge, "_read_private", lambda *args: json.dumps(client.manifest).encode())
    return client


def _client_response(**extra):
    return {
        "mode": "inventory", "status": "registered", "reason": "ok", "ttl_seconds": 60,
        "connected": True, "inventory_ok": True, "source_exited": False,
        "version": 1, "epoch": "epoch", "sequence": 1, **extra,
    }


@pytest.mark.parametrize("proof", [None, "", "A" * 64, "g" * 64, "a" * 63, "a" * 65, 17, False, [], {}])
def test_opt_in_exchange_rejects_malformed_fingerprint(monkeypatch, proof):
    client = _fake_client(monkeypatch, _client_response(**{CONTINUITY: proof}))
    with pytest.raises(bridge.ShadowUnavailable, match="invalid-response"):
        client._exchange("register", **CALLER, endpoint=r"\\.\pipe\private", continuity=None)


def test_opt_in_exchange_rejects_fingerprint_on_non_registered_status(monkeypatch):
    client = _fake_client(monkeypatch, _client_response(status="unavailable", **{CONTINUITY: "a" * 64}))
    with pytest.raises(bridge.ShadowUnavailable, match="invalid-response"):
        client._exchange("register", **CALLER, endpoint=r"\\.\pipe\private", continuity=None)


def test_unrequested_fingerprint_is_rejected_on_legacy_exchange(monkeypatch):
    client = _fake_client(monkeypatch, _client_response(**{CONTINUITY: "a" * 64}))
    client.retained = False
    with pytest.raises(bridge.ShadowUnavailable, match="invalid-response"):
        client._exchange("ready")


def test_finite_inventory_exchange_keeps_its_original_response_shape(monkeypatch):
    response = _client_response()
    client = _fake_client(monkeypatch, response)
    client.retained = False
    assert client._exchange("ready") == response


def test_native_register_saves_validated_proof_but_drops_it_from_public_output(monkeypatch):
    fingerprint = "a" * 64
    client = _fake_client(monkeypatch, _client_response(**{CONTINUITY: fingerprint}))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", r"\\.\pipe\private")
    result = client.register(CALLER)
    assert result["status"] == "registered"
    assert CONTINUITY not in result and client.continuity == fingerprint
    assert client.writes[0][CONTINUITY] is None


def test_native_register_does_not_save_proof_without_registered_status(monkeypatch):
    client = _fake_client(monkeypatch, _client_response(status="unavailable", reason="closed"))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", r"\\.\pipe\private")
    result = client.register(CALLER)
    assert result["status"] == "unavailable"
    assert client.continuity is None and CONTINUITY not in result


@pytest.mark.parametrize("contradiction", [
    {"reason": "timeout"}, {"connected": False},
    {"inventory_ok": False}, {"source_exited": True},
])
def test_registered_proof_requires_positive_live_custody(monkeypatch, contradiction):
    client = _fake_client(monkeypatch, _client_response(continuity="a" * 64, **contradiction))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", r"\\.\pipe\private")
    with pytest.raises(bridge.ShadowUnavailable, match="invalid-response"):
        client.register(CALLER)
    assert client.continuity is None


def test_service_liveness_requires_conclusive_old_service_exit(monkeypatch):
    client = _fake_client(monkeypatch, _client_response())
    client.w.event = SimpleNamespace(WAIT_OBJECT_0=0, WAIT_TIMEOUT=258,
        WaitForSingleObject=lambda handle, timeout: 0)
    assert client.service_current() is False


@pytest.mark.parametrize("state", [0xFFFFFFFF, 128])
def test_service_liveness_does_not_treat_wait_errors_as_exit(monkeypatch, state):
    client = _fake_client(monkeypatch, _client_response())
    client.w.event = SimpleNamespace(WAIT_OBJECT_0=0, WAIT_TIMEOUT=258,
        WaitForSingleObject=lambda handle, timeout: state)
    with pytest.raises(bridge.ShadowUnavailable, match="peer-unavailable"):
        client.service_current()


def test_service_liveness_requires_source_and_exact_manifest(monkeypatch):
    client = _fake_client(monkeypatch, _client_response())
    client.w.event = SimpleNamespace(WAIT_OBJECT_0=0, WAIT_TIMEOUT=258,
        WaitForSingleObject=lambda handle, timeout: 258)
    assert client.service_current() is True
    monkeypatch.setattr(bridge, "_read_private", lambda *args: b'{"changed":true}')
    with pytest.raises(bridge.ShadowUnavailable, match="peer-mismatch"):
        client.service_current()

    def source_gone():
        raise bridge.ShadowUnavailable("peer-gone")

    client.source.check = source_gone
    with pytest.raises(bridge.ShadowUnavailable, match="peer-gone"):
        client.service_current()


def _constructor_fakes(monkeypatch, manifest, *, pipe_error=None):
    peers, opens = [], []

    class Peer:
        def __init__(self, _w, pid, sid, creation=None):
            self.pid, self.sid, self.creation, self.handle = pid, sid, creation, pid
            self.closed = False
            peers.append(self)

        def check(self):
            pass

        def close(self):
            self.closed = True

    class PipeError(Exception):
        winerror = 2

    file_api = SimpleNamespace(
        CreateFile=lambda *args: (opens.append(args) or (_ for _ in ()).throw(PipeError())) if pipe_error else 90,
        SECURITY_IDENTIFICATION=1,
    )
    w = SimpleNamespace(
        con=SimpleNamespace(GENERIC_READ=1, GENERIC_WRITE=2, OPEN_EXISTING=3,
            FILE_FLAG_OVERLAPPED=4, SECURITY_SQOS_PRESENT=8),
        file=file_api,
        pipe=SimpleNamespace(PIPE_READMODE_MESSAGE=1, SetNamedPipeHandleState=lambda *args: None,
            GetNamedPipeServerProcessId=lambda handle: manifest["pid"]),
        event=SimpleNamespace(WAIT_TIMEOUT=258, WAIT_OBJECT_0=0,
            WaitForSingleObject=lambda handle, timeout: 258),
    )
    monkeypatch.setattr(bridge, "_native", lambda: w)
    monkeypatch.setattr(bridge, "_self_sid", lambda _w: "same-user")
    monkeypatch.setattr(bridge, "_Peer", Peer)
    monkeypatch.setattr(bridge, "_read_private", lambda *args: json.dumps(manifest).encode())
    monkeypatch.setattr(bridge, "_PipeIO", lambda *args: SimpleNamespace(unresolved=False, close=lambda: None))
    return peers, opens, w


def _manifest(epoch="epoch"):
    return {"version": 1, "pid": 7, "creation": "service-creation", "epoch": epoch,
            "pipe": rf"\\.\pipe\pallium-inventory-{epoch}"}


def test_constructor_classifies_same_previous_manifest_as_retryable(monkeypatch, tmp_path):
    manifest = _manifest()
    peers, opens, _ = _constructor_fakes(monkeypatch, manifest)
    with pytest.raises(bridge.ShadowUnavailable) as error:
        bridge.NativeInventoryClient(tmp_path / "active.json", threading.Event(), retained=True,
                                     previous_manifest=manifest)
    assert error.value.category == "startup-unavailable"
    assert len(peers) == 1 and peers[0].closed and opens == []


def test_constructor_does_not_retry_a_malformed_previous_manifest(monkeypatch, tmp_path):
    manifest = {"version": 1, "pid": 7}
    peers, opens, _ = _constructor_fakes(monkeypatch, manifest)
    with pytest.raises(bridge.ShadowUnavailable) as error:
        bridge.NativeInventoryClient(tmp_path / "active.json", threading.Event(), retained=True,
                                     previous_manifest=manifest)
    assert error.value.category == "invalid-bootstrap"
    assert peers == [] and opens == []


def test_constructor_retries_only_a_valid_new_manifest_after_pipe_disappears(monkeypatch, tmp_path):
    manifest = _manifest("next-epoch")
    peers, opens, _ = _constructor_fakes(monkeypatch, manifest, pipe_error=True)
    with pytest.raises(bridge.ShadowUnavailable) as error:
        bridge.NativeInventoryClient(tmp_path / "active.json", threading.Event(), retained=True,
                                     previous_manifest=_manifest())
    assert error.value.category == "startup-unavailable"
    assert len(peers) == 2 and all(peer.closed for peer in peers) and len(opens) == 1


def test_constructor_retries_only_verified_missing_bootstrap(monkeypatch, tmp_path):
    peers, opens, w = _constructor_fakes(monkeypatch, _manifest())
    checks = []

    class Missing(Exception):
        winerror = 2

    def missing(_path):
        raise Missing()

    w.file.GetFileAttributes = missing
    monkeypatch.setattr(bridge, "_read_private", lambda *args: (_ for _ in ()).throw(
        bridge.ShadowUnavailable("file-unavailable")))
    monkeypatch.setattr(bridge, "_check_private_parent", lambda *args: checks.append(args))
    with pytest.raises(bridge.ShadowUnavailable) as error:
        bridge.NativeInventoryClient(tmp_path / "active.json", threading.Event(), retained=True)
    assert error.value.category == "startup-unavailable"
    assert len(checks) == 1 and peers == [] and opens == []


def test_constructor_does_not_retry_untrusted_bootstrap_failures(monkeypatch, tmp_path):
    peers, opens, _ = _constructor_fakes(monkeypatch, _manifest())
    checks = []
    monkeypatch.setattr(bridge, "_read_private", lambda *args: (_ for _ in ()).throw(
        bridge.ShadowUnavailable("unsafe-owner")))
    monkeypatch.setattr(bridge, "_check_private_parent", lambda *args: checks.append(args))
    with pytest.raises(bridge.ShadowUnavailable) as error:
        bridge.NativeInventoryClient(tmp_path / "active.json", threading.Event(), retained=True)
    assert error.value.category == "unsafe-owner"
    assert checks == [] and peers == [] and opens == []
