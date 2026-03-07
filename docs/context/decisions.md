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

## Open

### Ingestion policy

Need explicit rules for when a producer should submit a source item.

### Memory lifecycle

Need a clear model for candidate, active, corrected, rejected, superseded, and
consolidated memory states.

### Query contract

Need to define how generic the query API remains versus how much retrieval
intent is expressed by semantic layers.
