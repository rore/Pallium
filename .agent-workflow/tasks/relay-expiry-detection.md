<!-- agent-workflow:start -->
**Outcome:** Expired Relay claim requests record the fixed checkpoint that detected expiry in the existing exact-wake timing log.

**Target:** Relay claim-expiry attribution.

**Scope:** Only storage/sqlite_relay.py, api/routes.py, tests/test_agent_relay_e2e.py, tests/test_codex_wake.py and this Work Record. Carry a fixed server-origin expiry-detection label through the existing exception cause to the current log.

**Constraints:** Preserve HTTP409/body/schema, primary exception and cause behavior, existing clocks/deadlines/timers, transaction and rollback semantics, claim/ACK/lease/retry/fencing behavior and protected tests. Fixed labels only; no payloads, secrets, paths, SQL or inferred CPU/holder/loaded-source identity. No push, full CI, installed changes, restart or live capture in this step. Preserve the separate blocked privacy checkout.

**Completion criteria:** A local reviewable diff and focused caller-surface evidence distinguish all four detection checkpoints, use unknown/none for unsupported metadata, retain identical public errors and durable rollback state, and preserve original exceptions when metadata fails. Report all remaining full-validation/review gates without claiming release qualification or a physical-delay fix.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Expired Relay claim requests record the fixed checkpoint that detected expiry in the existing exact-wake timing log.","scope":"Only storage/sqlite_relay.py, api/routes.py, tests/test_agent_relay_e2e.py, tests/test_codex_wake.py and this Work Record. Carry a fixed server-origin expiry-detection label through the existing exception cause to the current log.","constraints":"Preserve HTTP409/body/schema, primary exception and cause behavior, existing clocks/deadlines/timers, transaction and rollback semantics, claim/ACK/lease/retry/fencing behavior and protected tests. Fixed labels only; no payloads, secrets, paths, SQL or inferred CPU/holder/loaded-source identity. No push, full CI, installed changes, restart or live capture in this step. Preserve the separate blocked privacy checkout.","completion_criteria":"A local reviewable diff and focused caller-surface evidence distinguish all four detection checkpoints, use unknown/none for unsupported metadata, retain identical public errors and durable rollback state, and preserve original exceptions when metadata fails. Report all remaining full-validation/review gates without claiming release qualification or a physical-delay fix."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** The implementation touches red persistence and API surfaces even though the wire contract and transaction behavior remain unchanged. Exception propagation and diagnostic failure must preserve caller-visible outcomes.

**Discovery:** Four existing check_claim_expiry calls detect expiry before acquisition, immediately after acquisition, before claim mutation following candidate selection, and after flush before commit. They currently raise the same RelayConflictError. The existing HTTP conversion preserves a cause, and exact-wake relay_turn_timing already carries bounded error categories and worker/snapshot/service/route intervals. Successful acquisition subphase timings and attested loaded-source identity are not available through this exception path.

**Material assumptions:** Fixed internal metadata can traverse the existing exception cause without a new exception class or response field. Missing, invalid or failing metadata must degrade to unknown without replacing the primary error. A detection checkpoint does not identify where elapsed time was consumed. Stop for scope growth, altered exception/cause semantics, or a need for a new tracing or identity subsystem.

**Plan:** Commit this Work Record and obtain independent technical plan review before code edits. Label all four existing expiry checks with before_acquisition, after_acquisition, pre_claim_mutation or post_flush_precommit. Best-effort metadata attachment retains the same exception class, message and args; route extraction from the existing cause accepts only exact fixed strings, falls back on metadata failure, and appends expiry_detected_at to the existing timing record. Non-expiry outcomes use none; expiry without trusted metadata uses unknown. Preserve the existing timing fields and all deadline checks and transaction boundaries. Extend the existing HTTP rollback journey with four exact-wake variants while retaining its eight original non-exact variants and every durable-state assertion. Extend owning log tests for fixed labels, missing/invalid/failing metadata and primary exception preservation. Run focused checks, then the whole-change selector; stop with the requested local diff/evidence and explicitly pending broader gates. Do not push or apply the change.

