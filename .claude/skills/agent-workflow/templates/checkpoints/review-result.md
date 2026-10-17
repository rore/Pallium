# review-result

## What the harness enforces

**`review.checkpoints_satisfied`** reports Redline's PR-label/CODEOWNER checkpoint state, blocking in binding mode and advisory in shadow mode. It supplies human attention, not agent technical review (SPEC §13.4).


## What stays reviewer judgment (SPEC §9.7)

The reviewer at every Risk level MUST assess:

- whether completion criteria are satisfied
- whether the recorded Verification Record is **adequate** (the harness validates presence and structural well-formedness, not adequacy)
- whether tests would detect the relevant failure and exercise its triggering path, and fakes reflect the real interface rather than repeat implementation assumptions
- whether evidence is sufficient
- whether scope expanded unintentionally
- whether assumptions remain unresolved
- whether the final diff changes the risk classification

Reassess the overall approach, not only the patch; apply [planning's mechanism/guarantee distinction](plan-and-review.md#approach).

When the repository already uses a roadmap and this work affects a tracked item's progress or scope, reconcile the owning item under that roadmap's guidance: status, shipped scope, remaining scope, obsolete next steps, placement, and directly affected prerequisites. State the result briefly in existing prose; no roadmap edit is needed when already accurate. Skip when no roadmap/item applies. For PR linkage, delivered contribution and owner handoff, follow [Source-item lifecycle](../../operating-mode.md#source-item-lifecycle).

Review identity: Routine may use normal PR review. Elevated/High require a clean-context non-implementer agent technical review; High also requires separate human result review. In `## Result review`, record `Agent technical review: <source ref>`, `Reviewed revision: <rev>`, and `Verification adequacy: <assessment>`, with inspected evidence, findings, and limits. Human review/approval/labels add to, never replace, the agent review. Unchanged-application reuse follows [Clean-context delegation](../../operating-mode.md#clean-context-delegation).

If evidence is insufficient, run or request the smallest behavioral check that resolves it; prefer the relevant end-to-end transition to rerunning a passing suite. Record authoritative result references; if unavailable, leave the gate unsatisfied.

Ready for review is not merged or released; verify delivery state in its owning system.

For agent-instruction changes, distinguish tested/installed behavior from observed real-use adoption; record any agreed bounded follow-up in the existing feature/release record with its owner and evidence.

## Satisfy-by paths in practice

**CODEOWNER approval.** With "Require Code Owner review" enabled, GitHub enforces owning-team approval. CI passes Redline the APPROVED reviewers that intersect `CODEOWNERS`.

Without `CODEOWNERS`, CI warns and passes no approvers, so codeowner-only checkpoints remain unsatisfied.

**Label satisfaction.** Some checkpoints accept a named label (`label: api-reviewed`). A maintainer applying the label asserts the review happened. Lower friction; suitable when review-by-anyone is acceptable. Redline's policy decides which path a checkpoint accepts.

## Relationship to plan-time approvals

Record plan approvals in the Work Record before implementation; satisfy result-review checkpoints on the PR afterward:

- **Plan-time** (slice D): agent-attested plan approval in the Work Record.
- **PR-time** (slice G): GitHub + CODEOWNERS evaluate; Redline surfaces; checker blocks only in binding mode.

High work has agent technical plan/result reviews, human-reviewed and approved plan, separate human result review, and any triggered PR checkpoint. These are distinct.

## Skill feedback check

Before marking `Ready for review`, load [`../skill-feedback.md`](../skill-feedback.md) if this task exposed any of these: repeated workaround, human correction, failed instruction/documented behavior, contradiction, broken reference, unmapped error/gate, or consequential guess from missing guidance. That guide owns the detailed triggers, filters, and safe submission steps. Otherwise, done.
