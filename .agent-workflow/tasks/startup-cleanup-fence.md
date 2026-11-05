# Fence startup retries after unresolved cleanup

Pull request: https://github.com/rore/Pallium/pull/377

## Discovery and plan review

The API startup retry helper calls the existing tree cleanup after failed readiness, but can start another generation even when that process remains alive. This is a separate startup safety defect; it does not explain historical service stalls. The health-probe loop and Windows tree termination implementation remain unchanged.

Independent non-implementer review approved the narrow direction: recheck the owned process after cleanup, report unresolved cleanup and stop startup retries while it remains alive. Do not introduce a new kill mechanism or extend timing budgets. Existing retry-exhaustion fixtures that model successful cleanup must make the fake process actually report exited; retain their retry-count requirements.

## Recovery state

Application baseline is main revision `447580f6`. This change has no installation or live-operation component.

<!-- agent-workflow:start -->
**Outcome:** API startup never launches a replacement while cleanup leaves its previous owned process alive.

**Target:** Pallium API supervisor startup.

**Scope:** app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, bounded test-only acquisition diagnostics in tests/test_relay_work_ref_associations_e2e.py, and this Work Record.

**Constraints:** Preserve health-probe behavior, process-tree termination, ownership and readiness fences, existing startup deadlines, bounded retry count and backoff. No live process operations, installation, persistent configuration, database or public API changes.

**Completion criteria:** Failed or raised cleanup with a live process stops after one spawn; confirmed cleanup and already-exited processes retain bounded retries. Supervisor callers report startup failure without starting worker helpers. Existing supervisor and tree-cleanup tests pass with unchanged behavior assertions.

**Requirement baseline:** {"source":"work-record-initial","outcome":"API startup never launches a replacement while cleanup leaves its previous owned process alive.","scope":"app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, and this Work Record.","constraints":"Preserve health-probe behavior, process-tree termination, ownership and readiness fences, existing startup deadlines, bounded retry count and backoff. No live process operations, installation, persistent configuration, database or public API changes.","completion_criteria":"Failed or raised cleanup with a live process stops after one spawn; confirmed cleanup and already-exited processes retain bounded retries. Supervisor callers report startup failure without starting worker helpers. Existing supervisor and tree-cleanup tests pass with unchanged behavior assertions."}

**Behavior changes:** [{"target":"task-context.scope","classification":"equivalent","before":"app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, and this Work Record.","after":"app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, bounded test-only acquisition diagnostics in tests/test_relay_work_ref_associations_e2e.py, and this Work Record.","reason":"Add bounded test-only evidence for the existing required CI gate; preserve every product requirement, deadline, status assertion and cleanup contract."}]

**Risk:** High

**Complexity:** Moderate

**Reason:** Startup generation ownership and cleanup affect orphan processes and availability, despite a small source change.

**Discovery:** The retry helper catches cleanup exceptions and continues; tree termination can log failure without raising. Checking poll after cleanup establishes whether its owned process has exited before another startup attempt. This does not prove descendant exit or authorize a stronger reaper.

**Material assumptions:** Existing process ownership and readiness tokens remain authoritative. poll returning an exit code is the existing parent-process lifecycle boundary, not proof that every descendant exited. Replacement readiness continues to reject a foreign listener.

**Plan:** Add one post-cleanup liveness fence in _start_api_with_retry. Keep the existing cleanup and exception behavior. Add deterministic startup/caller witnesses and correct only fake cleanup state in existing exhaustion fixtures, preserving their assertions. Run focused nodes, both supervisor files, the whole-change selector and required full validation before publication.

**Verification plan:** Startup fencing and preserved retries → deterministic _start_api_with_retry and run_supervisor controls plus both supervisor files. Whole-change regression coverage → scripts/test-plan.py --base origin/main and its required full non-slow suite. Policy compliance → boundary report, risk classification and workflow check. Caller contract before merge → existing PR test job.

**Plan review:** Agent technical review: independent non-implementer recovery_diagnostics_review confirmed PLAN GO for this exact Work Record at main 447580f6 before source edits, narrowed to the post-cleanup startup fence after rejecting stronger kill machinery and health-counter changes. The same independent reviewer confirmed PLAN GO at a8f029ff for the bounded test-only acquisition observer, preserving all deadlines, assertions, retries, GC policy and controlled cleanup behavior.

**Approvals:** Approved by user 2026-10-29: "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". This covers necessary bug-fix work; unrelated environment changes remain outside scope. No live operation is planned here.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Implementation: `_start_api_with_retry` now checks the owned process after the existing forced tree cleanup. If `poll()` still reports alive, it logs unresolved cleanup and returns before backoff or another spawn. Cleanup exceptions retain their existing catch behavior and take the same liveness check. Tests cover no-effect and raised cleanup, already-exited retry behavior, startup caller failure before worker helpers, and fake successful cleanup in existing retry-exhaustion/budget cases; their retry-count assertions are preserved.

