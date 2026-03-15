# Privacy-Aware Scope And Sharing

## Goal

Define a generic visibility model for Pallium so scope-aware packages can:

- preserve explicit visibility boundaries on ingested evidence and derived memory
- enforce access before retrieval ranking
- keep derivation fail-closed by default
- support later bounded cross-container reuse through explicit shared derived memory rather than accidental widening of local memory

The goal is to add enough durable architecture for privacy-aware behavior without turning Pallium into a full authorization system or forcing connector-specific concepts into the generic core.

## Why This Needs A Design First

Pallium already has strong locality metadata such as `container_ref`, `thread_ref`, and `session_ref`, but those refs are descriptive context, not a privacy model.

If later cross-container or shared-memory features reuse those refs as if they were privacy boundaries, Pallium will quietly couple retrieval, derivation, and sharing semantics to one upstream conversation shape. That would be brittle for the current package and worse for any future semantic package.

The right move is to separate three concerns:

1. locality and correlation metadata
2. visibility enforcement
3. later shared-memory publication

## Non-Goals

This design is not trying to:

- define one final user-facing access-control product
- hardcode connector-specific concepts such as Slack channels or DMs into the core model
- make every existing package immediately require visibility metadata
- ship cross-container reuse in the same slice as the visibility foundation
- replace existing locality refs with a new ontology

## Core Principles

1. Visibility is separate from locality.
   `container_ref`, `thread_ref`, `session_ref`, `actor_ref`, and `source_ref` remain descriptive context unless a package explicitly maps them into visibility policy.

2. The consumer provides the current visibility context, not the whole policy.
   Producer or application code supplies the visibility boundary for ingest and query. Pallium owns the visibility semantics and enforcement once that boundary is supplied.

3. The ingest and query contract should match.
   The same `visibility_context` shape should be used on ingest and query so consumers do not need one model for storage and another for retrieval.

4. Fail closed for scope-aware packages.
   If a package requires visibility to enforce safe retrieval or derivation, missing visibility data should prevent retrieval or promotion rather than silently broadening visibility.

5. Local derived memory preserves visibility by default.
   Direct memory and higher-level memory should stay inside the visibility context of their supporting evidence unless the package explicitly creates a separate shared derived object.

6. Broader reuse happens through explicit shared memory.
   Cross-scope reuse should create a separate shared derived memory object with its own target visibility and provenance, not widen a local memory object in place.

7. Access is enforced before ranking.
   Retrieval should apply visibility filtering before lexical retrieval, vector retrieval, fusion, or reranking.

## Phase-1 Consumer Contract

Use the same shape on ingest and query:

```json
{
  "visibility_context": {
    "kind": "public" | "limited" | "user",
    "id": "..." | null
  }
}
```

Meaning:

- `public`
  - globally visible
  - `id = null`
- `limited`
  - visible within one bounded shared context
  - use for private channel, group, room, or similar shared limited audience
  - `id` required
- `user`
  - visible only within one user-private context
  - `id` required

This keeps the contract small, avoids invalid combinations such as separate `privacy + type` fields, and still preserves the distinction between a bounded shared audience and a user-private audience.

## How Pallium Interprets It

On ingest:

- the source item belongs to the supplied `visibility_context`
- local derived memory preserves that same `visibility_context` by default

On query:

- the request is happening inside the supplied `visibility_context`
- Pallium expands that current context into the visible set internally

Phase-1 visibility expansion rules:

- query in `public` can see:
  - `public`
- query in `limited:X` can see:
  - `public`
  - `limited:X`
- query in `user:U1` can see:
  - `public`
  - `user:U1`

So the consumer supplies the current boundary, while Pallium owns the built-in visibility semantics.

## Conceptual Model

### Visibility Context

Visibility context is the consumer-facing boundary carried on source items and query requests.

It needs to answer:

- is this memory globally visible, shared within one bounded context, or private to one user context?
- if it is bounded, which concrete context does it belong to?

Phase-1 core shape:

- `kind`
- `id`

This is intentionally smaller than a full authorization model.

### Local Derived Memory

Local derived memory is any memory object whose visibility is preserved from its supporting evidence.

Examples:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `pattern_memory`
- `continuity_memory`
- later `task_checkpoint`

Default rule:

- local derived memory cannot become visible outside the visibility context of its evidence just because it is more abstract

### Shared Derived Memory

Shared derived memory is a separate memory object intentionally published to a broader target visibility context under package policy.

Shared derived memory must not be modeled as a local memory object whose visibility was widened in place.

It needs separate provenance for at least:

- target visibility context
- lineage to supporting local memory and source evidence
- creation mechanism or package policy

This separate object model makes later revocation, supersession, and false-share debugging possible.

## Behavioral Rules

### Ingest

For scope-aware packages:

- ingest should accept producer-declared `visibility_context`
- missing required visibility data may remain persistable for debugging if desired, but it must not be broadly retrievable or promotable without explicit package policy
- locality refs should still be stored independently of visibility

### Direct Promotion

For scope-aware packages:

- direct memory should preserve the visibility context of the source evidence by default
- if supporting source items disagree on visibility context, promotion should fail closed in phase 1
- phase 1 should not attempt generalized narrowing or intersection logic

### Thread Aggregation

Thread aggregation is a reusable capability and therefore must not invent privacy semantics.

Required behavior:

