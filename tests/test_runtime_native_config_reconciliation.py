"""Caller regressions for the deployed native/config/hook/dashboard source slice."""
from __future__ import annotations

import json
from itertools import count
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from app import codex_bridge_pipe as bridge
from app import dashboard
from app.cli import setup_codex
from app.mcp import codex_desktop_bridge as lifecycle
from tests.test_agent_relay_hooks import ROOT, _load
from tests.test_codex_retained_wake import retained as retained
from tests.test_codex_retained_wake import (
    test_conclusive_source_channel_eof_clears_registration_while_source_is_alive as _source_close_caller,
)


@pytest.fixture(autouse=True)
def isolated_hook_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(bridge, "_native_uncertain", False)
    monkeypatch.setattr(bridge, "_retained", [])


@pytest.mark.parametrize("clock_state", ["valid", "raises", "nonfinite"])
def test_source_channel_observations_preserve_the_existing_disposal_contract(
    retained, monkeypatch, caplog, capsys, clock_state,
):
    ticks = count()
    def observed():
        if clock_state == "raises":
            raise OSError("private-clock-sentinel")
        return float("nan") if clock_state == "nonfinite" else next(ticks)
    monkeypatch.setattr(bridge, "_source_observation_clock", observed)
    _source_close_caller(retained, monkeypatch, caplog, capsys, "alive")
    records = [record for record in caplog.records
               if record.msg.startswith("codex_retained_source_channel_closed ")]
    assert len(records) == 1
    line = records[0].getMessage()
    fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
    assert fields["source_call"] == "read"
    assert fields["request_epoch"] == retained[0].epoch
    assert fields["request_sequence"] == fields["request_verb"] == "unknown"
    assert fields["request_process_ms"] == fields["request_write_ms"] == "unknown"
    if clock_state == "valid":
        assert fields["service_stage"] == fields["prior_service_stage"] == "maintenance"
        assert fields["service_stage_ms"] == fields["prior_service_stage_ms"] == "1000"
        assert fields["request_read_ms"] == "1000" and fields["request_read_outcome"] == "raised"
        assert 0 <= int(fields["request_read_age_ms"]) <= 600000
    else:
        assert fields["service_stage"] == fields["prior_service_stage"] == "unknown"
        assert fields["request_read_ms"] == fields["request_read_outcome"] == "unknown"
    assert fields["io_precheck_budget_ms"] == fields["io_was_pending"] == fields["io_settled"] == "unknown"
    assert "private-clock-sentinel" not in line


