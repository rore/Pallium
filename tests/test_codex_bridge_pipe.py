"""Temporary Windows kernel pipes; never the Desktop pipe or installed policy."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import codex_bridge_pipe as bridge

pytestmark = pytest.mark.slow
native = pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel pipe contract")


@pytest.fixture
def tmp_path(tmp_path):
    if sys.platform != "win32":
        yield tmp_path
        return
    # Python 3.13 mkdtemp adds OWNER RIGHTS; use the actual production private ACL.
    w = bridge._native()
    sid = bridge._self_sid(w)
    root = Path(__file__).resolve().parents[1] / "tmp"
    root.mkdir(exist_ok=True)
    directory = root / ("shadow-native-" + secrets.token_hex(16))
    bridge._secure_directory(w, directory, sid)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def policy(**changes):
    value = {
        "version": 1, "controller_runtime": "codex", "controller_thread_ref": "controller-α",
        "recipient_runtime": "codex", "recipient_endpoint_id": "relay-session-recipient",
        "recipient_session_ref": "recipient-β", "recipient_container_ref": "container-γ",
        "recipient_scope_generation": 2, "action": "shadow-only", "revision": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "revoked": False, "enabled": True,
    }
    value.update(changes)
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def provision(tmp_path, value=None, *, expected_revision=0):
    source = tmp_path / "operator-policy.json"
    source.write_bytes(encode(value or policy()))
    home = tmp_path / "isolated-home"
    bridge.provision_policy(source, home, expected_revision=expected_revision)
    return bridge.shadow_directory(home)


def wait_until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            pytest.fail("native worker did not reach expected state")
        time.sleep(.01)


@contextmanager
def running(tmp_path, *, value=None, snapshot=None, **kwargs):
    directory = provision(tmp_path, value)
    observations = []

    def observe(**scope):
        observations.append(scope)
        return {"endpoint_valid": True, "category": "eligible", "payload": "never-export-this"}

    service = bridge.ShadowService(directory, snapshot or observe, **kwargs)
    assert service.start() is service, "native APIs must be qualified on Windows"
    client = None
    try:
        wait_until(lambda: (directory / "active.json").exists() or service.stop_event.is_set())
        assert not service.stop_event.is_set(), "native service failed before publishing bootstrap"
        client = bridge.NativeShadowClient(directory / "active.json", threading.Event())
        yield service, client, directory, observations
    finally:
        if client is not None:
            client.dispose()
        service.stop()
        assert service.thread is not None and not service.thread.is_alive()
        assert service.grant is None
        assert not service.unresolved


def enroll(client):
    return client.enroll({"thread_ref": "controller-α", "turn_ref": "turn-δ"})


@pytest.mark.parametrize("raw", [b"", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b"{" * 2000],
                         ids=["empty", "array", "duplicate", "nonfinite", "invalid-utf8", "deep"])
def test_invalid_json_is_bounded(raw):
    with pytest.raises(bridge.ShadowUnavailable):
        bridge._json(raw)


@pytest.mark.parametrize("changes", [
    {"version": True}, {"action": "wake"}, {"controller_runtime": "other"},
    {"recipient_runtime": "other"}, {"recipient_endpoint_id": "alias"},
    {"revision": 0}, {"revision": True}, {"recipient_scope_generation": -1},
    {"enabled": 1}, {"revoked": "false"}, {"expires_at": "2026-01-01"},
    {"controller_thread_ref": " "}, {"recipient_session_ref": "x" * 256},
    {"recipient_container_ref": "bad\nname"}, {"unexpected": True},
])
def test_policy_rejects_invalid_fields(changes):
    with pytest.raises(bridge.ShadowUnavailable, match="invalid-policy"):
        bridge.ShadowPolicy.parse(encode(policy(**changes)))


def test_json_message_boundary_and_unicode_policy():
    assert bridge._json(b'{"a":"' + b"x" * (bridge.MAX_MESSAGE - 8) + b'"}')
    with pytest.raises(bridge.ShadowUnavailable, match="message-limit"):
        bridge._json(b" " * (bridge.MAX_MESSAGE + 1))
    parsed = bridge.ShadowPolicy.parse(encode(policy()))
    assert parsed.controller_thread_ref == "controller-α"
    assert parsed.valid(datetime.now(timezone.utc))


@native
def test_policy_private_acl_revision_and_owner_lock(tmp_path):
    directory = provision(tmp_path)
    w = bridge._native()
    sid = bridge._self_sid(w)
    for path in (directory, directory / "policy.json", directory / "policy.lock"):
        bridge._check_path(w, path, sid)
        descriptor = w.security.GetNamedSecurityInfo(
            str(path), w.security.SE_FILE_OBJECT,
            w.security.OWNER_SECURITY_INFORMATION | w.security.DACL_SECURITY_INFORMATION,
        )
        assert descriptor.GetSecurityDescriptorControl()[0] & 0x1000
        allowed = {w.security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorDacl().GetAce(i)[2])
                   for i in range(descriptor.GetSecurityDescriptorDacl().GetAceCount())}
        assert allowed == {sid, "S-1-5-18"}
    original = (directory / "policy.json").read_bytes()
    with pytest.raises(bridge.ShadowUnavailable, match="revision-conflict"):
        provision(tmp_path, policy(revision=2))
    assert (directory / "policy.json").read_bytes() == original
    provision(tmp_path, policy(revision=2), expected_revision=1)
    lock = bridge._lock_file(w, directory / "service.lock", sid)
    try:
        with pytest.raises(bridge.ShadowUnavailable, match="owner-busy"):
            bridge._lock_file(w, directory / "service.lock", sid)
    finally:
        bridge._close(lock)


@native
def test_native_enrollment_status_close_has_exact_scope_and_no_disclosure(tmp_path):
    with running(tmp_path) as (service, client, directory, calls):
        baseline = (directory / "policy.json").read_bytes()
        assert client.status() == {"mode": "shadow", "status": "inactive", "reason": "not-enrolled", "ttl_seconds": 0}
        result = enroll(client)
        assert result["status"] == "enrolled" and 0 < result["ttl_seconds"] <= 300
        assert set(result) == {"mode", "status", "reason", "ttl_seconds"}
        assert client.w.pipe.GetNamedPipeServerProcessId(client.io.handle) == os.getpid()
        assert client.status()["status"] == "eligible"
        assert len(calls) == 2
        assert all({k: v for k, v in call.items() if k != "deadline"} == {
            "endpoint_id": "relay-session-recipient", "runtime": "codex",
            "session_ref": "recipient-β", "container_ref": "container-γ", "scope_generation": 2,
        } for call in calls)
        assert "never-export-this" not in repr(result)
        assert client.close()["reason"] == "closed"
        wait_until(lambda: service.grant is None)
        assert (directory / "policy.json").read_bytes() == baseline
        assert sorted(p.name for p in directory.iterdir()) == ["active.json", "policy.json", "policy.lock", "service.lock"]


@native
@pytest.mark.parametrize("metadata", [{}, {"thread_ref": "other", "turn_ref": "turn"},
    {"thread_ref": "controller-α", "turn_ref": ""},
    {"thread_ref": "controller-α", "turn_ref": "turn", "extra": True}])
def test_controller_metadata_denied_before_snapshot(tmp_path, metadata):
    with running(tmp_path) as (service, client, _, calls):
        with pytest.raises(bridge.ShadowUnavailable, match="controller-mismatch"):
            client.enroll(metadata)
        assert service.grant is None and calls == []


@native
@pytest.mark.parametrize("changes", [{"revoked": True}, {"enabled": False},
    {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}, {"revision": 2}])
def test_policy_change_revokes_native_channel(tmp_path, changes):
    with running(tmp_path) as (service, client, directory, calls):
        enroll(client)
        current = json.loads((directory / "policy.json").read_bytes())
        current.update(changes)
        bridge._atomic_private(client.w, directory / "policy.json", bridge._self_sid(client.w), encode(current))
        with pytest.raises(bridge.ShadowUnavailable, match="policy-changed"):
            client.status()
        assert len(calls) == 1


@native
@pytest.mark.parametrize("fault", ["replay", "wrong-grant", "wrong-controller", "wrong-version", "extra-field"])
def test_invalid_native_request_disconnects_without_observation(tmp_path, fault):
    with running(tmp_path) as (service, client, _, calls):
        enroll(client)
        request = {"version": 1, "verb": "status", "epoch": client.epoch,
                   "policy_revision": client.policy.revision, "sequence": 2, "grant": client.grant}
        if fault == "replay":
            request["sequence"] = 1
        elif fault == "wrong-grant":
            request["grant"] = "invalid-grant"
        elif fault == "wrong-controller":
            request.update(verb="enroll", thread_ref="other", turn_ref="turn")
            del request["grant"]
        elif fault == "wrong-version":
            request["version"] = True
        else:
            request["extra"] = True
        deadline = time.monotonic() + 1
        client.io.write(request, deadline)
        with pytest.raises(bridge.ShadowUnavailable):
            client.io.read(deadline)
        wait_until(lambda: service.grant is None)
        assert len(calls) == 1


@native
def test_monotonic_lease_expiry_denies_and_drops_authority(tmp_path):
    now = [time.monotonic()]
    with running(tmp_path, clock=lambda: now[0]) as (service, client, _, calls):
        enroll(client)
        now[0] += bridge.LEASE_SECONDS + 1
        with pytest.raises(bridge.ShadowUnavailable):
            client.status()
        wait_until(lambda: service.grant is None)
        assert len(calls) == 1


@native
def test_idle_service_stop_cancels_kernel_accept_with_bounded_join(tmp_path):
    directory = provision(tmp_path)
    service = bridge.ShadowService(directory, lambda **_: pytest.fail("unexpected snapshot"))
    assert service.start() is service
    wait_until(lambda: (directory / "active.json").exists() or service.stop_event.is_set())
    assert not service.stop_event.is_set()
    started = time.monotonic()
    service.stop()
    assert time.monotonic() - started < .8
    assert not service.thread.is_alive() and not service.unresolved
    assert service.grant is None


@native
def test_restricted_token_cannot_read_private_policy_or_open_kernel_pipe(tmp_path):
    with running(tmp_path) as (_, client, directory, _):
        w = client.w
        token = w.security.OpenProcessToken(w.api.GetCurrentProcess(), w.con.TOKEN_ALL_ACCESS)
        restricted = w.security.CreateRestrictedToken(
            token, w.security.DISABLE_MAX_PRIVILEGE, [], [],
            [(w.security.CreateWellKnownSid(w.security.WinWorldSid, None), 0)],
        )
        manifest = json.loads((directory / "active.json").read_bytes())
        try:
            w.security.ImpersonateLoggedOnUser(restricted)
            for path in (str(directory / "policy.json"), manifest["pipe"]):
                with pytest.raises(w.types.error) as denied:
                    w.file.CreateFile(path, w.con.GENERIC_READ, 0, None, w.con.OPEN_EXISTING, 0, None)
                assert denied.value.winerror == 5
        finally:
            w.security.RevertToSelf()
            bridge._close(restricted)
            bridge._close(token)


@native
def test_first_pipe_instance_flag_rejects_competing_server(tmp_path):
    with running(tmp_path) as (_, client, directory, _):
        manifest = json.loads((directory / "active.json").read_bytes())
        w = client.w
        with pytest.raises(w.types.error) as conflict:
            w.pipe.CreateNamedPipe(
                manifest["pipe"], w.pipe.PIPE_ACCESS_DUPLEX | bridge.FIRST_PIPE_INSTANCE,
                w.pipe.PIPE_TYPE_MESSAGE | w.pipe.PIPE_READMODE_MESSAGE | w.pipe.PIPE_WAIT,
                1, 1024, 1024, 100, bridge._security_attributes(w, bridge._self_sid(w)),
            )
        assert conflict.value.winerror in {5, 231}


@native
def test_eof_drops_grant_and_restart_rejects_old_bootstrap(tmp_path):
    with running(tmp_path) as (service, client, directory, _):
        enroll(client)
        old_epoch = client.epoch
        client.dispose()
        wait_until(lambda: service.grant is None)
        service.stop()
        with pytest.raises(bridge.ShadowUnavailable):
            bridge.NativeShadowClient(directory / "active.json", threading.Event())
        replacement = bridge.ShadowService(directory, lambda **_: {"endpoint_valid": True, "category": "held"})
        try:
            assert replacement.start() is replacement
            wait_until(lambda: json.loads((directory / "active.json").read_bytes())["epoch"] != old_epoch)
            renewed_client = bridge.NativeShadowClient(directory / "active.json", threading.Event())
            try:
                assert renewed_client.status()["reason"] == "not-enrolled"
                assert replacement.grant is None
            finally:
                renewed_client.dispose()
        finally:
            replacement.stop()


@native
def test_owner_rights_is_not_accepted_for_a_different_owner():
    w = bridge._native()
    descriptor = w.security.ConvertStringSecurityDescriptorToSecurityDescriptor("O:SYD:P(A;;FA;;;OW)", 1)
    with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
        bridge._validate_descriptor(w, descriptor, bridge._self_sid(w), private=False)


@native
@pytest.mark.parametrize("raw", [b"{", b'{"version":1,"version":1}', b"\xff",
    b" " * bridge.MAX_MESSAGE, b" " * (bridge.MAX_MESSAGE + 1)],
    ids=["partial", "duplicate", "invalid-utf8", "maximum", "over-maximum"])
def test_malformed_and_maximum_frames_disconnect_without_snapshot(tmp_path, raw):
    with running(tmp_path) as (service, client, _, calls):
        deadline = time.monotonic() + 1
        client.io._operation(lambda ov: client.w.file.WriteFile(client.io.handle, raw, ov),
                             deadline, keepalive=raw)
        with pytest.raises(bridge.ShadowUnavailable):
            client.io.read(deadline)
        assert service.grant is None and calls == []


@native
def test_snapshot_deadline_never_issues_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "EXCHANGE_SECONDS", .1)

    def late_snapshot(**_):
        time.sleep(.15)
        return {"endpoint_valid": True, "category": "eligible"}

    with running(tmp_path, snapshot=late_snapshot) as (service, client, _, _):
        started = time.monotonic()
        with pytest.raises(bridge.ShadowUnavailable):
            enroll(client)
        assert time.monotonic() - started < .5
        wait_until(lambda: service.grant is None)
        assert client.grant is None


@native
def test_competing_owner_does_not_replace_manifest_or_grant(tmp_path):
    with running(tmp_path) as (service, client, directory, _):
        enroll(client)
        original = (directory / "active.json").read_bytes()
        grant = service.grant["handle"]
        competitor = bridge.ShadowService(directory, lambda **_: pytest.fail("competitor snapshot"))
        try:
            assert competitor.start() is competitor
            wait_until(competitor.stop_event.is_set)
            assert competitor.grant is None
            assert (directory / "active.json").read_bytes() == original
            assert service.grant["handle"] == grant
            assert client.status()["status"] == "eligible"
        finally:
            competitor.stop()


@pytest.mark.parametrize("fault", ["wait-failed", "result-incomplete"])
def test_uncertain_native_operation_retains_buffers_and_disables_future_native_work(monkeypatch, fault):
    retained = []
    monkeypatch.setattr(bridge, "_retained", retained)
    monkeypatch.setattr(bridge, "_native_uncertain", False)
    canceled = []
    closed = []

    class NativeError(Exception):
        winerror = 996  # ERROR_IO_INCOMPLETE must never authorize buffer disposal.

    class Handle:
        def Close(self):
            closed.append(self)

    event = Handle()

    def incomplete(*_):
        raise NativeError()

    w = SimpleNamespace(
        types=SimpleNamespace(OVERLAPPED=SimpleNamespace, error=NativeError),
        event=SimpleNamespace(CreateEvent=lambda *_: event, WAIT_OBJECT_0=0, WAIT_TIMEOUT=258,
                              WaitForSingleObject=lambda *_: 0xFFFFFFFF if fault == "wait-failed" else 0),
        file=SimpleNamespace(CancelIo=lambda h: canceled.append(h), GetOverlappedResult=incomplete),
    )
    handle, buffer, raw = Handle(), bytearray(b"pending-read"), bytes(b"pending-write")
    io = bridge._PipeIO(w, handle, threading.Event())
    with pytest.raises(bridge.ShadowUnavailable, match="transport-failed"):
        io._operation(lambda _: (997, buffer), time.monotonic() + .1, keepalive=raw)
    assert canceled == [handle]
    assert io.unresolved and bridge._native_uncertain and not bridge.native_available()
    assert retained[0][0] is io and retained[0][2] is buffer and retained[0][3] is raw
    io.close()
    assert closed == []


@native
@pytest.mark.parametrize("expiry", ["lease", "utc-policy"])
def test_snapshot_crossing_authority_expiry_denies_observation(tmp_path, expiry):
    now = [time.monotonic()]
    utc = [datetime.now(timezone.utc)]
    calls = []

    def snapshot(**_):
        calls.append(True)
        if len(calls) == 2:
            if expiry == "lease":
                now[0] += bridge.LEASE_SECONDS + 1
            else:
                utc[0] += timedelta(minutes=20)
        return {"endpoint_valid": True, "category": "eligible"}

    with running(tmp_path, snapshot=snapshot, clock=lambda: now[0], utc_clock=lambda: utc[0]) as (service, client, _, _):
        enroll(client)
        with pytest.raises(bridge.ShadowUnavailable):
            client.status()
        wait_until(lambda: service.grant is None)
        assert len(calls) == 2


@native
def test_foreign_ancestor_owner_denied_even_with_private_dacl():
    w = bridge._native()
    sid = bridge._self_sid(w)
    descriptor = w.security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"O:WDD:P(A;;FA;;;{sid})(A;;FA;;;SY)", 1,
    )
    with pytest.raises(bridge.ShadowUnavailable, match="unsafe-owner"):
        bridge._validate_descriptor(w, descriptor, sid, private=False)


@native
@pytest.mark.parametrize("case", ["exact-ancestor", "lookalike", "unrelated-service", "foreign-delete", "private-owner"])
def test_trusted_installer_exception_is_exact_and_ancestor_only(case):
    w = bridge._native()
    sid = bridge._self_sid(w)
    trusted = bridge.TRUSTED_INSTALLER_SID
    owner = trusted
    if case == "lookalike":
        owner = trusted.rsplit("-", 1)[0] + "-2271478465"
    elif case == "unrelated-service":
        owner = "S-1-5-80-0"
    dacl = f"D:P(A;;FA;;;{sid})(A;;FA;;;SY)"
    if case == "foreign-delete":
        dacl += "(A;;SD;;;WD)"
    descriptor = w.security.ConvertStringSecurityDescriptorToSecurityDescriptor(f"O:{owner}" + dacl, 1)
    if case == "exact-ancestor":
        bridge._validate_descriptor(w, descriptor, sid, private=False)
    else:
        category = "unsafe-acl" if case == "foreign-delete" else "unsafe-owner"
        with pytest.raises(bridge.ShadowUnavailable, match=category):
            bridge._validate_descriptor(w, descriptor, sid, private=case == "private-owner")


@native
def test_runtime_ancestor_foreign_delete_revokes_private_access_and_provision(tmp_path):
    with running(tmp_path) as (_, client, directory, _):
        enroll(client)
        w = client.w
        sid = bridge._self_sid(w)
        ancestor = tmp_path / "isolated-home"
        security = w.security.DACL_SECURITY_INFORMATION | w.security.PROTECTED_DACL_SECURITY_INFORMATION
        original = w.security.GetNamedSecurityInfo(str(ancestor), w.security.SE_FILE_OBJECT, security)
        baseline = (directory / "policy.json").read_bytes()
        broadened = w.security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f"D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;;SD;;;WD)", 1,
        )
        try:
            w.security.SetNamedSecurityInfo(str(ancestor), w.security.SE_FILE_OBJECT, security,
                                          None, None, broadened.GetSecurityDescriptorDacl(), None)
            # The private file and its direct parent remain unchanged; only an ancestor broadens.
            bridge._check_path(w, directory, sid)
            bridge._check_path(w, directory / "policy.json", sid)
            with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
                bridge._read_private(w, directory / "policy.json", sid)
            with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
                bridge._atomic_private(w, directory / "policy.json", sid, baseline)
            with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
                bridge._lock_file(w, directory / "new.lock", sid)
            with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
                client.status()
            with pytest.raises(bridge.ShadowUnavailable, match="unsafe-acl"):
                provision(tmp_path, policy(revision=2), expected_revision=1)
        finally:
            w.security.SetNamedSecurityInfo(str(ancestor), w.security.SE_FILE_OBJECT, security,
                                          None, None, original.GetSecurityDescriptorDacl(), None)
        assert bridge._read_private(w, directory / "policy.json", sid) == baseline
        assert not (directory / "new.lock").exists()
