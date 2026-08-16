---
id: fix-add-limit-to-injection-replay-simulation
title: Add a query cap (--limit) to injection_replay_simulation so it is runnable
status: queued
priority: low
commitment: uncommitted
---

## Summary

`evals/injection_replay_simulation.py` has no query-count cap: it replays ALL suppressed
injection queries (`decision_reason='same_thread_context_sufficient'`) for its hard-coded
container through an LLM (Haiku) classifier. On the live snapshot that is ~3,719 queries,
which does not finish within a reasonable window (it timed out at 10 min during the
2026-08-16 validation cycle), so the injection-value/redundancy signal could not be
collected.

## Why

This eval answers a strategically useful question: of the injections the system SUPPRESSED
as "thread already has the context," how many would actually have ADDED value (helpful) vs
been redundant/noise — i.e. is the 51% same-thread suppression correct. Today it is
effectively un-runnable at live-DB scale, so that question stays open.

## In Scope

- Add a `--limit N` flag (and optional deterministic sampling `--seed`) capping the number
  of suppressed queries classified, mirroring the pattern in the other evals.
- Optionally make the hard-coded `CONTAINER_REF` (line ~33) a `--container` flag so the eval
  can target smaller containers.
- Ensure `--cache-dir` reuse still works so partial runs accumulate.

## Out of Scope

- Changing the classification prompt, thresholds, or output schema.
- Any production/runtime change.

## Done When

1. `python -m evals.injection_replay_simulation --db-path <snapshot> --limit 100
   --cache-dir <dir>` completes and prints the per-threshold helpful/reinforcing/redundant/
   noise table.
2. The container is selectable (flag) or documented as intentionally fixed.

## Notes

Surfaced by the injection-vs-pull validation cycle (#5 could not complete). Evidence:
`evals/injection_replay_simulation.py` — no `--limit`, `CONTAINER_REF` hard-coded ~line 33,
reads all `same_thread_context_sufficient` rows. See
`docs/research/2026-08-16-injection-vs-pull-validation.md`.
