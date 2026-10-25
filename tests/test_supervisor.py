from __future__ import annotations

from tests.test_windows_service import guard_native_calls, guard_selected_mock

"""Unit tests for app.supervisor — health probe and restart resilience.

All tests use fake time, fake processes, and injectable parameters.
No real processes are spawned.  Not marked slow (fast, no real sleeping).
"""

from contextlib import contextmanager
import itertools
import os
from unittest.mock import patch

import pytest

with guard_native_calls():
    from app.supervisor import (
        _API_HEALTH_PROBE_FAIL_THRESHOLD,
        _API_HEALTH_PROBE_INTERVAL,
        _MAX_RAPID_RESTARTS,
        run_supervisor,
    )


@pytest.fixture(autouse=True)
def _isolate_supervisor_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path):
    home = tmp_path / "pallium"
    private_env = {
        "HOME": str(tmp_path / "profile"),
        "USERPROFILE": str(tmp_path / "profile"),
        "APPDATA": str(tmp_path / "profile" / "AppData" / "Roaming"),
        "PALLIUM_HOME": str(home),
        "PALLIUM_CONFIG_FILE": str(tmp_path / "config.toml"),
        "PALLIUM_ENV_FILE": str(tmp_path / ".env"),
        "PALLIUM_STORAGE_BACKEND": "memory",
        "PALLIUM_SQLITE_URL": f"sqlite:///{tmp_path / 'pallium.db'}",
        "PALLIUM_SNAPSHOT_ENABLED": "false",
        "PALLIUM_SNAPSHOT_PATH": str(tmp_path / "snapshots"),
        "PALLIUM_CODEX_WAKE_DIR": str(tmp_path / "codex-wake"),
        "PALLIUM_CLAUDE_WAKE_DIR": str(tmp_path / "claude-wake"),
    }
    for key, value in private_env.items():
        monkeypatch.setenv(key, value)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakePopen:
    """Minimal fake subprocess.Popen for supervisor tests."""

    _pid_counter = itertools.count(1000)

    def __init__(self, poll_returns=None):
        self.pid = next(self._pid_counter)
        self.returncode = 1
        # poll_returns: iterable of values; exhausted → returns None forever
        self._poll_iter = iter(poll_returns if poll_returns is not None else [])
        self._poll_exhausted = False
        self._killed = False
        self._terminated = False

    def poll(self):
        if self._poll_exhausted:
            return None
        try:
            val = next(self._poll_iter)
            return val
        except StopIteration:
            self._poll_exhausted = True
            return None

    def kill(self):
        self._killed = True

    def terminate(self):
        self._terminated = True

    def wait(self, timeout=None):
        pass


def _fake_kill_fn(process, *, force=False, **kwargs):
    """Test stand-in for _kill_tree that sets the same flags real terminate()/kill() set.

    Mirrors the production helper's escalation contract: force=False ≈ terminate,
    force=True ≈ kill. The supervisor's finally block calls force=False then
    later force=True — both must mark the FakePopen so existing assertions
    (._killed, ._terminated) keep their meaning.
    """
    if force:
        process._killed = True
    else:
        process._terminated = True


def _make_clock(times):
    """Return a clock() callable that yields values from *times* in sequence,
    then repeats the last value forever."""
    it = iter(times)
    last = [0.0]

    def clock():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return clock


def _counter_stop(n):
    """Return a should_stop callable that returns True after n calls."""
    calls = [0]

    def should_stop():
        calls[0] += 1
        return calls[0] > n

    return should_stop


# Common args for run_supervisor — no real snapshot, no reload
_BASE_ARGS = ["--host", "127.0.0.1", "--port", "19999", "--processors", "1", "--cleaners", "0"]


def _use_stop(monkeypatch, stop):
    @contextmanager
    def fake_graceful_stop(*, install=True):
        yield stop

    monkeypatch.setattr("app.supervisor.graceful_stop", fake_graceful_stop)


def test_zero_processors_keeps_api_available_without_worker():
    api_proc = FakePopen(poll_returns=[])
    commands = []

    def popen_factory(cmd, **kwargs):
        commands.append(cmd)
        return api_proc

    result = run_supervisor(
        ["--host", "127.0.0.1", "--port", "19999", "--processors", "0", "--cleaners", "0"],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        wait_for_api_fn=lambda *_, **__: True,
        should_stop=_counter_stop(0),
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert len(commands) == 1
    assert "serve" in commands[0]


def test_initial_api_retry_exhaustion_is_failure(monkeypatch):
    killed = []
    monkeypatch.setattr("app.supervisor._kill_tree", lambda proc, **_kw: killed.append(proc.pid))
    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=lambda *_args, **_kwargs: FakePopen(),
        sleep_fn=lambda _: None,
        wait_for_api_fn=lambda *_args, **_kwargs: False,
        kill_fn=_fake_kill_fn,
    )

    assert result == 1
    assert len(killed) == 5


def test_stop_during_initial_readiness_keeps_child_owned_and_skips_helpers(monkeypatch):
    from types import SimpleNamespace

    stop = SimpleNamespace(requested=False)
    _use_stop(monkeypatch, stop)
    processes = []
    commands = []

    def popen_factory(command, **_kwargs):
        commands.append(command)
        proc = FakePopen()
        processes.append(proc)
        return proc

    def ready_then_stop(*_args, **_kwargs):
        stop.requested = True
        return True

    result = run_supervisor(
        ["--processors", "1", "--cleaners", "1"],
        popen_factory=popen_factory,
        wait_for_api_fn=ready_then_stop,
        sleep_fn=lambda _: None,
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert len(commands) == 1
    assert processes[0]._terminated


def test_stop_before_initial_retry_starts_no_child(monkeypatch):
    from types import SimpleNamespace

    stop = SimpleNamespace(requested=True)
    _use_stop(monkeypatch, stop)
    calls = []

    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=lambda *_args, **_kwargs: calls.append(True),
        wait_for_api_fn=lambda *_args, **_kwargs: False,
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert calls == []


def test_runtime_api_retry_exhaustion_is_failure(monkeypatch):
    popen_calls = []

    def popen_factory(*_args, **_kwargs):
        proc = FakePopen(poll_returns=[1]) if not popen_calls else FakePopen()
        popen_calls.append(proc)
        return proc

    monkeypatch.setattr("app.supervisor._kill_tree", lambda *_args, **_kwargs: None)
    wait_calls = [0]

    def wait_for_api(*_args, **_kwargs):
        wait_calls[0] += 1
        return wait_calls[0] == 1

    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=popen_factory,
        wait_for_api_fn=wait_for_api,
        sleep_fn=lambda _: None,
        should_stop=lambda: False,
        clock=lambda: 0.0,
        kill_fn=_fake_kill_fn,
    )

    assert result == 1
    assert len(popen_calls) == 6


