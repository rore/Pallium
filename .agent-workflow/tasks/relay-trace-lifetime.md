# Give Relay trace writers one app-owned lifetime

<!-- agent-workflow:start -->
**Outcome:** Relay trace enqueue and drain belong to app composition rather than the memory-service facade, preserving caller-visible delivery and trace contracts.

**Target:** Pallium app construction, trace callbacks and resource teardown.

**Scope:** core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Include tests/conftest.py, tests/test_agent_relay_e2e.py, tests/test_codex_retained_connection_recovery.py, tests/test_codex_retained_wake.py, tests/test_codex_wake.py, tests/test_codex_wake_sqlite.py, tests/test_health.py, tests/test_relay_load_smoke.py, tests/test_agent_relay_hooks.py, tests/test_codex_bridge_pipe.py, tests/test_codex_claim_busy_retry.py, tests/test_relay_capacity_isolation.py and tests/test_relay_wake_health.py only to adapt real trace-owner references and resource cleanup, retaining all existing assertions. Other lifecycle/capacity tests are verification targets, not permission for unrelated edits.

**Constraints:** One trace owner per app; retain the 64-job bound, single worker, event snapshot, best-effort loss/rejection and existing redaction surface. Usage-audit ownership stays unchanged. Preserve source capture, scope, registration, deadlines, expiry, claims, tokens, generations and storage formats. No installed changes, restart, process inspection, new logging framework, per-poll logging, protected-test changes or edits to the manager-owned roadmap.

**Completion criteria:** Actual HTTP/wake callbacks can record trace without a memory-owned executor; partial app construction and startup failure clean owned workers; shutdown rejects new jobs and settles or cancels owned work before storage closes; cancellation and repeated/concurrent close cannot let a writer outlive storage. Existing trace/claim/ACK projections stay unchanged. Required checks and independent result review record actual outcomes and remaining gates.

