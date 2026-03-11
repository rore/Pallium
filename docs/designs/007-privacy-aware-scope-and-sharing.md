# Privacy-Aware Scope And Sharing

## Goal

Define a generic privacy-aware scope model for Pallium so scope-aware packages can:

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
2. privacy / visibility scope
3. later shared-memory publication

## Non-Goals

This design is not trying to:

- define one final user-facing access-control product
- hardcode Slack-like concepts such as public, private, channel, or dm into the core model
- make every existing package immediately require scope metadata
- ship cross-container reuse in the same slice as the scope foundation
- replace existing locality refs with a new ontology

## Core Principles

1. Scope is separate from locality.
   `container_ref`, `thread_ref`, `session_ref`, `actor_ref`, and `source_ref` remain descriptive context unless a package explicitly maps them into scope policy.

2. Producers declare native scope.
   Producer or application code is the source of truth for scope boundaries. Pallium should not infer privacy boundaries from text or correlation refs.

3. Fail closed for scope-aware packages.
   If a package requires scope to enforce safe retrieval or derivation, missing scope data should prevent broad retrieval or promotion rather than silently broadening visibility.

4. Derivation preserves or narrows scope by default.
   Direct memory and higher-level memory should stay inside the native scope of their supporting evidence unless the package explicitly creates a separate shared derived object.

5. Broader reuse happens through explicit shared memory.
   Cross-scope reuse should create a separate shared derived memory object with its own target scope and provenance, not widen a local memory object in place.

6. Access is enforced before ranking.
   Retrieval should apply access context filtering before lexical retrieval, vector retrieval, fusion, or reranking.

7. Packages own mapping and share policy.
   The generic core should carry scope plumbing and enforcement hooks. Packages decide how domain/locality context maps to scope and what is eligible for sharing.

## Conceptual Model

### Native Scope

Native scope is the visibility boundary that arrives with a source item or is preserved on a local derived memory object.

Conceptually, a native scope envelope needs to answer:

- what scope system or namespace is this package using?
- what concrete scope refs identify the allowed audience or boundary?
- which policy version interpreted those refs?

This does not require a final field-level schema in this document, but the model should support at least:

- package-owned scope namespaces
- one or more opaque scope refs
- policy version metadata

### Query Access Context

A query access context is the set of scopes the caller is allowed to see for a given request.

Retrieval flow for scope-aware packages should become:

1. receive query text plus access context
2. filter candidate source items and memory objects by allowed scope
3. run structured narrowing and ranked retrieval only inside the allowed set
4. package compact, evidence-backed results as usual

This keeps privacy enforcement orthogonal to retrieval sophistication.

### Local Derived Memory

Local derived memory is any memory object whose scope is preserved from or narrowed relative to its supporting evidence.

Examples:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `pattern_memory`
- later `continuity_memory`

Default rule:

- local derived memory cannot become visible outside the native scope of its evidence just because it is more abstract

### Shared Derived Memory

Shared derived memory is a separate memory object intentionally published to a broader target scope under package policy.

Shared derived memory must not be modeled as a local memory object whose scope was widened in place.

It needs separate provenance for at least:

- target scope
- share policy version
- lineage to supporting local memory and source evidence
- creation mechanism / package policy

This separate object model makes later revocation, supersession, and false-share debugging possible.

## Behavioral Rules

### Ingest

For scope-aware packages:

- ingest should accept producer-declared native scope
- missing required scope data should remain persistable if needed for debugging, but not broadly retrievable or promotable without explicit package policy
- locality refs should still be stored independently of scope

### Direct Promotion

For scope-aware packages:

- direct memory should preserve the native scope of the source evidence by default
- if multiple supporting source items disagree on native scope, promotion should fail closed unless package policy explicitly defines a legal narrower common scope

### Thread Aggregation

Thread aggregation is a reusable capability and therefore must not invent privacy semantics.

Required behavior:

- only aggregate source items that are compatible under the package's native-scope rules
- do not let a thread aggregate cross scope boundaries just because the same `thread_ref` appears
- expose scope-aware candidate filtering hooks at the capability boundary rather than hardcoding one package's policy into the capability itself

### Tiered Consolidation

Consolidation is also a reusable capability and must treat scope as a hard precondition, not a soft ranking factor.

Required behavior:

- only group local derived memory that is compatible under package scope policy
- do not let higher-level memory become broader than its support by default
- keep scope checks ahead of lexical overlap, topic similarity, time windows, and any future vector signals

### Retrieval

Retrieval for scope-aware packages must:

- enforce query access context before ranking
- keep superseded memory filtered as today
- preserve evidence-backed packaging
- expose enough trace data to debug why a candidate was excluded for scope reasons

At minimum, trace/debug outputs should be able to say:

- candidate was excluded because native scope was missing
- candidate was excluded because access context did not include the candidate scope
- candidate was returned as local memory vs shared derived memory

## Ownership Boundaries

### Core

Core should own:

- scope plumbing on generic primitives
- query access context plumbing
- fail-closed enforcement hooks
- generic provenance fields needed for native and shared scope handling

Core should not own:

- connector-specific scope labels
- package-specific mapping from locality refs to scope
- package-specific share eligibility rules

### Capabilities

Reusable capabilities should own:

- scope-aware candidate filtering hooks
- compatibility guards for aggregation and consolidation
- no package-specific scope semantics beyond the hook contract

### Semantic Packages

Semantic packages should own:

- mapping from domain/locality context to scope refs
- whether the package is scope-aware
- share eligibility policy
- any package-specific narrowing rules
- cross-scope publication policy for shared derived memory

### Application / Producer Layer

Application and producer code should own:

- declaring native scope on ingest
- supplying query access context on retrieval
- any user/application authorization logic outside Pallium itself

## Phased Implementation Plan

### Phase 1: Native Scope And Enforcement Foundation

Roadmap item:

- `add-privacy-aware-memory-scope-and-sharing-foundation`

Deliver:

- native scope on source items and memory objects
- query access context enforcement before ranking
- preserve/narrow derivation defaults
- scope-aware hooks in aggregation and consolidation
- trace and evaluation support for fail-closed behavior and privacy leaks

Do not deliver yet:

- broader shared derived memory publication
- cross-container reuse

### Phase 2: Explicit Shared-Derived-Memory Contract

Roadmap item:

- `add-explicit-shared-memory-derivation`

Deliver:

- separate shared derived memory objects
- target scope and share provenance metadata
- lineage to supporting local memory and evidence
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

Treat privacy-aware scope as necessary infrastructure, but keep each privacy-related roadmap slice narrow and testable.

For the privacy-specific path, the right sequence is:

1. native scope and enforcement foundation
2. explicit shared-derived-memory contract
3. bounded cross-container shared memory

This privacy path should follow the current retrieval explainability work and fit around the existing within-container roadmap work rather than displacing the current product claim.

For the current package, that product claim remains:

- better recurring-question recall
- bounded, evidence-backed memory
- no broad ambient workspace memory

## Open Design Questions

- what is the smallest generic scope envelope that is useful without overfitting one connector?
- for scope-aware packages, should missing native scope block promotion entirely or only block retrieval and sharing?
- what is the cleanest representation of shared derived memory lineage when one shared object depends on multiple local memory objects with different local scopes?
- how much scope detail should be visible in normal query results versus debug/trace outputs?
