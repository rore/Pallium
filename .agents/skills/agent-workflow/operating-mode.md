# operating-mode

For an in-scope change task when `agent-workflow.yaml` exists.

## Vocabulary

| Term | Meaning |
|---|---|
| **Work Record** | Marker-bounded task record. |
| **Slug** | Persisted task identifier, or the branch-derived fallback. |
| **Compact shape** | Fast-path Work Record for `(Routine, Simple)` tasks. SPEC §7. |
| **Expanded shape** | Full §9.4 Work Record. Required for any classification other than `(Routine, Simple)`. |
| **Risk** | `Routine`, `Elevated`, `High`. Determines approvals, reviews, verification. |
| **Complexity** | `Simple`, `Moderate`, `Large`. Determines planning depth and recovery requirements. |
| **Checkpoint** | A workflow gate: Establish Context, Discover, Assess Risk, Plan/Review, Implement, Verify, Review the Result. |

## The loop

```
0. Apply request scope before config; return for standalone read-only analysis.
1. Read agent-workflow.yaml.
2. Use the supplied Work Record identity, or derive the slug from the branch.
3. Classify, then read or initialise the Work Record.
4. At each checkpoint, write then act.
5. Update State at transitions.
6. Update Implementation prose at checkpoint boundaries.
7. On stop or handoff: leave recovery state explicit.
```

At pickup, pause, resume, handoff, and completion, if an applicable canonical roadmap item exists, carry its exact reference and reconcile or report task progress under that roadmap's rules; respect its designated owner/checkout and preserve broader unfinished scope.

## Source-item lifecycle

