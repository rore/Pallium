# Status

This page is the external-facing status view for Pallium.

If you want maintainer detail, read `docs/context/state.md` and `roadmap/`.
If you want evaluator-friendly status, start here.

## Current Product Claim

The current shipped claim is narrow:

Pallium helps an agent remember prior conclusions and resumed-work state from
agent-mediated conversations strongly enough to answer repeated questions and
resume interrupted work more reliably.

## What Works Today

Current shipped surface:

- local-first FastAPI service
- SQLite-backed storage
- `POST /items`, `POST /query`, `POST /query/debug`
- selected ingest for user messages, assistant outputs, and bounded assistant
  work artifacts
- compact `memory_hit` and `source_hit` results
- scoped `visibility_context` enforcement with fail-closed behavior in the
  current package
- routed retrieval over memory and source evidence
- thread-level carry-forward and resumed-work checkpoints in the current slice

## What Is Validated Today

The repo already contains meaningful proof layers:

- semantic regression coverage for the typed extraction path
- recurring-question benchmark coverage
- developer-work resumption benchmark coverage
- routed retrieval benchmark coverage
- public-corpus evaluation workflows for reviewed WildChat and WildBench slices
- privacy-aware retrieval behavior with debug trace visibility exclusions

This is stronger than a typical concept repo. The project includes both product
claims and ways to test those claims.

## What Is Still Experimental

These areas are implemented or explored, but still need more proof and tuning:

- how often higher-level carry-forward should beat lower-level evidence
- how far current resumed-work packaging should generalize across messier real
  traffic
- the exact boundary between broad recall, precise fact lookup, and work
  resumption routing
- how much public-corpus evaluation should drive the next retrieval upgrade

## What Is Intentionally Out Of Scope Right Now

Pallium is not currently trying to be:

- a broad workspace search layer
- a transcript archive
- a workflow engine
- an agent runtime
- a vector-first retrieval stack
- cross-container shared memory

## Likely Next Bets

The current repo-local roadmap points toward:

- vector retrieval behind the existing retrieval boundary
- hybrid lexical plus vector fusion
- explicit shared-memory derivation
- cross-container bounded memory

## Where To Go Deeper

- product problem and approach: [problem-and-approach.md](problem-and-approach.md)
- 10-minute local walkthrough: [getting-started.md](getting-started.md)
- runtime integration: [agent-integration.md](agent-integration.md)
- privacy model: [privacy-and-visibility.md](privacy-and-visibility.md)
- concepts and model: [overview.md](overview.md)
- stable architecture truth: [context/architecture.md](context/architecture.md)