**Requirement baseline:**
{"source":"task-owner-approved-refactor-plan-s3","outcome":"Relay trace enqueue and drain belong to app composition rather than the memory-service facade, preserving caller-visible delivery and trace contracts.","scope":"core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Existing lifecycle/capacity tests are verification targets, not permission for unrelated edits.","constraints":"One trace owner per app; retain the 64-job bound, single worker, event snapshot, best-effort loss/rejection and existing redaction surface. Usage-audit ownership stays unchanged. Preserve source capture, scope, registration, deadlines, expiry, claims, tokens, generations and storage formats. No installed changes, restart, process inspection, new logging framework, per-poll logging, protected-test changes or edits to the manager-owned roadmap.","completion_criteria":"Actual HTTP/wake callbacks can record trace without a memory-owned executor; partial app construction and startup failure clean owned workers; shutdown rejects new jobs and settles or cancels owned work before storage closes; cancellation and repeated/concurrent close cannot let a writer outlive storage. Existing trace/claim/ACK projections stay unchanged. Required checks and independent result review record actual outcomes and remaining gates."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:simplify-relay-lifecycle-and-capability-boundaries"}],"pull_requests":[]}

**Behavior changes:**
[{"target":"task-context.scope","classification":"coverage-only","before":"core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Existing lifecycle/capacity tests are verification targets, not permission for unrelated edits.","after":"core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Include tests/conftest.py, tests/test_agent_relay_e2e.py, tests/test_codex_retained_connection_recovery.py, tests/test_codex_retained_wake.py, tests/test_codex_wake.py, tests/test_codex_wake_sqlite.py, tests/test_health.py, tests/test_relay_load_smoke.py, tests/test_agent_relay_hooks.py, tests/test_codex_bridge_pipe.py, tests/test_codex_claim_busy_retry.py, tests/test_relay_capacity_isolation.py and tests/test_relay_wake_health.py only to adapt real trace-owner references and resource cleanup, retaining all existing assertions. Other lifecycle/capacity tests are verification targets, not permission for unrelated edits.","reason":"Complete caller/constructor discovery adds only existing trace-owner references and resource teardown adaptations; no caller-visible behavior or assertions change."}]

**Risk:** High

**Complexity:** Moderate

**Reason:** Red core/service.py changes a public facade's runtime ownership; architecture-review applies. Constructor failure, queued cancellation and concurrent teardown cross resource lifetimes. No persistence/security/API behavior change is intended.

**Discovery:** Current main retains a warmed single-worker trace executor and 64 slots in every PalliumService, including non-HTTP services. The two production enqueue sites are app/dependencies.py routing and app/main.py recovery. Existing trace, wake, health and load fixtures call or observe the facade's enqueue/job/executor/slots. The shared client fixture deliberately does not enter lifespan and closes service/storage itself, so its teardown must also settle the app-owned trace worker. Existing production cleanup drains runtime users and correctness workers before service/storage close. S1 capture/output separation is already implemented; S2 registration policy remains coupled and unaccepted.

**Material assumptions:** Repository callers are the supported trace-facade consumers; search code/docs/tests before removal and stop if a real additional owner is found. App composition can supply the same optional trace callback without a new registry; standalone router callers may explicitly supply it and otherwise decline optional trace. Stop for any changed delivery/capture/registration contract or inability to settle owned storage users safely.

**Plan:** First invoke agent-workflow and classify the complete change in this isolated branch. Revalidate S1 and compare residual S2/S3 before edits. After independent plan review, move only trace worker mechanics into concrete app/relay_trace.py; keep one executor and nonblocking 64-slot admission. Copy events before submission and return slots on completion or cancellation. Serialize admission versus close; each close waits for worker settlement, including concurrent/repeated close. Clean constructor warmup failure; composition treats optional trace unavailability as a fixed logged decision. Construct one worker in the existing app composition try/cleanup boundary, share its callback with routes and lifespan recovery, reject further admission at teardown, and drain before service/storage disposal. Remove facade trace members and adapt actual callers/tests; retain usage audit. Add only bounded app-lifecycle logs with fixed values and no payload/token/raw exception. Update the stale decomposition design with delivered and remaining boundaries. Stop on contract expansion, uncertain ownership or required new framework.

**Verification plan:**
- Queue bound, snapshot and failure containment -> tests/test_relay_trace_worker.py capacity, enqueue and partial-start controls.
- Cancellation, repeated/concurrent close and slot ownership -> tests/test_relay_trace_worker.py concurrent-close and cancellation controls.
- Real HTTP trace/claim/ACK without memory trace facade -> tests/test_app_trace_lifecycle.py caller-surface lifecycle and existing Relay/wake tests.
- Constructor/startup failure, shutdown and cancelled lifespan drain before storage -> tests/test_app_trace_lifecycle.py held-writer storage-close witnesses and existing health/app lifecycle tests.
- Preserved complete application behavior -> affected subsystem files followed by scripts/test-plan.py-selected full non-slow validation once, with failures retained.
- Ownership/dependency boundary and workflow -> existing import-linter/Redline/workflow checks, same independent technical result review and required later human architecture/result/platform gates.

**Plan review:** Agent technical review: independent non-implementer reviewer, PLAN GO for e9a7a917 plus the inspected caller-scope amendment against base 9382b95b. The reviewer verified unchanged S1 files, independent S3 ownership, optional standalone callbacks, cancellation bookkeeping, partial construction and non-lifespan cleanup. Implementation and result validation remain required.

**Approvals:** Approved by user 2026-11-01: "I approve. And also, i think it might be better to go with the refactor plan we have, it may simplify tracking those issues. We should see that while the refactor we include enough logs to find problems". The task owner explicitly authorizes this first isolated source slice and justified reordering; this covers source execution, not installation or human result review.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery and slice disposition

Base: `9382b95b6496967c043269c8bee832eefafccc97`, branch `feat/relay-trace-lifetime`. Whole-change applicability is non-exempt because application files change. No incident-worktree or installed-overlay edits belong to this branch.

S1 is satisfied at this source tuple without another edit or full run. The Codex common, SessionStart, UserPromptSubmit, hook journey and deadline-test files are unchanged from reviewed PR #384 head `ad1a2483043d6765c7c4525744a3594c231561ab`. That PR's recorded full validation and required checks cover these unchanged files. `test_codex_prompt_capture_survives_enrichment_cutoff` exercises actual HTTP capture and reads the saved user source through its context endpoint while optional enrichment yields to scope output; its failure/late-worker branches preserve the single-request/no-replay obligation. SessionStart uses a child enrichment budget while essential scope/output retains the parent budget. This is reuse of source/test proof, not an installed reliability claim or a new acceptance of the whole feature.

S2 is not accepted or silently skipped: RetainedService still couples registration invalidation to `_drop(preserve_registration=...)`, with separate uncertain-I/O and identity constraints. That security-sensitive transition work remains distinct. The task owner's newer source-work direction supersedes the planning-only/recovery-start restriction for this isolated slice. S3 is reordered because the trace executor has no registration authority and can be moved independently; no historical stalled-delivery cause is assumed.

PR #384 remains a separate publication owner's change. Its seven-line storage optimization and tests are outside this branch; rebase or source reconciliation must preserve its final accepted result without importing incident-only diagnostics. The manager owns canonical roadmap state and later S2 disposition.

## Architecture checkpoint

Move one trace lifetime/dependency edge from the memory facade to app composition, retaining one bounded worker per app and existing callback shape. No transport/security/persistence format changes. Compatibility depends on the complete caller search and orderly teardown; tests must prove partial construction, enqueue rejection, cancellation and storage-close ordering. Human result review and required architecture checkpoint remain open before delivery.

## Implementation

Planning record created before application edits. Await independent plan review; preserve all earlier incident and installation records outside this checkout.

Full fresh-main caller search expanded only the owning test/fixture reach before implementation. Independent reviewer received this discovery correction. The shared fixture must close the app-owned trace worker before service/storage even when lifespan was never entered; production partial-construction cleanup owns the same worker. No memory-facade compatibility shim may hide an unowned pool.

Constructor-cleanup reach also includes tests/test_agent_relay_hooks.py, tests/test_codex_bridge_pipe.py, tests/test_codex_claim_busy_retry.py, tests/test_relay_capacity_isolation.py and tests/test_relay_wake_health.py solely for app-owned trace drainage before their existing service/storage cleanup. This is the same coverage-only ownership adaptation; no protocol assertions or protected tests change. The existing reviewer received this reach correction before those edits.

Independent technical plan review returned GO with the safeguards above. Source implementation may proceed within the approved isolated scope; High result review, required checks and human architecture/result gates remain separate. The manager confirmed the canonical source-start gate supersession and S3-before-S2 disposition; no roadmap edit is delegated to this branch.

Moved worker ownership and the two production callbacks to app composition. Usage audit remains on the service. Focused worker controls passed seven cases; callback/fixture adaptations and app caller-surface lifecycle coverage are next. No installed or incident-overlay edits occurred.

The complete callback/fixture adaptation retains existing assertions and injects the shared app worker only into trace-dependent standalone routers. Seven focused worker cases and the first 34-case app/fixture selection passed. The latter includes real HTTP trace readback and claim/ACK, optional worker-constructor failure, app construction failure, startup failure, normal shutdown and cancelled lifespan with a held trace writer; each storage-close witness observes completed writers. Existing non-lifespan fixture cleanup now owns trace drain before service/storage.

| Structural measurement | Before | After |
|---|---|---|
| Trace lifetime owner | Memory-service facade | App composition |
| Trace executors per app | One | One |
| Trace executors in non-HTTP service instances | One per service | Zero |
| Trace dependency on memory-service enqueue/job/slots | Present | Removed |
| Usage-audit owner | Memory service | Memory service |

The stale decomposition design now distinguishes already-delivered collaborator extractions and this app-owned trace boundary from remaining registration decisions. The actual whole-change selector reports the full lane; subsystem and required full validation are next.

The first subsystem run stopped at 205 passes and one existing hook-recovery failure. Exact-node diagnosis and an unchanged PR #384 baseline reproduced the same HTTP preflight refusal: a repository-contained short temporary directory made scope discovery exercise an additional Git scope transition. Moving test data outside all Git repositories made the unchanged exact node pass; no hook code or assertions were changed for this environmental prerequisite. Original failure and baseline XMLs are retained privately. Standalone retained-wake fixtures also received explicit shared trace callbacks as part of the caller adaptation; no default-owned pool was added.

The corrected affected subsystem selection passed 1,511 cases, with two existing skips and 362 slow deselections. Independent source review returned GO for the production ownership move, pending final validation. One additional caller-surface control now exercises a saturated 64-job trace queue through actual HTTP send, exact claim and ACK, then verifies later trace admission recovers. Two unused test imports were removed without changing assertions; the relevant teardown cases remain covered by the subsystem result and upcoming full lane.

## Evidence

No application checks run yet. S1 unchanged-source proof is reused as described above; current slice requires its own validation.

## Result review

Pending implementation and verification.
