---
id: idea-measurement-contract-honesty
title: Tighten the historical-reuse measurement contract (arm labels, KPI wording, count-gate in CI)
status: queued
priority: high
commitment: uncommitted
milestone: pallium-vnext-p1
---

## Summary

Three small measurement-honesty fixes surfaced by the vNext architect review,
bundled because they all sharpen what the reuse experiment can actually
conclude — and should land before the Experiment-1 data window matters:

1. **Guidance-arm labels.** The weak arm is labelled "tool-description-only",
   but the base guidance block already carries a resume-time nudge to pull
   history; the "strong" arm only adds a second, more imperative directive. The
   real contrast is *permit-nudge* vs *permit-nudge + "call it first"*, with no
   true zero-guidance baseline. Rename the arms honestly (e.g. "base" vs
   "strong") and document in the measurement contract that both arms carry a
   block-level permit, OR add a genuine neutral/tool-only arm if isolating
   description-only pull behaviour is actually wanted.
2. **KPI wording.** The rollup dedups by session (a session with multiple
   same-rung events counts once), so the metric is *fraction of eligible
   sessions with >=1 confirmed reuse x 100* — capped at 100 — not the
   "events per 100 sessions" the design text states. The implemented metric is
   arguably better; reconcile the doc wording to match it, and add a unit test
   pinning the session-incidence semantics so it can't silently drift.
3. **Count-gate in CI.** The deterministic per-path DB round-trip count baseline
   is guarded by a `slow`-marked test, so it runs in no default CI lane. A
   regression on the shared retrieval chokepoint would not auto-fail default CI.
   Promote the (deterministic, fast) count-compare step into the default gate.

## Why

vNext's entire thesis is *measure whether reuse is valuable*. If the
independent variable (guidance strength) is mislabelled and the KPI's stated
meaning differs from its computed meaning, the first live numbers will be
misread. These are documentation/naming/CI fixes with no product-behaviour
change, and they are cheap relative to the interpretation errors they prevent.

## In Scope

- Rename/document the guidance-strength arms across the setup CLI help, the
  installed block arm-marker, and the roadmap/measurement docs.
- Reconcile the KPI wording in the execution design + measurement contract to
  the session-incidence semantics; add a unit test pinning it.
- Move the deterministic count-compare into the default CI gate (keep the
  latency/benchmark portions `slow`).

## Out of Scope

- Changing the KPI computation itself (only its stated meaning).
- Changing guidance-block content beyond arm naming/labelling.
- Adding a third neutral arm unless a description-only baseline is explicitly
  wanted (call it out as the alternative, decide when scoping).

## Done When

1. Arm labels reflect that both carry a block-level permit; the measurement
   contract states this so the KPI delta is read correctly.
2. Design/contract KPI wording matches the implemented session-incidence metric,
   pinned by a test.
3. The deterministic count-regression compare runs in default CI.

## Notes

From the vNext architect review (findings S1, S2, and the CI verification gap).
Doc/naming/CI only — no retrieval or funnel behaviour change. Evidence:
`integrations/claude-code/claude_md_block.py`,
`roadmap/features/add-agent-historical-lookup-exposure.md`,
`evals/historical_lookup_measurement.py` (session dedup),
`evals/vnext_perf_harness.py` + `tests/test_vnext_perf_harness.py` (slow-marked).
