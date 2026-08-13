---
id: add-historical-lookup-funnel-telemetry
title: Historical-lookup measurement contract and event schema
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p0
---

## Summary

Define — before the lookup tool is exposed — the event schema, denominators, and
evaluation protocol that make Experiment 1 valid. Establish a linked event chain
(lookup → exposure → subsequent turn), the "eligible session" denominator, a
retrospective judge protocol, and a three-rung reuse ladder, so the reuse KPI is a
defensible measurement rather than a re-run of the old relevance-classification
problem offline.

## Why

The KPI cannot be computed today and, worse, is easy to compute *wrongly*. An MCP
call with an `agent_pull` origin only proves an agent executed a tool — not that it
decided independently rather than following "search our history"; that distinction
must be judged from the preceding conversation, not recorded as a deterministic tool
property. The audit also lacks a reliable event chain: no stable lookup id, raw
exposures aren't represented in `memory_usage_audit`, expansion has no parent link,
and there is no eligible-session denominator or tool-exposure population. Reporting
"reuse events per 100 sessions" on top of that would quietly recreate the relevance
problem. This item is the contract everything else measures against, so it precedes
tool exposure.

## In Scope

**Event chain (deterministic, logged online):**
- a stable `lookup_event_id` returned to the client on every historical lookup
- exposed raw source ids and their raw ranks recorded per lookup (a real
  tool-exposure population, not inferred)
- (optional, evaluated separately) a stable per-result **citation handle** the agent
  *may* cite, as a high-confidence *attribution* signal — **not** equated with verified
  incorporation (an agent can use history without citing, or cite without being
  influenced, and citation covers only answer text, not a changed command / path /
  edit) and **not required in the baseline Experiment 1 condition**, since requiring
  citation would add a behavioral instruction that contaminates natural-pull
  observation; builds on the existing `id_quote` reference kind
- `parent_lookup_id` on source-context expansion, linking expansion to its lookup
- client session + agent identity on the event
- subsequent-turn observation links (which turns followed the lookup)
- an `agent_pull` / `mcp_pull` origin marking the call as an agent-issued lookup
  (distinct from proactive injection) — **without** claiming it proves independent
  agent decision

**Denominators + protocol (defined before reporting):**
- explicit definitions of "substantive session" and "eligible session" (a session
  where historical lookup could plausibly have helped)
- sampling plan, judge rubric, judge calibration, and reported uncertainty intervals
- explicit treatment of empty / abandoned lookups
- user-directed-vs-agent-decided labeled **retrospectively** by the evaluator from
  the preceding conversation

**Reuse ladder (three distinct rungs, not one blurred metric):**
1. verified incorporation — retrieved history appears in the agent's reasoning, an
   action, or the answer (observational). Explicit citation of a returned handle is a
   *separate, optional* attribution signal (see event chain), not a substitute for
   this and not a materiality claim.
2. judged necessity / influence — a retrospective judge assesses whether the history
   shaped the work (observational, stronger claim)
3. downstream benefit — requires controlled exposure, user confirmation, or outcome
   comparison (not claimable from passive logs)

- historical-opportunity and missed-opportunity remain **sampled diagnostic
  estimates**; they do not gate the thesis unless judge reliability is demonstrated
- reuse-events-per-100-eligible-sessions rollup (extend `phase6_measurement.py`)
- keep visibility violations observable and reported *with* the count and types of
  attempted disallowed accesses (zero with no adversarial opportunity is not evidence)

## Out of Scope

- an online "historical opportunity detector" or live material-use matcher —
  explicitly rejected; opportunity and influence are retrospective sampled evaluations
- RAW/DERIVED/HYBRID shadow comparison (`idea-raw-derived-hybrid-shadow-eval`)
- continuation/handoff-success metrics (Phase 2 continuity)
- cross-user reuse metrics (Phase 3)

## Done When

1. Every lookup returns a `lookup_event_id`; exposures (source ids + ranks),
   expansion parentage, session/agent identity, and subsequent-turn links are
   recorded as a linked chain.
2. "Substantive session," "eligible session," sampling, judge rubric + calibration,
   uncertainty treatment, and empty/abandoned handling are documented before any
   "per 100 sessions" number is reported.
3. The three reuse rungs are reported separately; downstream benefit is only claimed
   where controlled exposure or confirmation exists.
4. Visibility violations are reported with attempted-disallowed-access counts/types.

## Notes

P0 contract: must land before the P1 tool is exposed. The minimal deterministic
event-logging ships with the P1 vertical slice; this item owns the schema,
denominators, and judge protocol.
Guarded paths: `core/service.py` (red), `storage/`, integration hooks. Start with
`/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md`
(P0 contract + Measurement model).
