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

### 2026-03-09 - Treat token budget as a first-class semantic design constraint

Prompt and response size should be managed deliberately as the semantic layer evolves.

Why:

- source item content is often the dominant token cost in extraction runs
- prompt growth can quietly make evals and production ingestion expensive
- explicit token-budget awareness helps balance precision against operating cost

### 2026-03-09 - Store prompt provenance with LLM-derived semantic artifacts

LLM-derived annotations, memory objects, and eval traces should record the prompt schema id, prompt schema version, and prompt variant that produced them.

Why:

- makes later maintenance and cleanup possible when prompts change
- supports comparing semantic behavior across prompt revisions
- keeps stored derived memory auditable instead of treating prompts as invisible runtime state

### 2026-03-12 - Position Pallium as derived knowledge memory for agents

Pallium should be positioned as a generic memory engine whose differentiated direction is derived knowledge memory, not only fact storage or episodic transcript recall.

Why:

- matches the implemented memory objects such as `decision`, `investigation_outcome`, `thread_summary`, `pattern_memory`, and `continuity_memory`
- better explains why evidence links, lifecycle, consolidation, and routed retrieval matter
- keeps the public claim narrow while still describing the real architectural direction

### 2026-03-20 - RRF as fusion baseline

Reciprocal Rank Fusion with k=60 and score scale=600. Chosen because it avoids
raw score blending between incompatible score scales (lexical token count vs
cosine similarity). Validated with real BGE-small embeddings.

### 2026-03-20 - Plugin-owned SourceItem embedding

SourceItem vector embedding is decided by the semantic plugin, not hard-coded in
core. Decoupled from semantic processing success (persisted before processing,
survives extraction failures). Policy: messages + assistant outputs >= 40 chars.

### 2026-03-20 - Local-first embedding via ONNX

OnnxEmbeddingProvider wraps onnxruntime + tokenizers directly, bypassing
fastembed's dependency chain. Same model, same output. fastembed works on
Python 3.12/3.13; onnx works on all supported versions.

### 2026-03-20 - Minimum similarity threshold 0.55

Validated that 0.3 provides zero noise filtering. 0.55 cuts false positives from
11 to 5 per query with zero recall loss. Provider-specific (BGE-small), not
architecture-level.

### 2026-03-20 - Minimum embedding content guard 40 chars

Texts shorter than 40 characters are too generic for meaningful vector
discrimination. Applied as a length check in build_embedding_text() and
source_item_embedding_text().

### 2026-03-21 - Bearer auth style for proxy-compatible providers

LLM provider config supports `auth_style` ("native" or "bearer") to switch
between `x-api-key` (direct Anthropic) and `Authorization: Bearer` (proxy
endpoints). Default is "native" for backward compatibility.

### 2026-03-21 - Per-role model configuration

Semantic packages support `model_roles` mapping (role -> model name) alongside
the package-wide `model` default. Mirrors the existing `prompt_variants`
pattern. Enables cost/quality optimization per LLM call type (e.g., Sonnet for
extraction, Haiku for summaries and resolver).

### 2026-03-21 - Combined LLM calls for thread and consolidation

Thread rebuild and consolidation each use a single combined LLM call instead of
separate extraction + enrichment calls. Reduces thread rebuild from 4 calls to
1 and consolidation from 2 to 1. Motivated by proxy rate limits and general
efficiency. Enrichment context is folded into the parent prompt schema.

### 2026-03-21 - Haiku for thread aggregation and consolidation roles

Thread aggregation (summary + checkpoint) and consolidation (pattern + continuity
memory) use Haiku instead of Sonnet. Benchmarked: identical routing accuracy
(11/11), improved work resumption contract (100% vs 92.3%), no wrong memory.
These roles have simpler schemas and code-level fallback defaults that compensate
for weaker LLM output. Write extraction stays on Sonnet (quality-critical,
14-field schema with strict evidence rules).

## Open

### Ingestion policy

Need explicit rules for when a producer should submit a source item.

### Memory lifecycle

Need a clearer generic lifecycle model that eventually covers:

- richer lineage across derivation, consolidation, and supersession
- confidence as a generic trust signal
- decay as retrieval-time freshness weighting
- any later expansion beyond the current `active` and `superseded` states

### Query contract beyond mixed hits

Need to define how far the query API should evolve toward structured filters,
retrieval intent, and result-type-specific controls.
