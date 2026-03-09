# Architecture

## Top-Level Shape

Pallium currently runs as a single local-first service with clear internal
module boundaries.

Main layers:

1. API layer
2. Generic core
3. Semantic use-case layer
4. Provider layer
5. Storage layer
6. Retrieval layer
7. Optional background jobs

## Implemented Semantic Slice

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
- indexing for both SourceItem and MemoryObject
- mixed query results with explicit result kinds
- compact source-hit cards with explicit event refs instead of raw full content
- evidence resolution from memory objects back to source items

Implemented semantic behavior:

- one deterministic in-repo plugin
- one LLM-backed plugin using a provider abstraction
- one summary annotation per ingested source item
- one typed_candidate annotation when decision rules or LLM extraction match
- one promoted decision memory object for decision-like inputs
- fallback discussion_summary promotion for non-decision inputs
- one supported_by relation from memory object to source item

Implemented provider behavior:

- one OpenAI-compatible adapter
- one Anthropic Claude adapter
- prompt-driven JSON output strategy with Pallium-side parsing and validation

## Generic Core

The core is domain-agnostic.

Core responsibilities:

- accept normalized source items and generic agent events
- persist source items
- persist annotations
- persist relations
- persist index entries
- persist promoted memory objects
- orchestrate processing
- orchestrate retrieval
- package evidence-backed results

Core entities:

- SourceItem
- Annotation
- Relation
- IndexEntry
- MemoryObject

The core does not know what a decision, incident, requirement, or pattern is.

## Target Model Refinement

The intended long-term shape is:

- SourceItem is the evidence layer
- Annotation is broad and additive
- MemoryObject is promoted reusable knowledge
- Relation keeps evidence and linkage explicit
- IndexEntry can target both SourceItem and MemoryObject

Important implications:

- a source item does not always become memory
- a source item may produce zero, one, or multiple memory objects
- a memory object should be able to link to one or more supporting source items
- later, higher-level memory objects may also be backed by multiple lower-level memory objects

## Semantic Use-Case Layer

The semantic layer defines meaning for a given use case.

Responsibilities:

- processing pipeline selection
- typed annotation and memory-object definitions
- promotion rules
- retrieval policy hints
- result shaping

Typed semantic artifacts are declared through schema metadata rather than
core-level domain tables.

Current generic fields for typed semantic artifacts:

- type
- schema_id
- schema_version
- payload

The first implementation uses a simple in-repo code plugin pattern, not a
dynamic plugin marketplace.

Promotion language should stay disciplined: a semantic plugin applies promotion
rules and decides whether extracted signals become durable memory objects.

## Provider Layer

The provider layer abstracts external model APIs from the semantic layer.

Responsibilities:

- send provider-specific HTTP requests
- extract text content from provider responses
- parse provider text into a JSON object
- leave semantic validation to Pallium code

The current provider contract is compatible with both OpenAI-compatible and
Claude-style APIs without exposing those wire formats to the semantic plugin.

## Producers and Consumers

Pallium does not depend on built-in connectors first.

Typical producers:

- agent runtimes
- connector services
- backfill scripts
- admin tools

Typical consumers:

- agent runtimes
- internal tools
- lightweight admin or review UIs

The current walking skeleton includes a simulated generic agent consumer so
write and read behavior are exercised end to end.

## Base Memory Flow

1. Producer submits a normalized SourceItem or assistant artifact event
2. Core persists the raw item, explicit refs, and provenance
3. Core creates a lexical index entry for the source item
4. Semantic layer creates Annotation objects
5. Semantic layer may promote one or more MemoryObject instances
6. Core stores Relation and IndexEntry objects for promoted memory
7. Consumer queries Pallium
8. Retrieval returns mixed memory and source evidence hits
9. Pallium returns compact evidence-backed results with structured refs for agent consumers

## Retrieval Model

Current implemented order of importance:

1. lexical retrieval
2. evidence resolution through relations
3. mixed result packaging across memory and source evidence

Target later direction:

1. structured filters
2. relations or entity links
3. lexical retrieval
4. optional vector retrieval

Returned results stay compact and cite supporting evidence.

## Relation Model

Relations should stay explicit and boring early on.

Stable early relation types:

- annotates
- supported_by
- mentions
- relates_to
- derived_from

## Storage and Jobs

The current implementation keeps storage simple and local-first.

- one database implementation today: SQLite
- no separate graph database requirement
- no separate vector database requirement
- no background jobs yet

The abstraction boundaries are intentionally thin so SQLite can be replaced by
Postgres later without changing the API or core flow.

## Tiered Memory Extension

Tiered memory remains an optional extension over the base flow.

It will add:

- periodic consolidation jobs
- higher-level synthetic MemoryObject instances
- links from consolidated memory to lower-level evidence

This remains additive:

- never replace lower-level evidence
- always retain support links
- keep consolidated objects queryable through the same retrieval APIs

