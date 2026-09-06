<!-- agent-workflow:start -->
**Outcome:** Relay wake remains loss-safe and model-silent during bounded service contention, while Pallium health and Relay control-plane requests remain responsive under reasonable concurrent memory load.

**Target:** Pallium local/private-cloud service.

**Scope:** Codex internal-wake hook behavior; Relay wake reconciliation/ownership; Relay HTTP execution isolation; SQLite connection initialization; focused operational telemetry; fast deterministic caller-surface, concurrency, and lifecycle tests; aligned Relay and operational-hardening roadmap/docs.

**Constraints:** One PR; preserve public Relay request/response and tenant-scope contracts; no new dependency or database backend; no long sleep or sustained stress test in the normal suite; retain durable at-least-once delivery and cross-platform Windows/Linux/macOS behavior; preserve unrelated `uv.lock` changes.

**Completion criteria:** (1) Internal Codex wake prompts never reach memory ingestion or the model when Relay is unavailable, busy, malformed, or empty. (2) Pending and expired-claimed exact-session work is re-woken indefinitely with bounded coalescing, including after ambiguous admission and restart. (3) Main-memory DB contention cannot consume Relay's execution capacity or make the in-memory health endpoint wait for the shared sync pool. (4) SQLite pooled connection creation cannot run persistent lock-taking PRAGMAs before its busy timeout. (5) Operators can distinguish Relay latency, busy, timeout, retry, and recovery outcomes. (6) Fast E2E proves observable behavior at the real HTTP/hook surfaces under deterministic contention and timeout boundaries; an opt-in load check demonstrates reasonable concurrent memory + Relay operation.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is a red API-contract zone and the change affects concurrency, durable delivery admission, and SQLite initialization. Several tightly related runtime, storage, hook, and test surfaces are involved, but the result remains one service and one delivery unit.

**Discovery:** Live 2026-09-06 incident showed main-DB `BEGIN IMMEDIATE` and connection-PRAGMA lock failures, a DB-free `/health` timeout, and two Relay deliveries claimed after the 0.75-second hook deadline then recovered much later. Relay already uses a separate 2.2 MB SQLite file; its indexed turn path measured ~3 ms median/~5.5 ms p99 on a disposable database. The single Uvicorn process exposes mostly sync routes through AnyIO's 40-token default worker pool. The Codex hook silently maps Relay exceptions to `None`, intentionally fails open for the exact internal wake, and then ingests that control prompt through `/item-and-query`; an existing test enshrines this behavior. Recovery scans only expired claims, while Codex queued/ambiguous ownership is process-local and unbounded. Every new SQLite connection runs persistent `auto_vacuum` and `journal_mode` PRAGMAs before `busy_timeout`; the incident failed at that exact hook. Existing roadmap `RW-002` incorrectly marks the fail-open case fixed.

**Material assumptions:** (1) Relay's existing delivery row can remain the durable retry source of truth; verified by pending/expired restart recovery. (2) A dedicated stdlib executor was disproved by shutdown-lifecycle testing because unclosed non-daemon workers outlived app instances; the implemented solution uses an app-owned AnyIO limiter plus an active-operation shutdown barrier. (3) Persistent PRAGMAs can move to one-time database bootstrap while preserving new-DB `auto_vacuum=INCREMENTAL` before WAL; verified by fresh/legacy DB tests. (4) The full test-run overlap is correlation, not a proven production-DB writer; the fix addresses the measured shared-worker and connection-initialization hotspots without encoding pytest-specific behavior.

**Plan:** 1. Add/adjust fast failing tests for internal-wake timeout/busy/malformed/invalid-scope suppression, post-timeout claim recovery, never-claimed pending recovery, restart, backlog, duplicate scheduling, and main-DB contention with Relay/health responsiveness. 2. Reserve the exact Codex control prompt: successful delivery still injects/ACKs; every other result blocks before dedup, memory, and model work. 3. Generalize the existing read-only wake-candidate reconciliation to pending plus expired claims and make Codex session/scope ownership bounded and stale-reclaimable; use existing event loop and delivery state, capped retry, and no new persistence table unless assumption 1 fails. 4. Route all Relay control-plane storage calls through an app-owned four-operation AnyIO limiter, track active operations for clean shutdown, and make `/health` async; preserve callback-after-success ordering. 5. Move persistent SQLite PRAGMAs into one-time initialization and install per-connection `busy_timeout` before ordinary work. 6. Reuse existing logging/metrics surfaces for bounded Relay latency/outcome/recovery visibility; do not add a telemetry subsystem. 7. Add an opt-in, short load harness/marked test outside the default suite, align `RW-002` and operational scale docs, run focused/full/platform checks, independent review, installed-service restart/health/integration verification, PR/CI/review-thread remediation, and merge. Stop and return to planning on public schema drift, cross-scope behavior, unbounded thread creation, or failure of deterministic exactly-once observable delivery.

