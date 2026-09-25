# review-result

## What the harness enforces

**`review.checkpoints_satisfied`** reports Redline's PR-label/CODEOWNER checkpoint state, blocking in binding mode and advisory in shadow mode. It supplies human attention, not agent technical review (SPEC §13.4).


## What stays reviewer judgment (SPEC §9.7)

The reviewer of Elevated and High work MUST also assess:

- whether completion criteria are satisfied
- whether the recorded Verification Record is **adequate** (the harness validates presence and structural well-formedness, not adequacy)
- whether evidence is sufficient
- whether scope expanded unintentionally
- whether assumptions remain unresolved
- whether the final diff changes the risk classification

When the repository already uses a roadmap and this work affects a tracked item's progress or scope, reconcile the owning item under that roadmap's guidance: status, shipped scope, remaining scope, obsolete next steps, placement, and directly affected prerequisites. State the result briefly in existing prose; no roadmap edit is needed when already accurate. Skip when no roadmap/item applies.

Review identity: Routine may use normal PR review. Elevated/High require a clean-context non-implementer agent technical review; High also requires separate human result review. In `## Result review`, record `Agent technical review: <source ref>`, `Reviewed revision: <rev>`, and `Verification adequacy: <assessment>`, with inspected evidence, findings, and limits. Human review/approval/labels add to, never replace, the agent review. Different model optional.

If evidence is insufficient, run or request the smallest behavioral check that resolves it; prefer the relevant end-to-end transition to rerunning a passing suite. Record authoritative result references; if unavailable, leave the gate unsatisfied.

Ready for review is not merged or released; verify delivery state in its owning system.

## Satisfy-by paths in practice

**CODEOWNER approval.** With "Require Code Owner review" enabled, GitHub enforces owning-team approval. CI passes Redline the APPROVED reviewers that intersect `CODEOWNERS`.

Without `CODEOWNERS`, CI warns and passes no approvers, so codeowner-only checkpoints remain unsatisfied.

**Label satisfaction.** Some checkpoints accept a named label (`label: api-reviewed`). A maintainer applying the label asserts the review happened. Lower friction; suitable when review-by-anyone is acceptable. Redline's policy decides which path a checkpoint accepts.

## Relationship to plan-time approvals

Plan-time approvals (Approvals field, clean-context Plan review reference) are recorded in the Work Record BEFORE implementation. Result-review checkpoint satisfaction happens on the PR AFTER implementation. Structurally distinct:

- **Plan-time** (slice D): agent-attested plan approval in the Work Record. Cheating window acknowledged.
- **PR-time** (slice G): GitHub + CODEOWNERS evaluate; Redline surfaces; checker blocks only in binding mode.

High work has agent technical plan/result reviews, human-reviewed and approved plan, separate human result review, and any triggered PR checkpoint. These are distinct.

## Skill feedback check

Before marking `Ready for review`, load [`../skill-feedback.md`](../skill-feedback.md) if this task exposed any of these: repeated workaround, human correction, failed instruction/documented behavior, contradiction, broken reference, unmapped error/gate, or consequential guess from missing guidance. That guide owns the detailed triggers, filters, and safe submission steps. Otherwise, done.
