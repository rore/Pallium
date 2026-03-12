# Pallium Overview

Pallium is a generic memory engine for agents. The current repo proves that
idea through one concrete package: `agent_conversation_memory`.

That distinction matters:

- the platform claim is generic agent memory
- the current product claim is better continuity for agent-mediated conversations

If you are evaluating the repo as a developer, read Pallium as "memory sidecar
for an agent runtime" rather than "general AI knowledge system."

## Current Product Claim

Today Pallium is trying to answer a narrow question well:

Can an agent remember the important conclusions and work state from prior
agent-mediated conversations strongly enough to answer repeated questions more
consistently and resume interrupted work with less re-orientation cost?

The implemented answer is:

- ingest selected source evidence
- derive compact, evidence-backed memory
- retrieve memory plus supporting evidence
- preserve privacy boundaries while doing it

## Core Model

The generic core centers on five primitives:

- `SourceItem`: the stored evidence unit submitted by a producer
- `Annotation`: semantic annotations derived from a source item
- `Relation`: explicit links between evidence and derived memory
- `IndexEntry`: retrieval materialization over source or memory text views
- `MemoryObject`: reusable memory promoted from evidence

Important design choices:

- source systems remain the system of record
- source items are persisted before memory derivation
- memory is additive and evidence-backed
- higher-level memory builds on lower-level memory, not on raw global clustering

## Current Semantic Packages

The repo currently exposes three semantic entry points:

- `demo_agent_memory`
  Deterministic skeleton for local smoke usage without a live LLM provider.
- `llm_agent_memory`
  LLM-backed typed extraction path over the generic semantic interface.
- `agent_conversation_memory`
  The current product package, with privacy-aware retrieval, thread summaries,
  resumed-work signals, and routed retrieval over multiple memory layers.

## What The Current Package Accepts

Primary evidence for `agent_conversation_memory`:

- `artifact_kind="message"` with `role="user"`
- `artifact_kind="assistant_output"` with `role="assistant"`

Selected assistant-originated work artifacts:

- `artifact_kind="tool_use_summary"` with `role="assistant"`
- `artifact_kind="todo_snapshot"` with `role="assistant"`

Those selected work artifacts exist to preserve explicit progress, blocker, and
next-step state without widening the package into raw tool-log ingest.

## Memory Types Shipped Today

Lower-level and thread-level memory:

- `decision`
- `investigation_outcome`
- `thread_summary`
- fallback `discussion_summary`

Higher-level and continuity-oriented memory:

- `pattern_memory`
- `continuity_memory`
- `task_checkpoint`

What each one is for:

- `decision`
  A compact conclusion plus rationale grounded in source evidence.
- `investigation_outcome`
  A compact finding grounded in explicit investigation evidence.
- `thread_summary`
  A bounded summary of one agent-mediated thread and its carried conclusions.
- `pattern_memory`
  Cross-thread recurring recall over bounded lower-level support.
- `continuity_memory`
  Repeated-answer carry-forward for already-answered questions.
- `task_checkpoint`
  Compact resumed-work state: task, current state, findings, blocker state, and
  next supported step when present.

## Retrieval Model

Current retrieval is intentionally simple and inspectable:

1. apply structured filters
2. enforce visibility before ranking for scope-aware packages
3. run lexical retrieval over source and memory text views
4. rerank inside `agent_conversation_memory` based on query intent
5. return compact `memory_hit` and `source_hit` cards

The debug path, `POST /query/debug`, exposes:

- lexical matched tokens
- selected text views
- routed-layer choice
- visibility exclusions

This matters because Pallium is trying to be operationally explainable, not just
"semantic search that seemed to work."

## Privacy Model

Pallium currently distinguishes locality metadata from privacy boundaries.

Locality metadata:

- `container_ref`
- `thread_ref`
- `session_ref`
- `actor_ref`
- `source_ref`

Privacy boundary:

- `visibility_context`

Current phase-1 visibility rules:

- `public` query sees `public`
- `limited:X` query sees `public` and `limited:X`
- `user:U1` query sees `public` and `user:U1`

Current safety posture:

- fail closed when scoped queries omit required visibility
- preserve exact visibility through direct promotion, thread aggregation, and
  bounded consolidation
- do not widen local memory into shared memory implicitly

## What Exists Beyond The Core API

The repo includes a stronger validation surface than a typical prototype:

- semantic regression batch and baseline
- agent-conversation test bed
- recurring-question benchmark
- developer-work resumption benchmark
- routed retrieval benchmark
- consolidation strategy runner
- tiered-memory validation benchmark
- bounded public-corpus evaluation path using reviewed WildChat and WildBench
  slices

That benchmark surface is part of the product story. Pallium is not only
asserting that the memory model sounds good; it is trying to measure whether the
current slice actually improves continuity.

## Current Limits

What is intentionally not shipped yet:

- vector retrieval
- hybrid lexical plus vector fusion
- explicit shared-memory derivation across broader scopes
- cross-container bounded memory
- broad ambient workspace ingestion
- raw tool-log or runtime-event archival

## Where To Go Next

- For integration details, read [agent-integration.md](agent-integration.md).
- For privacy rules, read [privacy-and-visibility.md](privacy-and-visibility.md).
- For stable architecture truth, read [context/architecture.md](context/architecture.md).
- For queue and status, read [../roadmap/board.md](../roadmap/board.md).