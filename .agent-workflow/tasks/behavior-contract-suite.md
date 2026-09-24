<!-- agent-workflow:start -->
**Outcome:** Pallium has a dedicated, evidence-backed regression for one accepted caller-visible Relay behavior, ready for workflow-only protection.

**Target:** Pallium.

**Scope:** Add `tests/behavior_contracts/README.md` and one standalone HTTP-to-hook RW-022 regression; leave the existing broad test file intact. Reconcile the roadmap item only if its status changes. Policy activation is a separate reviewed change.

**Constraints:** Do not claim automatic unloaded Codex wake, modify production behavior, protect broad mixed-purpose tests, add a CI job, CODEOWNERS, branch protection, or a required status. Keep the test deterministic and in the default PR `test` job.

**Completion criteria:** When one native wake submission is accepted for a busy Codex target, repeated recovery checks shall not submit duplicates; a later admitted hook turn shall emit and ACK the delivery once, and an overtaken wake shall not start an empty model turn. The standalone regression passes on current code, has a pre-fix failure witness, and runs in PR `test`.

**Requirement baseline:**
{"source":"roadmap/features/add-protected-behavioral-requirements-regression-suite.md","outcome":"Pallium has a dedicated, evidence-backed regression for one accepted caller-visible Relay behavior, ready for workflow-only protection.","scope":"Add `tests/behavior_contracts/README.md` and one standalone HTTP-to-hook RW-022 regression; leave the existing broad test file intact. Reconcile the roadmap item only if its status changes. Policy activation is a separate reviewed change.","constraints":"Do not claim automatic unloaded Codex wake, modify production behavior, protect broad mixed-purpose tests, add a CI job, CODEOWNERS, branch protection, or a required status. Keep the test deterministic and in the default PR `test` job.","completion_criteria":"When one native wake submission is accepted for a busy Codex target, repeated recovery checks shall not submit duplicates; a later admitted hook turn shall emit and ACK the delivery once, and an overtaken wake shall not start an empty model turn. The standalone regression passes on current code, has a pre-fix failure witness, and runs in PR `test`."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the intended test and Work Record files blue, but this selects an authoritative product contract. Moderate complexity covers standalone extraction, a historical regression witness, and PR verification.

**Discovery:** `roadmap/features/add-protected-behavioral-requirements-regression-suite.md` requires a small dedicated catalog and public-surface regression before a separate policy change. RW-022 records repeated accepted native queue prompts and empty turns; `tests/test_codex_wake.py::test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake` already drives HTTP, scheduler recovery, and the real hook, but lives in a broad mixed file. The existing `test` CI job runs `tests/`. Current docs exclude unattended unloaded Codex wake.

**Material assumptions:** The RW-022 test can be made standalone using contract-local isolation and existing shared `client` fixture; if extraction needs production changes or broad helper dependencies, return to planning. The documented pre-fix scheduler can provide a direct witness; if current test APIs make that revision incompatible, use a minimal controlled reintroduction in a disposable checkout and report the limitation. Task-owner selection is provisional until confirmed before policy activation.

**Plan:** 1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. 2. Get clean-context plan review. 3. Add only a plain catalog and self-contained RW-022 caller-surface regression under `tests/behavior_contracts/`; do not move or edit the broad existing file. 4. Run focused/default-suite tests and prove a pre-fix or controlled-fault failure witness. 5. Verify PR `test` and combined Redline/Agent Workflow harness, review findings, then merge the test-only PR. Stop and replan if the candidate is rejected or the witness cannot be established.

**Verification plan:** One accepted busy wake remains one native submission across recovery checks and delivers once via hook, while an overtaken wake is suppressed → standalone contract test plus original-failure witness. Default PR verification includes the protected directory → hosted `test (3.12)` and `test (3.13)` jobs. Work Record and scope remain valid → Redline and Agent Workflow checks.

**Plan review:** Pending clean-context review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discover: the initial roadmap candidate promising unloaded Codex wake conflicts with current shipped behavior, so the first contract is narrowed to RW-022's loaded/busy path. The existing broad regression and CI job are reusable evidence; policy activation stays in a separate PR.
- Assess risk: the planned files are blue by Redline, but defining a durable product obligation raises this test-only slice to Elevated.

## Evidence

- Pending.

## Result review

- Pending.
