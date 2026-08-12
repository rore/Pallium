# review-result

Closes the workflow. Reviewer evaluates the change against Task Context, plan, Risk/Complexity decision, Verification Record, final diff, and evidence prose. SPEC §9.7 lists the obligations.

## What the harness enforces

**`review.checkpoints_satisfied`** (blocking, non-waivable). Reads agent-redline's checkpoint satisfaction state from its verdict JSON. Each red-zone or contract-class change triggers one or more named checkpoints (`api-review`, `persistence-review`, `security-review`, `architecture-review`, …) from `agent-redline-policy.yaml`. Each checkpoint's `satisfiedBy` rules — typically:

- `codeownerApproval` — a CODEOWNER must approve the PR
- `{ label: <name> }` — a maintainer must apply a named PR label

Redline evaluates each triggered checkpoint against the PR's labels + CODEOWNER approvals (OR-semantics across `satisfiedBy` entries) and emits `satisfied: true | false`. The agent-workflow checker reads that state and **blocks the merge** when any triggered checkpoint is unsatisfied.

The harness does not re-implement redline's matching. Redline owns the rules; we surface the result.

Non-waivable per SPEC §13.4: checkpoint satisfaction MUST remain structurally distinct from human approval.

## What stays reviewer judgment (SPEC §9.7)

The reviewer of Elevated and High work MUST also assess:

- whether completion criteria are satisfied
- whether the recorded Verification Record is **adequate** (the harness validates presence and structural well-formedness, not adequacy)
- whether evidence is sufficient
- whether scope expanded unintentionally
- whether assumptions remain unresolved
- whether the final diff changes the risk classification

Routine work uses normal PR review; the reviewer still judges adequacy.

## Satisfy-by paths in practice

**CODEOWNER approval.** Repo's `CODEOWNERS` maps paths to teams. With "Require Code Owner review" in branch protection, GitHub enforces approvals come from the owning team. The CI template intersects the PR's APPROVED reviewers against this and passes the resulting login list to redline.

When no `CODEOWNERS` exists, CI emits a workflow-log warning and passes an empty approver list. Checkpoints whose only `satisfiedBy` is `codeownerApproval` surface as unsatisfied — that's correct.

**Label satisfaction.** Some checkpoints accept a named label (`label: api-reviewed`). A maintainer applying the label asserts the review happened. Lower friction; suitable when review-by-anyone is acceptable. Redline's policy decides which path a checkpoint accepts.

## Relationship to plan-time approvals

Plan-time approvals (Approvals field, clean-context Plan review reference) are recorded in the Work Record BEFORE implementation. Result-review checkpoint satisfaction happens on the PR AFTER implementation. Structurally distinct:

- **Plan-time** (slice D): agent-attested plan approval in the Work Record. Cheating window acknowledged.
- **PR-time** (slice G): GitHub + CODEOWNERS evaluate; redline surfaces; checker blocks.

A High-risk task in default profile mode passes through both: human-approved plan in Approvals + CODEOWNER-approved PR or maintainer-applied review label.

## Skill feedback check

Before marking `Ready for review`, walk this table.

| Trigger | Y/N |
|---|---|
| 1. Retried a gate ≥2 times for the same predicate. | |
| 2. Reviewer/human corrected me on something the skill should have said. | |
| 3. A skill instruction told me to do something that did not work. | |
| 4. Two skill sections contradicted each other. | |
| 5. A skill cross-reference was broken (file/anchor missing). | |
| 6. A CI predicate fired with a detail I could not map back to a skill instruction. | |
| 7. The skill was silent on a decision I had to make, and I guessed. | |

If any Y, load [`../skill-feedback.md`](../skill-feedback.md). If all N, done.