- only aggregate source items that have the exact same `visibility_context`
- do not let a thread aggregate cross visibility boundaries just because the same `thread_ref` appears
- expose visibility-aware candidate filtering hooks at the capability boundary rather than hardcoding one package's policy into the capability itself

### Tiered Consolidation

Consolidation is also a reusable capability and must treat visibility as a hard precondition, not a soft ranking factor.

Required behavior:

- only group local derived memory that has the exact same `visibility_context`
- do not let higher-level memory become broader than its support by default
- keep visibility checks ahead of lexical overlap, topic similarity, time windows, and any future vector signals

### Retrieval

Retrieval for scope-aware packages must:

- require `visibility_context` on the query and fail closed when it is missing
- expand the current query visibility according to the built-in phase-1 rules before ranking
- keep superseded memory filtered as today
- preserve evidence-backed packaging
- expose enough trace data to debug why a candidate was excluded for visibility reasons

At minimum, trace/debug outputs should be able to say:

- candidate was excluded because visibility context was missing
- candidate was excluded because the query visibility did not include the candidate visibility
- candidate was returned as local memory vs shared derived memory

## Ownership Boundaries

### Core

Core should own:

- `visibility_context` plumbing on generic primitives
- query visibility plumbing
- built-in phase-1 visibility expansion rules
- fail-closed enforcement hooks
- generic provenance fields needed for local and shared visibility handling

Core should not own:

- connector-specific labels such as Slack channel vs group internals
- package-specific mapping from locality refs to visibility context
- package-specific share eligibility rules

### Capabilities

Reusable capabilities should own:

- visibility-aware candidate filtering hooks
- exact-match compatibility guards for aggregation and consolidation
- no package-specific visibility semantics beyond the hook contract

### Semantic Packages

Semantic packages should own:

- whether the package is visibility-aware
- mapping from domain or locality context to `visibility_context`
- any later package-specific narrowing or share policy
- cross-scope publication policy for shared derived memory

### Application / Producer Layer

Application and producer code should own:

- declaring `visibility_context` on ingest
- supplying `visibility_context` on query
- any user or application authorization logic outside Pallium itself

## Downstream Mapping

This model fits the expected downstream shape cleanly:

- public team conversation:
  - `visibility_context = { "kind": "public", "id": null }`
- private team channel or group:
  - `visibility_context = { "kind": "limited", "id": "channel-123" }`
- user-private interaction:
  - `visibility_context = { "kind": "user", "id": "user-456" }`

Examples:

- a query in `public` sees only public memory
- a query in `limited:channel-123` can reuse public memory plus that bounded channel memory
- a query in `user:user-456` can reuse public memory plus that user's private memory

This gives the consumer one stable contract while keeping the enforcement semantics inside Pallium.

## Future Promotion To Broader Audiences

The phase-1 model intentionally leaves room for later explicit promotion from a narrower context to a broader audience.

Example future flow:

1. work happens inside `limited:channel-123`
2. Pallium forms local memory there
3. a later explicit share or promotion step creates a separate broader derived memory object in `public` or another `limited:*` audience
4. the original limited memory remains limited

This does not lose evidence. Later shared-memory design should preserve:

- lineage back to the original local memory
- lineage back to the original supporting evidence
- a distinction between full provenance and whatever evidence is safe to expose at the broader scope

That is exactly why explicit shared-memory derivation is a later separate slice.

## Phased Implementation Plan

### Phase 1: Visibility Foundation And Enforcement

Roadmap item:

- `add-privacy-aware-memory-scope-and-sharing-foundation`

Deliver:

- `visibility_context` on source items and memory objects
- query visibility enforcement before ranking
- exact-match derivation defaults for promotion, aggregation, and consolidation
- visibility-aware hooks in aggregation and consolidation
- trace and evaluation support for fail-closed behavior and privacy leaks

Do not deliver yet:

- broader shared derived memory publication
- cross-container reuse
- mixed-context derivation

### Phase 2: Explicit Shared-Derived-Memory Contract

Roadmap item:

- `add-explicit-shared-memory-derivation`

Deliver:

- separate shared derived memory objects
- target visibility and share provenance metadata
- lineage to supporting local memory and evidence
- controlled visible evidence for broader audiences
- lifecycle expectations for shared derived memory
- trace and evaluation support for false-share and stale-share cases

Do not deliver yet:

- package-specific cross-container grouping policy

### Phase 3: Bounded Cross-Container Shared Memory

Roadmap item:

- `add-cross-container-bounded-memory`

Deliver:

- package-specific bounded cross-container reuse behind explicit shared-memory policy
- stronger grouping guards than within-container memory
- false-merge and false-share evaluation for cross-container scenarios

## Current Recommendation

Treat visibility-aware scope as necessary infrastructure, but keep each privacy-related roadmap slice narrow and testable.

For the privacy-specific path, the right sequence is:

1. visibility foundation and enforcement
2. explicit shared-derived-memory contract
3. bounded cross-container shared memory

For the current package, this privacy path is now part of integration readiness, not optional later polish.

## Open Design Questions

- should missing `visibility_context` on ingest persist raw evidence for debugging, or be rejected entirely for scope-aware packages?
- how much visibility detail should be visible in normal query results versus debug or trace outputs?
- what package or operator gates should later explicit broader sharing require?
- when broader sharing exists, how should Pallium distinguish full lineage from evidence that is safe to expose at the broader visibility context?

