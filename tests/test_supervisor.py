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

from app.supervisor import _wait_for_api, _generate_launch_token, _start_api_with_retry


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
    """No token file (e.g. older child not implementing token write) →
    after grace period, trust TCP alone (back-compat)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()  # but no api_token file

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))

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
    """Without expected_nonce/run_dir, behavior is legacy: TCP success → True."""
    monkeypatch.setattr("socket.socket", _stub_socket_factory([True]))
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
    """Garbled token file → treated as 'absent', falls back via grace period.
    Avoids supervisor wedging on a partially-written file from a crashed write."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "api_token").write_text("not valid json {{{", encoding="utf-8")

    monkeypatch.setattr("socket.socket", _stub_socket_factory([True] * 100))

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
