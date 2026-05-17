from __future__ import annotations

"""Unit tests for app.supervisor — health probe and restart resilience.

All tests use fake time, fake processes, and injectable parameters.
No real processes are spawned.  Not marked slow (fast, no real sleeping).
"""

import itertools
from unittest.mock import patch

from app.supervisor import (
    _API_HEALTH_PROBE_FAIL_THRESHOLD,
    _API_HEALTH_PROBE_INTERVAL,
    _MAX_RAPID_RESTARTS,
    run_supervisor,
)

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
