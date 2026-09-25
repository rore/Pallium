---
id: select-tests-by-change-scope
title: Select validation by change scope
status: in-progress
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

Lead-owned roadmap checkout: C:/Dev/rore/Pallium/.worktrees/select-tests-by-change-scope. Work Record: `.agent-workflow/tasks/select-tests-by-change-scope.md`. Existing `stabilize-test-health-and-ci-cost` remains a completed, narrower slice. This change does not claim regression elimination or repair unrelated red CI.

## Verified implementation
PR #248 contains the implementation and is awaiting merge. Local focused lane: 14 passed in 30.90 seconds; full non-slow suite: 5323 passed, 34 skipped, 2 xfailed in 319.18 seconds. The actual 26-path Agent Workflow update in PR #247 selects governance. Independent review findings were addressed. The roadmap stays in progress until merge; broader application-subsystem selection remains out of scope.
