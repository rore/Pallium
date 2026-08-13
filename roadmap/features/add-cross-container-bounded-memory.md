---
id: add-cross-container-bounded-memory
title: Add bounded cross-container memory
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-vnext-p3
---

## Summary

Add a later-stage bounded shared-memory capability so Pallium can reuse prior conclusions across containers when strong evidence suggests the same recurring topic or question has appeared in multiple conversation spaces.

The feature should build on the generic privacy-aware scope foundation and the explicit shared-memory derivation path rather than extending container locality refs into an implicit privacy model.

## Why

Real recurring questions and conclusions can span multiple containers, such as different channels or conversation spaces. Limiting memory strictly to one container keeps false-merge risk low, but it also prevents Pallium from reusing valid prior conclusions that surfaced elsewhere.

This feature exists to capture that higher-value cross-container continuity while keeping safety stronger than within-container consolidation.

In the longer term, this is also the clearest bounded path toward coordination memory across separate workspaces or agent contexts, so it should not move ahead of the lifecycle and provenance work needed to keep shared reuse trustworthy.

## In Scope

- bounded cross-container shared-memory behavior for the active semantic package after the generic scope/sharing prerequisites exist
- package-specific mapping from local package context into explicit share targets
- stronger guards than current within-container tiered memory, including:
  - same semantic package only
  - eligible lower-level memory types only
  - strong overlap or shared-entity requirements
  - bounded time and candidate windows
- strategy-specific evaluation focused on false-merge risk across containers
- explicit evidence and lifecycle preservation for any cross-container higher-level memory
- retrieval-policy evaluation for when cross-container memory should be allowed to influence broad recurring-question answers

## Out of Scope

- inventing a second privacy model separate from the generic scope/sharing foundation
- broad global clustering over the full store
- default cross-container consolidation on every package
- connector-specific semantics in core
- ambient workspace memory over all chat or all source systems
- weakening current within-container safety guards in order to increase recall

## Done When

1. The generic privacy-aware memory scope enforcement foundation is already available for this slice to build on.
2. The explicit shared-memory derivation path is already available for this slice to build on.
3. Pallium can run at least one bounded cross-container shared-memory strategy behind explicit package policy.
4. Cross-container grouping is guarded by stronger constraints than within-container grouping.
5. The evaluation set includes hard false-merge scenarios across containers and privacy-leak or false-share scenarios across scopes.
6. The benchmark shows at least one real cross-container recurring-question case where shared memory helps.
7. The benchmark also shows that unrelated same-vocabulary content across containers does not merge or share under the chosen default policy.
8. Retrieval policy for cross-container shared memory is explicit rather than always-on.

## Notes

vNext gating (Phase 3): furthest-downstream sharing item. Gated behind
`idea-cross-user-raw-history-value` (does scoped raw history help another user at
all?) and `add-explicit-shared-memory-derivation`. Build only if the raw-first
experiment and the derived eval justify a bounded shared-derived object.

Initial design assumptions:

- container is a strong default memory boundary, but not an absolute law forever
- cross-container memory should be opt-in and more conservative than within-container memory
- broader reuse should happen through explicitly shared derived memory, not by widening local memory objects in place
- likely enabling signals include some combination of:
  - shared entities
  - strong lexical/topic overlap
  - repeated normalized question pattern
  - bounded time window
  - package-specific eligibility rules
- likely non-goals for the first slice:
  - global semantic grouping
  - channel-agnostic clustering with weak similarity only

Dependency note:

- this feature depends on `add-privacy-aware-memory-scope-and-sharing-foundation`
- this feature depends on `add-explicit-shared-memory-derivation`
- this feature depends on `add-bounded-memory-lifecycle-hardening`

This should be approached only after retrieval trace, hybrid retrieval groundwork, and the scope/sharing prerequisites are stronger, because cross-container mistakes will be harder to debug without explainability and explicit privacy boundaries.
