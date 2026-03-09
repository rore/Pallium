# Architecture

## Top-Level Shape

Pallium runs as a single local-first service with clear internal module boundaries.

Main layers:

1. API layer
2. Generic core
3. Semantic use-case layer
4. Provider layer
5. Storage layer
6. Retrieval layer
7. Optional background jobs

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

## Implemented Semantic Behavior

Implemented semantic behavior now includes:

- deterministic and LLM-backed semantic plugins
- one summary annotation per ingested source item
- one typed candidate annotation when extraction matches a typed memory path
- promoted typed memory for:
  - `decision`
  - `investigation_outcome`
- fallback `discussion_summary` for non-typed extraction results
- one `supported_by` relation from memory object to source item
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

Tiered memory remains an intended extension, not part of the current executable slice.

It should build on top of the stronger lower-level memory model now in place rather than replacing it.
