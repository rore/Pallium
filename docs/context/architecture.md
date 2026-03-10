# Architecture

## Top-Level Shape

Pallium runs as a single local-first service with clear internal module boundaries.

Main layers:

1. API layer
2. Generic core
3. Reusable capability layer
4. Semantic use-case layer
5. Provider layer
6. Storage layer
7. Retrieval layer
8. Optional background jobs

## Implemented Core and Retrieval Slice

Implemented HTTP endpoints:

- POST /items
- POST /query

Implemented abstractions:

- storage provider boundary
- retrieval provider boundary
- semantic plugin boundary
- LLM provider boundary

Implemented storage and retrieval behavior:

- SQLite-backed storage provider
- lexical retrieval over indexed text views
- indexing for both `SourceItem` and `MemoryObject`
- mixed query results with explicit result kinds
- compact source-hit cards with explicit event refs instead of raw full content
- evidence resolution from memory objects back to source items
- lifecycle-aware retrieval that excludes superseded memory by default

## Target Retrieval Architecture

The current executable slice is structured-plus-lexical retrieval. The target retrieval architecture is hybrid retrieval.

Target query flow:

1. structured narrowing
2. lexical retrieval over named text views
3. vector retrieval over selected text views
4. explicit fusion
5. optional reranking
6. compact, evidence-backed result packaging

Design implications:

- lexical retrieval remains mandatory because technical memory includes exact names, IDs, acronyms, and rare terms
- vector retrieval is additive, not a replacement for lexical retrieval
- fusion should be explicit rather than implicit score blending
- retrieval should stay debuggable so Pallium can explain whether a hit came from lexical retrieval, vector retrieval, or fusion
- both `SourceItem` and `MemoryObject` remain first-class retrieval targets

Current intended fusion baseline:

- Reciprocal Rank Fusion (RRF) first
- weighted blending only later if labeled evaluation justifies it

## Implemented Semantic Behavior

Implemented semantic behavior now includes:

- an explicit `agent_conversation_memory` runtime package over the current LLM-backed semantic path
- deterministic and LLM-backed semantic plugins
- one summary annotation per ingested source item
- one typed candidate annotation when extraction matches a typed memory path
- promoted typed memory for:
  - `decision`
  - `investigation_outcome`
- fallback `discussion_summary` for non-typed extraction results
- prompt provenance attached to LLM-derived annotations and memory objects

Prompt provenance fields currently tracked:

- `prompt_schema_id`
- `prompt_schema_version`
- `prompt_variant`

## Generic Core

The core remains domain-agnostic.

Core entities:

- `SourceItem`
- `Annotation`
- `Relation`
- `IndexEntry`
- `MemoryObject`

Important model properties:

- a source item does not always become memory
- a source item may produce zero, one, or multiple memory objects over time
- memory objects are evidence-backed and may point to one or more supporting source items
- relations stay explicit and boring early on

## Reusable Capabilities

Pallium now has its first reusable capability between the generic core and semantic packages: thread aggregation.

Current thread-capability behavior:

- atomic ingest remains the source-item unit
- items can be grouped by `container_ref + thread_ref`
- the capability rebuilds a deterministic thread aggregate as new items arrive
- semantic packages can consume that aggregate without making thread a universal core entity

The first package using this capability is `agent_conversation_memory`, which produces a queryable `thread_summary` memory object.

## Agent Conversation Memory Package

The first concrete product package is now agent conversation memory.

That package reuses the generic core and existing typed-memory path. It should be treated as the first semantic package proving value on top of Pallium, not as the definition of the platform itself.

Current package boundary:

- primary evidence units:
  - `artifact_kind="message"` with `role="user"`
  - `artifact_kind="assistant_output"` with `role="assistant"`
- primary value targets:
  - recurring-question recall
  - cross-thread continuity
  - assistant consistency
- explicit non-goals for the package:
  - all workplace chat
  - arbitrary ambient messages that never flowed through the agent
  - full transcript replay as the default retrieval shape

The package reuses the current typed-memory extraction path rather than introducing a separate semantic engine.

It now also uses the shared thread aggregation capability to build one active `thread_summary` memory object per `container_ref + thread_ref`. Each thread summary is evidence-backed, lifecycle-managed through supersession, and can carry forward active `decision` and `investigation_outcome` conclusions from that conversation thread.

## Lifecycle

Promoted memory now has a minimal lifecycle model:

- `active`
- `superseded`

Current behavior:

- newly promoted memory defaults to `active`
- superseded memory remains stored and evidence-backed
- default retrieval does not surface superseded memory as current
- raw source evidence remains searchable even when a promoted memory object is superseded

## Semantic Regression

The repo now treats semantic evaluation as a first-class product asset.

Implemented pieces:

- one committed JSONL regression batch
- one eval harness that records:
  - raw LLM output
  - parsed JSON
  - normalized extraction
  - final promoted artifacts
- one baseline metrics document for the chosen model and prompt path

Current chosen path:

- provider: OpenAI-compatible
- model: `gpt-5-mini`
- prompt variant: `strict_typed_memory_v4_evidence_guarded`
- prompt schema: `typed_memory_extraction`
- prompt schema version: `v4`

## Tiered Memory

Tiered memory remains the next intended extension, not part of the current executable slice.

It should build over:

- `thread_summary`
- `decision`
- `investigation_outcome`

rather than jumping directly from raw atomic events to higher-level memory.
