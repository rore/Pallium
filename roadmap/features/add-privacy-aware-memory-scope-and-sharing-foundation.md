---
id: add-privacy-aware-memory-scope-and-sharing-foundation
title: Add privacy-aware memory scope enforcement foundation
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a generic native-scope and query-enforcement foundation so scope-aware Pallium packages can fail closed, preserve or narrow scope through derivation, and prepare safely for later explicit shared-memory behavior.

This slice should establish the privacy boundary mechanics and the package/capability hooks needed for later shared-memory and cross-scope features without trying to ship broad cross-scope reuse in the same step.

## Why

Pallium is a generic memory engine, not a Slack memory engine. Current refs such as `container_ref`, `thread_ref`, and `session_ref` are useful locality metadata, but they are not a privacy model and should not become one accidentally.

For real downstream integration, especially where public and private memory can coexist, this is no longer a distant concern. Before Pallium can be treated as integration-ready, it needs a generic scope model that lets producers declare visibility boundaries, keeps retrieval fail-closed for scope-aware packages, and prevents local memory objects from silently turning into shared memory.

## In Scope

- define and implement one generic native-scope abstraction for `SourceItem` and `MemoryObject`
- treat scope as a first-class boundary distinct from descriptive refs such as container, thread, and session
- allow producer-declared native scope for scope-aware packages
- define query-time access context so retrieval filters by allowed scope before ranking
- define derivation rules where direct and higher-level memory preserve or narrow native scope by default
- make thread aggregation and consolidation accept scope-aware candidate filtering hooks at the capability boundary
- define package-owned mapping from domain/locality context into scope refs
- add storage, retrieval, and trace support needed to debug missing-scope, mixed-scope, and privacy-leak scenarios
- add evaluation requirements for privacy leaks and fail-closed behavior in scope-aware packages
- document the later explicit shared-memory path in design docs without implementing cross-scope sharing in this slice

## Out of Scope

- shipping actual shared-memory publication across broader scopes
- shipping one final access-control product integration
- hardcoding Slack-style concepts such as public, private, or dm into core contracts
- broad workspace-wide semantic grouping
- replacing existing locality refs with a new ontology
- making all existing packages immediately require scope metadata
- cross-container memory behavior itself

## Done When

1. Pallium has a documented and implemented generic abstraction for native scope that is independent of any one connector.
2. Scope-aware packages can attach native scope to source items and derived memory.
3. Retrieval enforces query access context before ranking for scope-aware packages and fails closed when required scope data is missing.
4. Direct and higher-level derivation preserve or narrow native scope by default.
5. The capability and package boundaries are explicit about what core owns, what reusable capabilities own, and what semantic packages own for scope handling.
6. Evaluation coverage includes missing-scope, mixed-scope, and privacy-leak cases.
7. The integration-readiness scenario and any later shared-memory work can build on this foundation instead of redefining privacy ad hoc.

## Notes

Current design direction:

- producer or application code is the source of truth for scope refs
- `container_ref`, `thread_ref`, `session_ref`, `actor_ref`, and `source_ref` stay descriptive unless a package maps them into scope policy explicitly
- retrieval should first enforce access scope, then apply normal structured and ranked retrieval
- broader reuse should happen only through a later explicit shared-memory path, not by widening local memory objects in place
- the full multi-phase design lives in `docs/designs/007-privacy-aware-scope-and-sharing.md`
