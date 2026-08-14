---
id: idea-retrieval-source-fetch-batching
title: Batch per-candidate source fetches on the shared retrieval path (volume-gated)
status: in-progress
priority: medium
commitment: uncommitted
---

## Summary

Two measured N+1 shapes on the retrieval + measurement paths, flagged
report-only during vNext perf validation. Fix only when observed volume
justifies it — both are cheap at current local-first scale.

## Why

- **Retrieval path (request-time):** the lexical path fetches the same source
  item up to three times per hit (forgotten-source gate + visibility/container
  check + hydration), and the source-only candidate window is ~4x the requested
  limit, giving a measured slope of ~9 engine queries per retrieval-limit slot
  (O(candidates)). This is the shared chokepoint the forgotten-source gate sits
  on; it predates vNext but vNext exercises it harder. It is regression-gated by
  a committed deterministic count baseline, so a regression is visible.
- **Measurement path (offline):** the reuse loader does a full-table scan for
  `event_type='lookup'` (the composite index leads with container, so it can't
  serve an event-type-only predicate) and one source-item query per exposed id
  per event. Both run offline in the rollup, never the request path.

## In Scope

- Batch the per-candidate source fetch into a single `WHERE id IN (...)` on the
  retrieval path, preserving the forgotten/visibility semantics and the gate
  ordering.
- Index or reorder the offline loader query (lead with container) when the
  funnel runs at volume.

## Out of Scope

- Any retrieval-ranking or fusion change (this is fetch batching only).
- Doing the work speculatively before volume warrants it.

## Done When

1. The retrieval per-slot query slope drops from O(candidates) to a small
   constant, with the deterministic count baseline updated and still green.
2. The offline loader no longer full-scans at volume.
3. Governance/visibility semantics unchanged (e2e invariants still pass).

## Notes

From the vNext architect review (findings C1, C2) and the perf/e2e validation
report (`docs/reports/vnext-perf-e2e-validation.md`). Explicitly deferred:
measure-not-fix boundary of the validation feature. Evidence: `core/query.py`
(candidate window), `core/filters.py` (forgotten gate ordering),
`evals/historical_lookup_measurement.py` (loader scan + per-id visibility).
