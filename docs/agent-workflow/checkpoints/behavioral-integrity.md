# Behavioral requirement integrity

## Establish

After writing Task Context and before discovery, copy its exact Outcome, Scope, Constraints, and Completion criteria into Requirement baseline as JSON:

    {"source":"work-record-initial","outcome":"...","scope":"...","constraints":"...","completion_criteria":"..."}

Use an authoritative source revision or item reference for source when one exists. Target is not behavioral. Never rewrite the baseline. Commit new records with a valid baseline in their first version. Legacy records already on the base branch without one stay parseable but cannot advance; ask the task owner to establish it from an authoritative source rather than guessing.

## Classify changes

Add Behavior changes only when Task Context or a configured contract changes. It is a JSON array.

| Classification | Use |
|---|---|
| equivalent | Wording or mechanics change; required behavior is identical. |
| coverage-only | More verification of the same obligation; no new product promise. |
| requirement-change | Behavior is weakened, removed, narrowed, deferred, manual, best-effort, otherwise redefined, or materially broadened/strengthened. |

Task entries target task-context.outcome, .scope, .constraints, or .completion_criteria. Record exact before, after, and reason. The checker requires the ordered chain to start at the baseline and end at current Task Context.

Contract entries use target repository-contract plus the exact changed path. One entry covers one path. Equivalent and coverage-only edits still need classification because the path is protected.

A requirement-change entry also includes:

    "impact":"...",
    "alternatives":"...",
    "authority":{"scope":"task|repository","name":"..."},
    "approval":{"by":"...","reference":"...","verbatim":"..."}

Before approval, keep State Blocked and do not update current Task Context or the contract. Task changes require the task owner (scope task, name task-owner, by user). For repository-protected contracts, use scope repository; authority.name and approval.by must equal one canonical CODEOWNERS token Redline reports for that path. For workflow-protected contracts, use scope task, name task-owner, and by user. That workflow evidence is not authenticated repository authority and does not guarantee merge prevention. Agent review, plan approval, and checkpoint routing do not substitute. Approval binds only that entry's exact before/after values.

## Configured contracts

`agent-redline-policy.yaml` owns behaviorContracts paths, protection mode, and PR verification. Repository protection also owns the CODEOWNER-only checkpoint and canonical owner evidence. Workflow protection has neither. Inspect only paths in Redline's versioned behaviorContractChanges detail. Work Record Verification or Verification plan must name its reported verification identifier.

Path protection is mutation integrity, not regression enforcement. Bootstrap requires explicit selection and live PR execution of both the named verification and combined harness. Repository protection additionally requires branch-required status, compatible last-match CODEOWNERS, and required Code Owner review. Workflow protection omits those controls and must be reported as not merge-enforced. The checker validates policy/detail/path agreement, mode-appropriate approval evidence, applicable checkpoint/owner facts, and verification linkage; with PR refs it compares the first committed baseline, but cannot judge semantics, authenticate a person or team, prove a test ran, prevent merge, prove initial accuracy, or detect rewritten branch history.

## Checkpoint actions

- Discover: compare relevant contracts with the request; conflicts block for authority.
- Plan: state preserved, coverage-only, or proposed requirement-change per affected behavior.
- Implement: never accommodate an incomplete implementation by editing Task Context, tests, docs, or contracts.
- Verify: test current Task Context and configured contracts through the named CI surface.
- Review result: compare current context to baseline and every change entry; inspect protected-path edits for misclassification, disabled tests, weaker proxies, or missing behavior.
