# Milestone: Ship a Shaped Memory Contract

**Date:** 2026-07-01
**Status:** Draft — ready to start
**Owner:** Rotem Hermon
**Duration:** ~6 weeks
**Governing constraint:** Make Pallium work. Simplification is a tool for that goal, not a
substitute for it. Balance both: cut mechanism when it doesn't earn its place, ship
capability when the narrow-target scenarios demand it.

---

## Engineering discipline (applies to every workstream, every PR)

Non-negotiable. If a change can't clear this bar, it doesn't ship this milestone.

### Before every change — architect review
- No implementation starts without architect-review sign-off on the approach.
  Route via [tools/pallium-architect-review/SKILL.md](../../tools/pallium-architect-review/SKILL.md).
- Change is classified per [agent-policy.yaml](../../agent-policy.yaml)
  (red/blue/gray + watch) before any file is edited.
- Red-zone changes require an explicit written rationale in the PR description
  and named human sign-off. Gray-zone changes require the rationale.
- Progress persisted to a temp file per session so the plan survives compaction
  and hand-off.

### During the change — defensive programming
- Validate inputs at every trust boundary: MCP tool arguments, storage writes,
  config reads, cross-package calls. No silent coercion of bad types.
- Fail loud, fail early. Log with enough context to reproduce; do not swallow
  exceptions to keep a pipeline "running."
- No new global mutable state. No unbounded queues, unbounded LLM prompts,
  unbounded recursion.
- Concurrency-safe by construction: any new writer to `memory_objects`,
  `source_items`, `relations`, or `index_entries` uses the existing
  `sqlite_queue` path or an equivalent serialization guard.
- Backward-compatible storage: schema migrations use the existing migration
  path in [storage/sqlite_schema.py](../../storage/sqlite_schema.py); no
  destructive column drops without a migration + rollback plan.
- Feature flags for anything that affects the live path: shadow tables,
  disabled-by-default config, or a per-container gate. Nothing new lights up
  in production without an explicit switch.
- Prompts are versioned and reviewed. Any new LLM prompt lands with a fixture
  eval and a documented failure mode.

### After the change — verification (no assumption-driven work)
- **Unit tests** for every new function that has non-trivial branching,
  concurrency, or storage effect. New code without tests is not reviewable.
- **Integration tests** for every new MCP tool, every new memory type, every
  new event trigger. Test through the same entry point production uses.
- **End-to-end tests** — every workstream that ships a user-facing capability
  drives it through the narrow-target scenario replays under
  `evals/narrow_target_claude_code/`. If a scenario doesn't exercise the
  change, add or extend one.
- **Regression sweep** before merge:
  - `python -m pytest tests/ -x -q` — full test suite green.
  - The relevant slice(s) named in the PR description
    (e.g. `tests/test_visibility_scope.py`) run to completion locally.
  - Narrow-target scenarios re-run against the branch; deltas from baseline
    documented in the PR body (positive or zero, never negative unless the PR
    explicitly justifies the regression).
  - For retrieval-adjacent changes: `evals/injection_policy_2026_06/analyze.py`
    on current data; document the precision delta.
  - For extraction changes: `evals/fact_consolidation_eval` or the equivalent
    per-type eval named in the workstream.
- **Code review after every change.** Independent reviewer, not the author.
  Reviewer confirms: architect-review sign-off exists, defensive-programming
  checklist met, tests cover the change, regression sweep results attached.
- **Rollback plan** documented for any change touching the live path:
  which config bit reverts it, which commit to revert, what data (if any) is
  orphaned.

### Explicit non-goals for discipline
- "It works on my machine" is not evidence. The regression sweep runs in CI
  or it doesn't count.
- No "we'll add tests in a follow-up." Follow-ups don't happen. Tests land
  in the same PR.
- No skipping architect review for "small" changes. The abstention data shows
  that small confidently-shipped changes are how the failure mode compounded.

