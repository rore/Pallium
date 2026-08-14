---
id: add-agent-historical-lookup-exposure
title: Agent exposure + guidance for historical lookup (Experiment-1 behavior lever)
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Make agents actually **pull history** on a live local service, and give Experiment 1 a
**guidance-strength lever** so it can compare arms. The P1 tools
(`pallium_search_history`, `pallium_expand_source`) are registered and auto-discovered,
but current memory guidance actively *discourages* proactive querying — which suppresses
the exact unprompted-pull behavior the reuse funnel measures. This feature owns the
*behavior* side (agents produce lookup events); the funnel feature owns the *pipes*
(events land, KPI computes). Both are required for a live Experiment-1 window.

## Why

Experiment 1 asks: *do agents reuse prior work often enough to matter, unprompted?* If
the deployed guidance says "don't query every turn; injection handles ~90%," agents will
rarely call the lookup tools and the funnel will read a near-zero rate that reflects the
*guidance*, not the *value* of history. To measure honestly we must (a) permit/encourage
a deliberate historical pull when prior work may exist, and (b) be able to vary guidance
strength as an experimental arm (*base* permit-nudge vs. a stronger skill/guidance
prompt that adds a "call it first" directive — both arms carry a block-level permit,
so the delta measures the call-first directive, not guidance presence) so the KPI
difference is attributable. The tools also need to be *discoverable
and self-explanatory enough* that an agent reaches for them at the right moment — this is
prompt/skill/description work, not new capability.

## In Scope

1. **Guidance that permits unprompted pulls.** Refine the historical-lookup guidance in
   the memory integration blocks (Claude Code / Codex `CLAUDE.md`/`AGENTS.md` guidance
   and the injected block generation) so it explicitly *permits and encourages a
   deliberate `pallium_search_history` pull when prior work on this task may exist* —
   without encouraging query-spam on every turn (keep the "injection handles routine
   recall" framing for injection, but carve out the deliberate-historical-pull case).
   Distinguish the two behaviors clearly so the change is targeted.
2. **Experiment-1 guidance-strength lever.** Provide a toggle so a run can select
   *base* (the block-level permit nudge; NOT a zero-guidance baseline) vs *strong*
   (base plus an explicit "call it first" resume directive at task start). Both arms
   carry a block-level permit — the delta measures the call-first directive. The
   lever should be a config/flag or a skill that can be installed or not — something the
   experiment harness can flip and record as the arm label, so the KPI delta is
   attributable to guidance strength.
3. **Refreshed skills with the P1 tools.** Update the stale Codex `pallium-memory` skill
   to include `pallium_search_history` / `pallium_expand_source` (and their
   when-to-use), and add the equivalent Claude Code historical-lookup guidance/skill so
   both integrations expose the tools consistently. Ensure tool descriptions themselves
   read as "reach for me when resuming or building on prior work."
4. **Tool-description review.** Verify the registered tool descriptions in the MCP server
   are self-explanatory for unprompted use (name, one-line purpose, when-to-use, what a
   result means) — tighten wording only; no behavior change to the tools.
5. **Minor hygiene.** Reconcile the no-op `--stdio` arg in
   `integrations/codex/.mcp.json` while touching the integration surface.

## Out of Scope

- The persisted lookup-event table, rollup loader, and judge harness — those are
  `add-historical-lookup-reuse-funnel` (this feature assumes they exist / lands after).
- Arming the funnel by default / service-install config seeding — also the funnel
  feature (item 5 there).
- Any change to what the lookup/expansion tools *do* (retrieval behavior, scoring,
  source-only semantics) — this is exposure/guidance only.
- Running the actual Experiment-1 measurement window (that is an operational step once
  both features + perf/e2e validation land).

## Done When

1. On a fresh local install, the deployed memory guidance permits/encourages a
   deliberate historical pull (does not discourage the lookup tools), and the two
   integrations (Claude Code + Codex) expose `pallium_search_history` /
   `pallium_expand_source` with clear when-to-use text.
2. A guidance-strength lever exists (toggle or install-or-not skill) that an experiment
   run can set to *base* (permit-nudge) vs *strong* (permit-nudge + call-first) and record as an arm
   label.
3. The stale Codex skill is refreshed with the P1 tools; the Claude Code equivalent
   exists; tool descriptions read as self-explanatory for unprompted use; the
   `--stdio` no-op is reconciled.
4. A behavioral smoke check (manual or scripted) shows an agent calling
   `pallium_search_history` unprompted under the stronger-guidance arm on a
   history-relevant task — confirming the lever moves behavior before the measurement
   window opens.

## Notes

Split out of `add-historical-lookup-reuse-funnel` (was item 6 there). Feeds strategy
**decision-point 1** (do agents reuse history?) by supplying the *behavior* the funnel
counts. Runs **after** the funnel feature (need the event pipes to exist before behavior
matters) and **before** the perf/e2e validation gate.

**Already verified in place** (don't rebuild): both P1 tools are registered in
`app/mcp/server.py` (`pallium_search_history`, `pallium_expand_source`) with `agent_pull`
attribution in `app/mcp/client.py`; the MCP endpoint is mounted at `/mcp` (port 19836);
registration is scripted (`pallium setup claude-code` → `claude mcp add`; Codex
`.mcp.json`). The gap is *guidance that suppresses proactive pulls* and *no Experiment-1
lever* — not tool registration.

**Risk: mostly non-guarded → likely Elevated.** Touches `integrations/` (guidance +
skills; not a guarded path), tool-description strings in `app/mcp/` (guarded, but
description-only, no behavior change), and possibly a small config toggle for the lever.
No new persistence, no `core/service.py` orchestration change, no retrieval-behavior
change. A change-classification at Work-Record time confirms; if the lever needs a config
default or block-generation edit it stays within Elevated.
