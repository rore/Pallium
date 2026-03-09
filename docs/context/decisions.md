# Decisions

## Accepted

### 2026-03-07 - Generic core with semantic layer

Pallium will be built as a generic memory core with an extensible semantic
use-case layer on top.

Why:

- keeps the project reusable beyond a single internal consumer
- avoids baking domain objects into the core
- supports OSS positioning as a memory tool for agents

### 2026-03-07 - Source systems remain systems of record

Pallium should not mirror external systems wholesale.

Why:

- avoids duplication of authoritative stores
- keeps memory focused on derived knowledge
- reduces noise and storage bloat

### 2026-03-07 - Tiered memory is an extension, not v1 core

Tiered consolidation is important and should be designed for, but not required
for the first implementation.

Why:

- keeps v1 manageable
- preserves a differentiated long-term direction
- allows consolidation to be added without distorting the core model

### 2026-03-08 - Build a walking skeleton before deep model hardening

The project should start with a minimal end-to-end skeleton that includes all
major system elements, then evolve iteratively.

Why:

- reduces the risk of locking in the wrong abstractions too early
- keeps the system mentally graspable while the design is still evolving
- gives continuous end-to-end proof as capabilities expand

### 2026-03-08 - Use Python for the main Pallium service

The first implementation should use Python.

Why:

- best fit for rapid iteration on semantic processing and consolidation logic
- strong ecosystem for retrieval and text-heavy workflows
- good enough performance for a local-first, non-multi-tenant internal service
- aligns with the walking-skeleton approach better than a heavier runtime

### 2026-03-08 - Use a single-service architecture first

Pallium should start as a single local-first service with clear internal module
boundaries instead of multiple services.

Why:

- keeps the first implementation small and understandable
- preserves end-to-end flow without distributed-system overhead
- still allows later extraction of boundaries if needed

### 2026-03-08 - Start with a simulated agent-memory consumer

The first end-to-end usage should include a simulated generic agent that uses
Pallium as its unstructured memory layer.

Why:

- keeps the project grounded in a real consumer workflow
- exercises both write and read paths from the start
- avoids building storage and retrieval without proving actual use

### 2026-03-09 - Keep external dependencies behind replaceable abstractions

The first slice should isolate external dependencies behind thin interfaces.

Why:

- keeps the core and API independent of SQLite-specific logic
- preserves the ability to add Postgres later without changing core flow
- applies the same design posture to retrieval and semantic processing

### 2026-03-09 - Memory objects are explicitly evidence-backed

The intended model is that memory objects always point to one or more
supporting source items.

Why:

- keeps durable memory grounded in evidence
- supports later many-to-many evidence relationships without changing the core shape
- prepares the model for later synthesis and consolidation

### 2026-03-09 - Promotion is plugin-driven and selective

A source item does not automatically become a memory object.

Why:

- preserves the distinction between evidence, interpretation, and durable memory
- keeps the generic core disciplined
- avoids turning the system into a store of low-value promoted summaries

### 2026-03-09 - Mixed retrieval over memory and source evidence

The next retrieval layer should return both promoted memory and raw evidence in one explicit response contract.

Why:

- moves Pallium closer to its real value than memory-only lexical search
- keeps answers grounded in raw evidence
- reduces the risk that retrieval overfits to promoted summaries only

### 2026-03-09 - Validate typed memory before LLM extraction

The next semantic milestone should introduce deterministic typed memory for `decision` before adding an LLM-backed semantic plugin.

Why:

- separates architecture risk from LLM-quality risk
- proves that typed promotion works before semantic quality becomes the main variable
- keeps the next LLM milestone focused on extraction quality against a stable contract

### 2026-03-09 - Use provider-neutral prompts for structured semantic extraction

The first LLM-backed semantic milestone should work across both OpenAI-compatible and Claude-style APIs through a shared Pallium-side extraction contract.

Why:

- avoids provider lock-in through JSON mode or tool-calling features
- keeps the semantic plugin unaware of provider wire formats
- makes semantic quality comparable across providers under one extraction contract

## Open

### Ingestion policy

Need explicit rules for when a producer should submit a source item.

### Memory lifecycle

Need a clear model for candidate, active, corrected, rejected, superseded, and
consolidated memory states.

### Query contract beyond mixed hits

Need to define how far the query API should evolve toward structured filters,
retrieval intent, and result-type-specific controls.
