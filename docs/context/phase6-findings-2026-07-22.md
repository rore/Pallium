# Phase 6 Findings — Injection-Policy Abstention Measurement Window

**Date:** 2026-07-22
**Spec:** [`docs/specs/2026-06-27-injection-policy-abstention.md`](../specs/2026-06-27-injection-policy-abstention.md)
**Runbook:** [`docs/runbooks/2026-06-27-injection-policy-phase6.md`](../runbooks/2026-06-27-injection-policy-phase6.md)
**Measurement JSON:** [`evals/injection_policy_2026_06/phase6_2026-07-22.json`](../../evals/injection_policy_2026_06/phase6_2026-07-22.json)
**Measures:** injection-precision + downstream-task-effect (per lessons.md Invariant 2). Not candidate-recovery.

## Summary

The Phase 6 measurement window (planned for ~4 weeks starting ~2026-07-05) was
never run until now. Running it surfaces a decisive result: **the abstention
plan only half-shipped.** The suppression half (demote noisy types, add
grounding gates) is fully live and working. The delivery half (Phase 4
deterministic triggers + Phase 5b usage population) is effectively dead code.
The plan therefore cannot be evaluated as designed — its own success metric
has almost no data because the mechanisms that were supposed to produce that
data never fired.

## What the window shows (since 2026-07-04)

Source: `evals.injection_policy_2026_06.phase6_measurement --since 2026-07-04`.

- **On-demand triggers never fired.** Across the entire audit-log history,
  `post_tool_failure`, `retry_threshold`, and `session_start_checkpoint` fired
  **0 times each — ever**, not just in the window. `demoted_type_discovery`
  shows `n_triggered_injections = 0` for all four demoted types
  (`investigation_outcome`, `thread_summary`, `fact_summary`,
  `task_checkpoint`).
- **Session-start orientation delivers nothing.** `session_start_orientation`
  issued 386 queries all-time, **0 injections** — every one resolved to
  `no_relevant_memory`.
- **Proactive usage rate is 0%.** Of 31 populated usage-audit rows in the
  window (`user_prompt_submit`), `referenced_in_next_turn` was true **0 times**
  (`usage_rate = 0.0`). Human `rating_precision` on the same slice is 0.90 —
  i.e. what little is injected is rated on-topic but is not observably used in
  the next turn. Both cells are below the runbook's `n >= 30` trust bar only
  marginally (n=31), so treat the 0% usage as directional, not conclusive.
- **Whole-system injection rate** fell from ~67% (2026-W17) to ~2–3%
  (2026-W29), dominated by `no_relevant_memory` and
  `same_thread_context_sufficient` skips.

## Root causes (both validated against code + live data)

1. **`post_tool_failure` / `retry_threshold` are structurally incapable of
   firing.** The Claude Code hook read `tool_response.get("output")` /
   `.get("error")`, but Claude Code's Bash `tool_response` carries
   `stdout` / `stderr` / `interrupted` and **no exit-code field**
   (`is_error` is False even on real failures; error text often lands on
   stdout). So `failed` was always False. Evidence: every retry-counter state
   file is `{}` across ~60 sessions and weeks of failing commands. **Fixed** on
   branch `fix-injection-triggers-orientation` (opt-in via
   `PALLIUM_POSTTOOL_TRIGGERS=1`).

2. **`session_start_orientation` is filtered out by the grounding gates.** The
   generic orientation query ("recent decisions, progress, and open tasks")
   shares no content vocabulary with topical memory subjects, so candidates die
   at (a) the set-level `should_allow_injection` gate, (b) the per-candidate
   raw-BM25 floor (`min_raw_lexical_bm25 = 12`), and (c) the content-overlap
   gate — the BM25 floor fires first and is intent-independent. These gates are
   the correct off-topic-injection fix from the weak-spot-#6 work; they are
   simply incompatible with a vocabulary-free orientation query. (Fix in
   progress under architect review.)

## Decision-matrix reading

The runbook's matrix maps this window to:

> "usage_rate is consistently None / triggers never fire → the trigger shape
> is wrong; revisit before scaling."

**Verdict: do NOT conclude the abstention thesis is wrong, and do NOT re-enable
proactive types.** The demoted types have *no post-policy data at all* because
their delivery path never ran — that is unmeasured, not measured-bad. The two
types that stayed proactive (`decision`, `constraint_memory`) show recent
rating precision of 67% / 71% (near the 70% bar, small n) — not a mandate to
loosen. The correct next step is to **repair the delivery half, then re-run
this window for real.**

## Actions

- **Done:** repaired the failure trigger (branch
  `fix-injection-triggers-orientation`); added `main()`-level regression tests
  that drive the real payload shape (the gap that hid the bug).
- **In progress:** repair session-start orientation so `decision` /
  `constraint_memory` surface at session start, capped and flag-gated, without
  reopening the retired `orientation_recency` layer (commit f9756f0).
- **Then:** enable both on a pilot container *together with* the Phase 3b
  demotion config on that container (so trigger contribution is attributable),
  let a real 2–4 week window accumulate, and re-run
  `phase6_measurement.py`. Success = the three dead `trigger_origin`s move off
  0 and demoted-type triggered retrievals become measurable.

## Caveats

- Phase 5b populator produced only 31–33 rows in the window; the usage signal
  is thin. Part of that is the near-zero injection volume itself (nothing to
  populate). Repairing delivery should also restore a measurable Phase 5b
  stream.
- All numbers here are injection-precision / downstream-use, measured on
  self-rated feedback + `memory_usage_audit`. They say nothing about
  candidate-recovery (the retriever finds strong candidates fine — that was
  verified separately via `/query/debug`).
