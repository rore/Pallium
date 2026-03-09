# Memory Model

## Goal

Clarify what enters Pallium, what becomes memory, and how evidence, semantic
interpretation, and durable memory relate to each other.

## What Goes In

Pallium should ingest selected normalized source items, not everything.

Good first inputs:

- chat threads or discussion summaries
- meeting summaries
- bot investigation summaries
- selected excerpts plus references when an external source matters to the
  discussion

## What Stays Outside

These remain systems of record and should usually be queried directly:

- issue trackers
- code and documentation repositories
- telemetry and logs
- document management platforms

Pallium may store references to them or derived knowledge based on them, but it
should not mirror them wholesale by default.

## Core Layers

### 1. SourceItem

The raw normalized unit that came in.

Examples:

- a thread transcript
- a meeting summary
- a bot conversation summary
- a selected external excerpt with provenance

Source items are the evidence layer. If an item is ingested, it should be
stored even if it never becomes memory.

### 2. Annotation

What the system understood from a source item.

Annotations are broad and additive. A single source item should be able to
accumulate multiple annotations over time.

Stable early annotation families:

- summary
- entities
- tags or classification
- typed candidate

Examples of typed candidates:

- decision_candidate
- investigation_candidate
- rationale_candidate

Annotations are used to:

- enrich retrieval and filtering
- support promotion rules
- link related evidence through shared entities or tags
- feed later consolidation jobs

### 3. MemoryObject

A promoted reusable knowledge object produced by a semantic layer.

Examples:

- decision
- requirement rationale
- investigation outcome
- discussion summary
- later, topic summary or pattern memory

The core stores these generically. Their meaning comes from the semantic layer.

A memory object is not just stored text. It is reusable, evidence-backed
knowledge that helps a downstream agent answer future questions with less raw
context.

## Promotion Model

A source item does not automatically become memory.

The intended shape is:

- source item -> zero memory objects
- source item -> one memory object
- source item -> multiple memory objects

Promotion is not fuzzy "the system thinks this matters" behavior. A semantic
use-case plugin applies promotion rules and decides whether typed annotations or
other extracted signals should become durable memory objects.

That keeps the architecture disciplined:

- core stores primitives
- semantic layers define meaning
- promotion rules decide what becomes durable memory

## Evidence Model

Memory objects should be explicitly evidence-backed from day one.

Even when the first slice mostly behaves like one source item produces one
memory object, the intended model is many-to-many:

- one memory object may be supported by multiple source items
- one source item may support multiple memory objects

This should be represented through explicit relations, not by collapsing the
source items into the memory object.

Examples:

- a decision memory supported by a Slack thread, a meeting summary, and a doc
  excerpt
- a later pattern memory supported by multiple investigations and discussions

## Relation Model

Relations are important, but should stay boring and explicit early on.

Good stable relation types:

- annotates
- supported_by
- mentions
- relates_to
- derived_from

The goal is to capture clear evidence and linkage, not to introduce vague graph
semantics too early.

## Index Model

Index entries should not be limited to memory objects.

The intended target model is:

- some index entries target SourceItem
- some index entries target MemoryObject

Why:

- sometimes retrieval should return raw evidence
- sometimes retrieval should return distilled knowledge
- later retrieval can combine both without changing the core shape

## Important v1 Constraint

Not every source item should produce a memory object.

Promotion should stay selective, because otherwise the system becomes a junk
store of low-value summaries.

## Likely Early Memory Types

For a first team-knowledge-oriented semantic layer, the most useful durable
objects are likely:

- decision
- investigation_outcome
- discussion_summary

Requirement rationale may also be useful, but it overlaps with decisions and
could be introduced after the first cut if needed.

## Open Questions

- explicit ingestion policies
- candidate versus active memory states
- correction and supersession model
- confidence thresholds for promotion
- when retrieval should prefer raw evidence versus promoted memory
