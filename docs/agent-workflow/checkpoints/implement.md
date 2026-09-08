# implement

The longest stretch of the work — where scope drift, assumption decay, and silent-fix culture do the most damage.

> **Drift signal.** More than ~30 minutes wall time or ~5 file edits without touching the Work Record's Implementation prose → you've drifted. Stop, write what just happened, then continue. The `workrecord.commit_order` advisory predicate catches retroactive Work Records.

## Before writing the first line

List the specific files or classes you intend to modify. Record it in Implementation prose. If during implementation you discover you need to touch something not on this list, treat it as potential scope expansion (Rule 2 below) — stop and decide before continuing.

## Where to record what

| Surface | What goes there |
|---|---|
| **Work Record** (marker block) | Risk, Complexity, State, Approvals — harness-validated. Do NOT edit mid-implementation unless an assumption failure changes them. |
| **Work Record prose** (under `## Implementation`) | Decisions, deviations from the plan, things the planner missed. One short paragraph per checkpoint sub-step — the audit trail. |
| **Commit messages** | Per-commit "why," not just "what." |
| **PR description** | Final synthesis: what shipped, what's verified, what was deferred. Written after Verify. |

If a decision is structural (future readers benefit), put it in code AND Implementation prose. Code-only comments rot; Work Records age into history.

## Rules

1. **Stay on the task branch from a known revision.** Don't switch the base mid-stream. If main moves, rebase explicitly and note it in Implementation prose. The verification plan references a revision; that revision must stay reachable.

2. **Approved scope = the Scope field, period.** If you want a change not in Scope: either skip it (note it in Implementation prose as a follow-up) or stop and expand scope (returns to Establish-Context + Plan-and-Review).

3. **No unrelated refactoring.** Open a separate task. Reasons: reviewer reviews the *declared* scope, unrelated changes inherit unrelated risk, the verification plan covers declared scope.

4. **Write planned tests as part of Implement, not as an afterthought.** For bug fixes: regression test that fails BEFORE the fix when practical (SPEC §9.6 SHOULD).

5. **Delegate test runs to a sub-agent or separate invocation** that returns only STATUS / SUMMARY / FAILURES. Do not let full compiler or test-runner output accumulate in the implementing agent's context — it crowds out task state and degrades decision quality on long sessions.

6. **Record material decisions in Implementation prose in-line.** Things the planner didn't anticipate: pivoted approaches, discovered constraints, deferred refinements. Routine details (file names, signatures) belong in code review, not prose.

7. **Pause on assumption failure.** Stop coding → update Material assumptions with the disproving evidence → decide next step per the recorded action → record the pivot in Implementation prose. The harness can't enforce this; it's a discipline.

8. **Stop on boundary violation.** Non-waivable. Surface in conversation → treat as material scope change → either pivot to avoid it or escalate to the developer. A change that *fixes* an existing boundary violation is welcome; a change that *creates* one is not.

## What counts as material scope expansion

- Changes the **Risk** classification (adds a red-zone touch)
- Changes the **Target** (touches a different service/repo)
- Changes the **Outcome** (the user-facing result is different)
- Adds work the planner did not approve

Small refinements (a helper, a renamed local) are fine. Rule of thumb: *would the reviewer have approved a different plan if they'd known about this change?* If yes, return to planning.

## Keeping recovery state current

A reader who picks up the Work Record + task branch + Implementation prose can resume without asking you what you were doing.

- Update prose at every phase boundary (end of investigation, hypothesis confirmed/disproved, chunk of code lands).
- Don't wait until done. By then the context is gone.
- The State field stays `Ready to implement` until Verify flips it.

## What the harness validates

| Predicate | What it checks |
|---|---|
| `risk.boundary_violation_absent` | No boundary violation in redline's verdict. Blocks. |
| `risk.declared_not_below_detected` | Declared Risk matches what redline detects on the actual diff. Blocks. |
| `exceptions.well_formed` | If Exceptions field has entries, each is structurally complete. |
| `exceptions.not_against_boundary` | Exceptions can't waive `boundary_violation` or shape preconditions. |
| `exceptions.not_expired` | Exception expiry dates (if set) haven't passed. |

Everything else — scope discipline, refactor avoidance, assumption hygiene, decision recording — is enforced by the reviewer at Review-the-Result, not by a predicate.

## Anti-patterns — stop if you find yourself in one

- **Mid-task scope creep.** Started fixing X, discovered Y, started fixing Y. Work Record still says X. PR will be reviewed against X. → Stop, return to planning.
- **Silent assumption drift.** Decided the original assumption was wrong but kept going because "it's close enough." → Stop, update the assumption + record the pivot.
- **"While I'm in here" refactor.** Touched 30 files instead of 3 because you cleaned up other stuff. → Stash the refactor; separate task.
- **Failing-test omission.** Test fails locally, you decide it's flaky, don't investigate. → Stop. Fix the flake (and record it) or pivot the implementation. Don't push.
- **State-flip during implementation.** Moved State from `Ready to implement` to `Ready for review` without running verification. → State is set by Verify, not by you.
- **Plan-after-the-fact.** Implemented something, then edited the plan to match. → The plan is a commitment, not a postmortem. Record divergence; don't rewrite history.

## Done with Implement when

1. Scope is exhausted: all approved work is in the diff.
2. Implementation prose is current: a reviewer can see what happened.
3. No assumption is stale: every Material assumption holds or has been updated.
4. Verification has not yet run — Verify is the next checkpoint.

**Not done** if you're "almost done but want to skip the last test," considering an "unrelated fix," or have an assumption that feels wrong but you haven't updated it.
