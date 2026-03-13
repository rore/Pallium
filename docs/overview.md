# Concepts And Model

This is the second-level concepts doc.

If you are still evaluating Pallium at a product level, read these first:

- [../README.md](../README.md)
- [problem-and-approach.md](problem-and-approach.md)
- [getting-started.md](getting-started.md)

Read this file when you want the internal model behind the product story.

## Plain-English Mental Model

Pallium does four things:

1. stores selected evidence from an agent-mediated conversation
2. derives compact reusable memory from that evidence
3. keeps memory linked back to the supporting source items
4. retrieves both memory and source evidence together

That is the plain-English model. The internal terms come after that.

## Core Implementation Vocabulary

The generic core centers on five primitives:

- `SourceItem`
  one stored evidence unit submitted by a producer
- `Annotation`
  semantic annotations derived from a source item
- `Relation`
  explicit links between evidence and derived memory
- `IndexEntry`
  retrieval materialization over source or memory text views
- `MemoryObject`
  reusable memory promoted from evidence

These terms matter for contributors and deeper integrators. They are not the
first thing a new evaluator needs.

## Current Package Surface

The repo currently exposes three runtime and package entry points:

- `demo_agent_memory`
  deterministic skeleton for local smoke usage without a live LLM provider
- `llm_agent_memory`
  LLM-backed typed extraction path over the generic semantic interface
- `agent_conversation_memory`
  the current product package focused on repeated questions, resumed work, and
  scoped continuity

## What The Current Package Actually Stores

The current product slice is built around selected evidence, not exhaustive
mirroring.

Primary evidence today:

- user messages
- final assistant outputs
- selected assistant work artifacts such as compact findings, blocker state, or
  next steps

The package then derives compact reusable memory that can represent jobs such
as:

- prior conclusions
- investigation findings
- thread orientation
- resumed-work checkpoints
- bounded cross-thread carry-forward

The internal memory kinds exist to serve those jobs. They are implementation
labels, not the first story you should tell a new reader.

## Retrieval Model

Current retrieval flow is:

1. apply structured filters
2. enforce visibility before ranking for scope-aware packages
3. run lexical retrieval over source and memory text views
4. rerank inside `agent_conversation_memory` based on the query shape
5. return compact `memory_hit` and `source_hit` cards

`POST /query/debug` exposes the retrieval trace, including lexical matches,
selected text views, routed-layer choice, and visibility exclusions.

## Privacy Model In One Sentence

Locality is not privacy.

`container_ref`, `thread_ref`, and related refs help correlate events. The
actual privacy boundary for the current package is `visibility_context`, and it
is enforced before ranking.

## Current Limits

The current concepts and model do not imply that Pallium already supports:

- vector retrieval
- hybrid fusion
- explicit shared-memory publication
- broad ambient workspace ingestion
- full workflow-state orchestration

## Read Next

- For runtime usage, read [agent-integration.md](agent-integration.md).
- For privacy detail, read [privacy-and-visibility.md](privacy-and-visibility.md).
- For stable architecture truth, read [context/architecture.md](context/architecture.md).