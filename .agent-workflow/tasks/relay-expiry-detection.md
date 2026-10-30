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

**Plan review:** Pending independent technical plan review; no implementation may start before it is recorded.

**Approvals:** Approved by user 2026-10-29: "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". Reused standing bug-fix implementation authority and the task-owner's explicit diagnostic-only scope; no new human review, publication or live-change approval is claimed.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Context and exact canonical feature relationship recorded before application/test edits.
- Scope is diagnostic coverage for a future genuine occurrence; it does not resolve physical delay or waive broader feature/refactor gates.
- The existing canonical roadmap item remains active. Its broader state is unchanged by this local preparation.
