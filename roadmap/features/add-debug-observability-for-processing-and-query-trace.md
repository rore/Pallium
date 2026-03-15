---
id: add-debug-observability-for-processing-and-query-trace
title: Debug observability for processing, queue health, and query trace
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

Add explicit opt-in observability for async processing, thread rebuilds, queue health, memory provenance, and query decision tracing so Pallium can explain what was ingested, what was processed, what memory was created, why a query returned specific results, and why backlog items are stalled or unclaimable.

## Why

Async ingest and routed retrieval made Pallium materially more realistic, but they also made failures and bad results harder to explain without direct SQLite inspection.

For the current product slice, explainability is part of the product claim. When memory or retrieval looks wrong, Pallium needs a supported way to answer what arrived, what processing did, what memory lineage exists, and why the debug path or queue looks the way it does.

## In Scope

- add `[observability] integration_debug` plus `PALLIUM_OBSERVABILITY_INTEGRATION_DEBUG` as an explicit local opt-in
- emit structured JSON debug events for source-item processing outcomes, failures, memory provenance, and thread rebuild outcomes only when that flag is enabled
- persist compact per-item observability state in `SourceItem.metadata`
- classify processing failures with stable categories instead of only stack traces
- extend `GET /items/{source_item_id}/processing` with additive observability fields
- extend `POST /query/debug` with candidate-flow counts, result summaries, routed exclusion reasons, and memory-vs-source origin details
- add `GET /debug/queue/health` for status counts, unclaimable pending reasons, active leases, and recent failures
- keep query/runtime semantics unchanged while making them inspectable
- add focused regression coverage for the new debug surfaces and opt-in logging behavior

## Out of Scope

- changing ranking, routing, or memory policy
- introducing an external tracing backend
- broad production observability platform work
- changing the normal `/query` contract
- changing the current single-package queue ownership model

## Done When

1. Integration debug logging is disabled by default and only emits structured events when explicitly enabled.
2. `GET /items/{source_item_id}/processing` reports failure category, annotation count, produced memory types, rebuild status, and memory provenance.
3. `GET /debug/queue/health` reports queue counts, unclaimable pending reasons, active leases, and recent failures without direct DB spelunking.
4. `POST /query/debug` reports candidate counts before and after visibility filtering, returned result summaries, and routed exclusion reasons.
5. Thread rebuild debug output explains visibility scope, considered input count, supersession, and final summary selection.
6. Focused API, worker, routing, and config tests pass locally for the new observability surfaces.

## Notes

Failure categories currently normalized in this slice:

- `missing_use_case`
- `missing_visibility_context`
- `unknown_use_case`
- `malformed_payload`
- `extractor_failure`
- `llm_failure`
- `thread_rebuild_failure`
- `unexpected_runtime_failure`

Queue-health unclaimable pending reasons currently normalized in this slice:

- `missing_use_case`
- `retry_backoff_active`
- `unknown_use_case`
- `missing_visibility_for_scoped_use_case`
- `legacy_max_attempts_exhausted_pending`

Per-item debug state stays embedded in source-item metadata in v1. This slice deliberately avoids a separate observability store.
