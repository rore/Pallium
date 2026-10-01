"""Temporary Windows kernel pipes; never the Desktop pipe or installed policy."""

from __future__ import annotations

import json
import asyncio
import logging
import os
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import tempfile
import subprocess
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import codex_bridge_pipe as bridge

pytestmark = pytest.mark.slow
native = pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel pipe contract")
INVENTORY_CALLER = {"thread_ref": "source-chat", "turn_ref": "source-turn"}


@pytest.fixture
def inventory_caplog(caplog):
    root = logging.getLogger()
    logger = bridge._log
    root.removeHandler(caplog.handler)
    logger.addHandler(caplog.handler)
    caplog.set_level(30, logger=logger.name)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        root.addHandler(caplog.handler)


@pytest.fixture
def test_db_url(tmp_path_factory):
    # Keep the HTTP fixture's SQLite lifetime out of the eagerly disposed policy directory.
    return f"sqlite:///{tmp_path_factory.mktemp('shadow-http') / 'test.db'}"


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


@native
@pytest.mark.asyncio
async def test_stdio_mcp_native_sqlite_shadow_full_caller_lifecycle(client, tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    scope = {"container_ref": "git:example.test/native-shadow"}
    recipient = "recipient-β"
    registered = client.post("/relay/turn", json={"runtime": "codex", "session_ref": recipient, **scope})
    assert registered.status_code == 200, registered.text
    endpoint = registered.json()["session"]
    assert client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": "sender", **scope}).status_code == 200
    payload = "private payload must stay pending"
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": "codex:" + recipient, "payload": payload, **scope,
    })
    assert sent.status_code == 200, sent.text
    message_id = sent.json()["message_id"]

    def ordinary_read():
        response = client.get("/relay/messages/" + message_id, params=scope)
        assert response.status_code == 200, response.text
        return response.json()

    storage = client.app.state.pallium_service._storage

    def persisted_relay_state():
        with closing(sqlite3.connect(storage._relay_engine.url.database)) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'relay_%'").fetchall()
            return {table: sorted(db.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall(), key=repr)
                    for (table,) in tables}

    before = ordinary_read()
    assert before["deliveries"][0]["state"] == "pending"
    persisted = persisted_relay_state()
    directory = provision(tmp_path, policy(
        recipient_endpoint_id=endpoint["endpoint_id"], recipient_session_ref=recipient,
        recipient_container_ref=scope["container_ref"], recipient_scope_generation=endpoint["scope_generation"],
    ))
    service = bridge.ShadowService(directory, storage.relay_shadow_snapshot)
    assert service.start() is service
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PALLIUM_MCP_TRANSPORT": "stdio", "PALLIUM_AGENT_REF": "codex",
        "PALLIUM_CODEX_BRIDGE_MODE": "shadow",
        "PALLIUM_CODEX_SHADOW_BOOTSTRAP_FILE": str(directory / "active.json"),
        "CODEX_APP_TOOLS_PIPE_PATH": "unused-desktop-presence-sentinel",
        "PALLIUM_BASE_URL": "http://127.0.0.1:1", "PALLIUM_CONTAINER_REF": scope["container_ref"],
    })
    # Only the unrelated ordinary HTTP client is stubbed; all shadow components are real.
    child = """from app.mcp import server
class StatusClient:
    def __init__(self, ctx): pass
    async def get_status(self): return {"status": "healthy"}
server.PalliumMcpClient = StatusClient
server.main()
"""
    params = StdioServerParameters(command=sys.executable, args=["-c", child],
                                   cwd=str(Path(__file__).resolve().parents[1]), env=env)
    try:
        wait_until(lambda: (directory / "active.json").exists() or service.stop_event.is_set())
        assert not service.stop_event.is_set()
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    async def invoke(operation, metadata):
                        response = await session.call_tool("pallium_codex_bridge_shadow_" + operation, {}, meta=metadata)
                        assert not response.isError
                        result = json.loads(response.content[0].text)
                        assert set(result) <= {"mode", "status", "reason", "ttl_seconds"}
                        assert payload not in repr(result) and str(directory) not in repr(result)
                        return result

                    enrolled = await invoke("enroll", {"threadId": "controller-α", "turnId": "turn-1"})
                    assert enrolled["status"] == "enrolled", enrolled
                    assert service.grant is not None
                    shadow, normal = await asyncio.wait_for(asyncio.gather(
                        invoke("status", {"threadId": "controller-α", "turnId": "turn-2"}),
                        session.call_tool("pallium_status", {}),
                    ), timeout=3)
                    assert shadow["status"] == "held" and shadow["reason"] == "evidence-limited"
                    assert not normal.isError and json.loads(normal.content[0].text) == {"status": "healthy"}
                    wrong = await invoke("status", {"threadId": "other", "turnId": "turn-3"})
                    assert wrong["reason"] == "wrong-controller"
                    assert ordinary_read() == before
            wait_until(lambda: service.grant is None)
            errors.seek(0)
            assert "unused-desktop-presence-sentinel" not in errors.read()
        assert ordinary_read() == before
        assert persisted_relay_state() == persisted
    finally:
        service.stop()
        assert not service.thread.is_alive() and not service.unresolved
        assert service.grant is None
        client.app.state.pallium_service.close()
        storage.close()


class FakeDesktop:
    """Isolated kernel byte pipe using this test process, never Desktop capability."""

    def __init__(self, response=None, *, allow_call=False):
        self.w = bridge._native()
        self.stop = threading.Event()
        self.endpoint = rf"\\.\pipe\inventory-test-{secrets.token_hex(16)}"
        self.requests = []
        self.connections = 0
        self.response = response
        self.allow_call = allow_call
        self.io = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        handle = self.w.pipe.CreateNamedPipe(self.endpoint,
            self.w.pipe.PIPE_ACCESS_DUPLEX | self.w.con.FILE_FLAG_OVERLAPPED | bridge.FIRST_PIPE_INSTANCE,
            self.w.pipe.PIPE_TYPE_BYTE | self.w.pipe.PIPE_WAIT | self.w.pipe.PIPE_REJECT_REMOTE_CLIENTS,
            1, 65536, 65536, 1000, bridge._security_attributes(self.w, bridge._self_sid(self.w)))
        self.io = bridge._DesktopIO(self.w, handle, self.stop)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    self.io.accept(time.monotonic() + .1)
                    break
                except bridge.ShadowUnavailable as exc:
                    if exc.category != "deadline" or self.io.unresolved:
                        raise
            if self.stop.is_set():
                return
            self.connections += 1
            while not self.stop.is_set():
                try:
                    request = self.io.read(time.monotonic() + .1)
                except bridge.ShadowUnavailable as exc:
                    if exc.category == "deadline" and not self.io.unresolved:
                        continue
                    raise
                self.requests.append(request)
                assert request.get("jsonrpc") == "2.0" and request.get("id") == len(self.requests)
                if request.get("method") == "tools/list":
                    assert set(request) == {"jsonrpc", "id", "method"}
                    value = {"jsonrpc": "2.0", "id": request["id"], "result": {
                        "tools": [{"name": "example-β", "description": "private native content", "inputSchema": {"type": "object"}}]}}
                else:
                    assert self.allow_call and request.get("method") == "tools/call"
                    value = {"jsonrpc": "2.0", "id": request["id"], "result": {"content": []}}
                value = self.response(request, value) if self.response else value
                if value is None:
                    continue
                if isinstance(value, bytes):
                    raw = len(value).to_bytes(4, "little") + value
                    self.io._operation(lambda ov: self.w.file.WriteFile(self.io.handle, raw, ov), time.monotonic() + 1, raw)
                else:
                    self.io.write(value, time.monotonic() + 1)
        except bridge.ShadowUnavailable:
            pass
        finally:
            self.io.close()

    def close(self):
        self.stop.set()
        self.thread.join(.5)
        assert not self.thread.is_alive() and not self.io.unresolved


def inventory_policy(service, source=None, **changes):
    w = bridge._native()
    current = bridge._Peer(w, os.getpid(), bridge._self_sid(w))
    try:
        path, version = bridge._process_image(w, current.handle)
        value = {"version": 1, "action": "desktop-inventory-only", "revision": 1,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
            "enabled": True, "revoked": False, "service_pid": os.getpid(),
            "service_creation": current.creation, "service_epoch": service.epoch,
            "source_pid": (source or current).pid, "source_creation": (source or current).creation,
            "desktop_pid": os.getpid(), "desktop_creation": current.creation,
            "desktop_user_sid": bridge._self_sid(w), "desktop_executable": path, "desktop_version": version}
        value.update(changes)
        return value
    finally:
        current.close()


def arm_inventory(directory, value):
    w = bridge._native()
    bridge._atomic_private(w, directory / "policy.json", bridge._self_sid(w), encode(value))


def read_proof(directory):
    w = bridge._native()
    for phase in ("failure", "after", "exit", "before"):
        path = directory / f"proof-{phase}.json"
        if path.is_file():
            return bridge._json(bridge._read_private(w, path, bridge._self_sid(w)))
    return {"before_inventory_ok": False, "after_inventory_ok": False, "source_exited": False, "failure": "none"}


def watch_replacements(monkeypatch):
    events = []
    original = os.replace

    def replace(source, destination):
        try:
            return original(source, destination)
        except OSError as exc:
            events.append((Path(destination).name, {5: "access-denied", 32: "sharing-conflict"}.get(exc.winerror, "other")))
            raise

    monkeypatch.setattr(os, "replace", replace)
    return events


@native
def test_policy_held_reader_excludes_bounded_writer_until_handle_cleanup(tmp_path, monkeypatch):
    w = bridge._native()
    sid = bridge._self_sid(w)
    path = tmp_path / "policy.json"
    raw = encode(inventory_policy(SimpleNamespace(epoch="diagnostic-epoch")))
    bridge._atomic_private(w, path, sid, raw)
    held, release = threading.Event(), threading.Event()
    read_results = []
    original_read = w.file.ReadFile

    def read(handle, *args):
        result = original_read(handle, *args)
        held.set()
        assert release.wait(1), "reader-release-timeout"
        return result

    monkeypatch.setattr(w.file, "ReadFile", read)
    monkeypatch.setattr(os, "replace", lambda *args: pytest.fail("replace occurred while policy reader owns lock"))

    def reader():
        read_results.append(bridge._read_private(w, path, sid))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        assert held.wait(1)
        start = time.monotonic()
        with pytest.raises(bridge.ShadowUnavailable, match="policy-busy"):
            bridge._atomic_private(w, path, sid, raw, deadline=start + .03)
        assert time.monotonic() - start < .15
    finally:
        release.set()
        thread.join(1)
    assert not thread.is_alive() and read_results == [raw]
    token = bridge._policy_lock(w, path, sid)
    token.Close()


@contextmanager
def inventory_running(tmp_path, monkeypatch, *, response=None, arm=True, changes=None,
                      trial_relay=None, trial_registry=None):
    home = tmp_path / "inventory-home"
    directory = bridge.prepare_inventory_service(home)
    desktop = FakeDesktop(response)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", desktop.endpoint)
    service = bridge.InventoryService(directory, trial_relay=trial_relay, trial_registry=trial_registry)
    client = None
    assert service.start() is service
    try:
        wait_until(lambda: (directory / "active.json").exists() or service.stop_event.is_set())
        assert not service.stop_event.is_set()
        client = bridge.NativeInventoryClient(directory / "active.json", threading.Event())
        assert client.ready()["status"] == "ready"
        if arm:
            arm_inventory(directory, inventory_policy(service, **(changes or {})))
        yield service, client, directory, desktop
    finally:
        if client:
            client.dispose()
        service.stop()
        desktop.close()
        assert not service.thread.is_alive() and not service.unresolved
        assert service.custody is None


