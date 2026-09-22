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

Protect Pallium's accepted, externally observable requirements with a dedicated
`tests/behavior_contracts/**` suite and Agent Workflow's repository behavior
contracts. Agents may refactor ordinary implementation tests, but changes to the
protected suite must be classified, reviewed by its Code Owner, and exercised by
required CI.

## Why

Implementation tests can stay green after a product requirement is downgraded or
relabelled. The durable contract must say what users can observe; tests are evidence
for that contract, not authority to redefine it.

## Contract Layout

Keep the authoritative surface small:

- `tests/behavior_contracts/README.md` is a plain Markdown catalog. Each entry names
  the accepted behavior, authoritative source, original failure class, protected
  test, public surface, and observable outcome.
- `tests/behavior_contracts/test_*.py` contains dedicated black-box regressions and
  contract-local fixtures. Do not protect today's broad mixed-purpose test files.
- the required `behavior-contracts` CI check runs this directory exactly.
- one `behaviorContracts` block in `agent-redline-policy.yaml` protects the directory,
  names that check, and routes edits through a CODEOWNER-only `behavior-review`
  checkpoint.

No custom manifest schema, parser, semantic-equivalence heuristic, or second gate is
needed. Required CI proves the tests ran. Redline protects path mutations and requires
classification/linkage. Base-branch CODEOWNERS plus required Code Owner review
establish repository authority. Humans decide whether an `equivalent` or
`coverage-only` claim is honest.

## Which Tests Qualify

Promote a behavior only when every condition holds:

1. It is an accepted, externally observable product obligation, not an internal call
   sequence, helper contract, or current implementation detail.
2. It has an authoritative source and a concrete original failure or regression class.
3. Its test drives the caller-visible HTTP, MCP, or hook surface and asserts state or
   output through the corresponding public read path.
4. The test has a regression witness: it fails on the original bad revision or on the
   smallest controlled reintroduction/fault that reproduces that failure class.
5. It is deterministic and bounded enough to run on every required CI execution.
6. It shares the protected set's required check and last-match CODEOWNERS authority.

Reject or defer unit/helper tests, broad files containing unrelated cases, manual or
flaky live checks, tests with no traceable requirement/failure, and tests that can pass
through fixture or prompt relabelling without the required end behavior.

Selection is requirements-first: identify an accepted behavior and original failure,
find the strongest existing evidence, write or extract one dedicated public-surface
regression under the protected directory, prove the regression witness, then ask the
human owner to select or reject it. Existing tests are evidence sources; they are not
protected automatically.

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

These are candidates, not automatically accepted contract files. Each must pass the
qualification rule independently.

## Activation Sequence

1. In an explicitly authorized governance/CI PR, add path-covering CODEOWNERS, the
   dedicated `behavior-contracts` job, base-revision CODEOWNERS evidence plumbing in
   Agent Workflow CI, and the contract tests/catalog. Preserve Pallium's import-linter
   customization.
2. After merge, enable and live-verify branch protection/rulesets requiring both the
   `behavior-contracts` status and Code Owner review. Pallium currently has no
   CODEOWNERS, branch protection, or rulesets, so activation is blocked until this is
   true on the base branch.
3. In a later reviewed policy PR, add the `behaviorContracts` block and dedicated
   `behavior-review` checkpoint. Stop if candidates do not share one required check
   and identical last-match owner tokens; split or defer them instead.
4. Thereafter, every protected-path edit records `equivalent`, `coverage-only`, or
   `requirement-change` in the Work Record. Requirement changes need exact repository
   authority approval; passing tests do not substitute for that decision.

## Out of Scope

- enabling `behaviorContracts`, editing CI/CODEOWNERS, or adding contract tests in the
  current Agent Workflow consumer-sync task
- protecting every test, fixture wording, internal call sequence, or current bug
- protecting broad existing files merely because they contain one valuable regression
- automated judgment of semantic equivalence or test adequacy
- treating renamed prompts, queue acceptance, or internal calls as proof of required
  end behavior

## Done When

1. The dedicated directory contains the catalog and selected public-surface regressions,
   each with a verified original-failure witness.
2. The `behavior-contracts` check and required Code Owner review are enforced on the
   base branch, and Agent Workflow CI uses base-revision CODEOWNERS evidence.
3. A separate reviewed policy change activates `tests/behavior_contracts/**` with the
   matching verification id and checkpoint.
4. CI fails when protected regressions fail; deletion or mutation is classified and
   routed to the canonical owner; human review decides whether replacement coverage
   preserves the contract or changes the requirement.

## Notes

Sequence immediately after urgent wake reliability. Expand only from accepted product
behavior whose external contract and original failure are known. The first slice should
protect the smallest valuable subset, not all five candidates at once.
