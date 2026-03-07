# Core Architecture

## Goal

Define the base architecture for `Pallium` as a generic memory engine for
agents.

## Positioning

Pallium is:

- a generic memory engine
- local-first
- evidence-backed
- extensible through semantic layers

Pallium is not:

- a system of record
- a connector platform first
- an agent runtime
- a replacement for source retrieval

## Core Shape

Pallium has three major layers:

1. generic core
2. semantic use-case layer
3. external producers and consumers

## Generic Core

The core owns durable mechanics only.

Responsibilities:

- ingest normalized source items
- persist source items
- persist annotations
- persist relations
- persist index entries
- persist durable memory objects
- orchestrate pipelines
- orchestrate retrieval
- package evidence-backed results
- track provenance and versioning

Core entities:

- `SourceItem`
- `Annotation`
- `Relation`
- `IndexEntry`
- `MemoryObject`

The core should not know what a decision, requirement, investigation, or
pattern is.

## Semantic Layer

The semantic layer defines meaning.

Responsibilities:

- processing-step selection
- typed annotation definitions
- typed durable memory definitions
- promotion rules
- retrieval policy
- result shaping

The semantic layer should not require domain-specific core tables. Instead,
typed artifacts should be stored generically with schema metadata such as:

- `type`
- `schema_id`
- `schema_version`
- `payload`

This keeps the core generic while still allowing validation and versioned
semantics.

## Producers and Consumers

Pallium should begin with APIs, not built-in connectors.

Typical producers:

- agent runtimes
- connector services
- backfill scripts
- admin tools

Typical consumers:

- agent runtimes
- internal tools
- review/admin UIs later

## Base Flow

1. Producer submits a normalized source item.
2. Core persists the raw item and provenance.
3. Semantic layer creates annotations.
4. Semantic layer may promote some outputs into durable memory objects.
5. Core creates relations and index entries.
6. Consumer queries Pallium.
7. Retrieval combines structured, lexical, and optional semantic signals.
8. Pallium returns compact evidence-backed results.

## Retrieval Model

Preferred retrieval order:

1. structured filters
2. relations or entity links
3. lexical retrieval
4. optional vector retrieval

Embeddings should be an enhancement, not the whole foundation.

## Key Open Questions

- memory lifecycle states
- ingestion policy and promotion criteria
- query contract between generic core and semantic layer
- exact storage approach for v1
