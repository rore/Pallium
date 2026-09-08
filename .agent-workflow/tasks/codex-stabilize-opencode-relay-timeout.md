<!-- agent-workflow:start -->
**Outcome:**
Windows-full CI retains parallel coverage while the new OpenCode real-service actor/Relay lifecycle E2E runs reliably without xdist process contention.

**Target:**
The Windows-full job in `.github/workflows/ci.yml`.

**Scope:**
Change only `.github/workflows/ci.yml` and this Work Record. Add `tests/test_stable_actor_identity_e2e.py` to the existing Windows process-sensitive serial slice and exclude it from the remaining parallel suite.

**Constraints:**
Do not change production code, test assertions, sleeps, subprocess timeouts, PR smoke coverage, Linux CI, or pytest defaults. Do not make an always-run test intrinsically slower or run any test twice.

**Completion criteria:**
Both Windows-full Python versions run the restart-service, structural-work-reference, and stable-actor modules exactly once with xdist disabled; exclude all three from the subsequent xdist run; retain fail-fast behavior; and pass in hosted main CI. All other CI jobs remain unchanged.

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Agent-redline classifies `.github/workflows/ci.yml` as gray, requiring Elevated handling. Product and test contracts remain unchanged.

**Discovery:**
Main run 34160195493 failed both Windows-full versions in the same new test after 21m28s and 23m49s. The OpenCode hook produced its scope reminder but missed the Relay payload. The test passes locally in 2.98s serially. All integrations intentionally use the same short Relay budgets (750ms claim, 500ms acknowledgement), so changing product timeouts would break parity and host-latency policy. The repository already serializes an analogous OpenCode external-process E2E in Windows-full for the same xdist contention class. Contention is still a hypothesis: the helper also returns null on HTTP, network, and JSON errors, so hosted serial results are decisive. Existing docs drift: this test has a startup polling loop but is not slow-marked; this CI-only task retains its intended non-slow coverage.

**Material assumptions:**
- Serial scheduling removes Windows full-suite process contention. If hosted serial execution still fails, stop and diagnose the harness/service lifecycle instead of increasing product timeouts.
- Adding the module to the existing serial command and ignoring it in the remainder preserves exact-once coverage. Verify both commands' collection.
- The roughly three-second serial module is acceptable and does not make any test intrinsically slower.

**Plan:**
Add `tests/test_stable_actor_identity_e2e.py` to the existing Windows-full process-sensitive `pytest -n 0` command and add the matching `--ignore` to the unchanged parallel remainder. Make no product or test changes. Key convention: reuse the exact existing serial-lane pattern. Target files: `.github/workflows/ci.yml` and this Work Record. Stop if focused serial execution fails or collection shows duplicate/omitted coverage.

**Verification plan:**
- Serial slice -> run the exact combined serial command locally.
- Exact-once coverage -> collect both serial and remaining commands; confirm all three modules appear only in the serial collection.
- Workflow integrity -> parse the YAML, run agent-workflow check, and inspect the final diff.
- Hosted correctness -> require PR CI green, resolve all review findings, merge, then require Windows-full Python 3.12 and 3.13 on main to pass.

**Plan review:**
Approved 2026-09-08 by clean-context strong reviewer `/root/serial_lane_plan_review`: the existing serial slice is the smallest fix that preserves exact-once coverage, product budgets, assertions, fail-fast behavior, and PR/Linux profiles. Contention remains a hypothesis gated by both hosted Windows-full versions.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Work Record created before the CI workflow edit.
- Clean-context strong plan review approved the narrow serial-lane change with no blocking findings; existing slow-marker docs drift recorded but intentionally left out of scope.
- Added the stable-actor E2E module to the existing Windows-full serial process-sensitive command and excluded it from the parallel remainder. No product or test code changed.
- The patch helper hit the known Windows process-creation failure; exact file-scoped deterministic replacements were used for the Work Record and workflow.

## Evidence

- Main run 34160195493: Windows-full Python 3.12 failed after 21m28s and Python 3.13 after 23m49s in `test_opencode_public_relay_lifecycle_uses_configured_actor_against_real_service`.
- Focused local test: 1 passed in 2.98s with `-n 0`.
- Exact combined serial slice: 37 passed, 1 skipped in 93.74s.
- Collection partition: 38 serial + 4,632 parallel = 4,670 original selected nodes; zero overlap and zero union delta.
- Full non-slow suite: 4,636 passed, 32 skipped, 2 xfailed in 185.05s.
- Workflow YAML parsed successfully; final diff is limited to the two scoped files.
- Local redline verdict: GRAY, no boundary violations or checkpoints; agent-workflow checker clean with the repository virtualenv interpreter; `git diff --check` clean.

## Result review

- Approved 2026-09-08 by strong reviewer `/root/serial_lane_plan_review`: actual diff matches scope; exact-once collection is proven; product code, tests, PR/Linux/smoke behavior, fail-fast flags, and pytest defaults are unchanged. Hosted Windows-full remains the decisive post-merge gate.
