# Architecture

## Top-Level Shape

Pallium has three main layers:

1. Generic core
2. Semantic use-case layer
3. External producers and consumers

## Generic Core

The core is domain-agnostic.

Core responsibilities:

- accept normalized source items
- persist source items
- persist annotations
- persist relations
- persist index entries
- persist promoted memory objects
- run processing pipelines
- orchestrate retrieval
- package evidence-backed results

Core entities:

- `SourceItem`
- `Annotation`
- `Relation`
- `IndexEntry`
- `MemoryObject`

The core should not know what a decision, incident, requirement, or pattern is.

## Semantic Use-Case Layer

The semantic layer defines meaning for a given use case.

Responsibilities:

- processing pipeline selection
- typed annotation and memory-object definitions
- promotion rules
- retrieval policy
- result shaping

The semantic layer should declare types through schema metadata rather than by
requiring core-level domain tables.

Expected generic fields for typed semantic artifacts:

- `type`
- `schema_id`
- `schema_version`
- `payload`

## Producers and Consumers

Pallium should not depend on built-in connectors first.

Typical producers:

- agent runtimes
- connector services
- backfill scripts
- admin tools

Typical consumers:

- agent runtimes
- internal tools
- lightweight admin or review UIs

## Base Memory Flow

1. Producer submits a normalized `SourceItem`
2. Core persists raw item and provenance
3. Semantic layer creates `Annotation`s
4. Semantic layer may promote some outputs into durable `MemoryObject`s
5. Core creates `Relation`s and `IndexEntry`s
6. Consumer queries Pallium
7. Retrieval combines structured, lexical, and optional semantic signals
8. Pallium returns compact evidence-backed results

## Retrieval Model

Preferred order of importance:

1. structured filters
2. relations/entity links
3. lexical retrieval
4. optional vector retrieval

Returned results should stay compact and cite supporting evidence.

## Tiered Memory Extension

Tiered memory is an optional extension over the base flow.

It adds:

- periodic consolidation jobs
- higher-level synthetic `MemoryObject`s
- links from consolidated memory to lower-level evidence

This should remain additive:

- never replace lower-level evidence
- always retain support links
- keep consolidated objects queryable through the same retrieval APIs
