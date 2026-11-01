# Give Relay trace writers one app-owned lifetime

<!-- agent-workflow:start -->
**Outcome:** Relay trace enqueue and drain belong to app composition rather than the memory-service facade, preserving caller-visible delivery and trace contracts.

**Target:** Pallium app construction, trace callbacks and resource teardown.

**Scope:** core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Existing lifecycle/capacity tests are verification targets, not permission for unrelated edits.

**Constraints:** One trace owner per app; retain the 64-job bound, single worker, event snapshot, best-effort loss/rejection and existing redaction surface. Usage-audit ownership stays unchanged. Preserve source capture, scope, registration, deadlines, expiry, claims, tokens, generations and storage formats. No installed changes, restart, process inspection, new logging framework, per-poll logging, protected-test changes or edits to the manager-owned roadmap.

**Completion criteria:** Actual HTTP/wake callbacks can record trace without a memory-owned executor; partial app construction and startup failure clean owned workers; shutdown rejects new jobs and settles or cancels owned work before storage closes; cancellation and repeated/concurrent close cannot let a writer outlive storage. Existing trace/claim/ACK projections stay unchanged. Required checks and independent result review record actual outcomes and remaining gates.

**Requirement baseline:**
{"source":"task-owner-approved-refactor-plan-s3","outcome":"Relay trace enqueue and drain belong to app composition rather than the memory-service facade, preserving caller-visible delivery and trace contracts.","scope":"core/service.py; app/relay_trace.py; app/main.py; app/dependencies.py; tests/test_relay_trace_worker.py; tests/test_app_trace_lifecycle.py; tests/test_relay_delivery_trace.py; docs/designs/refactor-service-decomposition.md; this Work Record. Existing lifecycle/capacity tests are verification targets, not permission for unrelated edits.","constraints":"One trace owner per app; retain the 64-job bound, single worker, event snapshot, best-effort loss/rejection and existing redaction surface. Usage-audit ownership stays unchanged. Preserve source capture, scope, registration, deadlines, expiry, claims, tokens, generations and storage formats. No installed changes, restart, process inspection, new logging framework, per-poll logging, protected-test changes or edits to the manager-owned roadmap.","completion_criteria":"Actual HTTP/wake callbacks can record trace without a memory-owned executor; partial app construction and startup failure clean owned workers; shutdown rejects new jobs and settles or cancels owned work before storage closes; cancellation and repeated/concurrent close cannot let a writer outlive storage. Existing trace/claim/ACK projections stay unchanged. Required checks and independent result review record actual outcomes and remaining gates."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:simplify-relay-lifecycle-and-capability-boundaries"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** Red core/service.py changes a public facade's runtime ownership; architecture-review applies. Constructor failure, queued cancellation and concurrent teardown cross resource lifetimes. No persistence/security/API behavior change is intended.

**Discovery:** Current main retains a warmed single-worker trace executor and 64 slots in every PalliumService, including non-HTTP services. The two production enqueue sites are app/dependencies.py routing and app/main.py recovery. One trace test calls the facade directly. Existing cleanup drains runtime users and correctness workers before service/storage close. S1 capture/output separation is already implemented; S2 registration policy remains coupled and unaccepted.

**Material assumptions:** Repository callers are the supported trace-facade consumers; search code/docs/tests before removal and stop if a real additional owner is found. App composition can supply the same optional trace callback without a new registry; standalone router callers may explicitly supply it and otherwise decline optional trace. Stop for any changed delivery/capture/registration contract or inability to settle owned storage users safely.

**Plan:** First invoke agent-workflow and classify the complete change in this isolated branch. Revalidate S1 and compare residual S2/S3 before edits. After independent plan review, move only trace worker mechanics into concrete app/relay_trace.py; keep one executor and nonblocking 64-slot admission. Copy events before submission and return slots on completion or cancellation. Serialize admission versus close; each close waits for worker settlement, including concurrent/repeated close. Clean constructor warmup failure; composition treats optional trace unavailability as a fixed logged decision. Construct one worker in the existing app composition try/cleanup boundary, share its callback with routes and lifespan recovery, reject further admission at teardown, and drain before service/storage disposal. Remove facade trace members and adapt actual callers/tests; retain usage audit. Add only bounded app-lifecycle logs with fixed values and no payload/token/raw exception. Update the stale decomposition design with delivered and remaining boundaries. Stop on contract expansion, uncertain ownership or required new framework.

**Verification plan:** New focused worker controls cover the queue boundary, event snapshot, writer/submit/start failure, cancellation, repeated/concurrent close and ownership release. Caller-surface app tests cover constructor/partial-start failure, no memory trace facade, successful trace HTTP/wake behavior, and trace drain before storage close under request cancellation. Run affected composition/trace/capacity and service lifecycle files; reuse unchanged S1/expiry controls. Run scripts/test-plan.py against origin/main, workflow/redline/import checks and one required full non-slow lane; preserve failures and scope any correction. Obtain the same independent technical source/result review. Required human result/architecture and platform CI gates remain separate; no installation is authorized.

**Plan review:** Pending the existing independent reviewer; no application edits yet.

**Approvals:** Approved by user 2026-11-01: "I approve. And also, i think it might be better to go with the refactor plan we have, it may simplify tracking those issues. We should see that while the refactor we include enough logs to find problems". The task owner explicitly authorizes this first isolated source slice and justified reordering; this covers source execution, not installation or human result review.

**Exceptions:** —

**State:** Blocked
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

## Evidence

No application checks run yet. S1 unchanged-source proof is reused as described above; current slice requires its own validation.

## Result review

Pending implementation and verification.
