![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Agents are bad at continuity.

They forget why decisions were made, lose investigation outcomes, and struggle
to resume interrupted work without replaying transcripts or rediscovering
context.

Pallium is a local-first memory sidecar for agents. It helps them remember
prior decisions, findings, and work state so they can answer follow-up
questions and resume interrupted work without replaying full transcripts.

Under the hood, the current slice stores selected evidence, derives compact
evidence-backed memory, and returns small reusable memory and evidence cards.

The current product slice is deliberately narrow: agent-mediated conversations,
repeated questions, resumed-work continuity, and privacy-safe scoped memory.
In other words, Pallium is currently optimized for conversation continuity, not
general knowledge memory.

## Why Not Just Transcript Search, Summaries, Or A Vector DB?

Common approaches each solve part of the problem and miss part of it:

- transcript replay is large, noisy, and expensive to keep re-feeding to a
  model
- prompt summaries are brittle and often lose the evidence behind conclusions
- vector search can find related text, but not durable explicit decisions,
  investigation findings, or compact work-state checkpoints by itself
- runtime-local state helps within a session, but usually does not give you
  reusable cross-thread memory with clear evidence and scoped visibility rules

Pallium's current approach is to keep small reusable memory for agent-mediated
conversations, especially repeated questions and resumed work, while preserving
links back to supporting evidence.

## What You Get If You Add Pallium

Today Pallium's concrete value is:

- better follow-up consistency on repeated questions
- better resumed-work continuity after interruptions
- scoped memory that keeps public and private context separated
- compact answerable context instead of transcript replay
- a debug path that explains why retrieval returned what it did

## What Is Shipped Today

This repo already ships a real working slice, not just design docs. Today it
can:

- ingest selected conversation evidence and bounded work artifacts
- return compact memory and source evidence cards
- support repeated-question recall and resumed-work continuity
- enforce fail-closed scoped visibility for public and private memory
- expose a debug trace for retrieval and visibility behavior

Implementation surface:

- one local-first FastAPI service
- SQLite-backed storage
- `POST /items`, `POST /query`, and `POST /query/debug`
- lexical retrieval plus package-owned routed retrieval for the current slice

## Why Believe It Is Real?

The repo includes proof, not just claims:

- regression coverage for typed memory extraction
- benchmarks for repeated-question recall
- benchmarks for resumed-work continuity
- routed retrieval evaluation for choosing between memory and source evidence
- reviewed public-corpus evaluation slices from WildChat and WildBench
- privacy-aware retrieval with visibility exclusion trace

## How Integration Works

The runtime model is simple:

1. send selected events to `POST /items`
2. call `POST /query` before answering a follow-up question or resuming work
3. use the returned compact memory and evidence cards in your runtime or prompt

Use `POST /query/debug` when you need to understand missing results, routed
layer choice, or visibility exclusions.

For the current slice, the best inputs are:

- agent-mediated user messages
- final assistant outputs
- selected assistant work artifacts such as explicit blocker summaries or next
  steps

## Evaluate It In 10 Minutes

If you want to try Pallium quickly:

- run the local service plus processor
- ingest a small sample conversation
- query a repeated question
- query a resumed-work question
- inspect `POST /query/debug`

Follow [docs/getting-started.md](docs/getting-started.md).

## What Pallium Is Not

Pallium is not:

- a transcript archive
- a vector DB wrapper
- an agent runtime
- a workflow engine
- broad workspace search
- a system-of-record database

## What Is Not Shipped Yet

The current repo does not yet ship:

- vector retrieval behind the retrieval boundary
- hybrid lexical plus vector fusion
- explicit shared-memory derivation
- cross-container bounded memory
- broad ambient workspace ingestion

## Roadmap UI

Pallium uses the vendored minimap app in `tools/minimap/` as the local UI for its roadmap files. If you want to inspect the roadmap, current focus, and item details visually instead of reading the markdown files directly, run `node tools/minimap/server.js` from the repo root and open the printed local URL.

## Read Next

Recommended reading order:

- [docs/problem-and-approach.md](docs/problem-and-approach.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/agent-integration.md](docs/agent-integration.md)
- [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md)
- [docs/status.md](docs/status.md)
- [docs/overview.md](docs/overview.md)
- [docs/context/architecture.md](docs/context/architecture.md)