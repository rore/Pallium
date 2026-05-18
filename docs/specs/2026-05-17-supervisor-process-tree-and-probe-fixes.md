# Supervisor Process-Tree, Probe Self-ID, and Logging Visibility Fixes

**Date:** 2026-05-17
**Status:** in-progress (working plan — survives context compaction)

## Problem Statement (validated)

Live Pallium service queue went stuck at ~15:23 today. Five `source_items` with `processing_attempts=0` because the processor died with the supervisor.

### Three coupled problems (all confirmed against code/system)

1. **uv venv stub orphans the real interpreter.**
   - `.venv/Scripts/python.exe` is a 46,592 B uv launcher stub.
   - `~/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe` is the 91,648 B real entry that loads `python313.dll`.
   - `subprocess.Popen` records the stub PID. `Popen.terminate()` / `Popen.kill()` use Win32 `TerminateProcess`, non-recursive — kills only the stub. Real interpreter survives, holds TCP port.
   - Three call sites affected:
     - `app/supervisor.py:339` (probe-kill)
     - `app/supervisor.py:347` (finally-terminate)
     - `app/supervisor.py:358` (finally-kill)

2. **`_wait_for_api` is not self-identifying.**
   - `app/supervisor.py:75-88` — bare `connect((host, port))`. Returns success against any process bound to the port, including an orphan from a prior generation.
   - `_start_api_with_retry` ([app/supervisor.py:118-136]) treats orphan's bound socket as proof the new child is healthy → `return proc`s the doomed child → next loop iter detects child died → restart counter increments → eventually rapid-restart-limit trips and supervisor exits, taking processor with it.

3. **`[supervisor]` log lines invisible under wscript launcher.**
   - `app/runtime_logging.py:30-41` — `emit_runtime_log` builds a logger with `propagate=False` + a per-call `StreamHandler(sys.stdout/sys.stderr)`.
   - Under wscript (`WshShell.Run "...", 0, False`) python inherits no console; those streams discard.
   - `configure_file_logging` attaches a `FileHandler` to root, but `propagate=False` skips it.
   - Children's stdout/stderr is captured by `_popen_with_log` redirecting to file directly — that path doesn't depend on `emit_runtime_log` semantics.

## Architectural Decision

Use a single `_kill_tree(process, *, force, timeout)` helper in `app/supervisor.py` that does the right thing per OS:

- **Windows**: `subprocess.run(["taskkill", "/T", ("/F" if force else ""), "/PID", str(pid)], check=False, capture_output=True, timeout=...)`. Treat exit codes 0 (killed), 128 (process not found), 1 (no instance) as success. Always call `process.wait(timeout)` afterward.
- **POSIX**: `os.killpg(os.getpgid(pid), SIGTERM if not force else SIGKILL)`. Requires API/processor/cleaner spawn to use `start_new_session=True` on POSIX so they get their own process group. Tolerate `ProcessLookupError`.

Replace at all three Windows-affected sites in supervisor.py.

For Linux symmetry, extend `_default_popen` to set `start_new_session=True` on POSIX (cross-platform discipline; Linux isn't broken today but the same orphan class would emerge if any child spawns its own descendants — e.g., uv-managed Python on Linux uses the same launcher pattern; `python3 -m foo` doesn't spawn a sub-interpreter, but a future onnxruntime-style native lib could).

## Implementation Sequence

### Phase 1 — Fix 1: `_kill_tree` helper

**Changes:**
- `app/supervisor.py`:
  - Add `_kill_tree(process, *, force=False, timeout=5.0, runner=subprocess.run)` helper.
  - Replace `api_slot.process.kill()` at line 339 with `_kill_tree(api_slot.process, force=True)`.
  - Replace `process.terminate()` at line 347 with `_kill_tree(process, force=False)`.
  - Replace `process.kill()` at line 358 with `_kill_tree(process, force=True)`.
  - Add `start_new_session=True` to `_default_popen` on POSIX.

**Tests (add `tests/test_supervisor_kill_tree.py`):**
- `_kill_tree` calls taskkill /T (no /F) when force=False on Windows
- `_kill_tree` calls taskkill /T /F when force=True on Windows
- `_kill_tree` treats taskkill exit 128 as success (process already dead)
- `_kill_tree` treats taskkill exit 0 as success
- `_kill_tree` calls `os.killpg(os.getpgid(pid), SIGTERM)` on POSIX when force=False
- `_kill_tree` calls `os.killpg(os.getpgid(pid), SIGKILL)` on POSIX when force=True
- `_kill_tree` tolerates ProcessLookupError on POSIX (already dead)
- `_kill_tree` calls process.wait(timeout) after kill
- `_kill_tree` does not raise when subprocess.run times out
- supervisor finally block uses `_kill_tree` (existing test parity)
- probe-kill uses `_kill_tree(force=True)` (existing test parity)

### Phase 2 — Fix 3: Logging visibility

**Changes:**
- `app/runtime_logging.py`:
  - Rewrite `emit_runtime_log` to use the root logger (`propagate=True`) so it is captured by `configure_file_logging`'s `FileHandler`.
  - Keep stdout/stderr fallback behavior: if the root logger has NO handlers attached, attach a single transient StreamHandler on first use (so `capsys` test pattern still works).
  - Stop creating/destroying handlers per call — that's a perf and correctness footgun.

**Tests (extend `tests/test_runtime_logging.py`):**
- emit_runtime_log lines reach a FileHandler attached to root (regression for the wscript bug)
- emit_runtime_log still appears on stdout when no root handlers are configured (regression for current `capsys` usage)
- emit_runtime_log doesn't duplicate output when both file and stream handlers are attached
- existing cleaner test (`test_cleaner_runtime_logs_are_timestamped_and_labeled`) still passes

