# Narrow Target — Claude Code Sessions in the Pallium Repo

**Date:** 2026-07-01
**Status:** Draft — v1 target definition for milestone W2
**Owner:** Rotem Hermon
**Parent spec:** [`2026-07-01-milestone-shaped-memory-contract.md`](2026-07-01-milestone-shaped-memory-contract.md)

---

## Why a narrow target

"Generic agent memory across arbitrary containers" has no pass/fail. Every
routing/extraction/lifecycle change we ship gets measured against vibes.
Pallium's own live-feedback data shows a 55% bad proactive-injection rate;
without a target we can't tell whether any given fix moved the number for
a real workflow or moved it in aggregate on a corpus we don't live in.

**One target this milestone: Claude Code sessions on the Pallium repository
itself (this repo, `github.com/rore/pallium`, container_ref
`git:github.com/rore/pallium`).**

Chosen because:

- We use it every day. Regressions surface within hours, not weeks.
- The workflows are concrete: TDD, spec authoring, roadmap grooming,
  investigation, refactoring, dependency management on Windows.
- Existing memory data is dense in this container — no cold-start.
- If it works here, it plausibly works elsewhere. If it doesn't work here,
  broader generalization is premature.

**Non-goal:** proving Pallium works "in general." That's a later milestone,
gated on this one passing.

---

## The seven scenarios (5 positive + 2 negative)

Each scenario has:
- **Setup** — how the canned session is constructed.
- **Trigger turn** — the message where Pallium should (or should not) surface something.
- **Pass condition** — what "correct behavior" looks like, as a deterministic assertion.
- **Fail modes** — the specific failures the assertion is designed to catch.

Every scenario replay under `evals/narrow_target_claude_code/` implements
one of these; each returns `PASS` or `FAIL` with a machine-readable diagnostic.

### Positive scenarios — memory should surface

#### Scenario 1 — Don't repeat a previously-failed command

**Setup.** Session A on branch `test/uv-sync` runs `uv sync` in this repo.
The command fails (Windows ASR blocks `Scripts/python.exe`; see
`~/.claude/python-on-windows.md`). Post-tool-use hook records the failure
via `agent_work_trace_turn`. Session ends.

**Trigger turn.** Session B (new, fresh) in the same repo. User asks the
agent to "set up the Python dependencies." Agent is about to invoke
`uv sync`.

**Pass condition.** Before the agent invokes `uv sync`, Pallium delivers
(via SessionStart or PreToolUse event trigger, whichever fires) a memory
whose content names the prior failure — either as an `operational_fact`
with `failure_count >= 1`, an `investigation_outcome` documenting the
ASR block, or the constraint from `python-on-windows.md`. The specific
type is not the metric; **surfacing on time** is.

**Fail modes caught.**
- Silent re-run of the failing command (memory did not surface).
- Post-facto surfacing after the failure (surface came too late).
- Wrong memory surfaced (e.g., a different unrelated failure).

**Metrics attributed.** Injection-precision for the surfaced memory (if any),
downstream-task-effect for the session outcome.

#### Scenario 2 — Recall the Python-on-Windows constraint

**Setup.** No prior Pallium memory required (the constraint lives in
`~/.claude/CLAUDE.md`); but if a prior investigation memory about the
ASR block exists, it's included.

**Trigger turn.** Fresh session. User says: "Create a new virtualenv for
this project and install pytest into it." Agent is about to run
`python -m venv .venv` or `uv venv`.

**Pass condition.** Before the venv-creation command runs, Pallium (or
the always-loaded `~/.claude/CLAUDE.md` block) makes the constraint
available to the agent, and the agent takes the recommended path
(`uv pip install --target <dir>` targeting a real interpreter, not a
stub launcher).

**Fail modes caught.**
- Agent runs `uv venv` blind → user file gets toast-spammed.
- Constraint memory exists but is not surfaced.
- Constraint memory surfaced but agent ignores it (agent-side bug, but
  scenario logs it).

