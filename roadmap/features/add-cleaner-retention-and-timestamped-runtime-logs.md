---
id: add-cleaner-retention-and-timestamped-runtime-logs
title: Cleaner retention and timestamped runtime logs
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a dedicated cleaner runtime, freshness-aware hot-store retention, and timestamp-prefixed runtime logs so Pallium does not drift into a forever transcript archive and live integration runs remain readable.

This slice should prune stale/noisy history safely, preserve evidence for retained memory and retained injectable working-state memory, and make Pallium-owned runtime logs chronological by eye.

## Why

Live downstream-agent traffic now produces a real stream of raw source items, derived memory, superseded thread summaries, and observability metadata. Without a cleaner-driven retention model, the hot SQLite store will grow noisier and larger over time.

At the same time, current logs are hard to follow because timestamps are buried inside JSON payloads rather than prefixed consistently across processor, supervisor, and observability lines.

## In Scope

- add a dedicated cleaner runtime separate from processors:
  - new cleaner CLI
  - runner/supervisor support for cleaners alongside processors
- local combined mode should start one cleaner by default
- multi-instance deployment must be able to disable cleaner explicitly per instance
- protect correctness with a dedicated maintenance lease so multiple cleaners are safe but redundant
- add retention config for:
  - enabled flag
  - run interval
  - lease seconds
  - batch size
- use freshness-aware retention classes rather than naive TTL from creation time
- keep active `decision` and `investigation_outcome` indefinitely in v1
- retain active working-state memory while fresh:
  - `thread_summary`
  - `task_checkpoint`
  - `continuity_memory`
  - `pattern_memory`
- aggressively prune stale superseded memory, especially superseded thread summaries and checkpoints
- give raw source items bounded TTL by class:
  - low-value meta `message` / `assistant_output`: shortest
  - ordinary raw `message` / `assistant_output`: bounded
  - selected assistant work artifacts: longer than ordinary chat turns
- strip `observability_debug` metadata from older retained source items while keeping semantic provenance and `pallium_semantic_signals`
- only delete a source item when:
  - processing is settled
  - no active lease exists
  - its retention window expired
  - no retained memory still depends on it as evidence
- extend queue/debug health with retention status and last-run stats
- make retention and packaging observability easy to correlate with downstream integration behavior
- unify Pallium-owned logs under timestamp-prefixed output for:
  - observability JSON events
  - processor status lines
  - cleaner status lines
  - supervisor status lines
  - runner-started server logs
  - query/packaging output that reports final injected block/result count and labels

## Out of Scope

- cold/archive storage for expired raw evidence
- public retention administration APIs beyond debug visibility
- processor-side retention work
- deleting evidence that still supports retained active memory
- changing Uvicorn internals outside the Pallium-owned runner/config path

## Done When

1. A dedicated cleaner process can be started on its own and through the Pallium runner/supervisor.
2. Cleaner work is protected by a maintenance lease and is safe under multiple configured cleaners.
3. Freshness-aware retention removes stale working-memory, stale superseded memory, and expired raw chat evidence while preserving evidence for retained memory and retained injectable working-state memory.
4. Older retained source items lose bulky `observability_debug` metadata without losing semantic provenance or semantic signals.
5. `GET /debug/queue/health` reports retention status and last-run stats.
6. Pallium-owned runtime logs begin with visible timestamps and remain easy to follow chronologically across observability, processor, cleaner, supervisor, and runner-started server output.
7. Live integration operators can correlate query issued/skipped, Pallium packaging, and final injected block/result count from the timestamped logs and debug surfaces.
8. Retention and logging regressions pass alongside existing async worker, privacy, and routing slices.

## Notes

Implementation defaults:

- keep cleaner work completely out of normal processor loops
- use the explicit memory freshness field introduced by the preceding memory-quality slice as the retention anchor for working-memory kinds
- processors and cleaners should share the same structured logger/formatter so timestamps and component labels are consistent
- retain active lower-level conclusions indefinitely in v1, but let stale working-memory and superseded history expire
- add focused tests for:
  - cleaner lease behavior
  - evidence-protection safety
  - stale working-memory expiry
  - raw source-item deletion cascades
  - metadata stripping
  - timestamp-prefixed logging across runtime components
  - correlation of packaging/injection-related log output with the downstream integration flow

