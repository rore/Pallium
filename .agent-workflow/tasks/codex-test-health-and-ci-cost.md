<!-- agent-workflow:start -->
**Outcome:** The required test lanes exercise the installed MCP surface hermetically, ordinary PR feedback stays fast, redundant/docs-only CI spend is avoided, and the deliberately slow suite has measured scheduled coverage.

**Target:** Pallium test and CI infrastructure.

**Scope:** `.github/workflows/ci.yml`, `tests/test_mcp_server.py`, `docs/testing-conventions.md`, and aligned Work Record/roadmap files. `pyproject.toml`, product code, eval expectations, and broad slow-test repairs are explicitly excluded.

**Constraints:** Product code and public contracts remain unchanged; no new third-party dependency beyond the existing `mcp` optional extra; code-bearing changes retain Linux 3.12/3.13 plus Windows smoke coverage; generated P2, credentialed, live-service, and external-dataset scenarios must not become build gates; successful PR feedback must not become materially slower.

**Completion criteria:** An MCP-enabled default run passes the four scope-aware status tests; required CI cannot silently skip MCP server coverage; superseded runs cancel and docs/roadmap-only main pushes avoid the Python matrix; slowest-test diagnostics are emitted; and a measured hermetic slow lane runs on a schedule while opt-in/live work stays explicitly excluded.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classifies `.github/workflows/ci.yml` as gray and CI scheduling is operationally consequential; all other intended files are blue and no boundary or formal checkpoint applies. Moderate because coverage, cost, timing diagnostics, and slow-test taxonomy interact.

**Discovery:** The default configuration collects 4,592 of 4,762 tests (`-m 'not slow' -n 4`) across 281 files and runs in about three minutes on Linux. Recent successful main runs show ~2-minute Windows smoke and 19–24-minute full Windows jobs per Python version, with one 53-minute test-step outlier; overlapping main pushes duplicate both full jobs. A clean MCP-enabled local profile took 217 seconds and exposed four deterministic `pallium_relay_status` test failures because those tests omit the now-required paired Relay scope. CI installs `.[dev,vector]`, and `tests/test_mcp_server.py` uses module-level `pytest.importorskip('mcp')`, so required CI currently skips that surface. The 170 slow-deselected tests are not run by the nightly workflow because it inherits the same default marker filter. A neutral audit produced 32 failed, 135 passed, 1 skipped, 1 xfailed, and 1 xpassed in 87 seconds; failures cluster in stale semantic/eval expectations, including the already-roadmapped work-resumption scenario-count drift. After source inspection excluded the opt-in Linux service and vector/download-capable live runner, a 12-test explicit infrastructure allowlist passed serially in 34.67 seconds. Recent timeout/deadline CI failures were repaired, but local order/load-sensitive failures and the missing optional-extra coverage show remaining hygiene debt.

**Material assumptions:** (1) Installing the already-declared `mcp` extra in required Linux lanes keeps PR completion within the existing practical budget; disproof is a material median increase, which triggers a dedicated focused MCP lane instead. (2) Push-only path ignores are limited to Markdown under `docs/` and `roadmap/`; under GitHub all-files-ignored semantics, mixed code/test/workflow/dependency changes still run, subject to GitHub documented large-diff limits. (3) The inspected 12-test snapshot/storage/concurrency/Relay allowlist is the only scheduled slow subset in this round, runs serially with a 15-minute job timeout, and remains separate from opt-in Linux service, vector/download-capable live, and stale eval tests. The 32 failing slow tests are recorded as a separate roadmap repair; no marker or `pyproject.toml` change is permitted.

**Plan:** 1. Make the four MCP status tests supply a paired scope and prove the complete MCP server file runs when the optional extra is installed. 2. Update CI with native concurrency grouped by workflow + event + ref, push-only `docs/*.md`/`docs/**/*.md` and `roadmap/*.md`/`roadmap/**/*.md` ignores, the existing `mcp` extra plus an explicit import assertion in required Linux coverage, and native `--durations=20` output on Linux, Windows smoke/full, and scheduled slow commands; preserve current code-bearing PR lanes. 3. Add a scheduled Ubuntu 3.13 slow-smoke job with `timeout-minutes: 15` running `python -m pytest tests/test_snapshot.py tests/test_snapshot_concurrent.py tests/test_snapshot_failure.py tests/test_storage_sqlite.py tests/test_thread_summary_accumulation.py tests/test_relay_load_smoke.py -m slow -n 0 -q --durations=20`; install the existing dev/vector/MCP extras, add no marker, and do not schedule the 32-failure stale eval group. 4. Add an active roadmap item, verify workflow syntax/semantics, focused MCP tests, default suite, selected slow lane, and redline/workflow gates; mark roadmap done only after evidence. Stop on product-code changes, a new dependency, loss of code-bearing coverage, or an unbounded slow-suite redesign.

