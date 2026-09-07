---
id: stabilize-test-health-and-ci-cost
title: Stabilize test health and CI cost
status: done
priority: high
commitment: committed
milestone: engineering-health
lane: test-infrastructure
---

## Summary

Restore required MCP test coverage, make test timing visible, cancel superseded runs, avoid redundant docs-only push matrices, and add a bounded nightly slow smoke.

## In Scope

- fix scope setup in the four stale Relay status tests
- install and explicitly import the existing MCP extra in required Linux CI
- report the 20 slowest tests in every pytest CI command
- cancel only superseded runs for the same workflow, event, and ref
- skip push CI only when every changed file is Markdown under `docs/` or `roadmap/`
- run the inspected hermetic slow smoke allowlist nightly and serially

## Out of Scope

- product behavior or public contract changes
- new dependencies or pytest markers
- repairing stale semantic and eval expectations in the complete slow suite
- opt-in service, live-provider, model-download, or generated P2 CI coverage

## Done When

1. The MCP server tests and full default suite pass with MCP installed.
2. Structural tests protect the CI event, dependency, timing, and slow-lane contracts.
3. The explicit nightly slow command passes and workflow/governance checks are clean.
