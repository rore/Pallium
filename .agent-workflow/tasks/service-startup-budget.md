# Emergency startup budget and timing

<!-- agent-workflow:start -->
**Outcome:** Allow observed slow API startup to complete within a bounded budget and expose the startup stage consuming time.

**Target:** Existing API supervisor and application startup.

**Scope:** app/supervisor.py, app/main.py, tests/test_supervisor.py, existing application startup tests, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.

**Constraints:** Manager alone owns installed approval, backup, restart and health checks. Preserve nonce fencing, cancellation, retry count/backoff and cleanup. No payload/token logging, new settings, dependencies, recovery framework, schema changes or full-suite run in the emergency loop.

**Completion criteria:** Focused deterministic checks cover startup beyond30s, bounded exhaustion, cancellation, identity rejection and stage success/failure logs; independent review accepts the exact delta and manager receives rollout/rollback scope. Installed recovery remains manager-owned and unproved until observed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Allow observed slow API startup to complete within a bounded budget and expose the startup stage consuming time.","scope":"app/supervisor.py, app/main.py, tests/test_supervisor.py, existing application startup tests, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.","constraints":"Manager alone owns installed approval, backup, restart and health checks. Preserve nonce fencing, cancellation, retry count/backoff and cleanup. No payload/token logging, new settings, dependencies, recovery framework, schema changes or full-suite run in the emergency loop.","completion_criteria":"Focused deterministic checks cover startup beyond30s, bounded exhaustion, cancellation, identity rejection and stage success/failure logs; independent review accepts the exact delta and manager receives rollout/rollback scope. Installed recovery remains manager-owned and unproved until observed."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Gray/watch app runtime surfaces; availability and child ownership matter. No red contracts, storage, API response or governance changes.

**Discovery:** Manager reports existing f31 startup repeatedly killed at30s while /health shows initializing; final supervisor exhaustion leaves service down. Source passes30s explicitly on initial and recovery paths. Application builds storage/service before lifespan, so lifespan-only logging misses that cost. This establishes a too-short incident budget, not the expensive stage or AcceptEx cause.

**Material assumptions:**120s is a bounded emergency allowance, not a measured upper bound. Five attempts plus backoff consume nominal620s excluding cleanup/spawn. Existing wrapper180s is not the complete retry budget; manager proposes existing parameter660s for one approved observation. Unknown stall remains failure, never health success.

**Plan:** Invoke Agent Workflow and classify before edits. Use one120s constant in existing wait default and retry caller. Log attempt PID/budget/monotonic elapsed and fixed outcome. Use existing logger/contextlib for pre-lifespan storage/service start/end/failure timings; lifespan start/complete logs. Add fake-clock/socket and logging regressions; run only focused private tests. Independent plan/result review, no publication or live operation by this worker.

**Verification plan:** Slow startup after30s succeeds without retry -> real wait helper with fake socket/token/clock. Deadline, death, cancellation and wrong token remain rejected -> existing and new supervisor tests. Pre-bind build timing includes success/failure -> private log-helper test. No exceptions swallowed or payload logged -> source review and log assertions.

**Plan review:** Requested independent read-only review from Pal chat01a1156c-e388-7850-9c42-cc2fcb5dbd51 before production edits.

**Approvals:** Human incident restoration direction conveyed by manager chat01a0d7ce-83c6-77e2-90f7-d413894059e1 explicitly authorizes isolated120s slice and focused checks; installed changes require separate exact approval. No High-risk human gate at this classification.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-08: Migration paused and its private edits preserved. Created separate branch feat/service-startup-budget at retained published source bc6dda12; no production edit yet. Manager owns emergency live restoration. Exact Relay wake trace returned transport_unavailable; authorized app fallback used. Pending independent plan review, then immediate minimal implementation and focused check.
