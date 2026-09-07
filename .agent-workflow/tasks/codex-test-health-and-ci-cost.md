<!-- agent-workflow:start -->
**Outcome:** The required test lanes exercise the installed MCP surface hermetically, ordinary PR feedback stays fast, redundant/docs-only CI spend is avoided, and the deliberately slow suite has measured scheduled coverage.

**Target:** Pallium test and CI infrastructure.

**Scope:** `.github/workflows/ci.yml`, MCP server tests, testing conventions, and aligned Work Record/roadmap files; test-only fixes required by measured slow-lane failures may be added after an explicit scope check.

**Constraints:** Product code and public contracts remain unchanged; no new third-party dependency beyond the existing `mcp` optional extra; code-bearing changes retain Linux 3.12/3.13 plus Windows smoke coverage; generated P2, credentialed, live-service, and external-dataset scenarios must not become build gates; successful PR feedback must not become materially slower.

**Completion criteria:** An MCP-enabled default run passes the four scope-aware status tests; required CI cannot silently skip MCP server coverage; superseded runs cancel and docs/roadmap-only main pushes avoid the Python matrix; slowest-test diagnostics are emitted; and a measured hermetic slow lane runs on a schedule while opt-in/live work stays explicitly excluded.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Agent-redline classifies `.github/workflows/ci.yml` as gray and CI scheduling is operationally consequential; all other intended files are blue and no boundary or formal checkpoint applies. Moderate because coverage, cost, timing diagnostics, and slow-test taxonomy interact.

**Discovery:** The default configuration collects 4,592 of 4,762 tests (`-m 'not slow' -n 4`) across 281 files and runs in about three minutes on Linux. Recent successful main runs show ~2-minute Windows smoke and 19–24-minute full Windows jobs per Python version, with one 53-minute test-step outlier; overlapping main pushes duplicate both full jobs. A clean MCP-enabled local profile took 217 seconds and exposed four deterministic `pallium_relay_status` test failures because those tests omit the now-required paired Relay scope. CI installs `.[dev,vector]`, and `tests/test_mcp_server.py` uses module-level `pytest.importorskip('mcp')`, so required CI currently skips that surface. The 170 slow-deselected tests are not run by the nightly workflow because it inherits the same default marker filter. Recent timeout/deadline CI failures were repaired, but local order/load-sensitive failures and the missing optional-extra coverage show remaining hygiene debt.

**Material assumptions:** (1) Installing the already-declared `mcp` extra in required Linux lanes keeps PR completion within the existing practical budget; disproof is a material median increase, which triggers a dedicated focused MCP lane instead. (2) All-files-ignored semantics on push path filters safely skip Python CI only when a main commit is confined to docs/roadmap Markdown; any code/test/workflow file still triggers the matrix. (3) Existing slow tests can be divided using current opt-in guards or the smallest additional marker; if a hermetic subset cannot be identified without broad rewrites, stop before scheduling and record the taxonomy blocker rather than create a flaky nightly gate.

**Plan:** 1. Make the four MCP status tests supply a paired scope and prove the complete MCP server file runs when the optional extra is installed. 2. Update CI with native concurrency cancellation, push-only docs/roadmap path ignores, the existing `mcp` extra in required Linux coverage, and `pytest --durations` output; preserve current code-bearing PR lanes. 3. Run the existing slow suite once in a clean environment, classify failures/skips as hermetic versus explicit live/external work, and add only the smallest safe scheduled slow lane plus corresponding marker/convention changes if required. 4. Add an active roadmap item, verify workflow syntax/semantics, focused MCP tests, default suite, selected slow lane, and redline/workflow gates; mark roadmap done only after evidence. Stop on product-code changes, a new dependency, loss of code-bearing coverage, or an unbounded slow-suite redesign.

**Verification plan:** MCP hermeticity → run `tests/test_mcp_server.py` and the full non-slow suite with `mcp` installed. CI behavior → statically parse YAML and assert event/path/concurrency/matrix/command contracts with the existing workflow-test pattern or a focused structural test. Runtime/cost → collect duration output and compare required lane shape to the current 3-minute Linux/2-minute smoke baseline; no speculative timing gate. Slow coverage → collect and run `-m slow` under neutral credentials/config, document exact selected/deselected/pass/skip/fail counts, and prove the scheduled command selects only deterministic tests. Governance → `git diff --check`, redline report, Agent Workflow checker, clean-context result review, and green PR CI.

**Plan review:** Pending required clean-context Elevated-risk review.

**Approvals:** Not required at this risk level; user explicitly authorized the proposed round with “ok, let's do this”.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07 Establish Context: reused the clean isolated worktree on branch `codex/test-health-and-ci-cost`; the active root checkout and its unrelated uncommitted hook work remain untouched.
- 2026-09-07 Discover: measured current collection and recent CI lanes, profiled the MCP-enabled default suite, identified four stale scope-less MCP status tests hidden by the missing optional extra, confirmed overlapping full Windows main jobs, and found the nightly workflow excludes all 170 slow tests.
- 2026-09-07 Assess Risk: clean-context redline review classified the intended diff GRAY because `.github/workflows/ci.yml` is unclassified/operational; tests, docs, roadmap, and Work Record are blue; no checkpoint or boundary risk.

## Evidence

Pre-edit baseline: 4,592 selected / 170 slow-deselected tests; local MCP-enabled default profile `4 failed, 4554 passed, 32 skipped, 2 xfailed in 217.17s`. Recent successful main-job medians: Linux 3.0 minutes, Windows smoke 2.0 minutes, Windows full 19.9 minutes per version; observed full-Windows maximum 53.0 minutes.

## Result review

Pending.