**Verification plan:** (1) When `/relay/turn` is empty, busy, malformed, delayed beyond the client deadline, or unreachable, the exact internal wake shall produce a structured block and zero main-DB/model work → real Codex UserPromptSubmit caller-surface tests. (2) When claim completion is ambiguous or no claim occurs, eligible work shall be retried after deterministic lease/grace advancement, across app restart, and injected/ACKed once → full-app HTTP + hook lifecycle E2E with fake clocks/events. (3) When main DB writers occupy ordinary request workers, `/health` and Relay turn/send/ACK shall remain bounded and correct → deterministic executor-saturation/SQLite-contention E2E. (4) Fresh and legacy databases shall retain WAL/auto-vacuum semantics and new pooled connections shall set timeout without repeated persistent PRAGMAs → SQLite lifecycle and concurrent-connection tests. (5) Relay request and recovery outcomes shall be locally observable without affecting model context → log/metrics contract tests. (6) Existing Relay, Codex, Claude, storage, snapshot, service, and full suites plus workflow/redline checks shall pass; optional load harness shall meet a recorded latency/error threshold without joining the normal suite.

**Plan review:** Clean-context Luna review `/root/reliability_plan_review`; accepted with app-layer executor ownership, bounded low-cardinality telemetry, exact-session retry ownership/terminal conditions, and successful-delivery behavior preserved.

**Approvals:** Approved by user 2026-09-06T19:59:09+03:00: "ok, so you have here a list of items, do them all in a single pr, we should make sure pallium is not so easily brought down. it should sustain reasonable load (also, pallium was originally suppoosed to work in a private cloud for multi users, there's no chance it can do it if it fails for a single user)"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06 discovery and high-risk planning recorded before code changes.
- Clean-context redline review classified `api/routes.py` as RED/API_CHANGE with API review required, found no proposed boundary violation, and constrained executor ownership to `app`. Plan review found no blocker after requiring fail-closed sentinel handling, exact-session bounded retry ownership, low-cardinality telemetry, and real caller-surface lifecycle coverage.

- Root slice: Relay HTTP storage calls now use app-owned independent AnyIO capacity; /health stays on the event loop; a deterministic caller-surface test proves both respond while ordinary sync capacity is saturated (1 passed in 0.34s). Hook Relay timeout failures now emit bounded operation/type/latency diagnostics without scope or payload.
- Cancellation keeps the client request cancelled while the synchronous Relay operation finishes; the app shutdown barrier waits before closing storage. Claude registration now awaits the same Relay runner before reporting success.
- Pending and expired claims reconcile at startup and every 30 seconds. Codex retries retain the oldest per-session trigger, and exact internal wakes block before memory/model work unless the hook rendered a verified delivery.
- The opt-in mixed-load witness is marked `slow`, excluded from normal pytest, and completes in under one second locally.

## Evidence

- Incident log: `%USERPROFILE%\.pallium\logs\pallium.log`, 2026-09-06 16:09–16:25 UTC.
- Disposable nominal Relay-turn benchmark: p50 2.958 ms, p95 4.723 ms, p99 5.522 ms over 250 empty turns.
- Focused reliability suite: 208 passed, 2 skipped, 4 pre-existing Pydantic warnings in 18.99 seconds.
- Opt-in mixed memory/Relay load witness: 1 passed in 0.97 seconds with `-m slow -n0`.
- Final normal suite: 4,532 passed, 33 skipped, 2 expected failures, 4 pre-existing Pydantic warnings in 167.97 seconds; marked slow tests excluded by default.

## Plan review

`/root/reliability_plan_review` accepted the smallest corrected implementation: fail-closed exact sentinel; pending plus expired-claim recovery with stale ownership reclamation; app-owned Relay executor isolation; one-time persistent SQLite PRAGMAs; bounded telemetry; deterministic E2E. No schema redesign, dependency, or default stress suite.

## Result review

Clean-context Luna review of the complete committed diff found no blockers. It verified autocommit SQLite initialization and timeout restoration, independent Relay capacity and shutdown draining, persisted retry ownership, exact-wake fail-closed behavior, bounded diagnostics, single-process deployment ceiling, caller-surface coverage, and roadmap/docs alignment. The full suite exposed and closed two stale test assumptions plus one timing-dependent recovery assertion; the corrected tests pass deterministically. CodeRabbit found two stale roadmap descriptions of the old canonical-empty-only behavior; both were aligned to the fail-closed contract before merge.
- 2026-09-06 sentinel slice: exact Codex Relay wake now blocks on every unsuccessful Relay outcome before dedup/memory/context; focused hook suite passes (37 tests).
- SQLite slice: persistent auto_vacuum/WAL bootstrap moved to one-time initialization; pooled connections set busy_timeout first.