@pytest.mark.parametrize("fault", ["read", "write", "precheck", "pending"])
def test_ready_native_failure_preserves_request_and_io_diagnostics(monkeypatch, tmp_path, fault):
    """Use the real request/I/O/cleanup path, not a fabricated traceback."""
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setattr(bridge, "_native_uncertain", False)
    monkeypatch.setattr(bridge, "_retained", [])
    clock, closed, state = {"now": 100.0}, [], {"written": 0, "reading": False}
    monkeypatch.setattr(bridge, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    monkeypatch.setattr(bridge, "_close", lambda handle: closed.append(handle))

    class NativeError(Exception):
        winerror = 109

    def write(_handle, raw, _overlapped):
        if fault == "write":
            raise NativeError("private-native-sentinel")
        state["written"] = len(raw)
        return 0, None

    def read(*_args):
        state["reading"] = True
        if fault == "pending":
            return 997, b""
        raise NativeError("private-native-sentinel")

    def result(*_args):
        if state["reading"]:
            return 0
        if fault == "precheck":
            clock["now"] = 104.0
        return state["written"]

    def wait(_event, milliseconds):
        if milliseconds == 100:
            return 0
        clock["now"] = 104.0
        return 258

    w = SimpleNamespace(
        types=SimpleNamespace(OVERLAPPED=SimpleNamespace, error=NativeError),
        event=SimpleNamespace(CreateEvent=lambda *_: object(), WaitForSingleObject=wait,
                              WAIT_OBJECT_0=0, WAIT_TIMEOUT=258),
        file=SimpleNamespace(ReadFile=read, WriteFile=write, GetOverlappedResult=result,
                             CancelIo=lambda *_: None),
    )
    native = bridge.NativeInventoryClient.__new__(bridge.NativeInventoryClient)
    native.w, native.stop_event = w, threading.Event()
    native.bootstrap_path, native.sid = tmp_path / "bootstrap.json", "test-sid"
    native.manifest = {"version": 1, "pid": 42, "creation": "bounded", "epoch": "a" * 32, "pipe": "bounded"}
    native.sequence, native.unresolved = 0, False
    native.peer = SimpleNamespace(check=lambda: None, close=lambda: closed.append("peer"))
    native.source = SimpleNamespace(pid=os.getpid(), creation="2026-01-02T03:04:05+00:00",
                                   check=lambda: None, close=lambda: closed.append("source"))
    native.io = bridge._PipeIO(w, object(), native.stop_event)
    monkeypatch.setattr(bridge, "_read_private", lambda *_: json.dumps(native.manifest).encode())
    try:
        with pytest.raises(bridge.ShadowUnavailable) as caught:
            native.ready()
        error = caught.value
        call = lifecycle._ready_failure_call(error)
        assert call == ("write" if fault == "write" else "read")
        assert error.category == ("deadline" if fault in {"precheck", "pending"} else "transport-failed")
        request = lifecycle._ready_failure_request(error)
        assert request == ("a" * 32, 1, "ready")
        io_state = lifecycle._ready_read_state(error)
        expected = (("unknown",) * 3 if fault == "write" else
                    (-1000 if fault == "precheck" else 3000, fault == "pending", fault == "pending"))
        assert io_state == expected
        assert bridge._source_failure_io_state(error, call) == (
            (3000, False, False) if fault == "write" else expected
        )
        worker = lifecycle.InventoryWorker.__new__(lifecycle.InventoryWorker)
        worker._retained, worker._restart_allowed = True, True
        worker._finish(native, reason="idle-ready-deadline" if error.category == "deadline" else "idle-ready-transport",
                       ready_call=call, read_state=io_state, request=request)
        assert worker._restart_allowed and native.io is native.source is native.peer is None
        line = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
        assert f"own_pid={os.getpid()} native_creation=2026-01-02T03:04:05+00:00 unresolved=False" in line
        assert f"ready_call={call} read_precheck_budget_ms={expected[0]} read_was_pending={expected[1]} read_settled={expected[2]}" in line
        assert "request_epoch=" + "a" * 32 + " request_sequence=1 request_verb=ready" in line
        assert "private-native-sentinel" not in line
        assert "peer" in closed and "source" in closed and not bridge._native_uncertain
    finally:
        native.dispose()


@pytest.mark.parametrize("elapsed,ended,returned,observed,valid", [
    (0, 0, True, 0, True), (600, 0, False, 600, True),
    (-0.001, 0, True, 0, False), (600.001, 0, True, 0, False),
    (True, 0, True, 0, False), (0, 0, 1, 0, False),
    (0, 0, True, 600.001, False), (0, 1, True, 0, False),
    (float("nan"), 0, True, 0, False), (0, float("inf"), True, 0, False),
])
def test_source_request_observation_bounds(elapsed, ended, returned, observed, valid):
    fields = bridge._source_request_fields("a" * 32, {
        "sequence": 1, "verb": "register", "source-read": (elapsed, ended, returned),
    }, observed)
    assert fields[:3] == ("a" * 32, 1, "register")
    assert fields[3:6] == ((int(elapsed * 1000), "returned" if returned else "raised",
                           int((observed - ended) * 1000)) if valid else ("unknown",) * 3)
    assert fields[6:] == ("unknown",) * 6


@pytest.mark.parametrize("sequence,verb", [(True, "ready"), (0, "ready"), (1, "private-雪"), (1, [])])
def test_source_request_observation_never_logs_unvalidated_metadata(sequence, verb):
    fields = bridge._source_request_fields("private-epoch-sentinel", {
        "sequence": sequence, "verb": verb, "private-payload": "private-content-sentinel",
    }, 0)
    assert fields == ("unknown",) * 12


@pytest.mark.parametrize("source", ["startup", "resume", "compact"])
def test_codex_setup_and_packaged_matcher_preserve_existing_handlers(source):
    data = {"hooks": {"SessionStart": [{"matcher": "third-party", "hooks": [{"type": "command", "command": "unrelated"}]}]}}
    first = setup_codex._register_hooks(data)
    assert first["hooks"]["SessionStart"][0] == {"matcher": "third-party", "hooks": [{"type": "command", "command": "unrelated"}]}
    assert first == setup_codex._register_hooks(json.loads(json.dumps(first)))
    packaged = json.loads((ROOT / "integrations/codex/hooks/hooks.json").read_text(encoding="utf-8"))
    for hooks in (first, packaged):
        managed = [entry for entry in hooks["hooks"]["SessionStart"]
                   if any("session_start.py" in hook.get("command", "") for hook in entry["hooks"])]
        assert len(managed) == 1 and source in managed[0]["matcher"].split("|")


@pytest.mark.parametrize("relay_admission_clock", ["semantic"], indirect=True)
@pytest.mark.parametrize("endpoints,compact", [(0, False), (0, True), (2, False), (2, True)])
def test_dashboard_session_projection_avoids_global_collision_summary(
    client, monkeypatch, relay_admission_clock, endpoints, compact,
):
    storage = client.app.state.pallium_service._storage
    if endpoints:
        with relay_admission_clock(storage, expected_admissions=3):
            for session_ref, container in [("shared-雪", "scope-a"), ("shared-雪", "scope-b"), ("sender", "scope-a")]:
                response = client.post("/relay/turn", json={
                    "runtime": "claude-code", "session_ref": session_ref, "container_ref": container,
                })
                assert response.status_code == 200
        rows = client.get("/dashboard/api/relay/sessions", params={"compact": "true", "session_ref": "shared-雪", "runtime": "claude-code"}).json()["sessions"]
        recipient = next(row["id"] for row in rows if row["container_ref"] == "scope-a")
        sent = client.post("/relay/messages", json={
            "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": recipient,
            "payload": "private-dashboard-sentinel", "container_ref": "scope-a", "expires_in_seconds": 3600,
        })
        assert sent.status_code == 200
    before = client.get("/dashboard/api/relay/summary").json()
    calls = []
    original = dashboard._dashboard_relay_identity_collisions
    def record(session, *args, **kwargs):
        calls.append((kwargs.get("include_summary", True), kwargs.get("include_details", False)))
        execute = session.execute
        def without_global_aggregate(statement, *execute_args, **execute_kwargs):
            columns = set(statement.selected_columns.keys())
            assert not {"group_count", "endpoint_count", "delivery_count"}.issubset(columns)
            return execute(statement, *execute_args, **execute_kwargs)
        with monkeypatch.context() as query_patch:
            query_patch.setattr(session, "execute", without_global_aggregate)
            return original(session, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(dashboard, "_dashboard_relay_identity_collisions", record)
        response = client.get("/dashboard/api/relay/sessions", params={
            "compact": str(compact).lower(), "runtime": "claude-code", "session_ref": "shared-雪",
        })
        messages = client.get("/dashboard/api/relay/messages", params={"limit": 1})
    assert response.status_code == 200
    assert messages.status_code == 200
    body = response.json()
    assert body["total"] == len(body["sessions"]) == endpoints
    assert calls == [(False, False)] * (1 if compact else 2)
    if endpoints and not compact:
        assert all(row["possible_identity_collision"]["group_endpoint_count"] == 2 for row in body["sessions"])
        assert sum(row["possible_identity_collision"]["endpoint_claimable_delivery_count"] for row in body["sessions"]) == 1
    if endpoints:
        assert any(row.get("possible_identity_collision") and row["possible_identity_collision"]["group_endpoint_count"] == 2
                   for row in messages.json()["endpoint_sessions"])
    else:
        assert messages.json()["endpoint_sessions"] == []
    after = client.get("/dashboard/api/relay/summary").json()
    assert before["deliveries"] == after["deliveries"]
    assert before["possible_identity_collisions"]["group_count"] == after["possible_identity_collisions"]["group_count"] == (1 if endpoints else 0)
    assert "private-dashboard-sentinel" not in json.dumps(body)


# Reuse the exact focused PR381 compact-hook regressions; no historical test run is claimed here.

def test_codex_session_start_compact_restores_only_pinned_scope(monkeypatch, capsys):
    hook = _load("codex_session_start_compact", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "source": "compact", "session_id": "current-runtime-session", "cwd": "/different-project",
    })
    monkeypatch.setattr(hook._common, "get_pinned_container", lambda sid: (
        "git:example.test/project-東京" if sid == "current-runtime-session" else None
    ))
    for name in ("derive_container_ref", "derive_actor_ref", "pin_container", "relay_turn",
                 "acknowledge_relay", "_fetch_retrieval_fallback"):
        monkeypatch.setattr(hook, name, lambda *_a, **_k: pytest.fail("compact must only restore the pin"))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    context = output["additionalContext"]
    scope = json.loads(context.removeprefix("[Pallium scope — ").removesuffix("]"))
    assert scope == {"container_ref": "git:example.test/project-東京", "thread_ref": "current-runtime-session",
                     "agent_ref": "codex", "visibility": "private"}

@pytest.mark.parametrize("session,state", [
    (None, {"container_ref": "git:example/project"}),
    ("", {"container_ref": "git:example/project"}),
    (17, {"container_ref": "git:example/project"}),
    ("../other-session", {"container_ref": "git:example/project"}),
    ("current-session", None), ("current-session", {}),
    ("current-session", {"container_ref": ""}),
    ("current-session", {"container_ref": []}),
    ("current-session", {"container_ref": "git:example/bad\nscope"}),
    ("current-session", {"container_ref": "x" * 1300}),
])
def test_codex_compact_missing_or_invalid_pin_never_derives_scope(monkeypatch, capsys, session, state):
    hook = _load("codex_compact_invalid_pin", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "source": "compact", "session_id": session, "cwd": "/valid-but-unrelated-project",
    })
    monkeypatch.setattr(hook._common, "_read_session_state", lambda *_: state)
    for name in ("derive_container_ref", "derive_actor_ref", "pin_container", "relay_turn",
                 "acknowledge_relay", "_fetch_retrieval_fallback"):
        monkeypatch.setattr(hook, name, lambda *_a, **_k: pytest.fail("missing compact pin must fail closed"))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    assert capsys.readouterr().out == ""