def test_stop_during_runtime_retry_is_success(monkeypatch):
    from types import SimpleNamespace

    stop = SimpleNamespace(requested=False)
    _use_stop(monkeypatch, stop)
    popen_calls = []
    retry_kills = []

    def popen_factory(*_args, **_kwargs):
        proc = FakePopen(poll_returns=[1]) if not popen_calls else FakePopen()
        popen_calls.append(proc)
        return proc

    monkeypatch.setattr("app.supervisor._kill_tree", lambda proc, **_kw: retry_kills.append(proc.pid))
    wait_calls = [0]

    def wait_for_api(*_args, **_kwargs):
        wait_calls[0] += 1
        if wait_calls[0] == 1:
            return True
        stop.requested = True
        return False

    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=popen_factory,
        wait_for_api_fn=wait_for_api,
        sleep_fn=lambda _: None,
        should_stop=lambda: False,
        clock=lambda: 0.0,
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert retry_kills == [popen_calls[1].pid]


def test_stop_during_successful_runtime_replacement_cleans_owned_child(monkeypatch):
    from types import SimpleNamespace

    stop = SimpleNamespace(requested=False)
    _use_stop(monkeypatch, stop)
    processes = []
    commands = []

    def popen_factory(command, **_kwargs):
        commands.append(command)
        proc = FakePopen(poll_returns=[1]) if not processes else FakePopen()
        processes.append(proc)
        return proc

    readiness_calls = 0

    def ready_then_stop(*_args, **_kwargs):
        nonlocal readiness_calls
        readiness_calls += 1
        if readiness_calls == 2:
            stop.requested = True
        return True

    result = run_supervisor(
        ["--processors", "1", "--cleaners", "0"],
        popen_factory=popen_factory,
        wait_for_api_fn=ready_then_stop,
        sleep_fn=lambda _: None,
        should_stop=lambda: False,
        clock=lambda: 0.0,
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert readiness_calls == 2
    assert len(commands) == 3  # initial API, one processor, replacement API
    assert processes[1]._terminated
    assert processes[2]._terminated


def test_stop_during_slot_poll_skips_exit_restart(monkeypatch):
    from types import SimpleNamespace

    stop = SimpleNamespace(requested=False)
    _use_stop(monkeypatch, stop)

    class StopOnPoll(FakePopen):
        def poll(self):
            stop.requested = True
            return 1

    calls = []
    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=lambda *_args, **_kwargs: calls.append(True) or StopOnPoll(),
        wait_for_api_fn=lambda *_args, **_kwargs: True,
        should_stop=lambda: False,
        kill_fn=_fake_kill_fn,
    )

    assert result == 0
    assert calls == [True]


def test_repeated_zero_code_api_exits_are_failure():
    class RepeatedZeroExit(FakePopen):
        def poll(self):
            return 0

    result = run_supervisor(
        ["--processors", "0", "--cleaners", "0"],
        popen_factory=lambda *_args, **_kwargs: RepeatedZeroExit(),
        wait_for_api_fn=lambda *_args, **_kwargs: True,
        should_stop=lambda: False,
        clock=lambda: 0.0,
        kill_fn=_fake_kill_fn,
    )

    assert result == 1


def test_readiness_wait_observes_requested_stop(monkeypatch):
    from types import SimpleNamespace
    from app.supervisor import _wait_for_api

    stop = SimpleNamespace(requested=False)

    class RefusedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _timeout):
            pass

        def connect(self, _address):
            raise ConnectionRefusedError

    import socket
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: RefusedSocket())

    def request_stop(_delay):
        stop.requested = True

    assert not _wait_for_api(
        "127.0.0.1", 19999, timeout=5,
        sleep_fn=request_stop,
        stop=stop,
        clock=lambda: 0,
    )


# ---------------------------------------------------------------------------
# Test 1: health probe kills API after consecutive failures
# ---------------------------------------------------------------------------

def test_health_probe_kills_api_after_consecutive_failures():
    """API alive, probe fails twice → kill() called, counter resets."""

    api_proc = FakePopen(poll_returns=[])  # poll() always None (alive)
    worker_proc = FakePopen(poll_returns=[])

    procs = iter([api_proc, worker_proc])

    def popen_factory(cmd, **kwargs):
        return next(procs)

    # Clock: initial value, then advance past probe interval twice.
    # clock() is called once per iteration (probe check only — no call during slot poll
    # when all processes are alive and poll() returns None).
    # _last_probe init: 0.0
    # Iter 1 probe: 0.0 - 0.0 = 0 < 30 → no probe
    # Iter 2 probe: 0.0 - 0.0 = 0 < 30 → no probe
    # Iter 3 probe: 31.0 - 0.0 = 31 ≥ 30 → probe 1 fires (fail, _last_probe=31.0)
    # Iter 4 probe: 62.0 - 31.0 = 31 ≥ 30 → probe 2 fires (fail) → kill
    # Iter 5: should_stop fires → break before probe
    clock_values = [
        0.0,   # _last_probe init (before loop)
        0.0,   # iter 1 — probe check: 0.0 - 0.0 = 0 < 30 → no probe
        0.0,   # iter 2 — probe check: 0.0 - 0.0 = 0 < 30 → no probe
        31.0,  # iter 3 — probe check: 31.0 - 0.0 = 31 ≥ 30 → probe 1 fires (fail, _last_probe=31.0)
        62.0,  # iter 4 — probe check: 62.0 - 31.0 = 31 ≥ 30 → probe 2 fires (fail) → kill
        62.0,  # kill reset: _last_probe = clock() after kill (iter 5 breaks via should_stop before probe)
    ]
    clock = _make_clock(clock_values)

    # Probe always fails
    with patch("app.supervisor._tcp_probe", return_value=False):
        result = run_supervisor(
            _BASE_ARGS,
            popen_factory=popen_factory,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=clock,
            should_stop=_counter_stop(4),
            kill_fn=_fake_kill_fn,
        )

    assert api_proc._killed, "API process should have been killed after 2 consecutive probe failures"
    # probe_failures reset to 0 after kill — no further side effects in this test


