<!-- agent-workflow:start -->
**Outcome:** Pallium service management reaches a truthful ready result during legitimate cold start and the required status/queue diagnostics remain responsive under reasonable concurrent work.

**Target:** Local/private-cloud service diagnostics and cross-platform service readiness.

**Scope:** Isolate `/status` and `/debug/queue/health` from ordinary sync-worker starvation; replace queue-health full-row scanning with equivalent bounded SQL selection; make Windows and shared CLI readiness use elapsed-time budgets; add fast deterministic caller-surface/lifecycle regressions; align the Relay roadmap.

**Constraints:** Preserve all response schemas and readiness requirements; preserve Relay's independent capacity and shutdown safety; no new dependency; no wall-clock wait or sustained load in the normal suite; retain Windows/Linux/macOS behavior; preserve unrelated `uv.lock` work.

**Completion criteria:** (1) `/health`, `/status`, `/debug/queue/health`, and Relay remain prompt when ordinary AnyIO sync capacity is saturated. (2) Queue health returns the same results for empty, pending, processing, failed, expired-lease, unknown-use-case, retention, and completed-history cases without materializing every completed source row. (3) Service readiness is bounded by elapsed time, survives the measured cold-start class, and reports the last failed check. (4) Focused/full CI passes; the installed wrapper exits 0 and all three endpoints are healthy.

**Risk:** High

**Complexity:** Moderate

**Reason:** `app/main.py` and `api/routes.py` are red request/contract paths, and `storage/sqlite_queue.py` is persistence code. The public schema stays stable, but concurrency, shutdown, query equivalence, and multi-platform lifecycle behavior require coordinated verification.

**Discovery:** The first dogfood restart became healthy only after the 20-attempt wrapper had failed. Raising it to 60 attempts still failed at `/status` around 90 seconds, disproving a simple retry-count fix. After rebuild completion, eight `/status` samples still took 2.1–3.3 seconds against a 2-second probe; `/health` took 4–20 ms, and `/debug/queue/health` took about 5–7 seconds. Direct read-only SQLite counts took 0–51 ms, proving endpoint delay was not raw count cost alone. `/status` and queue health are sync routes sharing ordinary AnyIO capacity; queue health also loads every `source_items` ORM row (10,506 live rows, ~383 MB DB) and classifies completed rows in Python. The readiness loops use attempt counts or a 30-second total with per-probe values shorter than observed cold-start diagnostics.

**Material assumptions:** (1) A two-slot diagnostic limiter is sufficient because only the two required diagnostic routes use it; disprove with deterministic simultaneous saturation test, then stop rather than borrowing Relay capacity. (2) Queue-health output can be preserved by SQL-grouping status counts and selecting only pending, active-processing, recent-failed, active-thread-lease, and maintenance rows; disprove with existing edge/lifecycle tests. (3) A 120-second elapsed readiness budget covers the measured local cold-start class without claiming indefinite availability; disprove with installed witness, then diagnose the remaining blocker rather than increasing it again.

**Plan:** 1. Extend the existing sync-capacity caller-surface test so health, status, queue health, and Relay must all complete while the default worker is occupied. 2. Generalize the existing app-owned tracked operation runner to retain separate Relay and diagnostic limiters; route status and queue health through the diagnostic runner without changing payloads. 3. Replace queue-health all-source/all-thread materialization with aggregate counts and state-specific bounded selections while retaining existing classification helpers. 4. Replace Windows attempt budgeting with a 120-second elapsed deadline and raise the shared CLI lifecycle deadline to the same measured bound; keep endpoint validation and last-check diagnostics. 5. Add deterministic deadline/late-readiness tests with mocked sleeps, run focused and full verification, independent result review, installed restart, endpoint probes, PR/CI/review remediation, merge, and exact-main rollout.

**Verification plan:** Existing queue-health edge suites plus new completed-history and default-worker saturation E2E; Windows real-script harness with a tiny injected test deadline and a late-ready mocked path; CLI readiness unit/lifecycle tests; focused health/service/storage/Relay suites; full pytest/import/workflow/diff checks; installed wrapper and direct `/health`, `/status`, `/debug/queue/health` measurements. Slow/load evidence stays opt-in.

**Plan review:** Pending clean-context redline/architecture review of this Work Record and named paths.

**Approvals:** Standing user approval on 2026-09-06 to take managed work and PRs through done without repeated permission prompts; explicit instruction that service resilience bugs found while dogfooding must be fixed.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: The initial one-constant readiness patch was tested against the installed service and rejected after the 60-attempt run still failed. Live endpoint and direct-SQL timings expanded the root cause to diagnostic worker starvation, an unbounded queue-health scan, and non-time-based Windows readiness.