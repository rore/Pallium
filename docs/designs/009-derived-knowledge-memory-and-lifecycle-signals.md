# Derived Knowledge Memory And Lifecycle Signals

## Purpose

This document captures two related design directions for `Pallium`:

1. how to position Pallium within the broader memory-system landscape
2. how future generic lifecycle signals should extend the memory engine

The goal is to store durable design intent without overcommitting the near-term
roadmap.

## Architectural Styles In The Current Memory Ecosystem

Agent-memory systems are converging into three broad shapes.

### 1. Fact memory

Typical flow:

```text
conversation
   -> extract facts
   -> store facts
   -> retrieve facts later
```

Typical artifacts:

- user preferences
- profile facts
- stable project metadata

Typical value:

- personalization
- user profile continuity
- preference recall

Main property:

- memory objects are small facts

### 2. Episodic memory

Typical flow:

```text
interaction
   -> store episode
   -> embedding / lexical retrieval
   -> retrieve relevant episode later
```

Typical artifacts:

- conversation summaries
- previous task attempts
- prior investigations as episodes

Typical value:

- conversational continuity
- replay of past interactions
- recovery of earlier context

Main property:

- memory objects are episodes

### 3. Derived knowledge memory

Typical flow:

```text
source events
   -> semantic interpretation
   -> derived knowledge objects
   -> evidence-backed retrieval
```

Typical artifacts:

- decisions
- investigation outcomes
- thread summaries
- patterns
- carry-forward answers
- later, rules or organizational guidance

Typical value:

- preserving what was learned
- reducing repeated reasoning
- making prior conclusions reusable
- compact historical carry-forward for agents

Main property:

- memory objects are knowledge, not only facts or episodes

## Where Pallium Sits

Pallium is clearly in the third category.

Its current memory objects are not profile facts and not raw transcript replay.
They are already moving toward derived knowledge:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `pattern_memory`
- `continuity_memory`

This distinction matters because most systems marketed as "agent memory" are
primarily fact memory or episodic recall. Pallium is different because it is
trying to preserve reusable conclusions and patterns from agent-mediated
conversations.

## Product Positioning Implication

The public claim should remain narrow even if the architecture is broader.

Recommended framing:

- Pallium is a generic memory engine for agents
- its differentiated strength is derived knowledge memory
- the first proven product slice is derived knowledge memory for
  agent-mediated conversations

This is stronger than calling Pallium merely "chat memory" or "agent memory,"
but still narrower and safer than claiming general organizational knowledge
management.

## Why This Direction Is Hard

Derived knowledge memory is harder than fact or episodic memory because it
requires:

- semantic interpretation
- evidence tracking
- conflict handling
- revision over time
- careful retrieval weighting

Those requirements are already visible in Pallium's existing architecture:

- evidence relations
- lifecycle state
- tiered memory
- consolidation
- retrieval trace
- package-owned routing

This is why the next differentiators should be generic lifecycle improvements,
not just more storage or more retrieval modes.

## Future Lifecycle Layer

Three future extensions fit naturally above the current primitives:

- memory lineage
- memory confidence
- memory decay

These are not memory kinds and not semantic-package concepts.
They are generic memory-engine capabilities.

### Shared Principles

All three should follow the same design posture:

1. non-destructive memory evolution
2. evidence-backed knowledge
3. generic engine ownership rather than package semantics
4. primary effect on retrieval influence and reasoning weight, not storage deletion
5. transparency and inspectability over opaque automation

## Memory Lineage

### Purpose

Lineage explains how a memory object came to exist and how it evolved.

A memory object should be traceable in terms of:

- which source evidence supported it
- which annotations contributed to it
- which earlier memories contributed to it
- which consolidation or synthesis step produced it
- which earlier memory it superseded

### Core Principle

Memory is not only stored. It evolves through explicit transformations.

Conceptual chain:

```text
SourceItem
   -> Annotation
   -> MemoryObject
   -> Consolidation
   -> MemoryObject
```

### Design Direction

Lineage should be represented through explicit relations and provenance, for
example:

```text
memory_object supported_by source_item
memory_object derived_from annotation
memory_object consolidates memory_object
memory_object supersedes memory_object
```