### Phase 3 — Fix 2: Self-identifying probe

**Changes:**
- `app/supervisor.py`:
  - Generate a launch nonce per spawn attempt: `secrets.token_urlsafe(16)`
  - Pass via env var `PALLIUM_API_LAUNCH_TOKEN` to the child Popen.
  - `_wait_for_api` reads `{home}/run/api_token` after TCP success; requires `{nonce, pid}` to match expected nonce. Falls back to TCP-only success after configurable grace period (default 10s) for compatibility — this preserves existing test behavior where the API doesn't write a token.
- `app/main.py` (lifespan startup, line 169 area):
  - If `PALLIUM_API_LAUNCH_TOKEN` env is set, write `{PALLIUM_HOME}/run/api_token` with `{nonce, pid: os.getpid()}` JSON.
  - On lifespan shutdown, remove the file.

**Tests (extend `tests/test_supervisor.py`):**
- _wait_for_api succeeds when token file matches expected nonce
- _wait_for_api keeps waiting when token file is missing (during grace period)
- _wait_for_api falls back to TCP-only success after grace period if no env was set (back-compat)
- _wait_for_api rejects token mismatch (foreign bind) and keeps waiting
- existing supervisor tests still pass (they use `wait_for_api_fn=lambda *_, **__: True` which bypasses this entirely)

## Verification

- `python -m pytest tests/ -x -q` — full regression
- Smoke test the live service end-to-end:
  - `bash scripts/clean-data.sh` (or back up the DB)
  - `pwsh scripts/restart-service.ps1`
  - Ingest a test item, observe processing, observe `[supervisor]` lines in `~/.pallium/logs/pallium.log`

## Risks / Edge Cases

- `taskkill` race: process exits between Popen and taskkill — exit code 128 expected, treated as success.
- `taskkill` blocks if target is in a kernel wait — `timeout=5.0` ensures supervisor loop doesn't stall.
- POSIX `start_new_session=True` change affects signal forwarding for *interactive* runs (Ctrl+C from terminal won't naturally reach children). Acceptable: supervisor installs its own signal handlers and propagates via _kill_tree on shutdown.
- Token file race: child writes after lifespan startup, but uvicorn binds before lifespan starts. So between bind and lifespan-write there is a window where TCP probe succeeds but token isn't written. The grace period covers this.
- If `_wait_for_api` is called for a spawn that doesn't carry a launch token (back-compat / tests), it must not hang forever — fall back to TCP-only after grace.

## Out of Scope

- Windows Job Object adoption (more robust than taskkill /T but ctypes-heavy; deferred).
- Replacing scheduled task with a real Windows service (separate roadmap item).
- macOS launchd integration (already stubbed).

## Status Log

- 2026-05-17 — Plan written. Architect pre-review complete. Ready to start Phase 1 baseline tests.
- 2026-05-17 — Phase 1 implemented and reviewed. Findings addressed:
  - Removed exit code 1 from `_TASKKILL_SUCCESS_CODES` (means "could not be terminated", not success). Test flipped to `test_taskkill_exit_1_treated_as_failure`.
  - Restructured finally block to 3-pass shutdown: fan-out terminate (`wait_timeout=0`) → sequential wait → escalate. Bounds total shutdown time, eliminates redundant double-wait.
  - All 17 cross-platform kill-tree tests + 6 supervisor tests green.
- 2026-05-17 — Phases 2–3 (Fix 3 logger propagation, Fix 2 self-id launch token) implemented + reviewed. 3 IMPORTANT findings addressed: foreign-bind latch, alive-but-unverified proc kill, regression test for orphan-bound + token-cleaned scenario.
- 2026-05-17 — Test suite hygiene pass after fixes:
  - `tests/test_async_worker.py::test_supervisor_api_exit_is_always_fatal` had been hanging since 46d5e03 made the API slot restartable (its assertion `len(started) == 2` was never reachable post that change). Renamed to `test_supervisor_api_exit_propagates_when_restart_budget_exhausted` and rewritten to assert the actual post-46d5e03 behaviour: API crashes 4× under a frozen clock → rapid-restart budget exits with the original code.
  - `tests/test_service_logging.py::TestSupervisorLogFile` (3 tests) were each spending ~150 s in real `_wait_for_api` (5 attempts × 30 s timeout, sleep_fn no-op). Added `wait_for_api_fn=lambda *_, **__: True` and `kill_fn=lambda *_, **__: None` overrides. Same regression as the 062034d perf commit.
  - Result: full default suite went from 493 s → 41.7 s (12× faster). Slowest single test now 2.6 s.
  - Pre-existing failure `test_work_resumption_suppresses_cross_thread_checkpoint_when_local_context_sufficient` confirmed unchanged on stashed `main`; out of scope (routing decomposition regression noted in MEMORY.md).
- 2026-05-18 — Live e2e smoke uncovered a Fix 3 follow-up. Symptom: after restart, `[supervisor]` lines were absent from `pallium.log` while `[service]` / `[api]` / `[processor]` lines appeared. Root cause: `RuntimeLogFormatter("service")` on the FileHandler unconditionally rewrote `record.pallium_component = self._component`, so any propagated record (supervisor, api, etc.) was relabeled `[service]`, hiding the supervisor lines under the same prefix as the 3 startup lines from `_cmd_run`. Fix: `emit_runtime_log` now passes `extra={"pallium_component": component}` and `RuntimeLogFormatter.format` only sets the fallback label when the record carries no component of its own. New regression test `test_root_filehandler_preserves_component_label` in `tests/test_runtime_logging.py` (7 tests green). Verified live via two restarts: `[supervisor]`, `[service]`, `[api]`, `[processor]` all appear with correct labels; processor confirmed picking up an ingested smoke item end-to-end.