**Metrics attributed.** Downstream-task-effect (did the agent take the safe
path). Injection-precision if a constraint memory fires.

#### Scenario 3 — Resume an interrupted implementation

**Setup.** Session A works on `feature/foo` for ~30 turns. Mid-implementation,
partial code changes on disk, `task_checkpoint` memory written with prior
state (files edited, tests pending, next intended step). Session ends before
completion.

**Trigger turn.** Session B (new) on the same branch/path. User: "Continue
where you left off."

**Pass condition.** Pallium delivers the `task_checkpoint` on
SessionStart (event trigger `session_start` with branch+path match).
Agent resumes from the checkpoint's `next_intended_step` rather than
re-reading files from scratch.

**Fail modes caught.**
- No checkpoint surfaces → agent starts from scratch.
- Wrong checkpoint surfaces (from a different branch/task).
- Checkpoint surfaces but is stale/superseded and not marked as such.

**Metrics attributed.** Injection-precision. Downstream-task-effect (turns
saved vs baseline resume-from-cold).

#### Scenario 4 — Surface prior investigation when the same error class reappears

**Setup.** Session A hits a specific error (concrete text: e.g. an
`ImportError` for `agent_conversation_memory_routing_annotations`). Agent
investigates, resolves it, writes an `investigation_outcome` memory
naming the root cause and the fix. Session ends.

**Trigger turn.** Session B, weeks later. Agent hits the same error class
(same import failure, or a paraphrase producing the same error signature).
PostToolUse failure event fires.

**Pass condition.** Pallium delivers the prior `investigation_outcome`
via the PostToolUse-failure trigger. Delivery is on-demand
(trigger-based), not proactive — no injection on turns where the error
did not occur.

**Fail modes caught.**
- Proactive injection of the investigation on unrelated turns (violates
  abstention discipline).
- Failure to surface the investigation when the error actually recurs.
- Surfacing a superseded/wrong investigation.

**Metrics attributed.** Injection-precision on the recurring-error turn.
Specificity across all other turns in the session (this investigation
must NOT be injected when the error did not occur).

#### Scenario 5 — Preserve an architectural decision made in-conversation

**Setup.** Session A. User explicitly says: "Let's not use approach X here
because Y" (concrete: e.g., "no LLM-classifier for the abstention gate;
use per-type score thresholds instead"). Agent extraction/consolidation
writes a `decision` memory naming the choice and rationale. Session ends.

**Trigger turn.** Session B. User asks about a related task where approach
X might otherwise be a natural choice.

**Pass condition.** Pallium surfaces the `decision` memory before the
agent proposes an approach. Proactive delivery is acceptable here
(decisions are one of the two types that stay proactive per the
abstention policy) provided the block-score gate is met.

**Fail modes caught.**
- Decision was captured but not surfaced.
- Decision was captured, proactive, but score threshold too tight (missed).
- Decision was captured, proactive, and injected on unrelated turns
  (violates precision).

**Metrics attributed.** Injection-precision, specificity, downstream-task-
effect.

### Negative scenarios — memory should NOT surface

#### Scenario 6 — Prior investigation ruled a hypothesis out; new error is unrelated

