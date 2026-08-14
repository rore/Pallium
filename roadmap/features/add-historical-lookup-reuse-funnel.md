---
id: add-historical-lookup-reuse-funnel
title: Historical-reuse funnel population + local live measurement
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Populate and run the historical-reuse **measurement funnel** end-to-end on a local
Pallium service — the deferred *"P1 (with the lookup tool)"* column of the measurement
contract. P0 shipped the contract + `lookup_event_id` + an empty-safe rollup skeleton,
and the P1 vertical shipped the **capability** (`pallium_search_history` +
`pallium_expand_source`). But no lookup events are persisted, so the KPI cannot
compute. This closes the gap between "capability shipped" and "effectiveness
measurable": real agent usage on the local service produces the Phase-1 KPI —
**confirmed historical-reuse events per 100 eligible sessions**, reported as the three
distinct rungs — with a retrospective sampled judge.

## Why

The strategy's most important near-term validation (Experiment 1 / decision-point 1)
is behavioral: *do agents reuse prior work often enough to matter, unprompted?* That
question can only be answered from a populated funnel. Today `load_events_from_storage`
in `evals/historical_lookup_measurement.py` returns empty lists and there is no
persisted lookup-event chain in `storage/` — so on a live DB the rollup emits nothing.
This work is the prerequisite that turns the shipped lookup vertical into a measurable
experiment, and it is currently **untracked** (it fell into the seam between the P0
contract item and the three P1 capability items). Until it lands, the user cannot see
whether the new Pallium is effective.

## In Scope

1. **Persisted lookup event + exposures.** A storage record (the
   `historical_lookup_reuse_event` / lookup-exposure table named by the rollup seam)
   written by the dedicated historical-lookup path (`source_only` query behind
   `pallium_search_history`) **unconditionally** — NOT gated on the legacy
   `audit_log_enabled` flag. Carries: `lookup_event_id`, `session_id` (`thread_ref`),
   `agent_ref`, `container_ref`, `actor_ref`, `trigger_origin`, `created_at`, and the
   **exposed source ids + raw ranks** (+ fusion score) so a RAW arm / exposure is
   reconstructable.
2. **Expansion parentage.** Persist the source-context-expansion event carrying
   `parent_lookup_id` (today it is only *echoed* on the response), linking
   expansion → originating lookup.
3. **Rollup loader.** Implement `load_events_from_storage`: reconstruct **eligible
   sessions** (`(container_ref, thread_ref)` grouping; *substantive* = ≥1 user turn +
   ≥1 assistant work turn; container held ≥ N prior indexed source turns at session
   start, via a `(container_ref, created_at)` join) and load the persisted events; feed
   `compute_reuse_rollup` → per-100-eligible for each rung + Wilson intervals + the
   supporting rates (opportunity→lookup, lookup→useful-result), empty-data-safe.
4. **Retrospective sampled judge harness.** Operationalize the contract's judge
   protocol: sample lookups (and eligible sessions for opportunity/missed-opportunity)
   from a window; per lookup label (a) genuine historical opportunity, (b) rung-1
   verified incorporation + evidence span, (c) rung-2 judged influence,
   (d) **user-directed vs agent-decided** read from preceding turns via the
   subsequent-turn `(thread_ref, container_ref, created_at)` join; blinded A/B framing,
   ≥3 seeds + consensus, Cohen's κ on a double-rated subsample, Wilson intervals,
   empty/abandoned-lookup handling. Judge writes the rung labels the rollup consumes.
   Reuse `evals/anchor_probe/subagent_audit.py` (protocol) + `evals/eval_common.py`
   (judge providers).
5. **Local enablement — funnel armed by default.** A fresh local install must record
   events without manual config. Today `query_audit_log` defaults `False`
   (`app/config.py`) and `pallium service install`'s `_seed_config` strips the
   `[observability]` section, so tools work but the funnel records nothing. Ensure the
   dedicated lookup-event persistence is **unconditional** (per the contract — not
   gated on `audit_log_enabled`), and additionally arm the local install (seed
   `[observability]` / adjust the default / `pallium.example.toml`) so agent-pull
   events are captured out of the box. Add a health check (in `pallium setup
   claude-code` / `pallium service status`) that confirms the funnel is armed.
