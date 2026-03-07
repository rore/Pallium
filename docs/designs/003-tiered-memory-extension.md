# Tiered Memory Extension

## Goal

Add an optional extension that periodically consolidates lower-level memory into
higher-level reusable memory objects.

## Why It Matters

Tiered memory can improve long-term usefulness by:

- compressing noisy history
- grouping related memories
- surfacing recurring patterns
- improving retrieval across long time spans
- reducing prompt bloat for broad questions

## Position in the Architecture

Base Pallium flow:

- source item
- annotations
- durable memory object
- retrieval

Tiered extension adds:

- periodic consolidation jobs
- synthetic higher-level memory objects
- evidence links to lower-level objects

## Conceptual Levels

### Direct memory

Objects directly extracted from source items.

Examples:

- decision
- discussion summary
- investigation outcome

### Consolidated memory

Objects built from multiple lower-level objects.

Examples:

- topic summary
- pattern memory
- design evolution
- implementation pattern

The implementation should not hardcode a rigid hierarchy into the core.

## Principles

1. Additive only.
   Never replace original evidence.

2. Evidence-backed.
   Consolidated memory must point to supporting lower-level objects.

3. Periodic, not inline.
   Consolidation should run as background work.

4. Bounded scope.
   Consolidate within a topic, entity set, cluster, or time window.

5. Queryable like normal memory.
   Consolidated objects should use the same retrieval surface.

## Example Pipeline

1. select candidate memory objects
2. cluster by entities, relations, lexical overlap, optional embeddings, and
   time proximity
3. synthesize a higher-level object
4. persist it as a generic `MemoryObject`
5. link it back using relations such as `consolidates` and `supported_by`

## High-Value First Consolidation Target

A minimal first extension could produce `pattern_memory` from related direct
memories such as:

- investigations
- discussions
- decisions

This gives a strong signal boost without requiring a deep hierarchy.

## Additional Concerns

- freshness and staleness of consolidated objects
- rebuildability if models or prompts change
- retrieval weighting between direct and consolidated objects
