---
id: fix-reuse-kpi-artifact-taxonomy
title: Reuse KPI must recognize production assistant artifacts
status: done
priority: high
commitment: uncommitted
---

## Summary

The primary reuse KPI's eligible-session denominator is structurally **zero on real installs**. The
measurement treats assistant work as substantive only when `artifact_kind ∈ {assistant_output,
tool_use_summary, todo_snapshot}`, but the production Codex and Claude stop hooks write ordinary
assistant turns as `artifact_kind="message"`. So real sessions never become substantive → denominator
0 → the headline `reuse_per_100_eligible` reports `n/a (0 eligible)`.

## Why

Verified against the code:
- `evals/historical_lookup_measurement.py:253-255` — `_ASSISTANT_WORK_ARTIFACT_KINDS = {assistant_output, tool_use_summary, todo_snapshot}`; used at `:351`; substantive requires `has_user AND has_work` (`:359`).
- `integrations/codex/hooks/stop.py:166-172` and `integrations/claude-code/hooks/stop.py:161-167` write assistant turns as `artifact_kind="message"` (work-trace signal is `metadata["agent_work_trace_turn"]`, not a work-kind item).
- The three work kinds are produced only by the simulation harness (`app/agent_simulation.py:341`); no production ingest path rewrites `message`. Measurement reads `artifact_kind` raw (`:321-324`).

The whole "is vNext net-useful" question is unanswerable while the KPI it rests on is unmeasurable on
real data. This is the highest-leverage measurement fix.

## In Scope

- One canonical artifact taxonomy: either the measurement recognizes production `message` assistant
  turns (with an explicit substantive-work definition), or ingestion normalizes to a shared classifier.
  Prefer normalization/shared classifier over integration-specific special-cases inside the evaluator.

## Out of Scope

- Reuse-ladder rung labelling (separate signal).
- The retrospective judge rubric (`idea-reuse-judge-calibration`).

## Done When

1. Hook-to-measurement E2E for **both** Codex and Claude: ingest user prompt + normal assistant response through the real stop hooks, do a lookup via MCP, record downstream use, run the rollup — assert the session is eligible exactly once in the denominator and confirmed reuse appears exactly once in the numerator, using the artifact kinds a real install actually emits.
2. Eligibility boundary cases: user-only (not substantive), empty assistant response (not substantive), ordinary `message` (substantive), message+tool-summary (one eligible session), tool-only housekeeping (does not qualify), several assistant messages (denominator still one), Unicode content, at/just-below/just-above the substantive threshold.
3. Regression gate: no KPI fixture manually constructs an artifact shape production hooks cannot emit (unless explicitly a legacy-compat test).

## Notes

External-review register item 1 (severity High). Unblocks all downstream reuse measurement. Related:
`idea-measurement-contract-honesty` (Done — this is the concrete taxonomy repair it implied),
`fix-lookup-and-expansion-active-attribution`.
