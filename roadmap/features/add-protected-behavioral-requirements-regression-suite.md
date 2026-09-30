---
id: add-protected-behavioral-requirements-regression-suite
title: Protected behavioral requirements regression suite
status: done
priority: high
commitment: committed
milestone: engineering-health
lane: test-infrastructure
---

## Summary

Protect Pallium's accepted, externally observable requirements with a dedicated
`tests/behavior_contracts/**` suite and Agent Workflow's workflow-protected behavior
contracts. Agents may refactor ordinary implementation tests, but edits to the
protected suite must be classified and linked to PR verification; exact task-owner
approval is required only for a `requirement-change`. GitHub does not block merges.

## Why

Implementation tests can stay green after a product requirement is downgraded or
relabelled. The durable contract must say what users can observe; tests are evidence
for that contract, not authority to redefine it.

## Contract Layout

Keep the authoritative surface small:

- `tests/behavior_contracts/README.md` states qualification, organization, and
  collection rules; it does not duplicate a growing per-test inventory.
- `tests/behavior_contracts/test_*.py` contains dedicated black-box regressions and
  contract-local fixtures. Each test keeps its accepted source and failure class
  in its docstring, beside the public-surface assertion. Do not protect today's
  broad mixed-purpose test files.
- existing PR job `test` runs all of `tests/`, including this directory, and is the
  named verification. It is intentionally not a branch-required status.
- the combined Redline/Agent Workflow harness runs on every PR and checks protected
  path classification, approval evidence when applicable, and verification linkage.
- one later `behaviorContracts` block in `agent-redline-policy.yaml` protects the
  directory with `protection: workflow`, `verification: test`, and no checkpoint.

No custom manifest schema, parser, semantic-equivalence heuristic, separate CI job,
or second gate is needed. The existing test job proves the regressions run. Redline
makes protected-path edits red. Agent Workflow requires per-path classification and
verification linkage. Humans decide whether an `equivalent` or `coverage-only` claim
is honest. Workflow protection records task-owner approval but does not authenticate
repository authority or prevent a manual merge.

## Which Tests Qualify

Promote a behavior only when every condition holds:

1. It is an accepted, externally observable product obligation, not an internal call
   sequence, helper contract, or current implementation detail.
2. It has an authoritative source and a concrete original failure or regression class.
3. Its test drives the caller-visible HTTP, MCP, or hook surface and asserts state or
   output through the corresponding public read path.
4. The test has a regression witness: it fails on the original bad revision or on the
   smallest controlled reintroduction/fault that reproduces that failure class.
5. It is deterministic and bounded enough to run on every PR.
6. It runs under the named PR verification `test`; if that job stops covering the
   protected path, fix verification before changing the policy.

Reject or defer unit/helper tests, broad files containing unrelated cases, manual or
flaky live checks, tests with no traceable requirement/failure, and tests that can pass
through fixture or prompt relabelling without the required end behavior.

Selection is requirements-first: identify an accepted behavior and original failure,
find the strongest existing evidence, write or extract one dedicated public-surface
regression under the protected directory, prove the regression witness, then ask the
task owner to select or reject it. Existing tests are evidence sources; they are not
protected automatically.

## Initial Protected Requirements

1. Relay wakes supported loaded-idle recipients automatically; unloaded Codex tasks
   retain pending deliveries for a later ordinary turn and are not a current
   protected automatic-wake requirement.
2. Busy recipients are never preempted or steered; Relay work runs as a distinct
   following turn.
3. With the service cwd in a different repository, wake preserves the target cwd,
   worktree, container scope, model, reasoning effort, permissions, hooks, and MCP
   behavior—the original PR #167 failure class.
4. Observable delivery is exactly once across retries, uncertainty, interruption,
   and recovery.
5. Failures remain loss-safe and diagnosable with durable, sanitized evidence.

These are candidates, not automatically accepted contract files. Each must pass the
qualification rule independently. The first accepted protected contract is the narrower
RW-022 busy Codex single-flight behavior, added with a verified fault witness
in PR #242. The task owner selected it on 2026-09-24. Further accepted
behaviors enter only after they independently meet the qualification rule.

## Activation Sequence

1. In a dedicated contract-test PR, select accepted candidates, add dedicated
   public-surface regressions with test-local provenance, and prove each
   original-failure or controlled-fault witness.
2. Confirm existing CI job `test` still runs the protected directory on PRs and the
   combined Redline/Agent Workflow harness runs on PRs. These checks may fail visibly,
   but no branch-required status or GitHub merge block is claimed.
3. In a separate reviewed policy PR, activate the accepted directory:

   ```yaml
   behaviorContracts:
     protection: workflow
     paths:
       - "tests/behavior_contracts/**"
     verification: test
   ```

   Do not add a behavior checkpoint, CODEOWNERS, or branch protection.
4. Thereafter, every protected-path edit records `equivalent`, `coverage-only`, or
   `requirement-change` in the Work Record. Only a requirement change needs exact
   task-owner/user approval bound to its before and after values.

## Out of Scope

- enabling `behaviorContracts` or adding contract tests in the current Agent Workflow
  consumer-sync task
- adding CODEOWNERS, branch protection, a required status, or a dedicated CI job
- protecting every test, fixture wording, internal call sequence, or current bug
- protecting broad existing files merely because they contain one valuable regression
- automated judgment of semantic equivalence or test adequacy
- treating renamed prompts, queue acceptance, or internal calls as proof of required
  end behavior

## Done When

1. The dedicated directory contains selection rules and selected public-surface
   regressions with test-local provenance, each with a verified historical or
   controlled-fault failure witness.
2. Existing CI job `test` and the combined Redline/Agent Workflow harness execute on
   PRs, and affected Work Records link the `test` verification identifier. Neither job
   is claimed as branch-required or merge-enforced.
3. A separate reviewed policy change activates `tests/behavior_contracts/**` with
   `protection: workflow` and `verification: test`, without a behavior checkpoint.
4. Regression failures are visible in CI; deletion or mutation is red and requires
   semantic classification; requirement changes require exact task-owner approval;
   humans judge whether replacement coverage preserves the contract.

## Notes

Sequence immediately after urgent wake reliability. Expand only from accepted product
behavior whose external contract and failure class are known. The first slice
protected RW-022; later slices grow by distinct, independently verified
requirements without a hand-maintained catalog.
