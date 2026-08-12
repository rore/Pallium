# operating-mode

Active when `agent-workflow.yaml` exists at the repo root. Walks one engineering task from pickup to handoff. Supports compact (routine fast path) and expanded shapes.

## Vocabulary

| Term | Meaning |
|---|---|
| **Work Record** | One file per task, marker-bounded, holding structured state. Location configured by `agent-workflow.yaml`'s `workRecord.local.taskPath` (e.g. `.agent-workflow/tasks/{slug}.md`). |
| **Slug** | Task identifier substituted into the taskPath template. Derived from the branch name. |
| **Compact shape** | Fast-path Work Record for `(Routine, Simple)` tasks. SPEC §7. |
| **Expanded shape** | Full §9.4 Work Record. Required for any classification other than `(Routine, Simple)`. |
| **Risk** | `Routine`, `Elevated`, `High`. Determines approvals, reviews, verification. |
| **Complexity** | `Simple`, `Moderate`, `Large`. Determines planning depth and recovery requirements. |
| **Checkpoint** | A workflow gate: Establish Context, Discover, Assess Risk, Plan/Review, Implement, Verify, Review the Result. |

## The loop

```
1. Read agent-workflow.yaml.
2. Derive the slug from the current branch.
3. Classify (Risk + Complexity) and read or initialise the Work Record.
4. For each checkpoint: write the field, then act.
5. Update the State at every transition.
6. Update Implementation prose at every checkpoint boundary.
7. On stop or handoff: leave recovery state explicit.
```

## Step 1 — Read the config

Open `agent-workflow.yaml`. You need two facts:

- `workRecord.backend` — `local` (supported) or `jira` (not yet — stop and tell the developer).
- `workRecord.local.taskPath` — the per-task file path template, e.g. `.agent-workflow/tasks/{slug}.md`.

Anything else in the file is for later work items; do not act on it.

## Step 2 — Derive the slug

```bash
git rev-parse --abbrev-ref HEAD
```

Strip the first matching prefix from `slice/`, `feat/`, `feature/`, `fix/`, `bug/`, `chore/`, `demo/`. Replace any remaining `/` with `-`. Result is the slug.

On `main` (or any long-lived branch), stop. Operating mode runs on task branches.

## Step 3 — Classify, then read or initialise the Work Record

Decide classification before writing the file. Read [`templates/checkpoints/assess-risk.md`](templates/checkpoints/assess-risk.md) NOW — it carries the redline-verdict-to-Risk translation table and the engineering-judgment escape. The summary:

- **Risk** — `Routine` / `Elevated` / `High`. Derived from redline's pre-edit classification of the intended scope; may be raised by judgment, not lowered.
- **Complexity** — `Simple` / `Moderate` / `Large`.

| `(Risk, Complexity)` | Shape |
|---|---|
| `(Routine, Simple)` | Compact — fewer fields. Template: [`templates/work-record-routine.md`](templates/work-record-routine.md). |
| Anything else | Expanded — full §9.4 field set. Template: [`templates/work-record-expanded.md`](templates/work-record-expanded.md). |

Substitute the slug into the configured `taskPath`. If the file exists, parse it and pick up from its State. Otherwise copy from the matching template and fill in. On parse failure, repair the full template field set — markers alone aren't enough.

Surrounding prose above/below the marker block is free-form — Implementation, Evidence, and Result-review references live there.

## Step 4 — Walk the checkpoints

Write each field first, then act on it. Only when planning fields are populated may you begin implementation.

| Field(s) on compact | Field(s) on expanded | Checkpoint | Reference |
|---|---|---|---|
| Outcome, Target, Scope, Constraints, Completion criteria | same | Establish Task Context | [`establish-context.md`](templates/checkpoints/establish-context.md) |
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

The State field is one signal. The **Implementation prose** under the marker block is the other — and the more important one for recovery. The next agent reads the prose to understand what happened between Plan and Verify.

Update at every phase boundary:

- After Discover: name what you found that Outcome / Scope didn't anticipate.
- After Assess-Risk: if classification surprised you, note why.
- After Plan-and-Review (Elevated/High): the Plan + Plan-review fields ARE the update.
- During Implement: one-line entry per phase boundary in roughly chronological order. **Don't wait until the task is done.**
- At Verify: list actual checks and their results. Not a recap of the plan.

The `workrecord.commit_order` advisory predicate fires when the Work Record's first commit on a branch lands *after* the first code commit on the same branch — i.e., retroactive. Non-blocking; treat it as a signal to check whether recovery state was sacrificed.

## Delegating to subagents

When you spin off a subagent that affects the Work Record's outcome (writing code, running tests that decide pass/fail), the **subagent inherits this task's Work Record**. In the subagent's prompt include:

1. Path to the Work Record (don't paraphrase; point at the file).
2. What the subagent should update on completion (Implementation prose, Evidence, State).
3. The scope boundary (parts of Scope it may touch; parts it may not).
4. Read-only vs material (read-only subagents report and don't update the record; material subagents update it).

When the subagent finishes, sanity-check the Work Record. If the subagent updated it, the record reflects the work done; if not, you update before declaring the step done.

### Clean-context delegation

Some checkpoints (Elevated Plan review, High-risk approval prep, pre-edit Risk classification when redline isn't pre-integrated) require a **clean-context subagent** — one with no context from the current planning conversation. Canonical mechanism:

- **In Claude Code / harnesses with a Task/Agent primitive:** spawn a subagent (e.g., `Task` tool, `subagent_type: "Explore"` for read-only review, or a custom agent type). Pass the Work Record path + relevant source paths + SPEC reference + the question. Do not paraphrase the Work Record into the prompt — point at the file so the subagent reads it fresh.
- **In harnesses without a subagent primitive:** open a fresh session and provide the same inputs (Work Record file, SPEC reference, source links). The fresh session IS the clean context.

The subagent's review prose lands under a `## Plan review` heading in the Work Record. The marker-block `Plan review:` field references that section (or the session id).

## Step 7 — Resolve review threads before merge

CI green is not "ready to merge." Before invoking the merge:

- Read the PR's inline review threads: `gh api repos/{owner}/{repo}/pulls/{N}/comments` (line-level threads, where bot findings live) and `gh pr view <N> --json reviews,reviewThreads` (review summaries + thread state). Top-level PR comments via `gh pr view --json comments` are separate.
- Reply to each thread that names a finding — either with the fix's commit hash, or a one-line rationale for declining. Use `gh api repos/{owner}/{repo}/pulls/{N}/comments/{comment_id}/replies` to reply inline.
- Resolve the thread via GraphQL: `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "..."}) { thread { isResolved } } }'`. The thread ID comes from `reviewThreads` in the earlier `gh pr view` call.
- Only then merge.

The repo SHOULD enable GitHub's `required_conversation_resolution` branch-protection rule so the platform refuses merge while threads are open. Bootstrap proposes it; the harness assumes it.

## Step 8 — Stop and handoff

Before ending a session, even if the task is not done:

- Update State to the correct value (most often `Blocked` with one-line reason, or leave `Ready to implement` if you haven't started).
- In surrounding prose, note: current branch, last good revision (`git rev-parse HEAD` when working tree is clean), what's unfinished, what the next agent should do first.
- Commit the Work Record update. Uncommitted state buys nothing if the session crashes.

## CI predicates surfaced at PR time

`workrecord.exists`, `workrecord.markers_present`, `risk.declared`, `complexity.declared`, `workrecord.shape_matches_classification`, `workrecord.routine_fields_present` (compact) / `workrecord.expanded_fields_present` (expanded), `workrecord.state_valid`.

A failing predicate names the cause in its detail. Fix the marker block, push again — the sticky verdict comment refreshes on the next CI run. The harness does not judge whether the prose is right, only whether the structure is well-formed.