Test-only diagnostics now observe bounded GC metadata and SQLAlchemy busy-timeout cursor events during only the selected seed storage calls. The existing acquisition observer remains the source for phase wall time and total acquisition wall/thread CPU. The synthetic control checks event filtering, record cap, and callback/listener teardown after an exception. Product code, role A/B control behavior, deadlines, and assertions are unchanged.

## Evidence

The new fence/control and caller/exhaustion focused nodes passed. The serial supervisor files passed with local loopback enabled: `tests/test_supervisor.py tests/test_supervisor_kill_tree.py -q -n 0 -p no:cacheprovider` → 74 passed, 6 skipped. An earlier sandboxed attempt had 12 failures because local loopback was denied and the startup-budget fake had not yet been updated; the final elevated local-only run passed. No service, installed app, persistent config, or live database was touched.

The whole-change selector required the full non-slow suite. Against unchanged application commit `9ebd4658`, the corrected complete run passed: 8,379 passed, 37 skipped, 2 xfailed. The initial run used temporary directories inside a Git checkout and failed two hook scope tests; both unchanged nodes passed outside the checkout, and the complete corrected run used that isolation. Both reports remain in private evidence. Boundary checks passed, deterministic classification is GRAY with the supervisor path watched, and the workflow check is clean. Current-head CI remains required before merge.

Current CI is blocked by [the Python 3.12 job](https://github.com/rore/Pallium/actions/runs/40907609036/job/123567335961): `test_settled_relay_write_releases_gate_before_cleanup[reset-None-commit]` returned 503 while seeding its second association, before its controlled cleanup sequence. Acquisition evidence records 1,791 ms in setup PRAGMA, approximately equal wall and thread CPU time, with no captured native SQLite error. The physical cause is unresolved. Python 3.13 and Windows smoke passed. A bounded test-only observer is now available for a later qualifying Python 3.12 CI run; it cannot retrospectively attribute the recorded delay.

## CI diagnostic follow-up

The startup source remains unchanged. The test-only observer is disabled by default and activates only in CI on Python 3.12 for `reset-None-commit`, around that case's seed storage calls. It records bounded GC phase/generation and same-thread metadata plus timestamps for the first matching SQLAlchemy busy-timeout PRAGMA before/after cursor events. Existing acquisition diagnostics provide outer acquisition wall/thread CPU and setup-phase wall time; the new observer does not time the full PRAGMA call or prove that a GC event caused the delay. A focused synthetic-event control verifies record bounds and exception-safe teardown. It emits only timing/phase metadata on seed failure; it does not retain SQL text, parameters, IDs, paths, payloads or locals. The original seed assertions, deadline and controlled cleanup behavior remain unchanged. Independent plan review approved this test-only scope at a8f029ff.

Implementation file list: `tests/test_relay_work_ref_associations_e2e.py` (bounded observer and control only) and `.agent-workflow/tasks/startup-cleanup-fence.md` (this record). The worker reported a focused local run using Python 3.13 and `python -m pytest tests/test_relay_work_ref_associations_e2e.py -q -n 0 -p no:cacheprovider --basetemp <isolated-temp-outside-checkout>` → 35 passed in 20.47 seconds. This exercised the synthetic control and E2E file with diagnostic activation off. No XML or redirected log was retained for that local run; the independent reviewer accepted it as a reported result without inspecting a saved report. No rerun was made solely to recreate artifacts. The CI-only activation path remains pending, and the original CI failure remains physically unexplained.

Independent source review accepted diagnostic source hash `91678148` after correcting the synthetic GC event ordering. The application source remains unchanged. Per the evidence-reuse policy, the retained 8,379-pass full run covers unchanged targets and the reported 35-case run replaces this file's affected local coverage. These are separate runs, not a passing full run at the new revision. The refreshed whole-change selector still selects the full lane; workflow/Redline checks are clean with no boundary violation. Saved current-head platform CI results, especially the active Python 3.12 diagnostic path, remain required before result qualification or merge.

## Result review

Agent technical review: independent non-implementer recovery_diagnostics_review, final RESULT GO for draft publication.

Reviewed revision: 9ebd4658203bc84bac9484230076e421490ae82d

Verification adequacy: Independently inspected the full report (8,379 passed, 37 skipped, 2 xfailed, zero failures/errors), including both supervisor files (74 passed, 6 skipped), unchanged source hashes, clean workflow and GRAY classification with no boundary violations or required checkpoints. The guard and fixture corrections preserve health, reaper, readiness, timing and retry-count behavior. Current-head CI remains required before merge. The fence establishes owned-parent exit only, with no stronger descendant-cleanup claim.