def inventory_raw_exchange(client, request):
    deadline = time.monotonic() + 1
    client.io.write(request, deadline)
    return client.io.read(deadline)


def inventory_failure_records(caplog):
    message = "codex_inventory_failure stage=%s category=%s epoch=%s revision=%d"
    records = {id(record): record for record in caplog.records
               if record.name == "app.codex_bridge_pipe" and record.msg == message}
    return list(records.values())


@pytest.mark.parametrize("case,expected_stage,expected_category", [
    ("valid", "native-peer", "transport-failed"),
    ("missing", "native-peer", "unexpected"),
    ("unknown", "native-peer", "unexpected"),
    ("unicode", "native-peer", "unexpected"),
    ("unhashable", "native-peer", "unexpected"),
    ("raising", "native-peer", "unexpected"),
    ("unknown-stage", "unknown", "deadline"),
])
def test_inventory_failure_diagnostic_allowlists_untrusted_fields(
    tmp_path, inventory_caplog, case, expected_stage, expected_category,
):
    service = bridge.InventoryService(tmp_path)
    service._failure_context = ("a" * 32, 7)
    service._failure_stage = "private-stage-sentinel" if case == "unknown-stage" else "native-peer"

    class RaisingCategory(Exception):
        @property
        def category(self):
            raise OSError("private-category-sentinel")

    if case == "valid":
        error = bridge.ShadowUnavailable("transport-failed")
    elif case == "missing":
        error = RuntimeError("private-message-sentinel")
    elif case == "unknown":
        error = SimpleNamespace(category="private-category-sentinel")
    elif case == "unicode":
        error = SimpleNamespace(category="β-secret")
    elif case == "unhashable":
        error = SimpleNamespace(category=[])
    elif case == "raising":
        error = RaisingCategory("private-message-sentinel")
    else:
        error = bridge.ShadowUnavailable("deadline")

    service._record_failure(error)
    records = inventory_failure_records(inventory_caplog)
    assert len(records) == 1
    assert records[0].args == (expected_stage, expected_category, service._failure_context[0], 7)
    assert "private" not in repr(records[0].args) and "β" not in repr(records[0].args)


@pytest.mark.parametrize("failure", ["format", "write", "flush"])
def test_inventory_failure_diagnostic_sink_errors_keep_first_failure(tmp_path, monkeypatch, capsys, failure):
    service = bridge.InventoryService(tmp_path)
    service._failure_context = ("b" * 32, 9)
    service._failure_stage = "before-write"
    handler = next(h for h in bridge._log.handlers if isinstance(h, bridge._InventoryLogHandler))

    class BrokenStream:
        def write(self, value):
            if failure == "write":
                raise OSError("private-write-sentinel")

        def flush(self):
            if failure == "flush":
                raise OSError("private-flush-sentinel")

    if failure == "format":
        def broken_format(record):
            raise OSError("private-format-sentinel")
        monkeypatch.setattr(handler, "format", broken_format)
    else:
        monkeypatch.setattr(bridge.sys, "stderr", BrokenStream())

    service._record_failure(bridge.ShadowUnavailable("transport-failed"))
    assert service._failure_diagnostic == ("before-write", "transport-failed")
    service._failure_stage = "after-proof"
    service._record_failure(bridge.ShadowUnavailable("policy-inactive"))
    assert service._failure_diagnostic == ("before-write", "transport-failed")
    captured = capsys.readouterr()
    assert "private-" not in captured.err and "Traceback" not in captured.err


def test_inventory_old_sealed_proof_only_suppresses_its_own_failure_context(tmp_path, inventory_caplog):
    service = bridge.InventoryService(tmp_path)
    service.published_phases.add("after")
    service.proof = {"epoch": service.epoch, "revision": 4, "before_inventory_ok": True,
                     "after_inventory_ok": True, "source_exited": True, "failure": "none"}
    service._failure_stage = "transfer-authority"
    service._failure_context = (service.epoch, 4)

    service._record_failure(bridge.ShadowUnavailable("policy-changed"))
    assert inventory_failure_records(inventory_caplog) == []

    service._failure_context = (service.epoch, 5)
    service._failure_diagnostic = None
    service._record_failure(bridge.ShadowUnavailable("policy-changed"))
    records = inventory_failure_records(inventory_caplog)
    assert len(records) == 1
    assert records[0].args == ("transfer-authority", "policy-changed", service.epoch, 5)


@native
@pytest.mark.parametrize("sequence", ["4", None, [], True, 0, -1, 3, 2, "missing", 2**31],
                         ids=["string", "null", "list", "boolean", "zero", "negative", "equal", "decreasing", "missing", "over-max"])
def test_inventory_rejected_sequence_keeps_floor_and_live_custody(tmp_path, monkeypatch, sequence):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        custody = service.custody
        assert custody is not None and len(desktop.requests) == 1
        malformed = {"version": 1, "verb": "ready", "epoch": service.epoch, "sequence": sequence}
        if sequence == "missing":
            malformed.pop("sequence")
        rejected = inventory_raw_exchange(client, malformed)
        assert rejected["status"] == "unavailable"
        expected_echo = sequence if bridge._integer(sequence, 1) else 3
        assert rejected["sequence"] == expected_echo

        replay = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch, "sequence": 3})
        assert replay["status"] == "unavailable"
        accepted = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch, "sequence": 4})
        assert accepted["status"] == "ready" and accepted["sequence"] == 4
        assert service.thread.is_alive() and service.custody is custody
        assert desktop.connections == 1 and len(desktop.requests) == 1


@native
def test_inventory_maximum_sequence_is_accepted_then_replay_is_rejected(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        custody = service.custody
        maximum = 2**31 - 1
        accepted = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch,
                                                    "sequence": maximum})
        assert accepted["status"] == "ready" and accepted["sequence"] == maximum
        replay = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch,
                                                   "sequence": maximum})
        assert replay["status"] == "unavailable" and replay["sequence"] == maximum
        assert service.thread.is_alive() and service.custody is custody
        assert desktop.connections == 1 and len(desktop.requests) == 1


@native
def test_inventory_invalid_body_does_not_consume_floor_and_error_echoes_candidate(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        custody = service.custody
        malformed = {"version": 1, "verb": "unsupported", "epoch": service.epoch, "sequence": 100}
        rejected = inventory_raw_exchange(client, malformed)
        assert rejected["status"] == "unavailable" and rejected["sequence"] == 100
        accepted = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch, "sequence": 4})
        assert accepted["status"] == "ready" and accepted["sequence"] == 4
        assert service.thread.is_alive() and service.custody is custody
        assert desktop.connections == 1 and len(desktop.requests) == 1


@native
def test_inventory_valid_request_error_echoes_candidate_without_advancing_floor(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        custody = service.custody
        failed = inventory_raw_exchange(client, {"version": 1, "verb": "transfer", "epoch": service.epoch,
            "sequence": 4, "revision": 2, "endpoint": "\\\\.\\pipe\\unused"})
        assert failed["status"] == "unavailable" and failed["reason"] == "policy-changed"
        assert failed["sequence"] == 4
        accepted = inventory_raw_exchange(client, {"version": 1, "verb": "ready", "epoch": service.epoch, "sequence": 4})
        assert accepted["status"] == "ready" and accepted["sequence"] == 4
        assert service.thread.is_alive() and service.custody is custody
        assert desktop.connections == 1 and len(desktop.requests) == 1


@native
@pytest.mark.parametrize("fault,expected_stage", [
    ("missing-pipe", "native-open"), ("server-pid", "native-peer"),
], ids=["missing-desktop-pipe", "server-pid-error"])
def test_inventory_native_transfer_failure_keeps_owner_live_and_fenced(tmp_path, monkeypatch, inventory_caplog, fault, expected_stage):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        caplog = inventory_caplog
        expected_policy = bridge.InventoryPolicy.parse((directory / "policy.json").read_bytes())
        endpoint = desktop.endpoint
        if fault == "missing-pipe":
            endpoint = rf"\\.\pipe\inventory-missing-{secrets.token_hex(16)}"
            monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", endpoint)

        opened = []
        desktop_peers = []
        custody_ios = []
        original_create = service.w.file.CreateFile

        def create_file(path, *args):
            if path == endpoint:
                opened.append(path)
                desktop_peers.append(service.desktop)
            return original_create(path, *args)

        monkeypatch.setattr(service.w.file, "CreateFile", create_file)
        server_pid_calls = []
        if fault == "server-pid":
            original_server_pid = service.w.pipe.GetNamedPipeServerProcessId

            def get_server_pid(handle):
                custody = service.custody
                if custody is not None and handle == custody.handle:
                    server_pid_calls.append(handle)
                    custody_ios.append(custody)
                    raise OSError("private-native-lookup-sentinel")
                return original_server_pid(handle)

            monkeypatch.setattr(service.w.pipe, "GetNamedPipeServerProcessId", get_server_pid)

        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == "native-failed"
        assert service.thread.is_alive() and not service.stop_event.is_set() and not service.unresolved
        assert service.fenced and service.admitted is None and service.custody is None and service.desktop is None
        assert len(opened) == 1 and opened == [endpoint]
        assert len(desktop_peers) == 1 and desktop_peers[0].handle is None
        assert len(server_pid_calls) == (0 if fault == "missing-pipe" else 1)
        assert len(custody_ios) == (0 if fault == "missing-pipe" else 1)
        if custody_ios:
            assert custody_ios[0].handle is None
        assert desktop.connections == (0 if fault == "missing-pipe" else 1) and desktop.requests == []

        failure_path = directory / "proof-failure.json"
        failure = bridge._json(bridge._read_private(service.w, failure_path, service.sid))
        bridge._check_path(service.w, failure_path, service.sid)
        assert failure == {
            "version": 1, "epoch": service.epoch, "revision": expected_policy.revision,
            "policy_fingerprint": bridge._inventory_fingerprint(expected_policy),
            "before_inventory_ok": False, "after_inventory_ok": False,
            "source_exited": False, "failure": "native-failed",
        }
        assert not any((directory / f"proof-{phase}.json").exists() for phase in ("before", "exit", "after"))
        assert bridge.read_inventory_proof(directory, expected_policy) == {
            "status": "incomplete", "reason": "missing-phase", "source_exited": False,
            "before_inventory_ok": False, "after_inventory_ok": False,
            "historical_transport_pass": False,
        }
        assert endpoint not in repr(result) + repr(failure)
        assert "private-native-lookup-sentinel" not in repr(result) + repr(failure)
        records = inventory_failure_records(caplog)
        assert len(records) == 1
        assert records[0].args == (expected_stage, "unexpected", service.epoch, expected_policy.revision)

        open_count, server_pid_count = len(opened), len(server_pid_calls)
        try:
            retry = client.register(INVENTORY_CALLER)
        except bridge.ShadowUnavailable as exc:
            assert exc.category in {"transport-failed", "deadline"}
        else:
            assert retry["status"] == "unavailable" and retry["reason"] == "policy-changed"
        assert len(inventory_failure_records(caplog)) == 1
        assert len(opened) == open_count and len(server_pid_calls) == server_pid_count
        assert service.thread.is_alive() and not service.stop_event.is_set()
        assert service.fenced and service.admitted is None and service.custody is None and service.desktop is None
        assert desktop.connections == (0 if fault == "missing-pipe" else 1) and desktop.requests == []

    assert not service.thread.is_alive() and not service.unresolved
    assert service.custody is None and service.desktop is None
    assert service.source is None or service.source.handle is None
    assert not desktop.thread.is_alive() and not desktop.io.unresolved


@native
def test_inventory_ready_without_policy_and_cas_provisioning(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch, arm=False) as (service, client, directory, desktop):
        ready = json.loads((directory / "ready.json").read_bytes())
        manifest = json.loads((directory / "active.json").read_bytes())
        assert set(manifest) == {"version", "pid", "creation", "epoch", "pipe"}
        assert ready["source_pid"] == os.getpid() and ready["service_epoch"] == service.epoch
        assert not (directory / "policy.json").exists()
        assert client.register(INVENTORY_CALLER)["reason"] == "policy-inactive"
        assert desktop.connections == 0 and desktop.requests == []
        source = tmp_path / "inventory-policy.json"
        source.write_bytes(encode(inventory_policy(service)))
        bridge.provision_inventory_policy(source, directory.parent.parent)
        with pytest.raises(bridge.ShadowUnavailable, match="revision-conflict"):
            bridge.provision_inventory_policy(source, directory.parent.parent)
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        assert len(desktop.requests) == 1


@native
@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"revoked": True}, {"revision": 0}, {"revision": True},
    {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    {"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()},
    {"expires_at": "2026-01-01"}, {"service_epoch": "wrong"}, {"service_pid": 1},
    {"service_creation": "wrong"}, {"source_pid": 1}, {"source_creation": "wrong"},
    {"desktop_pid": 1}, {"desktop_creation": "wrong"}, {"desktop_user_sid": "S-1-5-18"},
    {"desktop_executable": "C:\\not-the-process.exe"}, {"desktop_version": "0.0.0.0"},
    {"action": "tools/call"}, {"action": []}, {"version": True}, {"extra": "secret"},
])
def test_inventory_invalid_authority_denies_before_endpoint_read_or_open(tmp_path, monkeypatch, changes):
    with inventory_running(tmp_path, monkeypatch, changes=changes) as (_, client, _, desktop):
        original = os.environ.get
        reads = []

        def env_get(name, *args):
            if name == "CODEX_APP_TOOLS_PIPE_PATH":
                reads.append(name)
                pytest.fail("capability read before independent finite authority")
            return original(name, *args)

        monkeypatch.setattr(os.environ, "get", env_get)
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable"
        assert reads == [] and desktop.connections == 0 and desktop.requests == []