# ---------------------------------------------------------------------------
# Test 2: no kill on single failure followed by success
# ---------------------------------------------------------------------------

def test_health_probe_no_kill_on_single_failure():
    """Probe fails once then succeeds — kill() must NOT be called."""

    api_proc = FakePopen(poll_returns=[])
    worker_proc = FakePopen(poll_returns=[])
    procs = iter([api_proc, worker_proc])

    def popen_factory(cmd, **kwargs):
        return next(procs)

    clock_values = [
        0.0,   # _last_probe init
        0.0,   # iter 1 probe check: 0 < 30 → no probe
        31.0,  # iter 2 probe check: 31 >= 30 → probe 1 fires, fails (_last_probe=31)
        62.0,  # iter 3 probe check: 62-31 >= 30 → probe 2 fires, succeeds → reset
        62.0,
    ]
    clock = _make_clock(clock_values)

    # Fail on first probe call, succeed on second
    probe_results = iter([False, True])

    def tcp_probe(host, port):
        return next(probe_results, True)

    with patch("app.supervisor._tcp_probe", side_effect=tcp_probe):
        run_supervisor(
            _BASE_ARGS,
            popen_factory=popen_factory,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=clock,
            should_stop=_counter_stop(4),
            kill_fn=_fake_kill_fn,
        )

    assert not api_proc._killed, "API must not be killed after only one failure followed by success"


# ---------------------------------------------------------------------------
# Test 3: no kill when probe always succeeds
# ---------------------------------------------------------------------------

def test_health_probe_no_kill_when_process_alive_and_healthy():
    """Probe always succeeds — kill() is never called."""

    api_proc = FakePopen(poll_returns=[])
    worker_proc = FakePopen(poll_returns=[])
    procs = iter([api_proc, worker_proc])

    def popen_factory(cmd, **kwargs):
        return next(procs)

    clock_values = [
        0.0,
        31.0,
        62.0,
        93.0,
        93.0,
    ]
    clock = _make_clock(clock_values)

    with patch("app.supervisor._tcp_probe", return_value=True):
        run_supervisor(
            _BASE_ARGS,
            popen_factory=popen_factory,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=clock,
            should_stop=_counter_stop(4),
            kill_fn=_fake_kill_fn,
        )

    assert not api_proc._killed, "API must not be killed when health probes always succeed"


# ---------------------------------------------------------------------------
# Test 4: API restart uses _start_api_with_retry
# ---------------------------------------------------------------------------

def test_api_restart_uses_retry_start():
    """When API exits, restart path calls _start_api_with_retry, not plain popen_factory."""

    # We patch _start_api_with_retry at the module level so both the initial
    # startup and any restart go through our controlled stub.
    #
    # Call 1: initial startup → return api_proc (which will later report exit)
    # Call 2: restart after exit → return restart_proc (stays alive)

    api_proc = FakePopen(poll_returns=[1])    # exits immediately on first poll
    restart_proc = FakePopen(poll_returns=[]) # replacement stays alive
    worker_proc = FakePopen(poll_returns=[])  # processor stays alive

    retry_calls = []

    def controlled_retry(cmd, host, port, **kwargs):
        retry_calls.append("call")
        if len(retry_calls) == 1:
            return api_proc
        return restart_proc

    # popen_factory is only called for worker slots (not the API, which goes via retry)
    def popen_factory(cmd, **kwargs):
        return worker_proc

    with patch("app.supervisor._start_api_with_retry", side_effect=controlled_retry):
        run_supervisor(
            _BASE_ARGS,
            popen_factory=popen_factory,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=_make_clock([0.0] * 20),
            should_stop=_counter_stop(10),
            kill_fn=_fake_kill_fn,
        )

    assert len(retry_calls) >= 2, (
        f"_start_api_with_retry called {len(retry_calls)} times; "
        "expected at least 2 (startup + restart)"
    )


# ---------------------------------------------------------------------------
# Test 5: worker restart uses plain popen (not _start_api_with_retry)
# ---------------------------------------------------------------------------

def test_worker_restart_uses_plain_popen():
    """When a worker (processor) exits, the restart path uses popen_factory directly."""

    api_proc = FakePopen(poll_returns=[])           # API stays alive
    worker_proc = FakePopen(poll_returns=[None, 1]) # worker alive then exits
    restart_worker = FakePopen(poll_returns=[])      # replacement stays alive

    worker_popen_calls = [0]

    def popen_factory(cmd, **kwargs):
        worker_popen_calls[0] += 1
        if worker_popen_calls[0] == 1:
            return worker_proc
        return restart_worker

    retry_call_count = [0]

    def controlled_retry(cmd, host, port, **kwargs):
        retry_call_count[0] += 1
        return api_proc  # initial startup always returns api_proc

    with patch("app.supervisor._start_api_with_retry", side_effect=controlled_retry):
        run_supervisor(
            _BASE_ARGS,
            popen_factory=popen_factory,
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=_make_clock([0.0] * 20),
            should_stop=_counter_stop(10),
            kill_fn=_fake_kill_fn,
        )

    # _start_api_with_retry should only have been called once (initial startup)
    assert retry_call_count[0] == 1, (
        f"_start_api_with_retry called {retry_call_count[0]} times; "
        "should only be called once (initial startup), not for worker restarts"
    )
    # popen_factory should have been called twice: initial worker + restart worker
    assert worker_popen_calls[0] >= 2, (
        f"popen_factory called {worker_popen_calls[0]} times; "
        "expected at least 2 (initial worker + restart)"
    )