6. **Runbook.** Document how to enable, use, and read the KPI on a local service, and
   wire the visibility-violation reporting format (0 violations *with* attempted-
   disallowed-access counts) into the rollup output.

> **Agent exposure / guidance moved out.** Making agents actually *pull* history
> (guidance that permits unprompted pulls + the Experiment-1 guidance-strength lever +
> refreshed Claude/Codex skills) is split into a dedicated feature —
> `add-agent-historical-lookup-exposure`. This feature owns the *pipes* (events land,
> KPI computes); that feature owns the *behavior* (agents produce the events). Both are
> required for a live Experiment-1 window.

## Out of Scope

- Rung 3 (downstream benefit) — needs a separate controlled-exposure step.
- RAW/DERIVED/HYBRID and derivation coverage/fidelity (shipped Continuous track).
- Online "historical-opportunity detector" / online material-use matcher (contract
  non-goals — these stay retrospective sampled evaluations).
- Requiring the agent to cite a handle in the baseline experiment condition.
- Phase 2 continuation/handoff and Phase 3 cross-user metrics.
- Multi-user denominators — local, single-user; session identity is treated 1:1 for
  the coding-agent integration (per the contract's integration-scoped denominator).

## Done When

1. On a **fresh** local install (no manual config edits), using Pallium normally,
   each `pallium_search_history` call persists a lookup event (unconditionally) with
   exposed source ids + raw ranks, and each `pallium_expand_source` persists an
   expansion event carrying `parent_lookup_id`.
2. `python -m evals.historical_lookup_measurement --db <local-db>` returns a **non-empty**
   rollup over a real window: reuse-per-100-eligible for rungs 1–2 with Wilson
   intervals + the supporting rates; still empty-data-safe when there are no events.
3. The retrospective judge harness runs over a sampled window and emits rung-1/rung-2
   labels + the user-directed-vs-agent-decided split + inter-rater κ on a double-rated
   subsample, feeding the rollup.
4. Visibility-violation reporting emits **0 violations** *with* attempted-disallowed-
   access counts/types (adversarial coverage referenced from the search/expansion
   items).
5. `pallium setup claude-code` / `pallium service status` reports whether the funnel is
   armed (agent-pull events captured out of the box on a fresh install).
6. A short runbook documents how to enable, use, and read the KPI on a local service.

## Notes

This is the deferred *"P1 (with the lookup tool)"* column of
`docs/specs/2026-08-13-historical-lookup-measurement-contract.md` and the
`load_events_from_storage` seam in `evals/historical_lookup_measurement.py`. Feeds
strategy **decision-point 1** (do agents reuse history?). Execution context:
`docs/designs/015-vnext-historical-work-execution.md` (Phase 1 success gate +
Measurement model).

**Already verified in place** (don't rebuild): both P1 tools are registered in
`app/mcp/server.py` (`pallium_search_history` L56, `pallium_expand_source` L176) with
`agent_pull` attribution hardcoded in `app/mcp/client.py`; the MCP endpoint is mounted
at `/mcp` on the main service (port 19836); registration is scripted (`pallium setup
claude-code` → `claude mcp add`; Codex `.mcp.json`); hooks are registered via
`~/.claude/settings.json`. The gaps are event *persistence* (default-off audit +
`_seed_config` stripping `[observability]`), and *guidance* that suppresses proactive
pulls with no Experiment-1 lever.

**Risk: guarded / High.** Touches `storage/` (new persistence table), the
`source_only` path in `core/query.py`, `core/service.py` (RED — orchestrator wiring /
architecture-review), the expansion path, and `app/cli/` (service config seeding +
setup health check) — plus `evals/` (loader + judge), config defaults, and a runbook
doc. High risk normally requires recorded human approval before implementation; the
user gave a **standing overnight approval** for High-risk changes in this package
(recorded verbatim in the Work Record). Likely delivered as **2 PRs** (a: funnel
persistence + rollup + judge; b: local enablement + armed-by-default + health check) to
keep the guarded surface reviewable — sequencing to be set in the Work Record. Agent
exposure/guidance is a separate feature (`add-agent-historical-lookup-exposure`).
