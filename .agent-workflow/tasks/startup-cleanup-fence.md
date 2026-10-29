# Fence startup retries after unresolved cleanup

## Discovery and plan review

The API startup retry helper calls the existing tree cleanup after failed readiness, but can start another generation even when that process remains alive. This is a separate startup safety defect; it does not explain historical service stalls. The health-probe loop and Windows tree termination implementation remain unchanged.

Independent non-implementer review approved the narrow direction: recheck the owned process after cleanup, report unresolved cleanup and stop startup retries while it remains alive. Do not introduce a new kill mechanism or extend timing budgets. Existing retry-exhaustion fixtures that model successful cleanup must make the fake process actually report exited; retain their retry-count requirements.

## Recovery state

Isolated branch based on main revision `447580f6`. No installed changes or publication. Another active branch contains hook repairs and remains subject to its existing publication hold. Private incident evidence is retained outside public artifacts.

<!-- agent-workflow:start -->
**Outcome:** API startup never launches a replacement while cleanup leaves its previous owned process alive.

**Target:** Pallium API supervisor startup.

**Scope:** app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, and this Work Record.

**Constraints:** Preserve health-probe behavior, process-tree termination, ownership and readiness fences, existing startup deadlines, bounded retry count and backoff. No live process operations, installation, persistent configuration, database or public API changes.

**Completion criteria:** Failed or raised cleanup with a live process stops after one spawn; confirmed cleanup and already-exited processes retain bounded retries. Supervisor callers report startup failure without starting worker helpers. Existing supervisor and tree-cleanup tests pass with unchanged behavior assertions.

**Requirement baseline:** {"source":"work-record-initial","outcome":"API startup never launches a replacement while cleanup leaves its previous owned process alive.","scope":"app/supervisor.py startup retry cleanup fence, tests/test_supervisor.py, and this Work Record.","constraints":"Preserve health-probe behavior, process-tree termination, ownership and readiness fences, existing startup deadlines, bounded retry count and backoff. No live process operations, installation, persistent configuration, database or public API changes.","completion_criteria":"Failed or raised cleanup with a live process stops after one spawn; confirmed cleanup and already-exited processes retain bounded retries. Supervisor callers report startup failure without starting worker helpers. Existing supervisor and tree-cleanup tests pass with unchanged behavior assertions."}

**Behavior changes:** []

**Risk:** High

**Complexity:** Moderate

**Reason:** Startup generation ownership and cleanup affect orphan processes and availability, despite a small source change.

**Discovery:** The retry helper catches cleanup exceptions and continues; tree termination can log failure without raising. Checking poll after cleanup establishes whether its owned process has exited before another startup attempt. This does not prove descendant exit or authorize a stronger reaper.

**Material assumptions:** Existing process ownership and readiness tokens remain authoritative. poll returning an exit code is the existing parent-process lifecycle boundary, not proof that every descendant exited. Replacement readiness continues to reject a foreign listener.

**Plan:** Add one post-cleanup liveness fence in _start_api_with_retry. Keep the existing cleanup and exception behavior. Add deterministic startup/caller witnesses and correct only fake cleanup state in existing exhaustion fixtures, preserving their assertions. Run focused nodes, both supervisor files, the whole-change selector and required full validation before publication.

**Verification plan:** Deterministic failed/raised cleanup and successful/already-exited controls through _start_api_with_retry and run_supervisor; both existing supervisor files; scripts/test-plan.py --base origin/main and its required checks, including full non-slow suite and workflow compliance. Existing PR test job will verify the caller contract before any merge.

**Plan review:** Agent technical review: independent non-implementer recovery_diagnostics_review source assessment at main 447580f6, narrowed to the post-cleanup startup fence after rejecting stronger kill machinery and health-counter changes. Reconfirm the recorded plan before source edits.

**Approvals:** Approved by user 2026-10-29: "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". This covers necessary bug-fix work; unrelated environment changes remain outside scope. No live operation is planned here.

## Implementation and verification evidence

Implementation: `_start_api_with_retry` now checks the owned process after the existing forced tree cleanup. If `poll()` still reports alive, it logs unresolved cleanup and returns before backoff or another spawn. Cleanup exceptions retain their existing catch behavior and take the same liveness check. Tests cover no-effect and raised cleanup, already-exited retry behavior, startup caller failure before worker helpers, and fake successful cleanup in existing retry-exhaustion/budget cases; their retry-count assertions are preserved.

Verification: the new fence/control and caller/exhaustion focused nodes passed. The requested serial supervisor files passed with local loopback enabled: `tests/test_supervisor.py tests/test_supervisor_kill_tree.py -q -n 0 -p no:cacheprovider` → 74 passed, 6 skipped. An earlier sandboxed attempt had 12 failures because local loopback was denied and the startup-budget fake had not yet been updated; the final elevated local-only run passed. No service, installed app, persistent config, or live database was touched. Whole-change selector/full suite remain with the parent task owner.

**State:** Ready for review
<!-- agent-workflow:end -->
