![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Agents are bad at continuity.

They forget why decisions were made, lose investigation outcomes, and struggle
to resume interrupted work without replaying transcripts or rediscovering
context.

Pallium is a local-first memory sidecar that stores selected evidence, derives
compact evidence-backed memory, and returns small reusable memory and evidence
cards so an agent can answer repeated questions and resume work more reliably.

The current product slice is deliberately narrow: agent-mediated conversations,
repeated questions, resumed-work continuity, and privacy-safe scoped memory.

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

- better repeated-question recall
- better resumed-work continuity
- privacy-safe scoped memory for public and private contexts
- compact evidence-backed results instead of transcript replay
- debuggable retrieval through `POST /query/debug`

## What Is Shipped Today

This repo already contains a real implemented slice, not just design docs:

- one local-first FastAPI service
- SQLite-backed storage
- `POST /items`, `POST /query`, and `POST /query/debug`
- selected ingest for user messages, assistant outputs, and bounded assistant
  work artifacts
- compact `memory_hit` and `source_hit` results
- lexical retrieval over both memory and source evidence
- package-owned routed retrieval for the current conversation-memory slice
- fail-closed `visibility_context` enforcement for scoped memory
- thread aggregation, higher-level carry-forward, and resumed-work checkpoints

## Why Believe It Is Real?

The repo also has a stronger validation story than most agent-memory projects:

- semantic regression coverage for the typed extraction path
- recurring-question benchmark coverage
- developer-work resumption benchmark coverage
- routed retrieval benchmark coverage
- public-corpus evaluation workflows for reviewed WildChat and WildBench slices
- privacy-aware retrieval and visibility exclusion trace in the current package

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

- run the local service
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

## Read Next

Recommended reading order:

- [docs/problem-and-approach.md](docs/problem-and-approach.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/agent-integration.md](docs/agent-integration.md)
- [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md)
- [docs/status.md](docs/status.md)
- [docs/overview.md](docs/overview.md)
- [docs/context/architecture.md](docs/context/architecture.md)