### Enforcement
- PR template (add if missing) has a checklist for the above; PRs merge only
  with the checklist filled.
- Weekly milestone check: any workstream that shipped without the checklist
  gets its most recent PR reviewed retroactively, and future PRs blocked
  until the process gap is closed.

---

## Why this milestone

Pallium has shipped ~14 major mechanism iterations in 6 months. Live feedback data
shows a 55% bad proactive-injection rate, dominated by memories that are topically
similar but irrelevant to the current turn. Adding a 15th mechanism doesn't move
that number.

An independent look at a comparable external system, plus a critical re-read of
Pallium's own state, exposes three real gaps and one real anti-pattern to avoid:

**Real gaps in Pallium:**
1. No explicit memory-interaction contract for the agent. Writes are inferred from
   conversation; the agent cannot say "yes, save this" or "no, that fact is wrong."
2. No shipped operational-memory object. `add-operational-fact-memory` is paused
   waiting for triggers to be perfect; the underlying capture is already live.
3. No narrow, testable target. "Generic agent memory" has no pass/fail, so we
   can't tell whether any given change moves the product.

**Anti-pattern to explicitly avoid:**
- Boosting a memory's retrieval score just because it was retrieved. When
  observed in comparable systems, the offline eval that reports headline
  retrieval numbers disables the feedback loop that's used in production —
  which means the reported number is measured with a mechanism that in
  production biases every subsequent retrieval, unmeasured. Pallium must not
  wire retrieval into ranking without evidence of downstream use.

## What this milestone ships

Six workstreams, sequenced so each ships something usable before the next
depends on it. A seventh workstream — simplification — runs alongside as a rule
applied to every PR, not as a separate sprint.

The measurable pass/fail is: **the five narrow-target scenarios (Workstream 2)
pass end-to-end at same-or-better precision than baseline, on a `semantic/`
that is smaller than it is today.**

---

## Workstream 1 — Finish the delivery-side fix

**Duration:** 2 weeks (start immediately)
**Attacks:** the measured 55% bad proactive-injection rate directly.

Continues [`docs/specs/2026-06-27-injection-policy-abstention.md`](2026-06-27-injection-policy-abstention.md).
This is the only workstream that directly moves the headline failure number.

### Tasks
- **Precondition (go/no-go by Wed of Week 1):** Verify Phase 0.5
  instrumentation has accumulated ≥7 days of fresh audit data with the
  block `score` field populated. If not met, Phase 2b defers to Week 2 and
  Week 1's W1 focus becomes Phase 1 re-validation on fresh data + Phase 6
  measurement setup.
- Complete Phase 2b — exact prospective replay on a fresh data window with the
  new `score` field populated. **Week 1 start depends on the precondition.**
- Complete Phase 6 — ~2-week measurement window with `memory_usage_audit`
  populated by `referenced_in_next_turn`.
- Publish per-type precision delta (before/after abstention) on the rated corpus
  at `evals/injection_policy_2026_06/`.

### Acceptance
- Held-out precision ≥ 70% on the types that stayed proactive
  (`constraint_memory`, `decision`).
  **Re-baseline note:** Phase 1 holdout analysis (2026-06-27) showed no
  type reached 70% on the held-out tail. Phase 2b exact-replay results
  govern the shipped precision target; if replay shows lower precision
  than the plan expected, re-baseline this acceptance criterion in the
  spec (documenting the delta and the reason) before shipping the
  workstream.
- Signed-off per-type report: which types earned their proactive status, which
  drop to on-demand permanently, which stay suspended.

### Files
- `evals/injection_policy_2026_06/phase6_measurement.py`
- Update status header on `docs/specs/2026-06-27-injection-policy-abstention.md`.

---

## Workstream 2 — Narrow the target

**Duration:** 1 week, no code
**Attacks:** the "can't tell if we're winning" problem.