Keep exact source IDs/links in prose; maintain Relationships per [capture rules](templates/checkpoints/establish-context.md#relationships).

|When|Action|
|---|---|
|Pickup/resume/leaving|Optional Pallium association: follow installed `pallium-memory` attach/detach guidance; never duplicate/remove hook-owned branch/Work Record refs.|
|PR creation|Link PR from source item under tracker rules.|
|Verified merge|Record delivered contribution/remaining scope; don't infer whole-feature completion from one PR.|
|Owner-managed tracker/checkout|Hand owner item/PR/contribution/remaining scope; keep update pending in Work Record until confirmed.|
|Missing tracker/Pallium/tools/identity|Don't block work or invent refs.|

## Step 1 — Read the config

Open `agent-workflow.yaml` and read:

- `workRecord.backend` — `local` (supported) or `jira` (not yet — stop).
- `workRecord.local.taskPath` — the per-task path template.
- applicability.documentationOnly, when present — load [`applicability.md`](templates/checkpoints/applicability.md); if exempt, return without a Work Record.
- `behaviorContracts` in `agent-redline-policy.yaml`, when present — load [`behavioral-integrity.md`](templates/checkpoints/behavioral-integrity.md).

## Step 2 — Resolve the identity

When given `agent-workflow:<slug>`, invoke `python <trusted-install>/scripts/agent-workflow-check.py --repo-root <checkout> --resolve-work-record --work-record-ref agent-workflow:<slug>`. Use the supplied identity verbatim; never compare or fall back to the branch, and never create a competing record.

Otherwise run `git rev-parse --abbrev-ref HEAD`, strip the first matching prefix from `slice/`, `feat/`, `feature/`, `fix/`, `bug/`, `chore/`, `demo/`, then replace remaining `/` with `-`. On a long-lived branch, stop unless it is the default and applicability passed.

## Step 3 — Classify, then read or initialise the Work Record

Read [`templates/checkpoints/assess-risk.md`](templates/checkpoints/assess-risk.md) before writing: Redline sets the Risk floor; Complexity is independent.

| `(Risk, Complexity)` | Shape |
|---|---|
| `(Routine, Simple)` | Compact — fewer fields. Template: [`templates/work-record-routine.md`](templates/work-record-routine.md). |
| Anything else | Expanded — full §9.4 field set. Template: [`templates/work-record-expanded.md`](templates/work-record-expanded.md). |

Resolve `taskPath` with the slug. If it exists, parse it. On updates, verify the owning task/PR's live delivery state before migrating its record; preserve completed history and leave unknown status unresolved. On takeover/resume, confirm next action, constraints, and verification from the record, repo, and authoritative links; repair gaps before acting. If absent, copy the matching template. On parse failure, restore every field.

Surrounding prose holds Implementation, Evidence, and Result-review references.

## Step 4 — Walk the checkpoints

Write each field first, then act on it. Only when planning fields are populated may you begin implementation.

| Field(s) on compact | Field(s) on expanded | Checkpoint | Reference |
|---|---|---|---|
| Outcome, Target, Scope, Constraints, Completion criteria, Requirement baseline | same | Establish Task Context | [`establish-context.md`](templates/checkpoints/establish-context.md) |
| (implicit) | Discovery | Discover | [`discover.md`](templates/checkpoints/discover.md) |
| Risk, Complexity, Reason | same | Assess Risk and Complexity | [`assess-risk.md`](templates/checkpoints/assess-risk.md) |
| Approach, Verification | Plan, Verification plan, Plan review, Approvals | Plan and Review | [`plan-and-review.md`](templates/checkpoints/plan-and-review.md) |
| (act on the plan) | (act on the plan) | Implement | [`implement.md`](templates/checkpoints/implement.md) |
| Verification | Verification plan | Verify | [`verify.md`](templates/checkpoints/verify.md) |
| (PR review) | (PR review) | Review the Result | [`review-result.md`](templates/checkpoints/review-result.md) |

If you re-classify mid-task, update Risk/Complexity and migrate the record's shape if needed. The checker blocks any record whose shape contradicts its classification.

## Step 5 — Update State at every transition

Allowed values:

- `Ready to implement` — planning fields written, coding not begun.
- `Blocked` (or `Blocked or returned to planning`) — stopped on assumption failure, scope question, or external blocker named in the Work Record.
- `Ready for review` — implementation done, verification ran, evidence reference is in surrounding prose.

Update as soon as the transition happens; don't batch at the end. A killed session that left State stale misleads the next agent.

## Step 6 — Update Implementation prose at every checkpoint transition

Update at every phase boundary:

- After Discover: name what you found that Outcome / Scope didn't anticipate.
- After Assess-Risk: if classification surprised you, note why.
- After Plan-and-Review (Elevated/High): the Plan + Plan-review fields ARE the update.
- During Implement: one-line entry per phase boundary in roughly chronological order. **Don't wait until the task is done.**
- At Verify: list actual checks and their results. Not a recap of the plan.

`workrecord.commit_order` advises when the first Work Record commit follows the first code commit; check recovery state.

## Delegating to subagents

Outcome-affecting subagents inherit this Work Record. Supply:

1. Path to the Work Record (don't paraphrase; point at the file).
2. Required updates (Implementation prose, Evidence, State).
3. Allowed and excluded scope.
4. Read-only (report, no edits) or material (update the record).
5. Exact target checkout; use explicit shell workdir or absolute write targets. Relative `apply_patch` targets the session cwd, not a prose-assigned checkout.

Check the finished subagent's record; repair missing updates before declaring the step done.

### Clean-context delegation

Elevated/High plan and result reviews require a clean-context non-implementer agent; High human reviews add to, never replace, these. Pre-edit risk classification uses deterministic Redline rules and judgment directly when clear; use a separate classifier only for material uncertainty.

With a Task/Agent primitive, spawn a read-only agent with the Work Record path, SPEC reference, and relevant source paths; do not paraphrase the record. Otherwise use a fresh session with the same references. Put plan-review prose under a Plan review heading and reference it in the marker field; record result evidence under ## Result review.

Choose the least costly capable reviewer; preserve independent/human/specialist requirements and user-selected settings.

Reuse completed technical plan/result reviews for unchanged application, including local installation: verify reviewed change identity/revision and destination compatibility with its assumptions/risk. Cite source review and revision, not a new review. Review only materially uncovered behavior, scope, assumptions, approach, or risk; don't restart a broad cycle for covered material. Reuse waives neither applicability/Work Records, destination verification, human review/approval, nor runtime trust.
## Step 7 — Resolve review threads before merge

CI green is not "ready to merge." Before invoking the merge:

- Read the PR's inline review threads: `gh api repos/{owner}/{repo}/pulls/{N}/comments` (line-level threads, where bot findings live) and `gh pr view <N> --json reviews,reviewThreads` (review summaries + thread state). Top-level PR comments via `gh pr view --json comments` are separate.
- Reply to each thread that names a finding — either with the fix's commit hash, or a one-line rationale for declining. Use `gh api repos/{owner}/{repo}/pulls/{N}/comments/{comment_id}/replies` to reply inline.
- Resolve the thread via GraphQL: `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "..."}) { thread { isResolved } } }'`. The thread ID comes from `reviewThreads` in the earlier `gh pr view` call.
- Only then merge.

The repo SHOULD enable GitHub's `required_conversation_resolution` branch-protection rule so the platform refuses merge while threads are open. Bootstrap proposes it; the harness assumes it.

## Step 8 — Stop and handoff

When coordinating a handoff, forward a received approval immediately; do not leave a task `Blocked` solely awaiting that approval.

Before ending a session, even if the task is not done:

- Update State to the correct value (most often `Blocked` with one-line reason, or leave `Ready to implement` if you haven't started).
- In surrounding prose, note: current branch, last good revision (`git rev-parse HEAD` when working tree is clean), what's unfinished, what the next agent should do first.
- Carry the exact source-item identity, Work Record identity, and resolved repository-relative path when known.
- Commit the Work Record update. Uncommitted state buys nothing if the session crashes.

## CI predicates surfaced at PR time

`workrecord.exists`, `workrecord.markers_present`, `risk.declared`, `complexity.declared`, `workrecord.shape_matches_classification`, `workrecord.routine_fields_present` (compact) / `workrecord.expanded_fields_present` (expanded), `workrecord.state_valid`.