# ---------------------------------------------------------------------------
# Test 6: API rapid-restart budget → supervisor shuts down
# ---------------------------------------------------------------------------

def test_api_rapid_restart_budget_triggers_shutdown():
    """API exits 3 times within 60s → supervisor shuts down (rapid-restart budget)."""

    # api_proc: poll() returns None (alive), then exits (non-zero) on each check
    # We need the API to be seen as exited on consecutive loop iterations.
    # Each "exit" triggers a restart attempt.  After _MAX_RAPID_RESTARTS=3, supervisor stops.

    # Track how many restart procs we've handed out.
    # Each proc must report exit (1) on every poll() call, not just the first.
    # The supervisor calls poll() twice per loop iteration on the active API slot:
    # once in the main exit-detection loop and once in the health-probe guard
    # (api_slot.process.poll() is None).  Using [1] * 20 ensures the exit is
    # visible on all calls so each crash is reliably detected.
    restart_procs = [FakePopen(poll_returns=[1] * 20) for _ in range(_MAX_RAPID_RESTARTS + 2)]
    restart_procs_iter = iter(restart_procs)

    restart_call_count = [0]

    def controlled_retry(cmd, host, port, **kwargs):
        restart_call_count[0] += 1
        return next(restart_procs_iter, FakePopen(poll_returns=[]))

    # All times within the rapid-restart window (< 60s)
    clock_times = [t * 1.0 for t in range(20)]
    clock = _make_clock(clock_times)

    result = None
    with patch("app.supervisor._start_api_with_retry", side_effect=controlled_retry):
        result = run_supervisor(
            _BASE_ARGS,
            popen_factory=lambda cmd, **kw: FakePopen(poll_returns=[]),  # worker stays alive
            sleep_fn=lambda _: None,
            wait_for_api_fn=lambda *_, **__: True,
            clock=clock,
            should_stop=_counter_stop(50),  # generous stop, rely on budget
            kill_fn=_fake_kill_fn,
        )

    # The supervisor should have stopped due to rapid-restart budget
    # After _MAX_RAPID_RESTARTS=3, it sets exit_code and breaks
    # restart_call_count[0] includes the initial startup (call 1) + restarts
    # Total _start_api_with_retry calls = 1 (startup) + _MAX_RAPID_RESTARTS (restarts) = 4
    # But the budget check fires BEFORE the 4th restart, so supervisor stops at restart 3
    # i.e. _start_api_with_retry called: 1 initial + up to _MAX_RAPID_RESTARTS = up to 4 times
    # The budget triggers on the 3rd crash AFTER recording that 3 restarts happened already
    assert _MAX_RAPID_RESTARTS <= restart_call_count[0] <= 1 + _MAX_RAPID_RESTARTS, (
        f"Expected {_MAX_RAPID_RESTARTS}–{1 + _MAX_RAPID_RESTARTS} total API starts, "
        f"got {restart_call_count[0]}"
    )
    assert result != 0, "Supervisor should exit with non-zero code when rapid-restart budget fires"


# ---------------------------------------------------------------------------
# Self-identifying readiness probe (_wait_for_api with launch token)
# ---------------------------------------------------------------------------

import json as _json
import http.client as _http_client
import socket as _socket
import threading as _threading
import time as _time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

with guard_native_calls():
    from app.supervisor import (
        _probe_initialized_health,
        _wait_for_api,
        _generate_launch_token,
        _start_api_with_retry,
    )


def _stub_socket_factory(connect_results: list[bool]):
    """Return a contextlib-managed fake socket that connects per the iterator.

    Each entry maps to one socket() call. True → connect succeeds (TCP probe
    passes), False → connect raises ConnectionRefusedError.
    """
    results = iter(connect_results)

    class _FakeSocket:
        def __init__(self, *_a, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def settimeout(self, *_): pass
        def connect(self, *_):
            try:
                ok = next(results)
            except StopIteration:
                ok = True
            if not ok:
                raise ConnectionRefusedError()
        def close(self): pass

    return _FakeSocket


def test_wait_for_api_succeeds_when_token_matches(tmp_path, monkeypatch):
    """Token file with correct nonce → probe succeeds."""
    nonce = "expected-token-xyz"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "api_token").write_text(_json.dumps({"nonce": nonce, "pid": 1234}), encoding="utf-8")

    # TCP succeeds on first try
    monkeypatch.setattr("socket.socket", _stub_socket_factory([True]))
    monkeypatch.setattr("app.supervisor._probe_initialized_health", lambda *_args, **_kwargs: True, raising=False)

    times = iter([0.0, 0.1, 0.2])
    clock = lambda: next(times, 0.5)

    result = _wait_for_api(
        "127.0.0.1", 19999,
        timeout=10.0, sleep_fn=lambda _: None,
        expected_nonce=nonce, run_dir=run_dir,
        clock=clock,
    )
    assert result is True