**Setup.** Session A investigates hypothesis H (e.g., "the FTS5 join is
slow"). Concludes H is not the root cause; the actual issue was
elsewhere. Writes an `investigation_outcome` memory. That memory
correctly names the ruled-out hypothesis and the actual fix.

**Trigger turn.** Session B hits a superficially-similar error (some FTS5
warning appears in logs) but the root cause is different (say, a
concurrency issue).

**Pass condition.** Pallium may surface the prior investigation
**as context**, tagged so the agent understands it's a ruled-out
hypothesis, but must not inject it as *the* answer, and must not
override or block the agent's own diagnosis. If surfacing at all, only
via a trigger-based path.

**Fail modes caught.**
- Proactive injection of the prior investigation as if it were the
  answer.
- Injection on a turn where the agent had already begun diagnosing
  correctly (interruption failure).
- Surfacing without the "ruled-out hypothesis" framing.

**Metrics attributed.** Specificity + injection-precision.

#### Scenario 7 — Two unrelated prior errors superficially match current query

**Setup.** Container has two `investigation_outcome` memories from
unrelated past errors, both containing the token "timeout" but with
different subjects (one about DB connection timeouts, one about HTTP
retry timeouts). Current query is about a third unrelated topic where
"timeout" appears once.

**Trigger turn.** Fresh query with mild "timeout" surface overlap.

**Pass condition.** Pallium injects neither prior investigation. If it
must return anything, it returns none (empty result set is the correct
answer). Specificity metric fires positively for this turn.

**Fail modes caught.**
- Either or both prior investigations injected.
- One injected because it had a slightly higher score (topical-similarity
  bias — exactly the 95% off-topic failure mode named in the abstention
  spec).

**Metrics attributed.** Specificity (must-not-inject correctness).

---

## Metrics — what the scaffold reports

For every scenario replay, the runner produces:

- **verdict**: `PASS` | `FAIL` | `INCOMPLETE` (setup error, not a real fail)
- **precision**: correct-injection / total-injection on this scenario's
  trigger turn (positive scenarios contribute; negative scenarios do not
  contribute injections to inject on, only non-injections)
- **specificity**: correct-non-injection / total-non-injection-opportunities
  across all turns in the scenario (negative scenarios contribute heavily;
  positive scenarios contribute on their non-trigger turns)
- **timing**: was the memory surfaced before the agent needed it, at the
  right event trigger, or too late
- **type distribution**: which memory types fired, whether the shape
  matched the scenario's expectation

Aggregate report writes to
`evals/narrow_target_claude_code/baseline_2026-07-01.json` with the
combined precision and specificity. Every subsequent PR in this
milestone re-runs the full suite and posts a delta in the PR body.

---

## What "baseline" means for this milestone

Baseline = today's Pallium (main, 2026-07-01) with the current abstention
Phase 3a/3b/4/5a/5b policy live. That's the number to beat. Any PR that
regresses on any scenario needs to justify why in the PR body; unjustified
regressions block merge.

**Note.** The baseline is expected to be imperfect. Scenarios 1, 2, 3, 4
may pass at 100% today (existing infrastructure covers them well); or
they may reveal existing gaps. The point of the baseline is to make
those numbers explicit, not to hit any particular target on day one.

---

## Non-goals for this milestone

- Additional scenarios beyond the seven. Expand only if evidence during
  weeks 3–6 shows a real coverage gap.
- Broader containers (other Claude Code repos, Codex sessions, other
  agents). Post-milestone.
- Comparison to external systems. Not the point.

---

## Deliverables checklist

- [x] This spec.
- [ ] `evals/narrow_target_claude_code/__init__.py`
- [ ] `evals/narrow_target_claude_code/README.md` (usage)
- [ ] Per-scenario replay skeleton (one file each; runnable placeholder that
      returns `INCOMPLETE` until wired to a real fixture):
  - [ ] `scenario_01_repeat_failed_command.py`
  - [ ] `scenario_02_recall_python_on_windows_constraint.py`
  - [ ] `scenario_03_resume_interrupted_implementation.py`
  - [ ] `scenario_04_surface_prior_investigation_on_error.py`
  - [ ] `scenario_05_preserve_architectural_decision.py`
  - [ ] `scenario_06_ruled_out_hypothesis_context_only.py`
  - [ ] `scenario_07_unrelated_prior_errors_no_injection.py`
- [ ] `run_all.py` — invokes each scenario, aggregates, writes
      `baseline_2026-07-01.json`.
- [ ] Baseline numbers checked in.

Skeletons land in Week 1; fixture wiring and baseline numbers land in
Week 2 (aligned with the milestone plan sequencing).
