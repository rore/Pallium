<!-- agent-workflow:start -->
**Outcome:**
Windows full CI completes reliably instead of failing on resource-sensitive OpenCode subprocess startup or incomplete fixed-time concurrent processing.

**Target:**
Pallium test suite.

**Scope:**
tests/test_structural_work_refs_e2e.py and tests/test_thread_summary_accumulation.py only.

**Constraints:**
Production behavior and public contracts unchanged. Do not lengthen always-run sleeps or subprocess timeouts; preserve caller-surface and concurrency assertions.

**Completion criteria:**
(1) The OpenCode structural-work-ref caller E2E exits promptly on Windows without manufacturing slow missing-executable launches. (2) The rapid-fire concurrent test deterministically reaches one active thread summary after its concurrent phase. (3) Focused tests pass repeatedly and CI passes.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Redline classified both intended test paths blue with no boundary finding. Moderate because two independent Windows CI liveness failures need distinct deterministic synchronization fixes.

**Discovery:**
Four recent Windows full runs failed the OpenCode helper after it cleared PATH and synchronously attempted bounded git launches; a later run passed that test but failed the rapid-fire test after its fixed 30-second poll with no worker error, zero summary, and only partial facts. Current main passes the OpenCode file in isolation, confirming resource-sensitive test liveness rather than a deterministic contract failure.

**Material assumptions:**
The OpenCode failure is caused by the broad E2E's missing-executable setup, already covered by dedicated resolver tests; if real-git execution changes expected refs, return to planning. The rapid-fire state converges after concurrent workers exit and a deterministic drain; if drain fails or produces duplicate summaries, treat it as a production bug and reclassify before editing core code.

**Plan:**
Keep the diff test-only. Remove PATH clearing from the broad OpenCode caller E2E so it exercises a normal installed runtime rather than repeated missing-executable timeouts. Replace the rapid-fire test's 30-second wall-clock poll with orderly worker shutdown, assert both workers exit, then use the existing synchronous drain to prove the concurrency-created state converges. Target files are the two scoped tests; stop and reclassify if production code is required.

**Verification plan:**
OpenCode caller E2E shall complete and preserve exact refs -> run its full parameter matrix repeatedly. Rapid-fire concurrency shall converge to exactly one active thread summary -> run the exact test repeatedly. Final diff shall remain test-only -> redline/workflow and git diff checks; CI shall pass all jobs.

**Plan review:**
Self-review: the plan removes two timing dependencies, reuses the existing drain, and preserves dedicated failure-path coverage.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Established the task from repeated Windows CI failures. Redline classified the intended test-only scope blue; no production code or boundary change is planned.

## Evidence

Pending.

## Result review

Pending.
