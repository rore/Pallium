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
agent-initiated lookups (and separately, whether the user told the agent to search),
record which lookups returned useful results, and — via retrospective evaluation on
sampled live turns, not an online detector — estimate historical opportunity and
material use. Seeds the primary KPI (confirmed reuse events per 100 substantive
sessions).

## Why

The KPI and Experiment 1 cannot be computed today: MCP lookups aren't attributable
(agent pulls are invisible and indistinguishable from user-directed ones), there is
no "opportunity" denominator, and `referenced_in_next_turn` captures citation, not
material use. Without this, we can't answer strategy decision-point 1 ("do agents
actually reuse history?"). Critically, opportunity and material-use must be measured
retrospectively by a judge over sampled turns — **not** rebuilt as a live production
router/matcher, which would recreate the exact relevance-classification problem the
proactive-injection path spent months fighting.

## In Scope

- attribute agent-initiated lookups distinctly in `query_audit_log` (an
  `agent_pull` / `mcp_pull` origin), and record separately whether the user
  explicitly directed the search — so "agent decided" vs "user told it to" are
  distinguishable
- deterministic funnel facts that are cheap and unambiguous to log online: lookup
  issued, results returned/empty, agent origin; add funnel metric event types
- **retrospective, sampled** evaluation for the ambiguous stages — historical
  *opportunity* (should this turn have triggered a lookup?) and *material use* (did
  the returned history actually shape the subsequent work?) — as an offline judge
  over query + returned history + subsequent turns, not an online classifier
- a reuse-events-per-100-sessions rollup (extend the `phase6_measurement.py`
  template) computed from the deterministic facts + the retrospective sample
- keep the visibility-violations = 0 gate observable

## Out of Scope

- an online "historical opportunity detector" or live material-use matcher —
  explicitly rejected; these are retrospective sampled evaluations
- RAW/DERIVED/HYBRID shadow comparison (`idea-raw-derived-hybrid-shadow-eval`)
- continuation/handoff-success metrics (Phase 2 continuity)
- cross-user reuse metrics (Phase 3)

## Done When

1. Agent-initiated lookups are attributable and separable from proactive injection
   *and* from user-directed lookups in the audit log.
2. A live window produces a reuse-events-per-100-sessions number plus a
   lookup→useful→material-use breakdown, with the ambiguous stages measured by a
   retrospective sampled judge.
3. Opportunity and material use are evaluated offline on sampled turns, not by a
   production router.
4. Visibility violations are observable and reported as 0.

## Notes

Guarded paths: `core/service.py` (red), `storage/`, integration hooks. Start with
`/agent-workflow`. This telemetry is the instrument for Experiment 1's gate.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1 + Measurement).
