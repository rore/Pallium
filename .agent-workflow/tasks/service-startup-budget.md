# Emergency startup budget and timing

<!-- agent-workflow:start -->
**Outcome:** Allow observed slow API startup to complete within a bounded budget and expose the startup stage consuming time.

**Target:** Existing API supervisor and application startup.

**Scope:** app/supervisor.py, app/main.py, app/runtime_logging.py, app/dependencies.py, tests/test_supervisor.py, tests/test_runtime_logging.py, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.

**Constraints:** Manager alone owns installed approval, backup, restart and health checks. Preserve nonce fencing, cancellation, retry count/backoff and cleanup. No payload/token logging, new settings, dependencies, recovery framework, schema changes or full-suite run in the emergency loop.

**Completion criteria:** Focused deterministic checks cover startup beyond30s, bounded exhaustion, cancellation, identity rejection and stage success/failure logs; independent review accepts the exact delta and manager receives rollout/rollback scope. Installed recovery remains manager-owned and unproved until observed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Allow observed slow API startup to complete within a bounded budget and expose the startup stage consuming time.","scope":"app/supervisor.py, app/main.py, tests/test_supervisor.py, existing application startup tests, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.","constraints":"Manager alone owns installed approval, backup, restart and health checks. Preserve nonce fencing, cancellation, retry count/backoff and cleanup. No payload/token logging, new settings, dependencies, recovery framework, schema changes or full-suite run in the emergency loop.","completion_criteria":"Focused deterministic checks cover startup beyond30s, bounded exhaustion, cancellation, identity rejection and stage success/failure logs; independent review accepts the exact delta and manager receives rollout/rollback scope. Installed recovery remains manager-owned and unproved until observed."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"requirement-change","before":"app/supervisor.py, app/main.py, tests/test_supervisor.py, existing application startup tests, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.","after":"app/supervisor.py, app/main.py, app/runtime_logging.py, app/dependencies.py, tests/test_supervisor.py, tests/test_runtime_logging.py, and this Work Record. Isolated emergency delta from merged PR307 source bc6dda12ad78bf1ab310bca4922dc046ec3607de; no migration or installation.","reason":"Record the already-reviewed plan refinement that places fixed startup stage timing in the existing logging helper and dependency builder.","impact":"No new setting or exception behavior; startup timing covers the actual expensive calls.","alternatives":"Keep less specific startup timing.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Root incident task, 2026-10-08, approval to complete the current reviewed fix","verbatim":"i might be gone later so you have my approval to drive this fix till merge and done"}}]

**Risk:** High

**Complexity:** Moderate

**Reason:** Gray/watch app runtime surfaces; availability and child ownership matter. No red contracts, storage, API response or governance changes.

**Discovery:** Manager reports existing f31 startup repeatedly killed at30s while /health shows initializing; final supervisor exhaustion leaves service down. Source passes30s explicitly on initial and recovery paths. Application builds storage/service before lifespan, so lifespan-only logging misses that cost. This establishes a too-short incident budget, not the expensive stage or AcceptEx cause.

**Material assumptions:**120s is a bounded emergency allowance, not a measured upper bound. Five attempts plus backoff consume nominal620s excluding cleanup/spawn. Existing wrapper180s is not the complete retry budget; manager proposes existing parameter660s for one approved observation. Unknown stall remains failure, never health success.

**Plan:** Invoke Agent Workflow and classify before edits. Use one120s constant in existing wait default and retry caller. Log attempt PID/budget/monotonic elapsed and fixed outcome. Use existing logger/contextlib for pre-lifespan storage/service start/end/failure timings; lifespan start/complete logs. Add fake-clock/socket and logging regressions; run only focused private tests. Independent plan/result review, no publication or live operation by this worker.

**Verification plan:** Slow startup after30s succeeds without retry -> real wait helper with fake socket/token/clock. Deadline, death, cancellation and wrong token remain rejected -> existing and new supervisor tests. Pre-bind build timing includes success/failure -> private log-helper test. No exceptions swallowed or payload logged -> source review and log assertions.

**Plan review:** Agent technical review: Pal chat01a1156c-e388-7850-9c42-cc2fcb5dbd51 inspected bc6dda12 source and accepted this exact minimal plan before production edits. Preserve existing grace/foreign-token latch, cancellation/cleanup, fixed log labels and unchanged exception propagation. This is temporary availability mitigation/observability, not root-cause closure.

**Approvals:** Approved by user 2026-10-08: "i might be gone later so you have my approval to drive this fix till merge and done". Combined integration is High risk; original component was Elevated. Installed changes retain their separately scoped approval.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

## Result review

Agent technical review: /root/incident_integration_review, independent non-implementer, accepted the combined source on 2026-10-08.
Reviewed revision: dba1bb1f743e456ab706e35f29edeeee97d68973.
Verification adequacy: component startup/cancellation/logging regressions accepted; combined full suite and CI remain pending. The 120-second budget remains mitigation, not root-cause closure.

## Component implementation history

2026-10-08: Migration paused and its private edits preserved. Created separate branch feat/service-startup-budget at retained published source bc6dda12; no production edit yet. Manager owns emergency live restoration. Exact Relay wake trace returned transport_unavailable; authorized app fallback used. Pending independent plan review, then immediate minimal implementation and focused check.

Plan refinement before added-file edits: manager conveys human correction that120s is a workaround, not a fix. Pal independently accepts moving the tiny helper into existing runtime_logging and wrapping exact dependencies calls with fixed labels service_storage, semantic_plugins, embedding_provider, vector_index_load, raw_source_backfill_check and vector_counts. Existing try/conditions and fallback/exception semantics remain. A completed stage means its call returned, not provider/index health; original error logs remain. No provider/storage changes. These narrower stages will guide root-cause work immediately after manager's installed observation. No full suite in this emergency loop; normal release gates remain for subsequent repository integration.

## Verification

Allocated focused invocation: existing development Python3.13, process-local PYTHONDONTWRITEBYTECODE=1, PYTHONNOUSERSITE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; `python -B -m pytest tests/test_supervisor.py tests/test_runtime_logging.py -q -n 0 -p xdist.plugin -p pytest_asyncio.plugin`. Result42 passed in1.10s, exit0; retained build/startup-emergency-focused.log. Fake processes/sockets/clock, private home/config/token fixtures; no live service access, subprocess startup, installed files or database operation. New cases assert actual retry caller budget120, real wait helper readiness45, five120s timeout/foreign-token attempts, cancellation/death, fixed success/failure logs and unchanged exception identity without sensitive content. Existing identity/grace and cleanup regressions also pass. No full-suite, CI, installed health or root-cause claim.

## Rollout handoff

Only four production files comprise this emergency mitigation. Manager must back up exact installed originals and verify base compatibility before applying this separable delta; no main-sync/schema/launcher/task/config/dependency change is bundled. One approved restart uses existing scripts/restart-service.ps1 with separately approved ReadinessTimeoutSeconds660 and retains all health/status/queue validation and identity fences. Nominal five120s attempts plus20s backoff exclude overhead;660 is an observation allowance, not an uptime guarantee. On incompatibility/failure restore exact backed-up files and use the same approved wrapper procedure; preserve diagnostics. Stage logs should identify the expensive block for immediate causal investigation.120s remains a temporary workaround.
