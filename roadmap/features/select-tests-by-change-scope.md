---
id: select-tests-by-change-scope
title: Select validation by change scope
status: done
priority: high
commitment: committed
milestone: engineering-health
lane: test-infrastructure
---

## Summary

Make documentation and supported Agent Workflow changes cheap to validate while keeping full regression coverage for application, mixed, or uncertain changes. One conservative selector serves local work and CI.

## Why

The blanket full-suite rule forces governance updates through unrelated application tests. Shared pytest fixtures also import application startup for governance-only tests. The previous test-health work improved timing and test dependencies but did not separate validation by change scope.

## In Scope

- Explicit documentation, governance, and full lanes with no dependency-inference framework.
- Complete Git change evidence, including local dirty/untracked files and both sides of renames.
- Full fallback for unknown paths, missing evidence, selector/CI/shared-configuration changes.
- Focused governance caller-contract checks without application fixtures.
- Existing full Linux, Windows smoke, full Windows push/nightly, and bounded nightly slow coverage.
- Stable CI result that rejects failed or unexpectedly skipped required checks.
- Updated agent instructions and testing documentation.

## Out of Scope

Application behavior changes, pruning regression tests, broad test-suite repairs, database changes, new dependencies, branch protection, and application subsystem selection.

## Done When

1. CLI lifecycle tests prove conservative selection across committed, dirty, untracked, renamed, deleted, mixed, and unknown changes.
2. CI uses trusted base selection; bootstrap or selection errors cannot silently bypass required tests.
3. Governance tests check accepted and rejected caller inputs without importing application fixtures.
4. Full CI remains for application and selector changes; scheduled full and bounded slow checks remain.
5. Documentation matches the delivered commands and limitations; required verification and review are complete.

## Notes

Canonical completion checkout: C:/Dev/rore/Pallium; implementation used isolated worktrees. Work Record: `.agent-workflow/tasks/select-tests-by-change-scope.md`. Existing `stabilize-test-health-and-ci-cost` remains a completed, narrower slice. This change does not claim regression elimination; two test-isolation/synchronization defects discovered during rollout are repaired without changing application behavior.

## Verified implementation
PR #248 merged the test-selection strategy; PR #249 fixed the Windows SQLite URL compatibility issue found during rollout and added the repair E2E file to Windows smoke. Local focused lane: 14 passed in 30.90 seconds; full non-slow suite: 5323 passed, 34 skipped, 2 xfailed in 319.18 seconds. The actual 26-path Agent Workflow update in PR #247 selects governance. Independent review findings were addressed. Broader application-subsystem selection remains out of scope.

## Final validation and delivery
The initial Linux failures were traced to unrelated native-wake diagnostic activity in an ordinary-turn test and an asynchronous restart sweep tested against a one-second deadline. Controlled before/after probes support the two reviewed test-only fixes. Related hook/wake/trace and protected-contract checks: 153 passed, 2 skipped; Codex wake file: 139 passed. Exact delivery, identity, scope and ACK assertions are preserved. Final PR and post-merge CI passed. At merge commit 05b4f138834f10afceae511eb682a28f58b91b93, each Linux version passed 5,301 tests; each full Windows version passed 5,329 tests across its serial and remaining-suite steps; Windows smoke passed 512 tests. Run: https://github.com/rore/Pallium/actions/runs/36152107636. Both clean local clones were synchronized, the installed wrapper restart succeeded, and health/status/queue checks passed with embeddings and ingestion healthy. Follow-up Work Record: `.agent-workflow/tasks/fix-relay-repair-sqlite-urls.md`.
