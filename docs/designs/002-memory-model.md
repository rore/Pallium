# Memory Model

## Goal

Clarify what enters `Pallium`, what becomes memory, and what should stay outside
it.

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

## Three Conceptual Levels

### 1. Source Item

The raw normalized unit that came in.

Examples:

- a thread transcript
- a meeting summary
- a bot conversation summary

### 2. Annotation

What the system understood from a source item.

Examples:

- summary
- entities
- tags
- classification
- extraction candidates

### 3. Durable Memory Object

A promoted reusable knowledge object produced by the semantic layer.

Examples:

- decision
- requirement rationale
- investigation outcome
- discussion summary

The core stores these generically. Their meaning comes from the semantic layer.

## What a Memory Is

A memory is not just stored text. It is a reusable, evidence-backed knowledge
object that can help a downstream agent answer future questions with less raw
context.

## Important v1 Constraint

Not every source item should produce a memory object.

Promotion should be selective, because otherwise the system becomes a junk
store of low-value summaries.

## Likely v1 Memory Types

For a first team-knowledge-oriented semantic layer, the most useful durable
objects are likely:

- `decision`
- `investigation_outcome`
- `discussion_summary`

`requirement_rationale` may also be useful, but it overlaps with decisions and
could be introduced after the first cut if needed.

## Open Questions

- explicit ingestion policies
- candidate versus active memory states
- correction and supersession model
- confidence thresholds for promotion