@native
def test_inventory_registration_idempotent_eof_preserves_service_custody(tmp_path, monkeypatch, inventory_caplog):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        assert not inventory_failure_records(inventory_caplog)
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        wait_until(lambda: desktop.connections == 1)
        handle = service.custody.handle
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        assert desktop.connections == 1 and len(desktop.requests) == 1
        assert not inventory_failure_records(inventory_caplog)
        before = read_proof(directory)
        assert before["before_inventory_ok"] and not before["source_exited"]
        client.dispose()
        wait_until(lambda: service.admitted is None)
        after = read_proof(directory)
        assert not after["after_inventory_ok"] and service.custody.handle is handle
        assert desktop.connections == 1 and len(desktop.requests) == 1
        assert "private native content" not in repr(after) and desktop.endpoint not in repr(after)
        for path in directory.iterdir():
            if path.suffix == ".json":
                assert desktop.endpoint.encode() not in path.read_bytes()


@native
def test_inventory_list_request_matches_desktop_optional_params_schema(tmp_path, monkeypatch):
    def current_desktop_schema(request, value):
        if "params" in request and request["params"] != {"threadStartKind": "default"}:
            return {"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32602, "message": "Invalid app tool request"}}
        return value

    with inventory_running(tmp_path, monkeypatch, response=current_desktop_schema) as (_, client, directory, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        assert desktop.requests == [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
        assert read_proof(directory)["before_inventory_ok"]


@native
def test_inventory_private_admission_binds_caller_turn_to_retained_custody(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        metadata = {"thread_ref": "source-chat", "turn_ref": "source-turn"}
        assert client.register(metadata)["status"] == "registered"
        assert service.caller == ("source-chat", "source-turn")
        assert service.custody is not None
        assert desktop.requests == [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]


@native
@pytest.mark.parametrize("changed", [
    {"thread_ref": "other-chat", "turn_ref": "other-turn"},
    {"thread_ref": "source-chat", "turn_ref": "other-turn"},
])
def test_inventory_changed_caller_pair_cannot_rebind_retained_custody(tmp_path, monkeypatch, changed):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        custody = service.custody
        result = client.register(changed)
        assert result["status"] == "unavailable" and result["reason"] == "peer-mismatch"
        assert service.caller == ("source-chat", "source-turn")
        assert service.custody is custody and len(desktop.requests) == 1


@native
@pytest.mark.parametrize("target_session", ["target", "source-chat"])
def test_inventory_service_installs_exact_trial_authority_before_relay_send(
    tmp_path, monkeypatch, client, target_session,
):
    from core.codex_wake import CodexWakeRegistry
    from core.relay import RelayService

    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    registry = CodexWakeRegistry(relay_service=relay)
    assert registry.initialize(old_owner_drained=True)
    scope = {"container_ref": "git:example.test/service-trial"}
    endpoint = relay.turn(runtime="codex", session_ref=target_session, **scope)["session"]["endpoint_id"]
    denied = threading.Event()
    original_warning = bridge._log.warning
    def note_warning(message, *args, **kwargs):
        if message == "codex_trial_install outcome=denied":
            denied.set()
        original_warning(message, *args, **kwargs)
    monkeypatch.setattr(bridge._log, "warning", note_warning)
    with inventory_running(
        tmp_path, monkeypatch, trial_relay=relay, trial_registry=registry,
    ) as (service, native_client, directory, desktop):
        assert native_client.register(INVENTORY_CALLER)["status"] == "registered"
        request = {
            "version": 1, "action": "codex-unloaded-payload-trial", "service_epoch": service.epoch,
            "revision": service.policy.revision, "source_thread_ref": INVENTORY_CALLER["thread_ref"],
            "endpoint_id": endpoint, "session_ref": target_session, "container_ref": scope["container_ref"],
            "trial_id": "fixed-trial",
        }
        bridge._create_phase(service.w, directory / "trial-request.json", service.sid, encode(request))
        if target_session == "source-chat":
            wait_until(lambda: denied.is_set() or (directory / "trial-installed.json").exists())
            assert denied.is_set()
            assert not (directory / "trial-installed.json").exists()
            assert not relay.codex_trial_native_suppressed(endpoint)
        else:
            wait_until(lambda: (directory / "trial-installed.json").exists())
            assert relay.codex_trial_native_suppressed(endpoint)
        assert registry.snapshot(endpoint) is None
        assert desktop.requests == [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]


@pytest.mark.parametrize("change,accepted", [
    ("valid", True), ("missing", False), ("wrong-namespace", False),
    ("wrong-name", False), ("extra-required", False), ("wrong-type", False),
    ("duplicate", False), ("ambiguous-required", False),
])
def test_inventory_owner_tool_descriptor_requires_exact_reviewed_shape(change, accepted):
    descriptor = {"namespace": "codex_app", "name": "send_message_to_thread", "inputSchema": {
        "type": "object", "properties": {"threadId": {"type": "string"}, "prompt": {"type": "string"}},
        "required": ["threadId", "prompt"],
    }}
    tools = [descriptor]
    if change == "missing":
        tools = []
    elif change == "wrong-namespace":
        descriptor["namespace"] = "other"
    elif change == "wrong-name":
        descriptor["name"] = "other"
    elif change == "extra-required":
        descriptor["inputSchema"]["required"].append("hostId")
    elif change == "wrong-type":
        descriptor["inputSchema"]["properties"]["threadId"]["type"] = "integer"
    elif change == "duplicate":
        tools.append(dict(descriptor))
    elif change == "ambiguous-required":
        descriptor["inputSchema"]["required"] = ["threadId", "threadId", "prompt"]
    assert bridge._owner_tool_schema_valid(tools) is accepted


@native
@pytest.mark.parametrize("owner_reply, expected_status", [
    ("success", "submitted"),
    ("error", "inconclusive"),
    ("tool-error", "inconclusive"),
    ("wrong-id", "inconclusive"),
    ("missing-before-descriptor", "denied"),
    ("malformed-before-descriptor", "denied"),
    ("spend-denied", "denied"),
    ("write-after-send-failure", "inconclusive"),
    ("source-exit-before-write", "inconclusive"),
])
def test_exclusive_trial_uses_one_retained_desktop_owner_call_while_source_alive(
    tmp_path, monkeypatch, client, owner_reply, expected_status,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dependencies import build_router
    from core.codex_wake import CodexWakeRegistry
    from core.relay import RelayService

    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    registry = CodexWakeRegistry(relay_service=relay)
    assert registry.initialize(old_owner_drained=True)
    scope = {"container_ref": "git:example.test/owner-action"}
    relay.turn(runtime="codex", session_ref="sender", **scope)
    endpoint = relay.turn(runtime="codex", session_ref="target", **scope)["session"]["endpoint_id"]
    app = FastAPI()
    app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                    codex_wake_registry=registry))
    route = TestClient(app)
    schema = {"type": "object", "properties": {
        "threadId": {"type": "string"}, "prompt": {"type": "string"},
    }, "required": ["threadId", "prompt"]}

    def desktop_response(request, value):
        if request["method"] == "tools/list":
            value["result"]["tools"] = ([] if owner_reply == "missing-before-descriptor"
                else [{"namespace": "codex_app", "name": "send_message_to_thread",
                       "inputSchema": {"type": "array"} if owner_reply == "malformed-before-descriptor" else schema}])
        elif owner_reply == "error":
            value = {"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32000, "message": "private native error"}}
        elif owner_reply == "tool-error":
            value["result"] = {"isError": True, "content": [{"type": "text", "text": "private native error"}]}
        elif owner_reply == "wrong-id":
            value["id"] = request["id"] + 1
        return value

    directory = bridge.prepare_inventory_service(tmp_path / "owner-home")
    desktop = FakeDesktop(desktop_response, allow_call=True)
    service = bridge.InventoryService(directory, trial_relay=relay, trial_registry=registry)
    child = None
    assert service.start() is service
    try:
        wait_until(lambda: (directory / "active.json").exists())
        child_home = tmp_path / "child-home"
        child_home.mkdir()
        env = os.environ.copy()
        env.update({"CODEX_APP_TOOLS_PIPE_PATH": desktop.endpoint, "USERPROFILE": str(child_home)})
        code = """import json,sys,threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient
c=NativeInventoryClient(Path(sys.argv[1]),threading.Event())
print(json.dumps(c.ready()),flush=True)
sys.stdin.readline()
print(json.dumps(c.register({"thread_ref":"source-chat","turn_ref":"source-turn"})),flush=True)
sys.stdin.readline()
c.dispose()
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(directory / "active.json")],
            cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        assert json.loads(child.stdout.readline())["status"] == "ready"
        arm_inventory(directory, inventory_policy(service, service.source))
        child.stdin.write("register\n")
        child.stdin.flush()
        assert json.loads(child.stdout.readline())["status"] == "registered"
        assert service.owner_tool_before is (owner_reply not in (
            "missing-before-descriptor", "malformed-before-descriptor"))
        bridge._create_phase(service.w, directory / "trial-request.json", service.sid, encode({
            "version": 1, "action": "codex-unloaded-payload-trial", "service_epoch": service.epoch,
            "revision": service.policy.revision, "source_thread_ref": "source-chat",
            "endpoint_id": endpoint, "session_ref": "target", "container_ref": scope["container_ref"],
            "trial_id": "owner-trial",
        }))
        wait_until(lambda: (directory / "trial-installed.json").exists())
        with monkeypatch.context() as guard:
            guard.setattr("app.dependencies.schedule_codex_relay_wake",
                          lambda *_a, **_k: pytest.fail("trial reached native wake launcher"))
            sent = route.post("/relay/messages", json={
                "sender_runtime": "codex", "sender_session_ref": "sender",
                "recipient": endpoint, "payload": "private payload never sent to Desktop", **scope,
            })
        assert sent.status_code == 200
        delivery_id = sent.json()["deliveries"][0]["delivery_id"]
        if owner_reply == "spend-denied":
            monkeypatch.setattr(relay, "spend_codex_trial", lambda **_kwargs: False)
        if owner_reply == "write-after-send-failure":
            original_write = service.custody.write
            def write_then_fail(value, deadline):
                original_write(value, deadline)
                if value.get("method") == "tools/call":
                    raise bridge.ShadowUnavailable("transport-failed")
            monkeypatch.setattr(service.custody, "write", write_then_fail)
        if owner_reply == "source-exit-before-write":
            original_ready = relay.codex_trial_action_ready
            def source_exits_after_spend(**kwargs):
                child.stdin.write("exit\n")
                child.stdin.flush()
                assert child.wait(timeout=3) == 0
                return original_ready(**kwargs)
            monkeypatch.setattr(relay, "codex_trial_action_ready", source_exits_after_spend)
        bridge._create_phase(service.w, directory / "trial-action.json", service.sid, encode({
            "version": 1, "action": "codex-unloaded-payload-owner-call", "service_epoch": service.epoch,
            "revision": service.policy.revision, "source_thread_ref": "source-chat",
            "endpoint_id": endpoint, "trial_id": "owner-trial", "delivery_id": delivery_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=180)).isoformat(),
        }))
        wait_until(lambda: (directory / "trial-bound.json").exists())
        wait_until(lambda: (directory / "trial-outcome.json").exists(), timeout=3)
        if owner_reply == "source-exit-before-write":
            assert child.poll() == 0
        else:
            assert child.poll() is None
            assert not (directory / "proof-exit.json").exists()
            assert not (directory / "proof-after.json").exists()
        outcome = json.loads((directory / "trial-outcome.json").read_text(encoding="utf-8"))
        if owner_reply == "source-exit-before-write":
            monkeypatch.setattr(relay, "codex_trial_action_ready", original_ready)
        assert set(outcome) == {"version", "service_epoch", "revision", "status"}
        assert "private native error" not in repr(outcome)
        assert outcome["status"] == expected_status
        assert relay.codex_trial_native_suppressed(endpoint)
        assert relay.codex_trial_action_ready(endpoint_id=endpoint, trial_id="owner-trial",
                                             delivery_id=delivery_id) is (expected_status not in ("denied",))
        no_call = expected_status == "denied" or owner_reply == "source-exit-before-write"
        assert desktop.connections == 1
        assert len([request for request in desktop.requests if request["method"] == "tools/call"]) == (
            0 if no_call else 1)
        if owner_reply != "source-exit-before-write":
            assert len(desktop.requests) == (1 if no_call else 2)
        service._maybe_execute_trial()
        assert len([request for request in desktop.requests if request["method"] == "tools/call"]) == (
            0 if no_call else 1)
        if no_call:
            return
        request = desktop.requests[1]
        assert request["method"] == "tools/call" and request["id"] == 2
        params = request["params"]
        assert set(params) == {"namespace", "tool", "arguments", "callerSource", "callId", "threadId", "turnId"}
        assert params["namespace"] == "codex_app" and params["tool"] == "send_message_to_thread"
        assert params["callerSource"] == "codex" and params["threadId"] == "source-chat"
        assert params["turnId"] == "source-turn" and isinstance(params["callId"], str) and params["callId"]
        assert params["arguments"]["threadId"] == "target"
        assert delivery_id in params["arguments"]["prompt"]
        assert "private payload" not in repr(request)
        assert route.get(f"/relay/messages/{sent.json()['message_id']}", params=scope).json()["deliveries"][0]["state"] == "pending"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        service.stop()
        desktop.close()


@native
@pytest.mark.parametrize("metadata", [None, {}, {"thread_ref": "source-chat"},
    {"thread_ref": "source-chat", "turn_ref": ""},
    {"thread_ref": "source-chat", "turn_ref": "source-turn", "extra": "x"}])
def test_inventory_invalid_private_caller_pair_denies_before_endpoint_transfer(tmp_path, monkeypatch, metadata):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        with pytest.raises(bridge.ShadowUnavailable, match="invalid-message"):
            client.register(metadata)
        assert service.custody is None and service.caller is None
        assert desktop.requests == []


@native
@pytest.mark.parametrize("fault,expected_stage,expected_category,expected_reason,request_count", [
    ("authority", "transfer-authority", "policy-changed", "policy-changed", 0),
    ("source", "before-source", "peer-mismatch", "peer-mismatch", 0),
    ("before-maintain", "before-authority", "policy-changed", "policy-inactive", 0),
    ("before-peer", "before-peer", "peer-mismatch", "policy-inactive", 0),
    ("write", "before-write", "transport-failed", "native-failed", 0),
    ("read", "before-read", "transport-failed", "native-failed", 1),
    ("validate", "before-validate-tool-fields", "invalid-response", "native-failed", 1),
    ("result", "before-result", "peer-mismatch", "peer-mismatch", 1),
    ("after-maintain", "before-authority", "policy-changed", "policy-inactive", 1),
    ("proof", "before-proof", "file-write-failed", "native-failed", 1),
], ids=["transfer-authority", "source-check", "before-maintain", "before-peer", "write", "read",
       "validate", "result", "after-maintain", "before-proof"])
def test_inventory_transfer_stage_diagnostics_from_private_caller(
    tmp_path, monkeypatch, inventory_caplog, fault, expected_stage, expected_category, expected_reason, request_count,
):
    state = {}

    def response(request, value):
        if fault == "validate":
            return {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{}]}}
        if fault == "after-maintain":
            path = state["directory"] / "policy.json"
            current = json.loads(path.read_bytes())
            arm_inventory(state["directory"], {**current, "revision": current["revision"] + 1})
        return value

    with inventory_running(tmp_path, monkeypatch, response=response) as (service, client, directory, desktop):
        caplog = inventory_caplog
        state["directory"] = directory
        expected_policy = bridge.InventoryPolicy.parse((directory / "policy.json").read_bytes())

        if fault in {"authority", "source"}:
            original = service._authorize
            calls = 0

            def authorize(revision=None):
                nonlocal calls
                calls += 1
                result = original(revision)
                if calls == 3 and fault == "authority":
                    raise bridge.ShadowUnavailable("policy-changed")
                if calls == 4 and fault == "source":
                    def source_gone():
                        raise bridge.ShadowUnavailable("peer-mismatch")
                    service.source.check = source_gone
                return result

            monkeypatch.setattr(service, "_authorize", authorize)
        elif fault == "before-maintain":
            original_observe = service._observe

            def fail_first_maintenance(deadline):
                original_load = service._load
                def fail_load():
                    monkeypatch.setattr(service, "_load", original_load)
                    raise bridge.ShadowUnavailable("policy-changed")
                monkeypatch.setattr(service, "_load", fail_load)
                return original_observe(deadline)

            monkeypatch.setattr(service, "_observe", fail_first_maintenance)
        elif fault == "before-peer":
            original_verify = bridge._DesktopPeer.verify
            calls = 0

            def fail_before_peer(self):
                nonlocal calls
                if self is service.desktop:
                    calls += 1
                    if calls == 5:
                        raise bridge.ShadowUnavailable("peer-mismatch")
                return original_verify(self)

            monkeypatch.setattr(bridge._DesktopPeer, "verify", fail_before_peer)
        elif fault in {"write", "read"}:
            name = "write" if fault == "write" else "read"
            original = getattr(bridge._DesktopIO, name)

            def fail_io(self, *args):
                if self is service.custody and (name == "read" or args[0].get("method") == "tools/list"):
                    raise bridge.ShadowUnavailable("transport-failed")
                return original(self, *args)

            monkeypatch.setattr(bridge._DesktopIO, name, fail_io)
        elif fault == "result":
            original_result = service._result
            def fail_result(*args, **kwargs):
                if kwargs.get("inventory_ok") is True:
                    raise bridge.ShadowUnavailable("peer-mismatch")
                return original_result(*args, **kwargs)
            monkeypatch.setattr(service, "_result", fail_result)
        elif fault == "after-maintain":
            pass
        elif fault == "proof":
            original_create = bridge._create_phase
            def fail_before(path_owner, path, sid, data):
                if path.name == "proof-before.json":
                    raise bridge.ShadowUnavailable("file-write-failed")
                return original_create(path_owner, path, sid, data)
            monkeypatch.setattr(bridge, "_create_phase", fail_before)

        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == expected_reason
        assert service.thread.is_alive() and not service.stop_event.is_set() and not service.unresolved
        assert service.fenced and service.admitted is None and service.custody is None and service.desktop is None
        if request_count:
            wait_until(lambda: len(desktop.requests) == request_count)
        assert desktop.connections <= 1 and len(desktop.requests) == request_count
        if fault != "authority":
            proof = read_proof(directory)
            assert proof["failure"] != "none"
            assert not proof["after_inventory_ok"]
        records = inventory_failure_records(caplog)
        assert len(records) == 1
        assert records[0].args == (expected_stage, expected_category, service.epoch, expected_policy.revision)


@native
@pytest.mark.parametrize("case,stage", [
    ("envelope", "validate-envelope"),
    ("version", "validate-version"),
    ("id-type", "validate-id-type"),
    ("id-match", "validate-id-match"),
    ("result-type", "validate-result-type"),
    ("result-fields", "validate-result-fields"),
    ("tools-type", "validate-tools-type"),
    ("tools-limit", "validate-tools-limit"),
    ("tool-type", "validate-tool-type"),
    ("tool-fields", "validate-tool-fields"),
    ("tool-name", "validate-tool-name"),
    ("tool-duplicate", "validate-tool-duplicate"),
    ("schema-type", "validate-schema-type"),
])
def test_inventory_validation_diagnostic_identifies_private_caller_rejection(
    tmp_path, monkeypatch, inventory_caplog, case, stage,
):
    secret = "private-native-sentinel"

    def response(request, value):
        tool = value["result"]["tools"][0]
        if case == "envelope":
            value["_meta"] = {"private": secret}
        elif case == "version":
            value["jsonrpc"] = secret
        elif case == "id-type":
            value["id"] = True
        elif case == "id-match":
            value["id"] = request["id"] + 1
        elif case == "result-type":
            value["result"] = []
        elif case == "result-fields":
            value["result"]["_meta"] = {"private": secret}
        elif case == "tools-type":
            value["result"]["tools"] = {}
        elif case == "tools-limit":
            value["result"]["tools"] = [tool.copy() for _ in range(513)]
        elif case == "tool-type":
            value["result"]["tools"] = [None]
        elif case == "tool-fields":
            del tool["inputSchema"]
        elif case == "tool-name":
            tool["name"] = f" {secret} "
        elif case == "tool-duplicate":
            value["result"]["tools"].append(tool.copy())
        elif case == "schema-type":
            tool["inputSchema"] = None
        return value

    with inventory_running(tmp_path, monkeypatch, response=response) as (service, client, directory, desktop):
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == "native-failed"
        assert not result["connected"] and not result["inventory_ok"]
        assert service.fenced and service.custody is None and service.desktop is None
        assert len(desktop.requests) == 1
        proof = read_proof(directory)
        assert proof["failure"] == "native-failed" and not proof["before_inventory_ok"]
        records = inventory_failure_records(inventory_caplog)
        assert len(records) == 1
        assert records[0].args == (f"before-{stage}", "invalid-response", service.epoch, 1)
        assert secret not in repr(records) and secret not in repr(proof)


@native
@pytest.mark.parametrize("schema", [
    {"type": "array", "items": {"type": "string"}},
    {"anyOf": [{"type": "object"}, {"type": "array"}]},
    {"properties": {"value": {"type": "string"}}},
])
def test_inventory_accepts_unrelated_dictionary_tool_schemas(
    tmp_path, monkeypatch, inventory_caplog, schema,
):
    def response(_request, value):
        value["result"]["tools"][0]["inputSchema"] = schema
        return value

    with inventory_running(tmp_path, monkeypatch, response=response) as (service, client, directory, desktop):
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "registered" and result["inventory_ok"]
        assert len(desktop.requests) == 1
        assert read_proof(directory)["before_inventory_ok"]
        assert not inventory_failure_records(inventory_caplog)


@native
def test_inventory_validation_diagnostic_valid_private_caller_response(tmp_path, monkeypatch, inventory_caplog):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "registered" and result["inventory_ok"]
        assert len(desktop.requests) == 1
        assert read_proof(directory)["before_inventory_ok"]
        assert not inventory_failure_records(inventory_caplog)


@native
@pytest.mark.parametrize("case,stage", [
    ("invalid-request", "before-validate-error-invalid-request"),
    ("tool-list-failed", "before-validate-error-tool-list"),
    ("wrong-id", "before-validate-envelope"),
    ("boolean-id", "before-validate-envelope"),
    ("wrong-jsonrpc", "before-validate-envelope"),
    ("boolean-code", "before-validate-envelope"),
    ("extra-envelope", "before-validate-envelope"),
    ("extra-error", "before-validate-envelope"),
    ("wrong-code", "before-validate-envelope"),
    ("wrong-message", "before-validate-envelope"),
    ("malformed-error", "before-validate-envelope"),
])
def test_inventory_desktop_error_envelope_classification_from_private_caller(
    tmp_path, monkeypatch, inventory_caplog, case, stage,
):
    secret = "private-native-error-sentinel"

    def response(request, _value):
        code, message = (-32602, "Invalid app tool request") if case == "invalid-request" else (
            -32000, "Codex app tool request failed")
        result = {"id": request["id"], "jsonrpc": "2.0", "error": {"code": code, "message": message}}
        if case == "wrong-id":
            result["id"] += 1
        elif case == "boolean-id":
            result["id"] = True
        elif case == "wrong-jsonrpc":
            result["jsonrpc"] = "1.0"
        elif case == "boolean-code":
            result["error"]["code"] = True
        elif case == "extra-envelope":
            result["private"] = secret
        elif case == "extra-error":
            result["error"]["data"] = secret
        elif case == "wrong-code":
            result["error"]["code"] = -1
        elif case == "wrong-message":
            result["error"]["message"] = secret
        elif case == "malformed-error":
            result["error"] = [secret]
        return result

    with inventory_running(tmp_path, monkeypatch, response=response) as (service, client, directory, desktop):
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == "native-failed"
        assert not result["connected"] and not result["inventory_ok"]
        assert service.fenced and service.custody is None and service.desktop is None
        assert len(desktop.requests) == 1
        proof = read_proof(directory)
        assert proof["failure"] == "native-failed" and not proof["before_inventory_ok"]
        records = inventory_failure_records(inventory_caplog)
        assert len(records) == 1
        assert records[0].args == (stage, "invalid-response", service.epoch, 1)
        assert secret not in repr(records) and secret not in repr(proof)


@native
def test_inventory_diagnostic_root_handler_cannot_leak_native_exception(
    tmp_path, monkeypatch, inventory_caplog, capsys,
):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        original = service.w.pipe.GetNamedPipeServerProcessId

        def fail_server_pid(handle):
            if service.custody is not None and handle == service.custody.handle:
                raise OSError("private-native-lookup-sentinel")
            return original(handle)

        monkeypatch.setattr(service.w.pipe, "GetNamedPipeServerProcessId", fail_server_pid)

        class BrokenStream:
            def write(self, value):
                raise OSError("private-log-sink-sentinel")

            def flush(self):
                pass

        root = logging.getLogger()
        handler = logging.StreamHandler(BrokenStream())
        root.addHandler(handler)
        try:
            result = client.register(INVENTORY_CALLER)
            assert result["status"] == "unavailable" and result["reason"] == "native-failed"
            assert service.thread.is_alive() and service.fenced and not service.unresolved
            assert service.custody is None and service.admitted is None and service.desktop is None
            assert desktop.connections == 1 and desktop.requests == []
            failure = read_proof(directory)
            assert failure["failure"] == "native-failed" and not failure["after_inventory_ok"]
            captured = capsys.readouterr()
            assert "private-native-lookup-sentinel" not in captured.err
            assert "Traceback" not in captured.err
        finally:
            root.removeHandler(handler)


@native
def test_inventory_transfer_keeps_primary_failure_when_logger_raises(
    tmp_path, monkeypatch, inventory_caplog, capsys,
):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        original = service.w.pipe.GetNamedPipeServerProcessId

        def fail_server_pid(handle):
            if service.custody is not None and handle == service.custody.handle:
                raise OSError("private-native-lookup-sentinel")
            return original(handle)

        def fail_logger(*args, **kwargs):
            raise OSError("private-log-sink-sentinel")

        monkeypatch.setattr(service.w.pipe, "GetNamedPipeServerProcessId", fail_server_pid)
        monkeypatch.setattr(bridge._log, "warning", fail_logger)
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == "native-failed"
        assert service._failure_diagnostic == ("native-peer", "unexpected")
        assert service.thread.is_alive() and service.fenced and not service.unresolved
        assert service.custody is None and service.admitted is None and desktop.requests == []
        captured = capsys.readouterr()
        assert "private-" not in captured.err and "Traceback" not in captured.err


@native
def test_inventory_primary_diagnostic_survives_secondary_failure_proof_error(
    tmp_path, monkeypatch, inventory_caplog,
):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        original_pid = service.w.pipe.GetNamedPipeServerProcessId

        def fail_server_pid(handle):
            if service.custody is not None and handle == service.custody.handle:
                raise OSError("private-native-lookup-sentinel")
            return original_pid(handle)

        original_create = bridge._create_phase

        def fail_failure_proof(w, path, sid, data):
            if path.name == "proof-failure.json":
                raise bridge.ShadowUnavailable("file-write-failed")
            return original_create(w, path, sid, data)

        monkeypatch.setattr(service.w.pipe, "GetNamedPipeServerProcessId", fail_server_pid)
        monkeypatch.setattr(bridge, "_create_phase", fail_failure_proof)
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and result["reason"] == "native-failed"
        assert service._failure_diagnostic == ("native-peer", "unexpected")
        assert service.thread.is_alive() and service.fenced and not service.unresolved
        assert service.custody is None and service.admitted is None and desktop.requests == []
        records = inventory_failure_records(inventory_caplog)
        assert len(records) == 1
        assert records[0].args == ("native-peer", "unexpected", service.epoch, 1)
        assert "private-native-lookup-sentinel" not in repr(result)


@native
def test_inventory_primary_diagnostic_survives_secondary_drop_failure(tmp_path, monkeypatch, inventory_caplog):
    with inventory_running(tmp_path, monkeypatch) as (service, client, _, desktop):
        original_pid = service.w.pipe.GetNamedPipeServerProcessId

        def fail_server_pid(handle):
            if service.custody is not None and handle == service.custody.handle:
                raise OSError("private-native-lookup-sentinel")
            return original_pid(handle)

        original_drop = service._drop
        calls = 0

        def fail_first_drop():
            nonlocal calls
            calls += 1
            original_drop()
            if calls == 1:
                raise OSError("private-cleanup-sentinel")

        monkeypatch.setattr(service.w.pipe, "GetNamedPipeServerProcessId", fail_server_pid)
        monkeypatch.setattr(service, "_drop", fail_first_drop)
        try:
            result = client.register(INVENTORY_CALLER)
        except bridge.ShadowUnavailable as exc:
            assert exc.category in {"peer-gone", "transport-failed", "deadline"}
        else:
            assert result["status"] == "unavailable"
        wait_until(lambda: not service.thread.is_alive())
        assert service._failure_diagnostic == ("native-peer", "unexpected")
        assert service.fenced and not service.unresolved and service.custody is None
        assert desktop.requests == []
        records = inventory_failure_records(inventory_caplog)
        assert len(records) == 1
        assert records[0].args == ("native-peer", "unexpected", service.epoch, 1)


@native
@pytest.mark.parametrize("fault", ["duplicate", "wrong-id", "boolean-id", "error", "wrong-jsonrpc", "tool-shape", "invalid-utf8", "empty", "timeout"])
def test_inventory_native_malformed_timeout_fences_custody(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(bridge, "EXCHANGE_SECONDS", .4)

    def bad(request, value):
        if fault == "duplicate":
            return b'{"jsonrpc":"2.0","id":1,"id":1,"result":{"tools":[]}}'
        if fault == "invalid-utf8":
            return b"\xff"
        if fault == "empty":
            return b""
        if fault == "timeout":
            return None
        if fault == "wrong-id":
            value["id"] += 1
        elif fault == "boolean-id":
            value["id"] = True
        elif fault == "error":
            del value["result"]
            value["error"] = {"code": -1, "message": "sensitive"}
        elif fault == "wrong-jsonrpc":
            value["jsonrpc"] = "1.0"
        elif fault == "tool-shape":
            value["result"]["tools"] = [{}]
        return value

    with inventory_running(tmp_path, monkeypatch, response=bad) as (service, client, _, desktop):
        if fault == "timeout":
            with pytest.raises(bridge.ShadowUnavailable):
                client.register(INVENTORY_CALLER)
            result = bridge._inventory_public("unavailable", "timeout")
            wait_until(lambda: service.custody is None)
        else:
            result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable" and not result["connected"]
        assert service.custody is None
        if fault != "timeout":
            try:
                assert client.register(INVENTORY_CALLER)["status"] == "unavailable"
            except bridge.ShadowUnavailable as exc:
                assert exc.category in {"transport-failed", "deadline", "stopped"}
        assert service.fenced
        assert desktop.connections == 1 and len(desktop.requests) == 1
        assert "sensitive" not in repr(result)


@native
@pytest.mark.parametrize("change", ["revoke", "expiry", "revision", "version"])
def test_inventory_runtime_authority_loss_closes_without_replacement(tmp_path, monkeypatch, change):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        policy_value = json.loads((directory / "policy.json").read_bytes())
        if change == "revoke":
            policy_value.update(revoked=True, enabled=False, revision=2)
        elif change == "expiry":
            policy_value["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        elif change == "revision":
            policy_value["revision"] = 2
        else:
            original = bridge._process_image
            monkeypatch.setattr(bridge, "_process_image", lambda w, h: (original(w, h)[0], "0.0.0.0"))
        arm_inventory(directory, policy_value)
        wait_until(lambda: service.custody is None)
        proof = read_proof(directory)
        assert not proof["after_inventory_ok"]
        try:
            assert client.register(INVENTORY_CALLER)["status"] == "unavailable"
        except bridge.ShadowUnavailable:
            assert service.fenced and service.custody is None
        assert desktop.connections <= 1 and len(desktop.requests) == 1


def test_inventory_frame_partial_read_write_and_limits(monkeypatch):
    incoming = bytearray()
    written = bytearray()
    io = bridge._DesktopIO(SimpleNamespace(file=SimpleNamespace()), object(), threading.Event())
    payload = encode({"data": "β"})
    incoming.extend(len(payload).to_bytes(4, "little") + payload)
    io.w.file.ReadFile = lambda _, size, ov: (0, bytes(incoming[:min(size, 2)]))
    io.w.file.WriteFile = lambda _, raw, ov: (0, raw)

    def operation(fn, deadline, keepalive=None):
        _, result = fn(None)
        if keepalive is None:
            del incoming[:len(result)]
            return len(result), result
        count = min(3, len(result))
        written.extend(result[:count])
        return count, None

    monkeypatch.setattr(io, "_operation", operation)
    assert io.read(time.monotonic() + 1) == {"data": "β"}
    io.write({"data": "β"}, time.monotonic() + 1)
    length = int.from_bytes(written[:4], "little")
    assert bridge._json(bytes(written[4:])) == {"data": "β"} and length == len(written) - 4
    for size in (0, bridge.MAX_DESKTOP_FRAME + 1):
        incoming.extend(size.to_bytes(4, "little"))
        with pytest.raises(bridge.ShadowUnavailable, match="message-limit"):
            io.read(time.monotonic() + 1)


@native
@pytest.mark.parametrize("field,value", [("pid", 1), ("creation", "other"), ("epoch", "other"), ("version", True)])
def test_inventory_stale_manifest_denies_before_native_access(tmp_path, monkeypatch, field, value):
    with inventory_running(tmp_path, monkeypatch, arm=False) as (_, client, directory, desktop):
        manifest = bridge._json(bridge._read_private(client.w, directory / "active.json", bridge._self_sid(client.w)))
        client.dispose()
        manifest[field] = value
        bridge._atomic_private(bridge._native(), directory / "active.json", bridge._self_sid(bridge._native()), encode(manifest))
        with pytest.raises(bridge.ShadowUnavailable, match="channel-unavailable"):
            bridge.NativeInventoryClient(directory / "active.json", threading.Event())
        assert desktop.connections == 0 and desktop.requests == []


@native
@pytest.mark.parametrize("ready_first", [False, True])
def test_inventory_unarmed_eof_releases_source_slot(tmp_path, monkeypatch, ready_first):
    directory = bridge.prepare_inventory_service(tmp_path / "unarmed-home")
    service = bridge.InventoryService(directory)
    first = replacement = None
    assert service.start() is service
    try:
        wait_until(lambda: (directory / "active.json").exists())
        first = bridge.NativeInventoryClient(directory / "active.json", threading.Event())
        if ready_first:
            assert first.ready()["status"] == "ready"
        else:
            wait_until(lambda: service.source is not None)
        first.dispose()
        wait_until(lambda: service.source is None)
        replacement = bridge.NativeInventoryClient(directory / "active.json", threading.Event())
        assert replacement.ready()["status"] == "ready"
        assert service.policy is None and service.custody is None
    finally:
        for client in (first, replacement):
            if client:
                client.dispose()
        service.stop()
        assert not service.unresolved


@native
def test_inventory_ready_does_not_extend_assignment_deadline(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch, arm=False) as (service, client, directory, _):
        original = service.ready_deadline
        assert client.ready()["status"] == "ready"
        assert service.ready_deadline == original
        service.ready_deadline = time.monotonic() - .01
        wait_until(lambda: service.source is None)
        assert service.custody is None and service.policy is None
        with pytest.raises(bridge.ShadowUnavailable):
            client.ready()


@native
@pytest.mark.parametrize("loss", ["revoke", "expiry"])
def test_inventory_loss_at_first_observation_entry_never_publishes_before_witness(tmp_path, monkeypatch, loss):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        original = service._observe

        def lose_authority(deadline):
            if loss == "revoke":
                value = inventory_policy(service, revision=2, enabled=False, revoked=True)
                arm_inventory(directory, value)
            else:
                service.utc_clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=400)
            return original(deadline)

        monkeypatch.setattr(service, "_observe", lose_authority)
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable"
        proof = read_proof(directory)
        assert not proof["before_inventory_ok"] and not proof["after_inventory_ok"]
        assert not proof["source_exited"] and proof["failure"] == "policy-inactive"
        assert desktop.requests == [] and service.custody is None


def test_inventory_maximum_json_frame_and_partial_body_deadline(monkeypatch):
    io = bridge._DesktopIO(SimpleNamespace(file=SimpleNamespace()), object(), threading.Event())
    raw = b'{"data":"' + b"x" * (bridge.MAX_DESKTOP_FRAME - 11) + b'"}'
    assert len(raw) == bridge.MAX_DESKTOP_FRAME
    incoming = bytearray(len(raw).to_bytes(4, "little") + raw)
    io.w.file.ReadFile = lambda _, size, ov: (0, bytes(incoming[:size]))

    def operation(fn, deadline, keepalive=None):
        _, result = fn(None)
        del incoming[:len(result)]
        return len(result), result

    monkeypatch.setattr(io, "_operation", operation)
    assert len(io.read(time.monotonic() + 1)["data"]) == bridge.MAX_DESKTOP_FRAME - 11
    incoming.extend((10).to_bytes(4, "little") + b"{}")
    original = io._operation

    def interrupted(fn, deadline, keepalive=None):
        if not incoming:
            raise bridge.ShadowUnavailable("deadline")
        return original(fn, deadline, keepalive)

    monkeypatch.setattr(io, "_operation", interrupted)
    with pytest.raises(bridge.ShadowUnavailable, match="deadline"):
        io.read(time.monotonic() + 1)


def test_inventory_unresolved_custody_retains_resource_and_fences_replacement(monkeypatch):
    service = bridge.InventoryService(Path("C:/isolated-inventory"))
    custody = SimpleNamespace(unresolved=True, close=lambda: pytest.fail("unresolved resource closed"))
    desktop = SimpleNamespace(close=lambda: pytest.fail("unresolved Desktop witness disposed"))
    service.custody, service.desktop = custody, desktop
    service._drop()
    assert service.unresolved and service.stop_event.is_set()
    assert service.custody is custody and service.desktop is desktop
    with pytest.raises(bridge.ShadowUnavailable, match="stopped"):
        service._authorize()


@native
@pytest.mark.asyncio
async def test_inventory_stdio_mcp_private_channel_fake_desktop_full_lifecycle(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    directory = bridge.prepare_inventory_service(tmp_path / "mcp-inventory-home")
    desktop = FakeDesktop()
    service = bridge.InventoryService(directory)
    assert service.start() is service
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PALLIUM_MCP_TRANSPORT": "stdio",
        "PALLIUM_AGENT_REF": "codex", "PALLIUM_CODEX_BRIDGE_MODE": "inventory",
        "PALLIUM_CODEX_INVENTORY_BOOTSTRAP_FILE": str(directory / "active.json"),
        "CODEX_APP_TOOLS_PIPE_PATH": desktop.endpoint, "PALLIUM_BASE_URL": "http://127.0.0.1:1"})
    child_code = """from app.mcp import server
class StatusClient:
    def __init__(self,ctx): pass
    async def get_status(self): return {"status":"healthy"}
server.PalliumMcpClient=StatusClient
server.main()
"""
    params = StdioServerParameters(command=sys.executable, args=["-c", child_code],
        cwd=str(Path(__file__).resolve().parents[1]), env=env)
    try:
        wait_until(lambda: (directory / "active.json").exists())
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    wait_until(lambda: service.ready_announced)
                    arm_inventory(directory, inventory_policy(service, service.source))
                    registered, ordinary = await asyncio.wait_for(asyncio.gather(
                        session.call_tool("pallium_codex_bridge_inventory_register", {},
                                          meta={"threadId": "source-chat", "turnId": "source-turn"}),
                        session.call_tool("pallium_status", {})), 5)
                    assert not registered.isError and not ordinary.isError
                    result = json.loads(registered.content[0].text)
                    assert result["status"] == "registered" and result["inventory_ok"]
                    assert json.loads(ordinary.content[0].text) == {"status": "healthy"}
                    assert read_proof(directory)["before_inventory_ok"]
                    assert len(desktop.requests) == 1 and desktop.connections == 1
            wait_until(lambda: read_proof(directory)["after_inventory_ok"], timeout=3)
            proof = read_proof(directory)
            assert proof["source_exited"] and proof["before_inventory_ok"] and proof["after_inventory_ok"]
            assert len(desktop.requests) == 2 and desktop.connections == 1
            errors.seek(0)
            assert desktop.endpoint not in errors.read()
    finally:
        service.stop()
        desktop.close()
        assert not service.unresolved and service.custody is None


@native
@pytest.mark.parametrize("second_loss", [None, "expiry", "version", "revoke", "shutdown", "exit-proof", "after-proof",
    "rearm-final-authority", "source-exit", "after-peer", "post-maintain-stop", "after-write", "after-read",
    "after-validate", "after-error-envelope", "after-result"])
def test_inventory_confirmed_source_process_exit_retains_same_connection(
    tmp_path, monkeypatch, inventory_caplog, second_loss,
):
    replacement_errors = watch_replacements(monkeypatch)
    directory = bridge.prepare_inventory_service(tmp_path / "exit-home")
    desktop = FakeDesktop()
    service = bridge.InventoryService(directory)
    caplog = inventory_caplog
    child = None
    if second_loss in {"after-validate", "after-error-envelope"}:
        desktop.response = lambda request, value: (
            ({"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{}]}}
             if second_loss == "after-validate" else
             {"jsonrpc": "2.0", "id": request["id"], "error": {
                 "code": -32000, "message": "Codex app tool request failed"}})
            if service.after_attempted else value
        )
    original_create_phase = bridge._create_phase

    def fail_exit_phase(w, path, sid, data):
        phase = "exit" if second_loss == "exit-proof" else "after"
        if second_loss in {"exit-proof", "after-proof"} and path.name == f"proof-{phase}.json":
            raise bridge.ShadowUnavailable("file-write-failed")
        return original_create_phase(w, path, sid, data)

    monkeypatch.setattr(bridge, "_create_phase", fail_exit_phase)
    if second_loss == "source-exit":
        native = bridge._native()
        original_wait = native.event.WaitForSingleObject

        def fail_source_exit_wait(handle, milliseconds):
            if (service.source is not None and handle == service.source.handle and service.proof is not None
                    and service.proof["before_inventory_ok"] and not service.after_attempted
                    and original_wait(handle, 0) == native.event.WAIT_OBJECT_0):
                return native.event.WAIT_FAILED
            return original_wait(handle, milliseconds)

        monkeypatch.setattr(native.event, "WaitForSingleObject", fail_source_exit_wait)
    elif second_loss == "after-peer":
        original_maintain = service._maintain
        def fail_after_peer_maintenance():
            if service.after_attempted:
                service.desktop.verify = lambda: (_ for _ in ()).throw(bridge.ShadowUnavailable("peer-mismatch"))
            return original_maintain()
        monkeypatch.setattr(service, "_maintain", fail_after_peer_maintenance)
    elif second_loss == "post-maintain-stop":
        original_maintain = service._maintain
        def stop_after_authority_maintenance():
            result = original_maintain()
            if service.after_attempted:
                service.stop_event.set()
            return result
        monkeypatch.setattr(service, "_maintain", stop_after_authority_maintenance)
    elif second_loss in {"after-write", "after-read"}:
        operation = second_loss.removeprefix("after-")
        original_operation = getattr(bridge._DesktopIO, operation)
        def fail_after_operation(self, *args):
            if service.custody is self and service.after_attempted:
                raise bridge.ShadowUnavailable("transport-failed")
            return original_operation(self, *args)
        monkeypatch.setattr(bridge._DesktopIO, operation, fail_after_operation)
    elif second_loss == "after-result":
        original_result = service._result
        def fail_after_result(*args, **kwargs):
            if service.after_attempted and kwargs.get("reason") == "observed":
                raise bridge.ShadowUnavailable("peer-mismatch")
            return original_result(*args, **kwargs)
        monkeypatch.setattr(service, "_result", fail_after_result)
    observe = service._observe
    observations = []

    def observe_with_loss(deadline):
        observations.append(1)
        if len(observations) == 2 and second_loss == "expiry":
            service.utc_clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=400)
        elif len(observations) == 2 and second_loss == "version":
            monkeypatch.setattr(bridge, "_process_image", lambda *args: (sys.executable, "0.0.0.0"))
        elif len(observations) == 2 and second_loss == "revoke":
            current = bridge._json(bridge._read_private(service.w, directory / "policy.json", service.sid))
            arm_inventory(directory, {**current, "revision": current["revision"] + 1, "revoked": True})
        elif len(observations) == 2 and second_loss == "shutdown":
            service.stop_event.set()
        return observe(deadline)

    monkeypatch.setattr(service, "_observe", observe_with_loss)
    assert service.start() is service
    try:
        wait_until(lambda: (directory / "active.json").exists())
        env = os.environ.copy()
        env["CODEX_APP_TOOLS_PIPE_PATH"] = desktop.endpoint
        child_code = """import json,sys,threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient
c=NativeInventoryClient(Path(sys.argv[1]),threading.Event())
print(json.dumps(c.ready()),flush=True)
sys.stdin.readline()
print(json.dumps(c.register({"thread_ref":"source-chat","turn_ref":"source-turn"})),flush=True)
sys.stdin.readline()
c.dispose()
"""
        child = subprocess.Popen([sys.executable, "-c", child_code, str(directory / "active.json")],
            cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8")
        assert json.loads(child.stdout.readline())["status"] == "ready"
        # Windows venv launcher may spawn the actual Python pipe owner.
        assert service.source.pid != os.getpid()
        armed = inventory_policy(service, service.source)
        baseline = bridge.InventoryPolicy.parse(encode(armed))
        arm_inventory(directory, armed)
        child.stdin.write("register\n")
        child.stdin.flush()
        assert json.loads(child.stdout.readline())["status"] == "registered"
        connection = service.custody.handle
        proof = read_proof(directory)
        assert proof["before_inventory_ok"] and not proof["source_exited"]
        child.stdin.write("exit\n")
        child.stdin.flush()
        assert child.wait(timeout=3) == 0
        if second_loss not in {None, "rearm-final-authority"}:
            wait_until(lambda: read_proof(directory)["failure"] != "none")
            proof = bridge.read_inventory_proof(directory, baseline)
            assert not proof["historical_transport_pass"] and not proof["after_inventory_ok"]
            assert proof["before_inventory_ok"]
            assert proof["source_exited"] is (second_loss not in {"exit-proof", "source-exit"})
            expected_requests = 2 if second_loss in {"after-proof", "after-read", "after-validate", "after-error-envelope", "after-result"} else 1
            assert len(desktop.requests) == expected_requests
            assert service.custody is None and desktop.connections == 1
            expected_failure = {
                "expiry": ("after-authority", "policy-inactive"),
                "exit-proof": ("exit-proof", "file-write-failed"),
                "after-proof": ("after-proof", "file-write-failed"),
                "source-exit": ("source-exit", "peer-mismatch"),
                "after-peer": ("after-peer", "peer-mismatch"),
                "post-maintain-stop": ("after-authority", "policy-inactive"),
                "after-write": ("after-write", "transport-failed"),
                "after-read": ("after-read", "transport-failed"),
                "after-validate": ("after-validate-tool-fields", "invalid-response"),
                "after-error-envelope": ("after-validate-error-tool-list", "invalid-response"),
                "after-result": ("after-result", "peer-mismatch"),
            }.get(second_loss)
            if expected_failure:
                records = inventory_failure_records(caplog)
                assert len(records) == 1
                assert records[0].args == (*expected_failure, service.epoch, baseline.revision)
            return
        try:
            wait_until(lambda: read_proof(directory)["after_inventory_ok"])
        except pytest.fail.Exception:
            pytest.fail(repr((service.stop_event.is_set(), service.unresolved, read_proof(directory), replacement_errors)))
        result = read_proof(directory)
        assert result["after_inventory_ok"] and result["source_exited"]
        assert not inventory_failure_records(caplog)
        assert service.custody is not None, (service.stop_event.is_set(), service.unresolved, read_proof(directory), replacement_errors)
        assert service.custody.handle is connection and desktop.connections == 1
        assert len(desktop.requests) == 2
        assert child.stderr.read() == ""
        # Completed evidence remains historical after ordinary later expiry and stop.
        service.utc_clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=400)
        wait_until(lambda: service.custody is None)
        assert not inventory_failure_records(caplog)
        if second_loss == "rearm-final-authority":
            wait_until(lambda: service.source is None)
            # Remove only this isolated trial's exact, service-owned sealed phase paths.
            for phase in bridge._PROOF_PHASES:
                path = directory / f"proof-{phase}.json"
                if path.exists():
                    path.unlink()
            service.utc_clock = lambda: datetime.now(timezone.utc)
            replacement = bridge.NativeInventoryClient(directory / "active.json", threading.Event())
            try:
                assert replacement.ready()["status"] == "ready"
                arm_inventory(directory, inventory_policy(service, service.source, revision=3))
                original_authorize = service._authorize
                calls = 0

                def fail_new_final_authority(revision=None):
                    nonlocal calls
                    calls += 1
                    result = original_authorize(revision)
                    if calls == 3:
                        raise bridge.ShadowUnavailable("policy-changed")
                    return result

                monkeypatch.setattr(service, "_authorize", fail_new_final_authority)
                result = replacement.register(INVENTORY_CALLER)
                assert result["status"] == "unavailable" and result["reason"] == "policy-changed"
                assert len(desktop.requests) == 2 and desktop.connections == 1
                records = inventory_failure_records(caplog)
                assert len(records) == 1
                assert records[0].args == ("transfer-authority", "policy-changed", service.epoch, 3)
            finally:
                replacement.dispose()
            service.stop()
            return
        service.stop()
        historic = bridge.read_inventory_proof(directory, baseline)
        assert historic["historical_transport_pass"] and historic["status"] == "historical"
        assert set(historic) == {"status", "reason", "source_exited", "before_inventory_ok",
                                 "after_inventory_ok", "historical_transport_pass"}
        assert not (directory / "proof-failure.json").exists()
    finally:
        if child is not None and child.poll() is None:
            child.stdin.close()
            child.wait(timeout=3)
        service.stop()
        desktop.close()
        assert not service.unresolved and service.custody is None


@native
@pytest.mark.parametrize("mutation", [None, "missing", "fingerprint", "revision", "epoch", "failure", "boolean", "expected",
    "directory", "reparse", "inspection-denied", "inspection-sentinel-denied", "before-exited", "exit-after", "after-before-false", "before-failed"])
def test_inventory_operator_phase_readback_is_correlated_historical_only(tmp_path, monkeypatch, mutation):
    with inventory_running(tmp_path, monkeypatch, arm=False) as (service, client, directory, desktop):
        expected = bridge.InventoryPolicy.parse(encode(inventory_policy(service)))
        values = {}
        for phase, exited, after in (("before", False, False), ("exit", True, False), ("after", True, True)):
            values[phase] = {"version": 1, "epoch": expected.service_epoch, "revision": expected.revision,
                "policy_fingerprint": bridge._inventory_fingerprint(expected), "before_inventory_ok": True,
                "after_inventory_ok": after, "source_exited": exited, "failure": "none"}
        if mutation == "fingerprint":
            values["after"]["policy_fingerprint"] = "0" * 64
        elif mutation == "revision":
            values["exit"]["revision"] += 1
        elif mutation == "epoch":
            values["after"]["epoch"] = "stale"
        elif mutation == "boolean":
            values["before"]["before_inventory_ok"] = 1
        elif mutation == "failure":
            values["failure"] = {**values["after"], "failure": "timeout"}
        elif mutation == "before-exited":
            values["before"]["source_exited"] = True
        elif mutation == "exit-after":
            values["exit"]["after_inventory_ok"] = True
        elif mutation == "after-before-false":
            values["after"]["before_inventory_ok"] = False
        elif mutation == "before-failed":
            values["before"]["failure"] = "timeout"
        for phase, value in values.items():
            if mutation != "missing" or phase != "exit":
                bridge._create_phase(service.w, directory / f"proof-{phase}.json", service.sid, encode(value))
        if mutation == "expected":
            expected = bridge.InventoryPolicy(**{**expected.__dict__, "service_pid": []})
        failure_path = directory / "proof-failure.json"
        if mutation == "directory":
            service.w.file.CreateDirectory(str(failure_path), bridge._security_attributes(service.w, service.sid, directory=True))
        elif mutation in {"reparse", "inspection-denied", "inspection-sentinel-denied"}:
            if mutation == "reparse":
                bridge._create_phase(service.w, failure_path, service.sid, b"{}")
            original_attributes = service.w.file.GetFileAttributes
            def attributes(filename):
                if str(filename) == str(failure_path):
                    if mutation == "reparse":
                        return service.w.con.FILE_ATTRIBUTE_REPARSE_POINT
                    if mutation == "inspection-sentinel-denied":
                        return -1
                    raise service.w.types.error(5, "GetFileAttributes", "injected denial")
                return original_attributes(filename)
            monkeypatch.setattr(service.w.file, "GetFileAttributes", attributes)
            if mutation == "inspection-sentinel-denied":
                monkeypatch.setattr(service.w.api, "GetLastError", lambda: 5)
        result = bridge.read_inventory_proof(directory, expected)
        assert set(result) == {"status", "reason", "source_exited", "before_inventory_ok",
                               "after_inventory_ok", "historical_transport_pass"}
        assert result["historical_transport_pass"] is (mutation is None)
        assert (result["status"] == "historical") is (mutation is None)
        if mutation not in {None, "missing", "failure"}:
            assert result["status"] == "invalid" and result["reason"] == "invalid-proof"
        assert desktop.connections == 0 and desktop.requests == []


@native
def test_inventory_phase_creation_does_not_overwrite_or_conflict_with_prior_reader(tmp_path):
    w = bridge._native()
    sid = bridge._self_sid(w)
    before = tmp_path / "proof-before.json"
    bridge._create_phase(w, before, sid, b'{"version":1}')
    handle = w.file.CreateFile(str(before), w.con.GENERIC_READ, w.con.FILE_SHARE_READ,
        None, w.con.OPEN_EXISTING, 0, None)
    try:
        bridge._create_phase(w, tmp_path / "proof-exit.json", sid, b'{"version":1}')
        with pytest.raises(bridge.ShadowUnavailable, match="file-write-failed"):
            bridge._create_phase(w, before, sid, b'{"version":2}')
    finally:
        bridge._close(handle)
    assert bridge._read_private(w, before, sid) == b'{"version":1}'
    assert not list(tmp_path.glob(".*.tmp"))


def test_inventory_proof_is_sealed_only_after_successful_after_publication(monkeypatch):
    service = bridge.InventoryService(Path("C:/isolated-inventory"))
    service.proof = {"after_inventory_ok": True, "failure": "none"}
    published = []
    monkeypatch.setattr(service, "_publish_proof", lambda: published.append(service.proof["failure"]))
    service._proof_failure("native-failed")
    assert published == ["native-failed"]
    service.proof["failure"] = "none"
    service.published_phases.add("after")
    service._proof_failure("stopped")
    assert service.proof["failure"] == "none" and published == ["native-failed"]


@native
@pytest.mark.parametrize("misuse", ["wrong-directory", "closed", "raw", "unissued", "altered-path", "altered-handle", "thread"])
def test_policy_lock_token_cannot_authorize_unrelated_or_closed_scope(tmp_path, misuse):
    w = bridge._native()
    sid = bridge._self_sid(w)
    path = tmp_path / "policy.json"
    bridge._atomic_private(w, path, sid, b'{"version":1}')
    token = bridge._policy_lock(w, path, sid)
    supplied = token
    unrelated = None
    try:
        if misuse == "wrong-directory":
            path = tmp_path / "other" / "policy.json"
        elif misuse == "closed":
            token.Close()
        elif misuse == "raw":
            supplied = token.handle
        elif misuse == "unissued":
            supplied = bridge._PolicyLock(token.path, sid, token.handle)
        elif misuse == "altered-path":
            path = tmp_path / "other" / "policy.json"
            token.path = path.parent / "policy.lock"
        elif misuse == "altered-handle":
            unrelated = bridge._lock_file(w, tmp_path / "unrelated.lock", sid)
            token.handle = unrelated
        elif misuse == "thread":
            errors = []
            def read_elsewhere():
                token.owner = threading.get_ident()
                try:
                    bridge._read_private(w, path, sid, policy_lock=token)
                except bridge.ShadowUnavailable as exc:
                    errors.append(exc.category)
            thread = threading.Thread(target=read_elsewhere)
            thread.start()
            thread.join(1)
            assert not thread.is_alive() and errors == ["invalid-policy-lock"]
            return
        with pytest.raises(bridge.ShadowUnavailable, match="invalid-policy-lock"):
            bridge._read_private(w, path, sid, policy_lock=supplied)
    finally:
        token.Close()
        if unrelated is not None:
            w.file.GetFileInformationByHandle(unrelated)
            bridge._close(unrelated)
        reusable = bridge._policy_lock(w, tmp_path / "policy.json", sid)
        reusable.Close()


def test_policy_lock_retries_only_explicit_real_contention(monkeypatch):
    w = SimpleNamespace()
    calls = []
    def deny(*args):
        calls.append(1)
        raise bridge.ShadowUnavailable("owner-busy")
    monkeypatch.setattr(bridge, "_lock_file", deny)
    with pytest.raises(bridge.ShadowUnavailable, match="owner-busy"):
        bridge._policy_lock(w, Path("C:/isolated/policy.json"), "sid")
    assert len(calls) == 1
    calls.clear()
    def contend(*args):
        calls.append(1)
        raise bridge.ShadowUnavailable("owner-busy", lock_contended=True)
    monkeypatch.setattr(bridge, "_lock_file", contend)
    start = time.monotonic()
    with pytest.raises(bridge.ShadowUnavailable, match="policy-busy"):
        bridge._policy_lock(w, Path("C:/isolated/policy.json"), "sid", start + .03)
    assert 1 < len(calls) < 20 and time.monotonic() - start < .15


@native
def test_inventory_failed_revoke_cas_preserves_old_authority_and_reports_failure(tmp_path, monkeypatch):
    home = tmp_path / "failed-revoke-home"
    directory = bridge.prepare_inventory_service(home)
    original = inventory_policy(SimpleNamespace(epoch="failed-revoke-epoch"))
    old = bridge.InventoryPolicy.parse(encode(original))
    arm_inventory(directory, original)
    proposed = tmp_path / "revoke-source.json"
    proposed.write_bytes(encode({**original, "revision": 2, "enabled": False, "revoked": True}))
    calls = []
    def reject(source, target):
        calls.append(1)
        raise PermissionError(13, "injected replacement denial")
    monkeypatch.setattr(os, "replace", reject)
    with pytest.raises(bridge.ShadowUnavailable, match="file-write-failed"):
        bridge.provision_inventory_policy(proposed, home, expected_revision=1)
    w = bridge._native()
    retained = bridge.InventoryPolicy.parse(bridge._read_private(w, directory / "policy.json", bridge._self_sid(w)))
    assert retained == old and retained.revision == 1 and not retained.revoked
    assert retained.valid(datetime.now(timezone.utc))
    assert calls == [1] and not list(directory.glob(".*.tmp"))
    token = bridge._policy_lock(w, directory / "policy.json", bridge._self_sid(w))
    token.Close()


@native
def test_inventory_competing_authenticated_child_cannot_replace_live_custody(tmp_path, monkeypatch):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        source = (service.source.pid, service.source.creation)
        connection = service.custody.handle
        client.dispose()
        code = """import json,sys,threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient
c=NativeInventoryClient(Path(sys.argv[1]),threading.Event())
try: print(json.dumps(c.ready()),flush=True)
finally: c.dispose()
"""
        child = subprocess.run([sys.executable, "-c", code, str(directory / "active.json")],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=4)
        assert child.returncode == 0 and child.stderr == ""
        result = json.loads(child.stdout)
        assert result["status"] == "unavailable" and result["reason"] == "busy"
        assert (service.source.pid, service.source.creation) == source
        assert service.custody.handle is connection and desktop.connections == 1
        assert len(desktop.requests) == 1


@native
@pytest.mark.parametrize("release", ["revoked", "expiry"])
def test_inventory_released_revision_requires_owned_phase_cleanup_before_rearm(tmp_path, monkeypatch, release):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        assert client.register(INVENTORY_CALLER)["status"] == "registered"
        if release == "revoked":
            previous = bridge._json(bridge._read_private(service.w, directory / "policy.json", service.sid))
            arm_inventory(directory, {**previous, "revision": 2, "revoked": True})
            revision = 3
        else:
            service.utc_clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=400)
            revision = 2
        wait_until(lambda: service.custody is None and service.replace_allowed)
        client.dispose()
        wait_until(lambda: service.source is None or service.stop_event.is_set())
        assert not service.stop_event.is_set()
        service.utc_clock = lambda: datetime.now(timezone.utc)
        replacement_desktop = FakeDesktop()
        replacement = None
        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", replacement_desktop.endpoint)
        try:
            replacement = bridge.NativeInventoryClient(directory / "active.json", threading.Event())
            assert replacement.ready()["status"] == "ready"
            arm_inventory(directory, inventory_policy(service, service.source, revision=revision))
            assert replacement.register(INVENTORY_CALLER)["reason"] == "busy"
            assert replacement_desktop.connections == 0 and replacement_desktop.requests == []
            # Explicit operator-owned cleanup, only this isolated completed trial's known evidence.
            for phase in bridge._PROOF_PHASES:
                path = directory / f"proof-{phase}.json"
                if path.exists():
                    path.unlink()
            assert replacement.register(INVENTORY_CALLER)["status"] == "registered"
            assert service.policy.revision == revision and len(replacement_desktop.requests) == 1
            assert replacement_desktop.connections == 1 and desktop.connections == 1
        finally:
            if replacement is not None:
                replacement.dispose()
            service.stop()
            replacement_desktop.close()


@native
@pytest.mark.parametrize("artifact", ["directory", "dangling-reparse-attributes", "inspection-denied", "parent-not-found",
    "inspection-sentinel-denied", "parent-sentinel-not-found"])
def test_inventory_prior_phase_presence_denies_before_capability_read(tmp_path, monkeypatch, artifact):
    with inventory_running(tmp_path, monkeypatch) as (service, client, directory, desktop):
        path = directory / "proof-before.json"
        if artifact == "directory":
            service.w.file.CreateDirectory(str(path), bridge._security_attributes(service.w, service.sid, directory=True))
        else:
            original_attributes = service.w.file.GetFileAttributes
            def attributes(filename):
                if str(filename) == str(path):
                    if artifact == "dangling-reparse-attributes":
                        return service.w.con.FILE_ATTRIBUTE_REPARSE_POINT
                    if "sentinel" in artifact:
                        return 0xFFFFFFFF
                    code = 3 if artifact == "parent-not-found" else 5
                    raise service.w.types.error(code, "GetFileAttributes", "injected inspection failure")
                return original_attributes(filename)
            monkeypatch.setattr(service.w.file, "GetFileAttributes", attributes)
            if "sentinel" in artifact:
                code = 3 if artifact == "parent-sentinel-not-found" else 5
                monkeypatch.setattr(service.w.api, "GetLastError", lambda: code)
        original_get = os.environ.get
        def env_get(name, *args):
            if name == "CODEX_APP_TOOLS_PIPE_PATH":
                pytest.fail("capability read despite prior phase or inconclusive inspection")
            return original_get(name, *args)
        monkeypatch.setattr(os.environ, "get", env_get)
        result = client.register(INVENTORY_CALLER)
        assert result["status"] == "unavailable"
        if artifact in {"directory", "dangling-reparse-attributes"}:
            assert result["reason"] == "busy"
        assert desktop.connections == 0 and desktop.requests == []


@native
def test_inventory_source_exits_during_first_read_never_qualifies_before_witness(tmp_path):
    directory = bridge.prepare_inventory_service(tmp_path / "first-exit-home")
    service = bridge.InventoryService(directory)
    child = None
    exit_witness = []
    def exit_during_response(request, value):
        assert request["id"] == 1
        child.stdin.write("exit\n")
        child.stdin.flush()
        state = service.w.event.WaitForSingleObject(service.source.handle, 1000)
        exit_witness.append(state == service.w.event.WAIT_OBJECT_0)
        assert exit_witness == [True]
        return value
    desktop = FakeDesktop(exit_during_response)
    assert service.start() is service
    try:
        wait_until(lambda: (directory / "active.json").exists())
        env = os.environ.copy()
        env["CODEX_APP_TOOLS_PIPE_PATH"] = desktop.endpoint
        code = """import json,os,sys,threading
from pathlib import Path
from app.codex_bridge_pipe import NativeInventoryClient
c=NativeInventoryClient(Path(sys.argv[1]),threading.Event())
print(json.dumps(c.ready()),flush=True)
sys.stdin.readline()
def exit_on_signal():
    sys.stdin.readline()
    os._exit(0)
threading.Thread(target=exit_on_signal,daemon=True).start()
c.register({"thread_ref":"source-chat","turn_ref":"source-turn"})
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(directory / "active.json")],
            cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8")
        assert json.loads(child.stdout.readline())["status"] == "ready"
        armed = inventory_policy(service, service.source)
        baseline = bridge.InventoryPolicy.parse(encode(armed))
        arm_inventory(directory, armed)
        child.stdin.write("register\n")
        child.stdin.flush()
        assert child.wait(timeout=3) == 0 and exit_witness == [True]
        wait_until(lambda: read_proof(directory)["failure"] != "none")
        proof = bridge.read_inventory_proof(directory, baseline)
        assert not proof["historical_transport_pass"]
        assert not proof["before_inventory_ok"] and not proof["after_inventory_ok"]
        assert not (directory / "proof-before.json").exists()
        assert not (directory / "proof-after.json").exists()
        assert desktop.connections == 1 and len(desktop.requests) == 1
        assert service.custody is None and child.stderr.read() == ""
    finally:
        if child is not None and child.poll() is None:
            child.stdin.write("exit\n")
            child.stdin.flush()
            child.wait(timeout=3)
        service.stop()
        desktop.close()
        assert not service.unresolved and service.custody is None
