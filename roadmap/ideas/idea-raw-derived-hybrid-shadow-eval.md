---
id: idea-raw-derived-hybrid-shadow-eval
title: RAW / DERIVED / HYBRID retrieval + representation evaluation
status: in-progress
priority: medium
commitment: committed
milestone: pallium-vnext-derived-eval
---

## Summary

On real historical lookups, shadow three candidate sets — RAW (source turns),
DERIVED (memory objects), HYBRID — and measure what a *shadow* can honestly measure:
candidate recovery, judged relevance, representation quality, and context cost at
equal token budget. Consumption and downstream benefit are explicitly **out** of the
shadow (an arm the agent never sees can't be "used") and are handled by a separate
controlled-exposure step.

## Why

Corpus studies found current derived memory gives no retrieval-recall advantage and
is a lossy consumption representation (~29% misleading). The strategy keeps
derivation as a continuously-evaluated optimization layer. But the last framing of
this item wrongly asked a shadow to report "downstream material use" — impossible
for a representation the agent never receives. This item is scoped to the two
retrieval-time seams a shadow can measure; the extraction/coverage seams live in
`idea-derivation-fidelity-eval`, and true consumption needs controlled exposure.

## In Scope (outline — detail when Phase 1 raw search lands)

Covers two of the four derivation seams:
- **derived-retrieval failure:** given a lookup, did the relevant derived object
  actually enter the DERIVED candidate set? (vs the relevant source entering RAW)
- **representation quality:** holding information and retrieval constant, is the
  rendered DERIVED representation correct, or misleading/unsupported, compared to the
  RAW turns?

Mechanics:
- a shadow runner reusing the `subtask_selector_shadow` seam + a new side table
- per-lookup record: RAW-only vs DERIVED-only recovery wins, judged relevance,
  misleading/unsupported rate, and **context cost at equal token budget** (or a
  quality-vs-token Pareto curve) — HYBRID must not win merely by receiving more
  context
- store the raw fusion score + source ids/ranks so a RAW arm is reconstructable
- construct the RAW arm as **candidate-level source-only** (derived/memory objects
  excluded before selection, not post-filtered), so RAW-vs-DERIVED isn't confounded
  by derived content leaking into the RAW candidate set
- record the derivation **schema / prompt / model version** on each DERIVED arm, and
  allow evaluating *new* derivation variants — so the track can answer "can better
  derivation win?", not just score the current implementation forever
- extend `evals/retrieval_ablation/` with RAW/DERIVED/HYBRID variants for periodic A/B
- shadow-only: never affects live injection/output

## Out of Scope

- **downstream material use / consumption from the shadow** — a shadow arm is never
  shown to the agent; consumption requires a separate controlled-exposure experiment
- extraction/coverage failures (`idea-derivation-fidelity-eval`)
- promoting derived memory before it demonstrates a repeated, measured advantage
- building a synthetic benchmark to prove derived memory superior (explicit non-goal)

## Done When

1. Real lookups are shadow-evaluated for derived-retrieval and representation quality
   across RAW/DERIVED/HYBRID without affecting output.
2. Context comparisons are at equal token budget or reported as a Pareto curve.
3. Each result names the seam (candidate-recovery vs representation) and records the
   derivation version, so new derivation variants can be compared.

## Notes

Continuous track, not a gating phase; depends on Phase 1 raw search (no RAW arm
before then). Paired with `idea-derivation-fidelity-eval` (extraction/coverage
seams) and a later controlled-exposure step for consumption. Feeds strategy
decision-point 3.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(Continuous evaluation track).
