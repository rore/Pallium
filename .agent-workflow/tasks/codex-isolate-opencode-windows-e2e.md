<!-- agent-workflow:start -->
**Outcome:**
Windows-full CI retains parallel coverage while the external-process OpenCode caller E2E runs reliably without xdist contention.

**Target:**
The Windows-full job in `.github/workflows/ci.yml`.

**Scope:**
Change only `.github/workflows/ci.yml` and this Work Record. Add `tests/test_structural_work_refs_e2e.py` to the existing serial Windows process-sensitive slice and exclude it from the remaining parallel suite.

**Constraints:**
Do not change production code, test assertions, sleeps, subprocess timeouts, PR smoke coverage, Linux CI, or pytest defaults. Do not make an always-run test intrinsically slower or run any test twice.

**Completion criteria:**
Both Windows-full Python versions run the restart-service and structural-work-reference modules exactly once with xdist disabled, exclude both from the subsequent xdist run, retain fail-fast behavior, and pass in hosted main CI. All other CI jobs remain unchanged.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
The change is limited to CI scheduling, but `.github/workflows/ci.yml` is a gray zone requiring Elevated handling. Product and test contracts remain unchanged.

**Discovery:**
Main runs 34028583850 and 34028928907 alternated the same 20-second OpenCode Node helper timeout between Windows-full Python 3.12 and 3.13 while the sibling version passed. PR #118 corrected the test to one real session and reduced redundant Git probes, yet post-merge run 34030583518 still timed out the same helper on Python 3.13 under the full xdist suite. The affected module passes serially in 5.26 seconds and under local xdist in 11.04 seconds. This is cross-worker external-process contention, not a version-specific product failure.

**Material assumptions:**
- Serial scheduling removes the full-suite process contention. If the hosted serial module still times out, stop and diagnose the Node harness lifecycle instead of increasing timeout.
- Adding the module to the existing serial command and ignoring it in the remainder preserves exact-once coverage. Verify both commands' collection.
- The roughly five-second serial module is acceptable and does not make any test intrinsically slower.

**Plan:**
Rename the existing Windows-full serial step to cover process-sensitive tests, add `tests/test_structural_work_refs_e2e.py` to its `pytest -n 0` command, and add the matching `--ignore` to the unchanged parallel remainder. Make no test or product changes.

**Verification plan:**
- Serial slice -> run the exact combined serial command locally.
- Exact-once coverage -> collect both serial and remaining commands; confirm both modules appear only in the serial collection.
- Workflow integrity -> run redline, agent-workflow, YAML parsing, and diff checks.
- Hosted correctness -> require both Windows-full Python 3.12 and 3.13 jobs on main to pass.

**Plan review:**
Approved 2026-09-06 by clean-context agent /root/ci_process_plan_review: the existing serial slice is the smallest root-cause fix; it preserves exact-once coverage, fail-fast behavior, assertions, and timeout bounds.

**Approvals:**
Standing user authorization to take managed PRs through review, CI, and merge.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Renamed the Windows-full serial step to process-sensitive tests, added the structural-work-reference E2E module to its existing `-n 0` command, and excluded that module from the parallel remainder. No test or product code changed.

## Evidence

- Main runs 34028583850, 34028928907, and 34030583518: same OpenCode Node helper timeout under Windows-full xdist; affected Python version alternates.
- Local affected module: 11 passed, 1 skipped in 5.26s serial; 11 passed, 1 skipped in 11.04s under xdist.
- Exact combined serial command: 35 passed, 1 skipped in 20.37s.
- Remaining-suite collection: 4,468 selected, 168 deselected; neither serial module collected.
- Run 34030583518 completed with Windows-full 3.12 green and only Windows-full 3.13 failing the same OpenCode Node timeout; all fast jobs green.

## Result review

- Self-review: the diff changes only Windows-full scheduling; both modules remain fail-fast and exact-once, with no timeout/sleep/assertion change. Hosted Windows-full 3.12 and 3.13 remain the decisive post-merge gate.