def test_wait_for_api_rejects_token_mismatch(tmp_path, monkeypatch):
    """Token file with WRONG nonce (foreign bind) → must keep waiting,
    never trust TCP, eventually timing out.

    Note: a wrong-nonce file makes ``_check_token`` return False, which
    routes around the grace path entirely. The test additionally sets a
    high ``grace_period`` value as a defense-in-depth signal, but the
    primary mechanism under test is the False return arming
    ``foreign_bind_seen`` and barring any subsequent grace fallback.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "api_token").write_text(
        _json.dumps({"nonce": "old-orphan-token", "pid": 9999}), encoding="utf-8"
    )

    # TCP always succeeds (orphan is bound)
    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))

    # Tight clock so timeout fires fast
    t = [0.0]
    def clock():
        v = t[0]
        t[0] += 0.6
        return v

    result = _wait_for_api(
        "127.0.0.1", 19999,
        timeout=2.0, sleep_fn=lambda _: None,
        expected_nonce="our-new-token", run_dir=run_dir,
        grace_period=999.0,  # defense-in-depth; primary mechanism is False → foreign_bind_seen
        clock=clock,
    )
    assert result is False, (
        "must time out rather than accept a foreign bind whose token nonce differs"
    )


def test_wait_for_api_orphan_then_token_cleanup_must_not_grace_through(tmp_path, monkeypatch):
    """REGRESSION — orphan held the port, then its lifespan finally deleted
    the token file mid-probe. The probe must NOT grace-fallback to True
    because a wrong-nonce was previously observed (orphan signature seen).

    Without the foreign_bind_seen latch, the probe would: see wrong nonce,
    keep waiting, see token file vanish (orphan cleanup), enter the
    missing-token grace path, time out → return True for the orphan."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    token_file = run_dir / "api_token"

    # Orphan token initially present
    token_file.write_text(_json.dumps({"nonce": "orphan-token", "pid": 9999}), encoding="utf-8")

    # TCP always succeeds (orphan stays bound)
    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))

    # On the 3rd clock tick, simulate the orphan deleting its token file.
    tick = [0]
    deletion_armed = [False]
    def clock():
        v = tick[0] * 1.0
        tick[0] += 1
        if tick[0] >= 3 and not deletion_armed[0]:
            deletion_armed[0] = True
            try:
                token_file.unlink()
            except FileNotFoundError:
                pass
        return v

    result = _wait_for_api(
        "127.0.0.1", 19999,
        timeout=20.0, sleep_fn=lambda _: None,
        expected_nonce="our-new-token", run_dir=run_dir,
        grace_period=2.0,
        clock=clock,
    )
    assert result is False, (
        "after seeing a foreign-nonce token, subsequent missing-token must NOT grace through"
    )


