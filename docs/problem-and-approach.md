# Problem And Approach

This document explains the developer problem Pallium is trying to solve and why
the current design is narrower than "agent memory" in the abstract.

## The Problem

Most agents can see the current thread. Many of them still fail at continuity.

Typical failure modes:

- they forget why a decision was made
- they lose investigation outcomes across later follow-ups
- they resume interrupted work without the right blocker, progress, or next-step
  state
- they blur public and private memory boundaries

This is the gap Pallium is aimed at.

## Why Common Approaches Break Down

### Transcript Replay

Transcript replay gives raw history, but it has obvious costs:

- too much text
- too much noise
- repeated prompt cost
- weak distinction between important conclusions and incidental chatter

### Prompt Summaries

Prompt summaries are useful, but they tend to be:

- lossy
- hard to audit
- easy to overwrite with a fresher but worse summary
- disconnected from source evidence

### Vector Search Alone

Vector search is useful for finding related text. It is weaker as a full
continuity layer because it does not by itself give you:

- explicit durable conclusions
- compact resumed-work state
- evidence-backed memory objects
- clear scoped visibility rules

### Runtime-Local State

Runtime-local state helps within one active execution path. It is weaker when
you need:

- cross-thread reuse
- later follow-up recall
- explainable evidence links
- scoped memory that survives beyond one in-memory session

## Pallium's Approach Today

Right now Pallium does five things:

1. stores selected evidence instead of mirroring everything
2. derives compact reusable memory from that evidence
3. keeps memory linked back to the supporting source items
4. retrieves compact memory and source evidence together
5. enforces scoped visibility before ranking for the current package

The key distinction is that Pallium is not only retrieving past text. It is
trying to preserve reusable continuity objects: compact conclusions, findings,
and work-state checkpoints that remain linked to evidence.

This is why the current docs describe Pallium as a memory sidecar rather than a
transcript store or search wrapper.

## Why Selective Ingest Matters

Pallium is not trying to ingest every event an agent sees.

Selective ingest is part of the design, not a temporary limitation. The current
goal is to preserve the few pieces of context that are worth carrying forward,
not to become a warehouse for everything the runtime sees.

For the current package, those high-value inputs are mostly:

- user messages that define the question or task
- final assistant outputs that contain reusable conclusions
- selected assistant work artifacts that capture findings, blockers, or next
  steps

## Why Evidence-Backed Memory Matters

The current product focus is not only trying to retrieve relevant text. It is
trying to preserve reusable context with traceable support.

That means Pallium can return:

- a compact memory card for fast orientation
- source evidence refs for grounding and auditability

This is a better fit for repeated-question and resumed-work scenarios than
relying only on raw retrieval.

## Current Product Focus

The present claim is intentionally narrow:

Pallium helps an agent stay oriented across repeated questions and interrupted
or resumed work in agent-mediated conversations.

That is narrower than:

- broad workspace search
- org-wide knowledge memory
- general connector sync
- full workflow-state orchestration

## Current Boundaries

Good fit today:

- agent-mediated conversation history
- repeated question answering
- resumed investigation or implementation work
- privacy-safe scoped recall in the same bounded context

Poor fit today:

- passive archive of all chat history
- raw tool or MCP event storage
- broad company knowledge search
- general-purpose memory shared across many unrelated contexts

## What To Read Next

- For a live local walkthrough, read [getting-started.md](getting-started.md).
- For runtime usage, read [agent-integration.md](agent-integration.md).
- For request and response shapes, read [http-api.md](http-api.md).
- For privacy rules, read [privacy-and-visibility.md](privacy-and-visibility.md).
- For what gets stored and derived, read [memory-model.md](memory-model.md).
- For product proof, read [validation.md](validation.md).
- For internal concepts, read [overview.md](overview.md).