@pytest.mark.parametrize("length", [1200, 1201])
def test_codex_compact_scope_obeys_exact_output_boundary(monkeypatch, capsys, length):
    hook = _load("codex_compact_output_boundary", "integrations/codex/hooks/session_start.py")
    overhead = len(hook.format_injection([], "x", 1200, thread_ref="current-session",
        agent_ref="codex", visibility="private")) - 1
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"source": "compact", "session_id": "current-session"})
    monkeypatch.setattr(hook._common, "get_pinned_container", lambda *_: "x" * (length - overhead))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    output = capsys.readouterr().out
    if length == 1200:
        assert len(json.loads(output)["hookSpecificOutput"]["additionalContext"]) == 1200
    else:
        assert output == ""

def test_codex_compact_emission_failure_does_not_fall_back_or_ack(monkeypatch, capsys):
    hook = _load("codex_compact_emit_failure", "integrations/codex/hooks/session_start.py")
    monkeypatch.setattr(hook, "read_hook_input", lambda: {"source": "compact", "session_id": "current-session"})
    monkeypatch.setattr(hook._common, "get_pinned_container", lambda *_: "git:example/project")
    def fail_emit(*args):
        raise OSError("controlled sink failure")
    monkeypatch.setattr(hook, "emit_context", fail_emit)
    for name in ("derive_container_ref", "pin_container", "relay_turn", "acknowledge_relay", "_fetch_retrieval_fallback"):
        monkeypatch.setattr(hook, name, lambda *_a, **_k: pytest.fail("compact emission failure must not consume messages"))
    with pytest.raises(SystemExit) as exited:
        hook.main()
    assert exited.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "controlled sink failure" in captured.err