Every downstream workstream is measured against these scenarios. If a change
doesn't move at least one, it doesn't ship this milestone.

### Target
**Claude Code sessions on the Pallium repo itself.**

Concrete because we live in it every day. Narrow enough to have real pass/fail.
General enough that if it works here, it plausibly works elsewhere.

### Named scenarios (v1 — expand only with cause)

1. **Don't repeat a previously-failed command.** Session A runs `uv sync` and it
   fails. Session B in the same repo attempts `uv sync`. Pallium surfaces the
   prior failure before the command runs.
2. **Recall the Python-on-Windows constraint before it bites.** Session A hits
   the ASR-blocked `Scripts/python.exe` issue. Session B, fresh, is about to run
   `python -m venv`. Pallium surfaces the constraint from `~/.claude/CLAUDE.md`
   or from the prior investigation memory.
3. **Resume an interrupted implementation correctly.** Session A gets partway
   through a task and hits token limit. Session B resumes on the same
   branch/path. Pallium surfaces the `task_checkpoint` with prior state intact.
4. **Surface a prior investigation when the same error class reappears.**
   Session A investigates and resolves an error. Session B hits the same error.
   Pallium surfaces the investigation outcome — on-demand, via the abstention
   event triggers, not proactively.
5. **Preserve an architectural decision made in-conversation.** Session A the
   user says "let's not use approach X because Y." Session B considers approach
   X for a related task. Pallium surfaces the decision.

### Negative scenarios (must also pass — precision AND specificity)

Positive-only scenarios can hide a false-injection increase. Two negative
cases explicitly test non-injection:

6. **Prior investigation ruled a hypothesis out; new session hits a related
   error from a different root cause.** Pallium surfaces the prior
   investigation via trigger (context-only), does not proactively inject it
   as "the answer," and does not block the agent from pursuing a new
   diagnosis.
7. **Two unrelated prior errors superficially match the current query terms.**
   Pallium does not inject either. Specificity (correct non-injections) is
   measured, not just precision (correct injections).

### Deliverables
- `docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md` naming
  the scenarios, their explicit pass conditions, and how each is measured.
- `evals/narrow_target_claude_code/` — one runnable scenario replay per case
  (7 total: 5 positive + 2 negative). Each plays a canned session end-to-end
  and reports pass/fail.
- Baseline numbers against today's Pallium checked in. These are the target
  to beat.

### Acceptance
- Seven runnable scenario replays (5 positive + 2 negative). All produce a
  deterministic pass/fail.
- Baseline report at `evals/narrow_target_claude_code/baseline_2026-07-01.json`
  reporting **both** metrics:
  - **precision** = correct injections / total injections
  - **specificity** = correct non-injections / total non-injections where
    memory exists that could have been injected
- Every subsequent PR in this milestone states which scenario(s) it moves
  AND commits to precision ≥ baseline AND specificity ≥ baseline. Never
  trade one for the other without explicit written justification.

---

## Workstream 3 — Explicit memory-write tools

**Duration:** 2 weeks
**Depends on:** Workstream 2 baseline.
**Attacks:** gap #1 (no interaction contract). Complements delivery work; does
not replace it — the abstention fix is still what attacks the 55%.

### Tools

Exposed via MCP in `mcp/server.py`:

- `pallium_remember(text, type, evidence?, confidence?)` — durable fact write.
- `pallium_correct(memory_id, corrected_text, reason)` — fix a wrong memory.
- `pallium_supersede(new_text, supersedes_id)` — explicit supersession chain.
- `pallium_forget(memory_id, reason)` — soft-delete with tombstone episode.
- `pallium_record_outcome(procedure_id, outcome, evidence?)` — feeds
  operational memory (Workstream 4).

### Storage