Lineage must remain additive and immutable:

- new transformations create new objects
- prior objects remain preserved
- superseded objects are not deleted

### Architectural Boundary

- `core/` should own the generic relation model and provenance shape
- `capabilities/` may compute reusable lineage-producing transforms such as consolidation
- `semantic/` may declare package-specific meaning, but should not redefine lineage itself

### Value

Lineage supports:

- explainable memory
- debuggability
- safe consolidation
- transparent knowledge evolution

## Memory Confidence

### Purpose

Confidence expresses how trustworthy a memory object is.

It should help Pallium distinguish between:

- well-supported conclusions
- weak summaries
- speculative or thinly grounded synthesis
- memories later weakened by contradiction

### Core Principle

Confidence should emerge from both structural and semantic signals.
It should not be a pure LLM belief score.

Useful inputs include:

- supporting evidence count
- supporting memory count
- diversity of support across discussions
- contradiction or later supersession
- source reliability when such metadata exists
- synthesis certainty, if explicitly produced

### Design Direction

Confidence should start as bounded, inspectable metadata, not a magical universal truth number.

Recommended initial posture:

- attach confidence metadata to `MemoryObject`
- compute it from explicit structural signals first
- allow semantic signals later as additive inputs
- use confidence to influence retrieval ranking and consolidation decisions
- do not block memory creation solely because confidence is low

### Architectural Boundary

- `core/` should own the generic confidence fields and retrieval hooks
- `capabilities/` may provide reusable confidence computation from relations or reinforcement
- `semantic/` may contribute package-specific inputs, but should not own the confidence concept itself

### Value

Confidence supports:

- safer retrieval ranking
- conflict-aware memory use
- better weighting of higher-level synthesis
- less over-trust in weak derived memory

## Memory Decay

### Purpose

Decay reduces the influence of stale memory over time without deleting history.

Many memories remain valid historically but should not dominate current answers
forever.

### Core Principle

Decay should affect influence, not storage existence.

Older or unreinforced knowledge may become:

- less relevant
- less preferred than reinforced knowledge
- secondary to newer related memory

### Design Direction

Decay should begin as retrieval-time freshness weighting derived from temporal
signals such as:

- age of the memory
- time since last reinforcement
- presence of newer related memory
- lifecycle state such as `active` vs `superseded`

Conceptually:

```text
effective_score = retrieval_score * confidence * freshness
```

Decay should not begin as deletion, archival, or hidden package-specific rules.

### Architectural Boundary

- `core/` should own timestamp access and retrieval-time weighting hooks
- `capabilities/` may own reusable reinforcement or freshness computation later
- `semantic/` may influence context-specific reinforcement, but decay itself remains generic

### Value

Decay supports:

- less dominance by stale memory
- preference for current conclusions
- historical retention without current-answer pollution
- long-term memory hygiene

## Relationship Between The Three

These concepts form a future memory-lifecycle layer above the current primitives.

```text
SourceItem
   -> Annotation
   -> MemoryObject
   -> Lineage relations
   -> Confidence assessment
   -> Freshness / decay influence
   -> Retrieval ranking
```

Their roles are distinct:

- lineage explains how memory was created
- confidence expresses how trustworthy it is
- decay controls how strongly it should influence retrieval now

## What Should Not Happen

These concepts should not become:

- new semantic memory kinds
- package-specific hidden heuristics
- a reason to weaken evidence requirements
- a justification for deleting older memory too early
- opaque aggregate scores with no debug surface

## Sequencing Guidance

These concepts are important, but they are not the next roadmap step.

Current evidence from the public-corpus evaluation path suggests Pallium first
needs:

- stronger real-interaction routing behavior
- better no-value suppression
- better source-evidence preference on local clarification / artifact-reuse queries

Lifecycle signals should stay as a future idea until the current product slice
is more proven on real interaction shape.

## Recommendation

Store these directions now as:

- accepted positioning guidance in `docs/context/`
- a design thread here in `docs/designs/`
- a future roadmap idea rather than a committed feature

That keeps the direction durable without letting it distort the current product
sequence.