def test_wait_for_api_falls_back_after_grace_when_token_missing(tmp_path, monkeypatch):
    """Missing-token grace still requires a healthy initialized HTTP response."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()  # but no api_token file

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))
    monkeypatch.setattr("app.supervisor._probe_initialized_health", lambda *_args, **_kwargs: True, raising=False)

    # Each clock() call jumps far enough that grace period elapses on the
    # second iteration after TCP starts succeeding.
    t = [0.0]
    def clock():
        v = t[0]
        t[0] += 6.0  # 0, 6, 12, 18, ...
        return v

    result = _wait_for_api(
        "127.0.0.1", 19999,
        timeout=60.0, sleep_fn=lambda _: None,
        expected_nonce="some-token", run_dir=run_dir,
        grace_period=10.0,
        clock=clock,
    )
    assert result is True, "missing token + grace expired → should trust TCP"


def test_wait_for_api_no_self_id_legacy_path(tmp_path, monkeypatch):
    """Without a token identity, the legacy path still requires initialized HTTP."""
    monkeypatch.setattr("socket.socket", _stub_socket_factory([True]))
    monkeypatch.setattr("app.supervisor._probe_initialized_health", lambda *_args, **_kwargs: True, raising=False)
    result = _wait_for_api(
        "127.0.0.1", 19999, timeout=5.0, sleep_fn=lambda _: None,
    )
    assert result is True


def test_wait_for_api_returns_false_when_process_dies(tmp_path, monkeypatch):
    """If the spawned process exits, _wait_for_api must return False
    immediately rather than continuing to TCP-probe."""
    monkeypatch.setattr("socket.socket", _stub_socket_factory([False] * 100))

    class _DeadProc:
        pid = 1234
        def poll(self): return 1  # already exited

    result = _wait_for_api(
        "127.0.0.1", 19999, timeout=10.0, sleep_fn=lambda _: None,
        process=_DeadProc(),
    )
    assert result is False


def test_wait_for_api_handles_corrupt_token_file(tmp_path, monkeypatch):
    """Garbled token uses grace, then still requires initialized HTTP health."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "api_token").write_text("not valid json {{{", encoding="utf-8")

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))
    monkeypatch.setattr("app.supervisor._probe_initialized_health", lambda *_args, **_kwargs: True, raising=False)

    t = [0.0]
    def clock():
        v = t[0]
        t[0] += 6.0
        return v

    result = _wait_for_api(
        "127.0.0.1", 19999,
        timeout=60.0, sleep_fn=lambda _: None,
        expected_nonce="x", run_dir=run_dir,
        grace_period=10.0,
        clock=clock,
    )
    assert result is True, "corrupt JSON → treated as absent, grace fallback applies"


@pytest.mark.parametrize("identity", ["nonce", "legacy", "grace", "corrupt_grace"])
def test_wait_for_api_requires_initialized_http_after_tcp(identity, tmp_path, monkeypatch):
    """TCP plus any existing identity route is insufficient while HTTP is initializing."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    kwargs = {}
    if identity == "nonce":
        nonce = "expected-token"
        (run_dir / "api_token").write_text(_json.dumps({"nonce": nonce}), encoding="utf-8")
        kwargs.update(expected_nonce=nonce, run_dir=run_dir)
    elif identity in {"grace", "corrupt_grace"}:
        if identity == "corrupt_grace":
            (run_dir / "api_token").write_text("not json", encoding="utf-8")
        kwargs.update(expected_nonce="missing-token", run_dir=run_dir, grace_period=0.0)

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 10))
    probes = []
    monkeypatch.setattr(
        "app.supervisor._probe_initialized_health",
        lambda *_args, **_kwargs: probes.append(True) or False,
        raising=False,
    )
    ticks = iter(range(100))
    result = _wait_for_api(
        "127.0.0.1", 19999, timeout=10.0, sleep_fn=lambda _: None,
        clock=lambda: next(ticks) * 0.6, **kwargs,
    )

    assert result is False
    assert probes, "a TCP/ownership candidate must be checked through HTTP"


@pytest.mark.parametrize(
    ("status_code", "health", "expected"),
    [
        (503, {"status": "initializing", "initialized": True}, True),
        (200, {"status": "degraded", "initialized": True}, True),
        (200, {"status": "ok"}, True),
        (503, {"status": "initializing", "initialized": False}, False),
        (200, {"status": "unknown"}, False),
        (200, {"status": []}, False),
        (200, {"status": "ok", "initialized": None}, False),
        (200, {"status": "ok", "padding": "x" * (65 * 1024)}, False),
    ],
)
def test_health_probe_accepts_only_initialized_or_legacy_healthy_http(
    status_code, health, expected, monkeypatch,
):
    body = _json.dumps(health).encode("utf-8")
    real_connection = _http_client.HTTPConnection
    real_timer = _threading.Timer
    timeouts = []
    timers = []
    timer_delays = []

    def make_connection(host, port, *, timeout):
        timeouts.append(timeout)
        return real_connection(host, port, timeout=timeout)

    def make_timer(*args, **kwargs):
        timer_delays.append(args[0])
        timer = real_timer(*args, **kwargs)
        timers.append(timer)
        return timer

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/health"
            self.send_response(status_code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr("app.supervisor.http.client.HTTPConnection", make_connection)
    monkeypatch.setattr("app.supervisor.threading.Timer", make_timer)
    try:
        assert _probe_initialized_health("127.0.0.1", server.server_port, 1.0) is expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
    assert timeouts == [1.0]
    assert len(timer_delays) == 1 and 0 < timer_delays[0] <= timeouts[0]
    assert len(timers) == 1 and not timers[0].is_alive()


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_health_probe_enforces_total_deadline_on_trickled_http(phase):
    response_body = _json.dumps({"status": "ok", "padding": "x" * 100}).encode()
    headers = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(response_body)).encode()
        + b"\r\nConnection: close\r\n\r\n"
    )
    listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve_slowly():
        try:
            client, _ = listener.accept()
            with client:
                client.recv(4096)
                if phase == "headers":
                    for byte in headers:
                        client.sendall(bytes([byte]))
                        _time.sleep(0.01)
                    client.sendall(response_body)
                else:
                    client.sendall(headers)
                    for byte in response_body:
                        client.sendall(bytes([byte]))
                        _time.sleep(0.01)
        except OSError:
            pass

    thread = Thread(target=serve_slowly, daemon=True)
    thread.start()
    started = _time.monotonic()
    try:
        assert _probe_initialized_health("127.0.0.1", port, 0.12) is False
        assert _time.monotonic() - started < 0.9
    finally:
        listener.close()
        thread.join(timeout=1.0)
    assert not thread.is_alive()


@pytest.mark.parametrize("fence", ["deadline", "stop", "process"])
def test_wait_for_api_rechecks_fences_after_health_probe(fence, tmp_path, monkeypatch):
    from types import SimpleNamespace

    elapsed = [0.0]
    stop = SimpleNamespace(requested=False)
    process = SimpleNamespace(returncode=None)
    process.poll = lambda: process.returncode

    def accept_then_trip_fence(*_args, **_kwargs):
        if fence == "deadline":
            elapsed[0] = 3.0
        elif fence == "stop":
            stop.requested = True
        else:
            process.returncode = 1
        return True

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True]))
    monkeypatch.setattr("app.supervisor._probe_initialized_health", accept_then_trip_fence)
    nonce = "owned-token"
    (tmp_path / "api_token").write_text(_json.dumps({"nonce": nonce}), encoding="utf-8")
    result = _wait_for_api(
        "127.0.0.1", 19999, timeout=2.0, sleep_fn=lambda _: None,
        process=process, stop=stop, expected_nonce=nonce,
        run_dir=tmp_path, clock=lambda: elapsed[0],
    )

    assert result is False


@pytest.mark.parametrize("scenario", [
    "owned", "foreign", "missing", "legacy", "nonce_changed", "stopped", "exited",
    "initializing", "degraded", "malformed",
])
def test_wait_for_api_terminal_failure_requires_owned_nonce(scenario, tmp_path):
    from types import SimpleNamespace

    nonce = "terminal-failure-owner"
    token_path = tmp_path / "api_token"
    if scenario not in {"missing", "legacy"}:
        token_path.write_text(_json.dumps({"nonce": "foreign" if scenario == "foreign" else nonce}))
    health = {"status": "failed", "initialized": False, "ready": False,
              "initialization_error": "service_initialization_failed"}
    status_code = 503
    if scenario == "initializing":
        health = {"status": "initializing", "initialized": False, "ready": False}
    elif scenario == "degraded":
        health = {"status": "degraded", "initialized": True, "ready": False}
        status_code = 200
    elif scenario == "malformed":
        health["ready"] = True
    process = SimpleNamespace(returncode=None)
    process.poll = lambda: process.returncode
    stop = SimpleNamespace(requested=False)
    elapsed, sleeps, requests = [0.0], [], []

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if scenario == "nonce_changed":
                token_path.write_text(_json.dumps({"nonce": "replacement"}))
            elif scenario == "stopped":
                stop.requested = True
            elif scenario == "exited":
                process.returncode = 1
            body = _json.dumps(health).encode()
            self.send_response(status_code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    def advance(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _wait_for_api(
            "127.0.0.1", server.server_port, timeout=2, sleep_fn=advance,
            process=process, stop=stop, expected_nonce=None if scenario == "legacy" else nonce,
            run_dir=tmp_path, grace_period=0, clock=lambda: elapsed[0],
        )
        assert result is (scenario == "degraded")
        if scenario == "owned":
            assert requests == ["/health"]
            assert sleeps == [], "terminal owned failure must not consume the startup budget"
        elif scenario == "degraded":
            assert requests == ["/health"]
            assert sleeps == []
        elif scenario not in {"stopped", "exited"}:
            assert elapsed[0] == 2, "unverified or nonterminal response must retain the wait policy"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert not thread.is_alive()


def test_generate_launch_token_is_unique():
    """Each call must produce a different token — otherwise a stale token from
    a crashed previous attempt could be confused for the next attempt."""
    tokens = {_generate_launch_token() for _ in range(50)}
    assert len(tokens) == 50, "launch tokens must be unique"
    # And reasonably long — guards against accidental short-token regression
    for t in tokens:
        assert len(t) >= 16


def test_start_api_with_retry_passes_unique_nonce_per_attempt(tmp_path):
    """Each retry attempt must mint a fresh nonce, and inject it as
    PALLIUM_API_LAUNCH_TOKEN into the child env."""

    captured_envs = []

    class _DyingPopen:
        def __init__(self, env):
            self.pid = 1
            self.returncode = 1
            self._env = env
        def poll(self): return 1  # immediately "dead" → triggers retry

    def popen_factory(cmd, **kwargs):
        captured_envs.append(kwargs.get("env", {}))
        return _DyingPopen(kwargs.get("env", {}))

    # wait_for_api always reports failure → exhaust retries
    def wait_fn(host, port, **kw):
        return False

    nonce_counter = [0]
    def gen_token():
        nonce_counter[0] += 1
        return f"token-{nonce_counter[0]}"

    _start_api_with_retry(
        ["dummy"], "127.0.0.1", 19999,
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        wait_for_api_fn=wait_fn,
        run_dir=tmp_path,
        token_fn=gen_token,
    )

    assert len(captured_envs) >= 2, "expected multiple attempts"
    nonces = [e.get("PALLIUM_API_LAUNCH_TOKEN") for e in captured_envs]
    assert all(n is not None for n in nonces), "every attempt must inject the token env var"
    assert len(set(nonces)) == len(nonces), f"nonces must differ across attempts, got {nonces}"


def test_start_api_with_retry_threads_nonce_to_wait_fn(tmp_path):
    """The nonce supplied to popen env must be the same one passed to wait_for_api_fn."""
    seen = {}

    class _AlivePopen:
        pid = 42
        returncode = None
        def poll(self): return None  # alive

    def popen_factory(cmd, **kwargs):
        seen["env_nonce"] = kwargs.get("env", {}).get("PALLIUM_API_LAUNCH_TOKEN")
        return _AlivePopen()

    def wait_fn(host, port, *, expected_nonce=None, run_dir=None, **kw):
        seen["wait_nonce"] = expected_nonce
        seen["wait_run_dir"] = run_dir
        return True

    _start_api_with_retry(
        ["dummy"], "127.0.0.1", 19999,
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        wait_for_api_fn=wait_fn,
        run_dir=tmp_path,
        token_fn=lambda: "fixed-nonce-abc",
    )

    assert seen["env_nonce"] == "fixed-nonce-abc"
    assert seen["wait_nonce"] == "fixed-nonce-abc", (
        "wait_for_api must receive the same nonce that was injected into child env"
    )
    assert seen["wait_run_dir"] == tmp_path


def test_start_api_with_retry_kills_alive_unverified_proc(tmp_path, monkeypatch):
    """REGRESSION — when wait_for_api returns False but the process is still
    alive (e.g. foreign bind held the port for the whole probe window), the
    retry path must kill the proc rather than hand the supervisor an
    'alive but unverified' child that will never serve traffic."""

    killed = []

    class _AliveProc:
        def __init__(self): self.pid = 7
        def poll(self): return None  # never exits on its own

    procs = []
    def popen_factory(cmd, **kwargs):
        p = _AliveProc()
        procs.append(p)
        return p

    # wait_for_api always returns False (probe never verifies)
    def wait_fn(host, port, **kw): return False

    # Patch _kill_tree at module level so we can observe kill calls
    def fake_kill(process, *, force=False, **kwargs):
        killed.append((process.pid, force))

    monkeypatch.setattr("app.supervisor._kill_tree", fake_kill)

    _start_api_with_retry(
        ["dummy"], "127.0.0.1", 19999,
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        wait_for_api_fn=wait_fn,
        run_dir=tmp_path,
        token_fn=lambda: "tk",
    )

    # Each unverified attempt should have triggered a kill (force=True)
    assert len(killed) >= 1, (
        f"expected the retry loop to kill alive-but-unverified procs, got kills={killed!r}"
    )
    assert all(force is True for _, force in killed), (
        f"unverified procs must be force-killed (taskkill /F /T), got {killed!r}"
    )
    # And the retry budget should have been exhausted (multiple Popen calls)
    assert len(procs) == 5, f"expected 5 attempts, got {len(procs)}"


@pytest.mark.parametrize("scenario", ["slow_ready", "timeout", "foreign", "stopped", "dead"])
def test_startup_budget_preserves_real_probe_fencing(tmp_path, monkeypatch, caplog, scenario):
    from types import SimpleNamespace

    elapsed = [0.0]
    stop = SimpleNamespace(requested=False)
    nonce = "private-test-nonce"
    (tmp_path / "api_token").write_text(
        _json.dumps({"nonce": "foreign" if scenario == "foreign" else nonce}), encoding="utf-8",
    )
    process = SimpleNamespace(pid=123, returncode=1 if scenario == "dead" else None)
    process.poll = lambda: process.returncode
    spawned, killed, budgets, durations = [], [], [], []

    class ProbeSocket:
        def __init__(self, *_args): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def settimeout(self, _timeout): pass
        def connect(self, _address):
            if scenario == "timeout" or elapsed[0] < 45:
                raise ConnectionRefusedError

    def advance(delay):
        elapsed[0] += delay
        if scenario == "stopped":
            stop.requested = True

    def spawn(*_args, **_kwargs):
        elapsed[0] = 0
        spawned.append(process)
        return process

    def wait(host, port, **kwargs):
        budgets.append(kwargs["timeout"])
        result = _wait_for_api(host, port, **kwargs, clock=lambda: elapsed[0], sleep_fn=advance)
        durations.append(elapsed[0])
        return result

    monkeypatch.setattr("socket.socket", ProbeSocket)
    monkeypatch.setattr("app.supervisor._probe_initialized_health", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.supervisor._kill_tree", lambda proc, **_kw: killed.append(proc))
    caplog.set_level("INFO")
    result = _start_api_with_retry(
        ["unused"], "127.0.0.1", 19999, popen_factory=spawn,
        sleep_fn=lambda _delay: None, wait_for_api_fn=wait, stop=stop,
        run_dir=tmp_path, token_fn=lambda: nonce,
    )
    assert budgets == [120.0] * len(spawned)
    assert nonce not in caplog.text
    if scenario == "slow_ready":
        assert result is process
        assert durations == [45.0]
        assert len(spawned) == 1 and killed == []
        assert "outcome=ready" in caplog.text
    else:
        assert result is None
        assert "outcome=unverified" in caplog.text
        assert len(spawned) == (1 if scenario == "stopped" else 5)
        assert len(killed) == (0 if scenario == "dead" else len(spawned))
        if scenario in {"timeout", "foreign"}:
            assert durations == [120.0] * 5


def test_cooperative_windows_api_failure_drains_instead_of_retrying(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import supervisor as module
    calls = []
    channel = SimpleNamespace(request=lambda: calls.append("stop"))
    root = SimpleNamespace(pid=123)
    def spawn(*_, **__):
        calls.append("spawn")
        return root
    monkeypatch.setattr(module, "_kill_tree", lambda *_, **__: pytest.fail("forced cleanup"))
    result = module._start_api_with_retry(
        ["private-child"], "127.0.0.1", 21987, popen_factory=spawn,
        wait_for_api_fn=lambda *_, **__: False, cooperative=channel,
        run_dir=tmp_path, token_fn=lambda: "private-token",
    )
    assert result is None and calls == ["spawn", "stop"]


@pytest.mark.parametrize("helpers", [(0, 0), (2, 1)], ids=["empty-helpers", "multiple-helpers"])
def test_cooperative_windows_stop_during_startup_retains_root_and_skips_snapshot(monkeypatch, tmp_path, helpers):
    from types import SimpleNamespace
    from app import supervisor as module, windows_service
    roots = []
    stop = SimpleNamespace(requested=False)
    class Managed:
        def spawn(self, command, *, attempts, stop, **options):
            assert not stop()
            root = SimpleNamespace(pid=321, poll=lambda: 0)
            attempts.append(root)
            roots.append(root)
            return root
        def request(self):
            stop.requested = True
        def close(self):
            pass
    managed = Managed()
    @contextmanager
    def stopping(**_):
        yield stop
    def ready(*_, **__):
        stop.requested = True
        return True
    snapshot = SimpleNamespace(enabled=True, snapshot_path=str(tmp_path), interval_seconds=1, max_snapshots=2)
    monkeypatch.setattr(windows_service, "inherited_stop", lambda: managed)
    monkeypatch.setattr(module, "graceful_stop", stopping)
    monkeypatch.setattr(module.AppConfig, "from_env", lambda: SimpleNamespace(snapshot=snapshot))
    monkeypatch.setattr(module, "restore_snapshot", lambda *_, **__: pytest.fail("database rewind"))
    monkeypatch.setattr(module, "create_snapshot", lambda *_, **__: pytest.fail("final shutdown snapshot"))
    result = module.run_supervisor(
        ["--processors", str(helpers[0]), "--cleaners", str(helpers[1])],
        popen_factory=lambda *_, **__: pytest.fail("uncontained spawn"),
        wait_for_api_fn=ready, kill_fn=lambda *_, **__: pytest.fail("forced cleanup"),
    )
    assert result == 0 and len(roots) == 1


def test_cooperative_windows_prebind_token_cannot_accept_foreign_healthy_listener(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import supervisor as module
    import json
    now, connects, health = [0.0], [], []
    (tmp_path / "api_token").write_text(json.dumps({"nonce": "own-attempt", "pid": 104}), encoding="utf-8")
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def settimeout(self, _):
            pass
        def connect(self, address):
            connects.append(address)
    def foreign(*_, **__):
        health.append("healthy-foreign-response")
        return True
    def advance(delay):
        now[0] += delay
    monkeypatch.setattr("socket.socket", lambda *_: Socket())
    monkeypatch.setattr(module, "_probe_initialized_health", foreign)
    root = SimpleNamespace(poll=lambda: None)
    assert not module._wait_for_api("127.0.0.1", 21987, timeout=1,
        process=root, expected_nonce="own-attempt", run_dir=tmp_path,
        bound_check=lambda: False, clock=lambda: now[0], sleep_fn=advance)
    assert connects and not health and root.poll() is None


@pytest.mark.parametrize("marker", ["own-public-instance", None, "stale-instance", "foreign-instance"], ids=["matching", "missing", "stale", "foreign"])
def test_cooperative_windows_supervisor_health_checks_responding_instance(monkeypatch, marker):
    from types import SimpleNamespace
    from app import supervisor as module, windows_service
    calls = []
    class Timer:
        def __init__(self, *_):
            pass
        def start(self):
            calls.append("fake-timer-start")
        def cancel(self):
            pass
        def join(self):
            pass
    response = SimpleNamespace(status=200,
        getheader=lambda name: marker if name == windows_service.SERVICE_INSTANCE_HEADER else None,
        read=lambda *_: b'{"status":"ok","initialized":true}')
    connection = SimpleNamespace(sock=SimpleNamespace(settimeout=lambda _: None),
        request=lambda *args: calls.append(args), getresponse=lambda: response,
        close=lambda: calls.append("closed"))
    monkeypatch.setattr(module.http.client, "HTTPConnection", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(module.threading, "Timer", Timer)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: 0))
    result = module._probe_initialized_health("127.0.0.1", 21987, 1, expected_instance="own-public-instance")
    assert result is (marker == "own-public-instance")
    assert calls[-1] == "closed" and ("GET", "/health") in calls
