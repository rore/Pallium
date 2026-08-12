---
id: add-historical-lookup-funnel-telemetry
title: Historical-lookup funnel telemetry and reuse KPI
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Instrument the historical-reuse funnel so Experiment 1 is measurable: distinguish
agent-initiated lookups, and record opportunity → lookup → useful result →
material use, seeding the primary KPI (confirmed reuse events per 100 substantive
sessions) and a missed-opportunity signal.

## Why

The KPI and Experiment 1 cannot be computed today: MCP lookups don't carry
`trigger_origin` (agent pulls are invisible), there is no "opportunity" denominator,
and `referenced_in_next_turn` captures citation, not material use. Without this,
we can't answer strategy decision-point 1 ("do agents actually reuse history?").

## In Scope

- attribute agent-initiated lookups distinctly in `query_audit_log`
- record the funnel stages (opportunity → agent query → useful result → material
  use) using `query_audit_log` / `memory_usage_audit` / `metrics`; add funnel
  metric event types
- a stronger-than-citation "material use" signal (beyond the current id-quote /
  verbatim-snippet matcher) without over-claiming behavior change
- a reuse-events-per-100-sessions rollup (extend the `phase6_measurement.py`
  template) and a missed-opportunity indicator
- keep the visibility-violations = 0 gate observable

## Out of Scope

- RAW/DERIVED/HYBRID shadow comparison (Phase 2 — `idea-raw-derived-hybrid-shadow-eval`)
- continuation/handoff-success metrics (Phase 3)
- cross-user reuse metrics (Phase 4)

## Done When

1. Agent-initiated lookups are attributable and separable from proactive injection
   in the audit log.
2. A live window produces a reuse-events-per-100-sessions number plus a
   lookup→useful→material-use breakdown.
3. A material-use signal exists that is stronger than pure citation matching.
4. Visibility violations are observable and reported as 0.

## Notes

Guarded paths: `core/service.py` (red), `storage/`, integration hooks. Start with
`/agent-workflow`. This telemetry is the instrument for Experiment 1's gate.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1 + Measurement).
