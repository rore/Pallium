---
id: add-async-ingest-queue-and-worker-processing
title: Async ingest queue and worker processing
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Make `POST /items` fast and predictable by moving semantic extraction, direct memory promotion, thread rebuild work, and related derived indexing off the request path. Ingest should synchronously persist the raw `SourceItem`, its raw lexical index entry, and queue state on `source_items`, then let a standalone worker process the item asynchronously.

## Why

The current write path does too much synchronous work for the current product slice. One ingest can trigger semantic extraction, multiple derived writes, and thread-level rebuilds before the caller gets a response.

That makes Pallium slower and more fragile exactly where realistic downstream integrations will feel it first. Before deeper retrieval upgrades, Pallium needs a stable eventual-consistency model with cheap raw ingest, explicit queue state, and process-safe worker execution over SQLite.

## In Scope

- keep `POST /items` request shape unchanged while extending the response with queue state
- persist queue state directly on `source_items` in v1 rather than introducing a separate queue table
- make ingest do only:
  - idempotency lookup by `source_type + source_id`
  - `SourceItem` persistence
  - raw source-item lexical indexing
  - queue-state initialization
  - immediate response
- move semantic extraction, direct memory promotion, relations, and thread rebuild work to a worker pipeline
- serialize thread-level rebuilds with a small thread-scope lease table keyed by use case, thread identity, and exact visibility
- add one public status endpoint: `GET /items/{source_item_id}/processing`
- implement a standalone worker CLI: `python -m app.worker`
- implement an opt-in local supervisor CLI that starts the API plus child workers
- keep raw source evidence queryable immediately while derived memory becomes eventually consistent
- add correctness and regression coverage for queue state, worker retries, privacy, and post-worker query behavior

## Out of Scope

- a separate ingest queue table in v1
- a public drain-queue endpoint
- moving consolidation into the worker in this slice
- heartbeat leases or multi-item claim batching for SQLite
- making supervisor mode the default runtime model
- coupling Pallium to one downstream runtime or workflow engine

## Done When

1. `POST /items` no longer calls semantic processing or thread rebuild work on the request path.
2. New source items persist raw evidence plus queue state, and return `pending` or `skipped` with the current known derived ids.
3. `GET /items/{source_item_id}/processing` reports current queue status and current derived ids.
4. `python -m app.worker` can safely claim, process, retry, and complete one-item SQLite work items with lease-based multi-process safety while deferring thread-level rebuilds onto one serialized thread scope at a time.
5. An opt-in supervisor CLI can start the API and a configured number of child workers, and shut them down cleanly.
6. Raw source evidence is queryable immediately after ingest, while derived memory and thread-level memory appear after worker completion.
7. Existing privacy and integration-readiness scenarios still pass once the queue is drained or workers complete.

## Notes

Queue fields live on `source_items` in v1:

- `use_case`
- `processing_status`
- `processing_attempts`
- `processing_claimed_by`
- `processing_claimed_at`
- `processing_lease_expires_at`
- `processing_completed_at`
- `processing_error`
- `processing_next_attempt_at`

Status rules:

- new ingest with valid processing prerequisites starts as `pending`
- scope-aware ingest missing required visibility starts as `skipped`
- `completed` means item-local processing for that source item finished and any needed thread-level rebuild has been durably scheduled or coalesced through the thread-scope lease path
- `failed` means max retries were exhausted

Worker rules:

- lease-based claim model, not in-memory locking
- one claimed source item per transaction for SQLite
- thread-level rebuilds use a separate SQLite-backed thread-scope lease row so only one worker can rebuild a given thread scope at once
- a deferred thread rebuild stays coalesced on that thread-scope row until some worker drains it
- default lease should be long enough for current LLM calls
- bounded retry backoff should preserve the last error string

This slice should also update repo docs that still describe background jobs as optional future work, because async processing becomes part of the main ingest/runtime architecture rather than a later operational nicety.