Every write records:
- `origin: agent_explicit | agent_inferred | user_requested`
  - `agent_explicit`: agent used `pallium_remember`, `pallium_correct`,
    `pallium_supersede`, or `pallium_forget`.
  - `agent_inferred`: extracted by the semantic pipeline from source items.
  - `user_requested`: user explicitly flagged content for storage
    (`artifact_kind="note"` or via UI).
- source session, agent id, container_ref
- confidence (**stored for audit only; never used in retrieval ranking**
  — see Invariant 1 enforcement below)
- correction reason (for `correct`/`supersede`/`forget`)
- explicit supersession chain: if superseded, links to the new memory via
  `superseded_by_id`.
- soft-delete tombstone: if forgotten, marked `is_soft_deleted=1` with
  reason; hidden from retrieval by default.

Superseded rows preserved for audit (Pallium's existing supersession pattern).
Soft-deleted rows hidden from recall by default; retrospective queries opt in.

### Explicit non-goals for W3
- Does not replace implicit similarity-based supersession. Both paths coexist.
- **No harsh-contradiction confidence penalty.** A user explicitly correcting a
  memory arguably makes the correction more reliable, not less. Skip until
  live data says otherwise.

### Invariant 1 enforcement in W3

The two invariants at the top of [`docs/context/lessons.md`](../context/lessons.md)
bind every PR in this workstream. Concretely for W3:

- Confidence scores recorded by `pallium_remember` are audit-only.
  Retrieval ranking must not use confidence as a boost signal.
  Confidence may inform downstream evaluation or filtering, but ranking
  changes require explicit verified use (outcome recorded, user confirmed,
  or offline evaluator judgment) — not the write itself.
- `pallium_correct` and `pallium_supersede` preserve old memories in the
  database for audit; they do not retroactively update the old memory's
  ranking or boost the corrected memory in retrieval.
- `pallium_record_outcome` records a fact but does not update retrieval
  ranking for the linked procedure or any related memories until W4
  integration testing verifies the contract.

Any violation of these three rules is a red flag during code review and
must be sent back before merge.

### Acceptance
- All five tools reachable from Claude Code and Codex integrations.
- Scenario 5 (preserve architectural decision) passes because the agent used
  `pallium_remember` at the moment the decision was stated.
- `origin` observable in `memory_objects`; queryable in the dashboard.
- **Concurrent-write handling:** correct/supersede on an already-superseded
  memory returns 409 Conflict; forget is idempotent on an already-forgotten
  memory.
- **Rollback plan documented and tested:** config kill-switch
  (`explicit_memory_writes.enabled = false`) disables all five tools
  without requiring schema migration.
- **Per-PR architect checkpoints** during the two-week implementation:
  (1) concurrency + validation review on the storage/sqlite.py + schema PR;
  (2) Invariant 1 review on the semantic/memory_writes.py PR;
  (3) soft-delete + consolidation interaction review before final merge.

### Files
- `mcp/server.py`, `storage/sqlite.py`, `semantic/memory_writes.py` (new)
- `tests/test_explicit_memory_writes.py` (new)

---

## Workstream 4 — Ship operational memory as an on-demand object

**Duration:** 2 weeks (development can overlap W3's testing tail; integration
begins only after W3 preconditions below are met)
**Depends on:** W3 (`pallium_record_outcome`), W1 event triggers (already live).
**Attacks:** gap #2 (no shipped operational-memory object).

**Precondition — hard gate:** W3 explicit-tools MCP surface, including
`pallium_record_outcome`, is merged, tested, and reachable from both
Claude Code and Codex integrations before W4 integration testing begins.
Target: end-of-day Wednesday of Week 3. If W3 slips beyond this, W4 start
defers; W4 development can continue in isolation but no shipping commit
until W3 is green.

Unpause [`roadmap/features/add-operational-fact-memory.md`](../../roadmap/features/add-operational-fact-memory.md).
Phase 4 triggers are shipped per `roadmap/scope.md`; resume gate is met.

### Shape

Per [`docs/specs/2026-05-31-operational-fact-memory-design.md`](2026-05-31-operational-fact-memory-design.md),
fields: `trigger`, `steps`, `evidence`, `success_count`, `failure_count`,
`last_confirmed_at`, `applicability` (`repo` | `machine_repo` + `scope_ref`).

### Derivation
- From `agent_work_trace_turn` metadata already captured by the Stop hook.
- No new capture surface.

### Delivery
- **On-demand only.** Trigger-based via the abstention Phase 4 event triggers
  (PostToolUse failure, SessionStart on repo match, user_prompt_submit with
  operational-intent signal).
- **Zero proactive injections.** Enforced by config default and asserted in test.

### Deliberate skips (learn from live data first)
- `success_count` / `failure_count` are stored but **not** wired into ranking.
  Ranking evolves once we have live signal.
- No proactive score threshold. Not applicable — this type isn't proactive.

### Acceptance
- Scenario 1 (don't repeat previously-failed command) passes.
- Scenario 2 (recall Python-on-Windows constraint) passes.
- Zero `injection_mode="proactive"` audit-log entries with
  `type=operational_fact` after ship.

### Files
- `semantic/agent_work_trace.py`, `semantic/operational_fact.py` (new)
- Integration tests under `evals/narrow_target_claude_code/`.

---

## Workstream 5 — Shadow-test typed one-pass extraction

**Duration:** 2 weeks, runs in parallel with W3–W4
**Attacks:** the temptation to rewrite extraction on aesthetics rather than data.

A single-call, strict-JSON typed extractor may or may not be better than
Pallium's current staged pipeline. Test it. Don't guess.

### Shadow pipeline
- New `semantic/extraction_typed_shadow.py`. Same inputs as the current
  extractor.
- Single LLM call, strict JSON, named arrays: `decisions`, `investigations`,
  `constraints`, `operational_facts`, `supersessions`.
- Outputs written to a shadow table `memory_objects_shadow`. **Zero effect on
  live retrieval.**
- Runs on every processed source item in parallel with the live extractor.

### Comparison eval
- Join shadow outputs against the rated-injection corpus.
- Per-type precision, recall, and drift vs the current extractor.
- Report at `evals/typed_extraction_shadow/report_YYYY-MM-DD.json`.

### Decision gate (per memory type)
Replace live extractor **for that type** only if shadow beats live with:
- ≥5-point precision improvement on the rated corpus, **and**
- no recall regression on that type, **and**
- no regression on any narrow-target scenario.

If shadow wins for type X, the live extractor for type X is **deleted** in the
same PR that promotes shadow — see W7 rules.

### Acceptance
- Shadow table populated for ≥2 weeks of live traffic.
- Per-type comparison report checked in.
- Explicit go/no-go per memory type. No stealth cutovers.

### Files
- `semantic/extraction_typed_shadow.py` (new)
- `storage/sqlite.py` (shadow table + migration)
- `evals/typed_extraction_shadow/compare.py` (new)

---

## Workstream 6 — Enforceable invariants

**Duration:** 30 minutes, ship this week
**Attacks:** the anti-pattern named at the top of this spec.

Two lines added to `docs/context/lessons.md` and referenced from `AGENTS.md`.
Enforced in PR review.

**Invariant 1:** A memory's ranking never boosts just because it was retrieved.
Ranking updates require evidence of downstream use — the agent cited it, the
next action changed, the user confirmed, an outcome was recorded via
`pallium_record_outcome`, or an offline evaluator judged it necessary.

**Invariant 2:** Every retrieval eval states which of three things it measures:
- **candidate recovery** (given we should retrieve X, can we find it?)
- **injection precision** (should anything have been injected, and was it right?)
- **downstream task effect** (did injecting anything actually help?)

These are three different measurements. Reports that don't state which will
be sent back.

Both invariants added to `AGENTS.md` under required reading so architect-review
catches violations before merge.

---

## Workstream 7 — Simplification pass

**Duration:** rolling, throughout the milestone
**Attacks:** accumulated complexity that makes the product hard to evolve —
without cutting anything that serves the promise.

Not a separate sprint. A rule applied to every PR in W1–W6:
**every PR either removes code or shows why it can't.**

### Baseline and target

| | Today | Target |
|---|---|---|
| `semantic/` lines | ~14,000 | ≤ 10,000 |
| Routing files (`agent_conversation_memory_routing_*`) | 14 | ≤ 5 |
| Config knobs shipped without a default | (unmeasured) | 0 |

If we hit the line target but scenarios regress, we cut too much. If we ship
features but the line count is flat, we simplified in name only. Both numbers
move together, or the pass didn't work.

### Concrete deletion candidates (audit and act)

1. **Collapse the 14 routing files.** `agent_conversation_memory_routing_{
   annotations, constants, floor, injection, justification, policy, scoring,
   selection, signals, suppression, trace}.py`. Target shape: one `routing.py`
   owning signal envelope → lane narrowing → scoring → selection, with `trace`
   and `justification` as siblings.

   **Audited plan (routing-file audit, Week 1):**
   - **Trivial merges (Phase 1, no test change):** `annotations.py` and
     `suppression.py` fold into `scoring.py`. `justification.py` archives to
     `docs/archived/` (unused in prod, kept for historical eval comparisons).
     Est. ~350 LOC reduction, 12 → 9 core files, no logic change.
   - **Hold (Phase 2, keep as siblings this milestone):** `constants.py`,
     `scoring.py`, `signals.py`, `policy.py`, `selection.py`, `injection.py`,
     `floor.py`, `trace.py`. Each is load-bearing or has focused test
     isolation value; touching risks precision regression.
   - **W8+ candidates:** `selection.py` (2372 LOC) modularization; `trace.py`
     fold once trace becomes stable.
   - **Gate:** existing routing tests green + narrow-target scenarios don't
     regress.

2. **Delete score-based proactive paths for on-demand / suspended types.**
   Any code that computes proactive score thresholds for `fact_summary`
   (suspended), `investigation_outcome` (on-demand), `thread_summary`
   (on-demand only) is dead. Grep, remove, update tests in the same PR.

3. **Audit unused prompt-role infrastructure.** `prompt_provenance.py`,
   `prompt_roles.py`, `prompt_variant_metrics.py` — if not on the live path,
   move to `evals/` or delete. **Judged by runtime import trace from named
   entry points** (`api/`, `mcp/`, integration hooks, `semantic/agent_conversation_memory.py`),
   not by grep alone. Import-only-from-tests counts as not-live.

4. **Collapse constraint sub-module remainder.** `agent_conversation_memory_
   constraints.py` — the constraint_policy lane was already deleted.
   **Pre-audit PR required before any deletion:** file audit lists what
   the module still owns, which files import it, and proposes concrete
   merge-or-delete disposition per top-level symbol. Deletion proceeds in
   a separate PR only after the audit PR is reviewed.

5. **Consolidate extraction paths after W5.** For each memory type where the
   shadow extractor wins per the W5 decision gate, in the same PR that
   promotes shadow:
   - **Delete** the extraction logic AND the prompt schema for that type
     in the losing extractor package.
   - **Keep** the memory type itself, its routing logic, its storage schema,
     and all existing memory objects of that type — they remain queryable
     from historical writes.
   - Same-PR atomicity: if the shadow promotion fails review, the old
     extraction path stays intact. No orphan state.
   - If a type is coupled to others across a shared prompt contract in the
     losing package (audited in W5 week 4 prep), that group of types is
     promoted or rejected together, not individually.

### Rules applied to every PR this milestone

- **New file requires justification.** Default: it fits in an existing file.
- **New config knob requires a default users won't need to touch.** No knob
  ships without a sensible default landed in the shipped config.
- **Deprecation without deletion is not simplification.** If W5 promotes a
  shadow path, the old path is deleted in the same PR.
- **One config section per package**, not one per feature. The existing
  `[injection.policy.types.*]` table shape is the pattern.

### Explicitly not touched during this milestone
- Storage schema (`memory_objects`, `source_items`, `relations`,
  `index_entries` — the four primitives from the annotation-layer removal).
- The abstention config surface (new, load-bearing).
- Hybrid retrieval (RRF + lexical + vector) — ablate individual components if
  a scenario says to; don't restructure preemptively.

### Balance clause

If a deletion pass would regress a narrow-target scenario or block a
committed workstream, we don't do that deletion this milestone. Simplification
serves working-Pallium, not the other way around.

---

## Sequencing

| Week | Ships | Simplification pass |
|---|---|---|
| 1 | W6 invariants. W2 narrow-target spec + scenarios. Start W1 Phase 2b. | Audit 14 routing files; land trivial mergers (constants, annotations). |
| 2 | W2 baseline eval numbers. W3 explicit-tools scaffolding. | Delete proactive paths for suspended types. |
| 3 | W3 explicit tools shipped. W1 Phase 6 measurement running. W5 shadow extractor writing. | Delete constraint sub-module remainder. |
| 4 | W4 operational memory shipped on-demand. First W5 comparison report. | Collapse remaining routing files (test-gated). |
| 5 | Two narrow-target scenarios passing (1, 2). W5 second report. | Prompt-role infrastructure audit + delete if unused. |
| 6 | W1 Phase 6 delta published. W5 per-type go/no-go. All five scenarios passing. | For each W5-promoted type, delete losing path in the same PR. |

Each week has a shippable artifact. If a workstream stalls, the others still
land. Nothing waits on a mechanism that hasn't proven itself against the
narrow-target scenarios.

## Milestone acceptance

At end of milestone:

1. **All five narrow-target scenarios pass** at ≥ baseline precision.
2. **Abstention delivers** ≥ 70% precision on remaining proactive types on
   held-out data (W1).
3. **Explicit memory tools live** in both integrations; observable `origin`
   field (W3).
4. **Operational memory shipped** as on-demand only; zero proactive injections
   (W4).
5. **Typed-extraction go/no-go published per memory type** (W5). Losing paths
   deleted where shadow won.
6. **`semantic/` ≤ 10k lines, routing ≤ 5 files** (W7). Zero new no-default
   config knobs shipped this milestone.
7. **Engineering-discipline compliance across every merged PR**: architect
   review before, code review after, defensive-programming checklist met,
   test coverage attached, regression sweep clean, rollback plan documented.
   Any PR lacking any of these is reviewed retroactively and blocks the
   next PR in that workstream.

If (1) and (2) don't land, the milestone did not succeed regardless of the
simplification numbers. If (7) slips, the milestone did not succeed regardless
of what shipped — the discipline is what keeps the shipped work from becoming
the next mechanism to unwind. Pallium working comes first.

## Not in this milestone

- Refactoring types into a flat episodic/knowledge/procedural taxonomy.
  Pallium's per-type policy is more expressive than a flat three-layer model.
- Adopting a different retrieval stack. Pallium already has hybrid
  RRF + lexical + vector.
- Wiring `success_count` into operational-memory ranking. Learn from live data
  first.
- Any new proactive injection surface.
- Broadening the target beyond "Claude Code in this repo" before the five
  scenarios pass here.

## References

- [`docs/specs/2026-06-27-injection-policy-abstention.md`](2026-06-27-injection-policy-abstention.md) — governs W1
- [`docs/specs/2026-05-31-operational-fact-memory-design.md`](2026-05-31-operational-fact-memory-design.md) — governs W4
- [`roadmap/scope.md`](../../roadmap/scope.md) — current shipped state, updated
  at milestone end
