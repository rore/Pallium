---
id: add-raw-historical-search-mode
title: Raw historical search retrieval mode
status: queued
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Add a retrieval mode that ranks raw `source_hit`s (prior agent/user turns) as
first-class results, under existing container/thread/actor/visibility scoping and
`source_type`/`role`/`artifact_kind`/`work_refs` filters, bypassing the
memory-centric routing/abstention pipeline that currently drops source turns.

## Why

The vNext thesis makes raw history a first-class retrieval substrate. The substrate
already exists — source turns are lexically + vector indexed and `source_hit` is a
real result kind — but the default query path routes everything through
`agent_conversation_memory` routing, which only scores `memory_hit`s and passes
`source_hit`s through inert. There is no code path that ranks raw turns by
relevance and returns them as the primary payload. Corpus evidence shows raw
hybrid search is already strong (~83% top-5), so exposing it well is high-leverage.

## In Scope

- a raw-ranked retrieval branch in `QueryExecutor.query` that ranks `source_hit`s
  via `CompositeRetrievalProvider` (RRF is already kind-agnostic) and returns them
  without the memory-only abstention gate
- honor existing scope (container/thread/actor/visibility) and the
  source_type/role/artifact_kind/work_refs filters
- a source-block result/render shape (excerpt + timestamp + thread/actor) distinct
  from memory injectable blocks
- retrieval trace coverage for the raw mode

## Out of Scope

- the agent-facing tool that invokes this mode (see `add-agent-historical-lookup-tool`)
- source-centric expansion (see `add-source-context-expansion`)
- changing the existing proactive/memory injection path or its abstention policy
- RAW/DERIVED/HYBRID shadow comparison (Phase 2)

## Done When

1. A caller can request raw-history search and receive relevance-ranked prior
   source turns as first-class results, scoped and visibility-enforced.
2. The raw mode does not alter `should_inject`/injectable_blocks for existing
   proactive queries.
3. Retrieval trace explains the raw-mode ranking.
4. Visibility enforcement on raw results is verified (fail-closed; 0 violations).

## Notes

Guarded paths: `core/service.py` (red), `core/query.py` (watch), `retrieval/`,
`api/`. Start the implementation slice with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
