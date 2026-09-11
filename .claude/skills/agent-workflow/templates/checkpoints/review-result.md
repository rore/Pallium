# review-result

## What the harness enforces

**`review.checkpoints_satisfied`** (mode-dependent, non-waivable). Reads agent-redline's checkpoint satisfaction state from its verdict JSON. Each red-zone or contract-class change triggers one or more named checkpoints (`api-review`, `persistence-review`, `security-review`, `architecture-review`, …) from `agent-redline-policy.yaml`. Each checkpoint's `satisfiedBy` rules — typically:

- `codeownerApproval` — a CODEOWNER must approve the PR
- `{ label: <name> }` — a maintainer must apply a named PR label

Redline evaluates each triggered checkpoint against the PR's labels + CODEOWNER approvals (OR-semantics across `satisfiedBy` entries) and emits `satisfied: true | false`. The checker surfaces unsatisfied checkpoints; they block in binding mode and remain advisory in shadow mode.

Redline owns matching; the harness surfaces its result separately from human approval (SPEC §13.4).


## What stays reviewer judgment (SPEC §9.7)

The reviewer of Elevated and High work MUST also assess:

- whether completion criteria are satisfied
- whether the recorded Verification Record is **adequate** (the harness validates presence and structural well-formedness, not adequacy)
- whether evidence is sufficient
- whether scope expanded unintentionally
- whether assumptions remain unresolved
- whether the final diff changes the risk classification

When the repository already uses a roadmap and this work affects a tracked item's progress or scope, reconcile the owning item under that roadmap's guidance: status, shipped scope, remaining scope, obsolete next steps, placement, and directly affected prerequisites. State the result briefly in existing prose; no roadmap edit is needed when already accurate. Skip when no roadmap/item applies.

Review identity: Routine may use normal PR review; Elevated requires a non-implementer (human or clean-context agent); High requires a separate human. Different model optional. Agent review cannot replace mandated human approval.

If evidence is insufficient, run or request the smallest behavioral check that resolves it; prefer the relevant end-to-end transition to rerunning a passing suite. Record authoritative result references; if unavailable, leave the gate unsatisfied.

## Satisfy-by paths in practice

**CODEOWNER approval.** With "Require Code Owner review" enabled, GitHub enforces owning-team approval. CI passes Redline the APPROVED reviewers that intersect `CODEOWNERS`.

Without `CODEOWNERS`, CI warns and passes no approvers, so codeowner-only checkpoints remain unsatisfied.

**Label satisfaction.** Some checkpoints accept a named label (`label: api-reviewed`). A maintainer applying the label asserts the review happened. Lower friction; suitable when review-by-anyone is acceptable. Redline's policy decides which path a checkpoint accepts.

## Relationship to plan-time approvals

Plan-time approvals (Approvals field, clean-context Plan review reference) are recorded in the Work Record BEFORE implementation. Result-review checkpoint satisfaction happens on the PR AFTER implementation. Structurally distinct:

- **Plan-time** (slice D): agent-attested plan approval in the Work Record. Cheating window acknowledged.
- **PR-time** (slice G): GitHub + CODEOWNERS evaluate; Redline surfaces; checker blocks only in binding mode.

A High-risk task in default profile mode passes through both: human-approved plan in Approvals + CODEOWNER-approved PR or maintainer-applied review label.

## Skill feedback check

Before marking `Ready for review`, load [`../skill-feedback.md`](../skill-feedback.md) if this task exposed any of these: repeated workaround, human correction, failed instruction/documented behavior, contradiction, broken reference, unmapped error/gate, or consequential guess from missing guidance. That guide owns the detailed triggers, filters, and safe submission steps. Otherwise, done.