@pytest.mark.parametrize("pin", ["valid", "missing", "corrupt"])
def test_codex_compact_actual_subprocess_restores_scope_without_network_or_state_mutation(tmp_path, pin):
    import os

    private_home = tmp_path / "private-home"
    sessions = private_home / ".pallium" / "hooks" / "state" / "sessions"
    sessions.mkdir(parents=True)
    current = sessions / "runtime-current.json"
    if pin == "valid":
        current.write_text(json.dumps({"container_ref": "git:example.test/scope-東京", "container_generation": 7}), encoding="utf-8")
    elif pin == "corrupt":
        current.write_text("{", encoding="utf-8")
    (sessions / "other-runtime.json").write_text(json.dumps({"container_ref": "git:example.test/other"}), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in sessions.iterdir()}
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    ledger = tmp_path / "forbidden-operations.jsonl"
    marker = tmp_path / "bootstrap-active"
    (bootstrap / "sitecustomize.py").write_text(
        "import os,socket,subprocess,urllib.request\n"
        "open(os.environ['PALLIUM_TEST_BOOTSTRAP_MARKER'],'w').write('active')\n"
        "def denied(*args,**kwargs):\n"
        " with open(os.environ['PALLIUM_TEST_NETWORK_LEDGER'],'a') as f:f.write('forbidden\\n')\n"
        " raise OSError('operations disabled in compact hook control')\n"
        "socket.socket.connect=socket.getaddrinfo=denied\n"
        "urllib.request.urlopen=urllib.request.OpenerDirector.open=denied\n"
        "subprocess.Popen=denied\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "integrations/codex/hooks/session_start.py")],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "compact",
                          "session_id": "runtime-current", "cwd": str(tmp_path / "other-project")}),
        capture_output=True, text=True, encoding="utf-8", timeout=10,
        env={**os.environ, "HOME": str(private_home), "USERPROFILE": str(private_home),
             "PYTHONPATH": str(bootstrap), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
             "PALLIUM_TEST_NETWORK_LEDGER": str(ledger), "PALLIUM_TEST_BOOTSTRAP_MARKER": str(marker)},
    )
    assert result.returncode == 0 and result.stderr == ""
    assert marker.read_text() == "active" and not ledger.exists()
    assert {p.name: p.read_bytes() for p in sessions.iterdir()} == before
    if pin == "valid":
        output = json.loads(result.stdout)["hookSpecificOutput"]
        assert output["hookEventName"] == "SessionStart"
        scope = json.loads(output["additionalContext"].removeprefix("[Pallium scope — ").removesuffix("]"))
        assert scope == {"container_ref": "git:example.test/scope-東京", "thread_ref": "runtime-current",
                         "agent_ref": "codex", "visibility": "private"}
    else:
        assert result.stdout == ""