**Verification plan:** MCP hermeticity → run `tests/test_mcp_server.py` and the full non-slow suite with `mcp` installed. CI behavior → statically parse YAML and assert event/path/concurrency/matrix/command contracts with the existing workflow-test pattern or a focused structural test. Runtime/cost → collect duration output and compare required lane shape to the current 3-minute Linux/2-minute smoke baseline; no speculative timing gate. Slow coverage → retain the full neutral audit counts (32 failed / 135 passed / 1 skipped / 1 xfailed / 1 xpassed), rerun the six-file command named in Plan step 3 (12 passed / 80 deselected in 34.67s locally), and verify opt-in Linux service/vector-download-capable live runners are absent. Governance → `git diff --check`, redline report, Agent Workflow checker, clean-context result review, and green PR CI.

**Plan review:** Senior clean-context review completed; three initial blockers were resolved and follow-up sign-off reports no remaining blockers. See `## Plan review`.

**Approvals:** Not required at this risk level; user explicitly authorized the proposed round with “ok, let's do this”.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07 Establish Context: reused the clean isolated worktree on branch `codex/test-health-and-ci-cost`; the active root checkout and its unrelated uncommitted hook work remain untouched.
- 2026-09-07 Discover: measured current collection and recent CI lanes, profiled the MCP-enabled default suite, identified four stale scope-less MCP status tests hidden by the missing optional extra, confirmed overlapping full Windows main jobs, and found the nightly workflow excludes all 170 slow tests.
- 2026-09-07 Assess Risk: clean-context redline review classified the intended diff GRAY because `.github/workflows/ci.yml` is unclassified/operational; tests, docs, roadmap, and Work Record are blue; no checkpoint or boundary risk.
- 2026-09-07 Plan discovery: the full slow marker is not schedulable as-is (32 failed / 135 passed / 1 skipped / 1 xfailed / 1 xpassed in 87.36s). Source inspection excluded the opt-in Linux service and vector/download-capable live runner; an explicit 12-test snapshot/storage/concurrency/Relay slow-smoke candidate passed serially in 34.67s.
- 2026-09-07 Plan review: senior clean-context review found and resolved marker/red-zone scope, cancellation-group isolation, slow-inventory safety, path-filter precision, MCP import proof, and timing-documentation gaps; follow-up sign-off granted after the exact scheduled command was recorded.
- 2026-09-07 Implement: committed revision `c93c7078`; four Relay status tests now provide paired configured scope, required Linux CI installs and proves MCP, all pytest jobs report durations, same-event/ref runs cancel, docs/roadmap-only pushes are ignored, and a bounded serial nightly slow smoke is scheduled. The machine-local `apply_patch` failure path was already established, so edits used narrowly scoped deterministic PowerShell replacements as permitted by local instructions.
- 2026-09-07 Verify: focused MCP regressions `4 passed`; full MCP module `47 passed`; CI structural contracts `5 passed`; exact nightly slow smoke `12 passed, 80 deselected in 32.88s`; full default suite `4563 passed, 32 skipped, 2 xfailed in 161.82s`; workflow YAML parsed; `git diff --check`, redline, and Agent Workflow gates passed.

## Plan review

Initial senior clean-context review required three changes before implementation:

1. Exclude `pyproject.toml` and new markers because marker registration is red-zone and would require architecture review. Resolved: the plan uses an explicit inspected file allowlist and makes `pyproject.toml` a stop condition.
2. Separate scheduled work from push/PR cancellation. Resolved: concurrency keys include workflow, event name, and ref, so newer runs replace only the same event/ref while nightly cannot be canceled by a push.
3. Inspect slow tests before execution/scheduling and exclude opt-in service or potential model-download paths. Resolved: the full audit is recorded as unhealthy, the Linux service and live exploratory runner are excluded, and the exact 12-test hermetic candidate passed serially with a bounded planned job.

The review also narrowed push ignores to Markdown under `docs/` and `roadmap/`, required an explicit MCP import assertion, selected native `--durations=20`, and identified stale `docs/testing-conventions.md` timing text. Follow-up review verified the exact six-file/12-test serial command, confirmed its temporary-storage/stubbed-provider/disabled-vector boundaries, and granted sign-off with no remaining blockers.
## Evidence

Pre-edit baseline: 4,592 selected / 170 slow-deselected tests; local MCP-enabled default profile `4 failed, 4554 passed, 32 skipped, 2 xfailed in 217.17s`. Recent successful main-job medians: Linux 3.0 minutes, Windows smoke 2.0 minutes, Windows full 19.9 minutes per version; observed full-Windows maximum 53.0 minutes.

Verified revision `c93c7078`: `tests/test_mcp_server.py` passed 47/47; the full non-slow suite passed 4,563 tests with 32 skips and 2 expected xfails in 161.82 seconds; the exact six-file slow smoke passed 12 tests with 80 deselected in 32.88 seconds; five CI structural tests, YAML parsing, diff checks, redline classification, and the Agent Workflow checker passed.

## Result review

Pending.