**Verification plan:**
Four source checkpoints reach the real HTTP log with unchanged 409/body and complete durable rollback -> tests/test_agent_relay_e2e.py::test_claim_expiry_rolls_back_waits_mutation_and_early_returns, preserving all eight existing variants and adding four exact-wake variants.
Safe fixed values, unknown/none fallback, invalid/failing metadata and unchanged exceptions -> owning tests/test_codex_wake.py category/pre-worker/lifecycle cases plus minimal focused controls.
Expired-then-fresh claim/ACK lifecycle, Unicode and unchanged durable attempts/token/scope state -> existing HTTP rollback and lifecycle readback assertions.
Scope and validation requirements -> exact diff/privacy check, Redline, Agent Workflow and scripts/test-plan.py over the complete change. Required full-suite/CI/formal result acceptance remain a later gate, not claimed by focused evidence.

**Plan review:** Agent technical review: build/expiry-detection-review/plan-review.txt, reviewing c7de1be0. PLAN GO for the five-path local implementation and focused verification; preserve annotation/extraction fallbacks and raise the original exception outside metadata handling. Publication and full result acceptance remain pending.

**Approvals:** Approved by user 2026-10-29: "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". Reused standing bug-fix implementation authority and the task-owner's explicit diagnostic-only scope; no new human review, publication or live-change approval is claimed.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Context and exact canonical feature relationship recorded before application/test edits.
- Scope is diagnostic coverage for a future genuine occurrence; it does not resolve physical delay or waive broader feature/refactor gates.
- The existing canonical roadmap item remains active. Its broader state is unchanged by this local preparation.
- Independent technical plan review approved the scoped implementation before application edits. The import-boundary check is clean; Redline confirms the existing API and persistence review checkpoints remain open for publication.
- Baseline RED witness: the original eight HTTP rollback variants passed; the four new exact-wake variants failed only on the absent expiry_detected_at field after the existing status/body/complete rollback assertions passed. The focused run finished with eight passes/four expected failures in 7.22s; evidence is in build/expiry-red/red.xml. This demonstrates missing attribution, not the physical cause of a delay.
- Implemented only the fixed server-origin metadata, cause validation and existing log suffix. Metadata failures preserve the original exception; no check, clock or transaction operation moved. The existing competent worker edited the two production files; the owner retained tests and workflow bookkeeping.
- Focused GREEN: 43 passed, 309 deselected in 21.16s across the owning HTTP/log/expiry cases; build/expiry-focused/focused.xml retains every case. This includes the eight unchanged rollback variants, four exact-wake variants, all fixed labels, missing/invalid metadata, failed writes/reads, original error class/args/cause/context, public error and complete durable snapshots.
- The whole-change selector requires the full lane: python -m pytest tests/ -x -q. This bounded step stops at a local diff and focused evidence as assigned. Required full non-slow validation, formal result review, human result review and API/persistence publication gates remain pending; no qualification waiver or release claim is made.
- Blocked at the requested manager-assessment/full-validation boundary, not by a demonstrated code failure. No push, full CI, installation, live instrumentation, restart or capture occurred. The separate privacy checkpoint remains intact.

## Checkpoint: api-review

Only an allowlisted diagnostic field is appended to the existing exact-wake timing log. HTTP status, detail body, response schema, error conversion and existing timing fields remain unchanged. Focused real HTTP/log journeys and unsafe-metadata controls verify the boundary.

## Checkpoint: persistence-review

Only best-effort metadata on the existing expiry exception changes. Every expiry check, claim mutation, flush, commit, rollback, clock and fence stays in its original position. Existing complete durable-state snapshots and four exact-wake variants verify no mutation survives a rejected request.
