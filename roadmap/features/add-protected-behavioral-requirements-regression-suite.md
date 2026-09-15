---
id: add-protected-behavioral-requirements-regression-suite
title: Protected behavioral requirements regression suite
status: queued
priority: high
commitment: committed
milestone: engineering-health
lane: test-infrastructure
---

## Summary

Protect Pallium's accepted, externally observable product requirements independently
from the implementation tests that currently demonstrate them. Agents may refactor
or replace implementation tests, but may not remove, skip, weaken, or silently
substitute protected behavior or acceptance criteria without an explicit,
versioned, human-approved requirement change.

## Why

Implementation tests can stay green after a product requirement is downgraded or
relabelled. The durable contract must say what users can observe; tests are evidence
for that contract, not authority to redefine it.

## In Scope

- derive a concise protected-requirements catalog from already accepted Pallium
  behavior, without freezing known bugs or implementation details
- map every protected requirement to public-surface tests and its original failure
  reproductions
- compare protected mappings and checks with a trusted base in CI, including
  changes to the protecting gate and manifest themselves
- detect deleted, skipped, weakened, or replaced checks; route semantic weakening
  to explicit human approval because automation cannot prove behavioral equivalence
- require replacement coverage to preserve the prior requirement and still fail on
  the original bug
- exercise real caller-visible surfaces and observable outcomes; fixture or prompt
  relabelling cannot convert a valid failure into a pass

## Initial Protected Requirements

1. Relay wakes loaded-idle and unloaded eligible recipients automatically, without
   a manual user prompt; queue-only next-turn fallback cannot replace unloaded wake.
2. Busy recipients are never preempted or steered; Relay work runs as a distinct
   following turn.
3. With the service cwd in a different repository, wake preserves the target cwd,
   worktree, container scope, model, reasoning effort, permissions, hooks, and MCP
   behavior—the original PR #167 failure class.
4. Observable delivery is exactly once across retries, uncertainty, interruption,
   and recovery.
5. Failures remain loss-safe and diagnosable with durable, sanitized evidence.

## Out of Scope

- implementing the suite, manifest, CI gate, or new runtime behavior in this item
- protecting every test, fixture wording, internal call sequence, or current bug
- treating renamed prompts or queue acceptance as proof of required end behavior
- allowing an agent or automated equivalence check to approve weaker requirements

## Done When

1. A versioned protected-requirements manifest is distinct from implementation
   tests and maps each requirement to real public-surface evidence.
2. The joint automatic-wake and workspace/settings-safety regressions fail on the
   original defects and pass only when both behaviors hold together.
3. CI blocks deletion, skipping, weakening, or non-equivalent replacement of a
   protected check, and the gate/manifest cannot weaken their own protection.
4. Requirement evolution is explicit, versioned, and human-approved, with the
   prior requirement and rationale retained.

## Notes

Sequence immediately after urgent wake reliability. Expand from accepted product
behavior only when its external contract and original failure are known; do not
turn this into a frozen inventory of implementation tests.
