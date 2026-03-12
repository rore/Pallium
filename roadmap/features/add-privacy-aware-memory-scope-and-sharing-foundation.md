---
id: add-privacy-aware-memory-scope-and-sharing-foundation
title: Add privacy-aware memory scope enforcement foundation
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add a generic `visibility_context` and query-enforcement foundation so scope-aware Pallium packages can fail closed, preserve visibility through derivation, and prepare safely for later explicit shared-memory behavior.

This slice should establish the privacy boundary mechanics and the core/capability hooks needed for later shared-memory and cross-scope features without trying to ship broad cross-scope reuse in the same step.

## Why

Pallium is a generic memory engine, not a Slack memory engine. Current refs such as `container_ref`, `thread_ref`, and `session_ref` are useful locality metadata, but they are not a privacy model and should not become one accidentally.

For real downstream integration, especially where public and private memory can coexist, this is no longer a distant concern. Before Pallium can be treated as integration-ready, it needs a generic visibility model that lets consumers declare one current visibility context, keeps retrieval fail-closed for scope-aware packages, and prevents local memory objects from silently turning into shared memory.

## In Scope

- define and implement one generic `visibility_context` abstraction for `SourceItem` and `MemoryObject`
- use the same consumer-facing `visibility_context` shape on ingest and query
- phase-1 consumer contract:
  - `kind: public | limited | user`
  - `id: string | null`
- make Pallium own the built-in phase-1 visibility rules:
  - `public` query sees `public`
  - `limited:X` query sees `public` plus `limited:X`
  - `user:U1` query sees `public` plus `user:U1`
- require query-time visibility enforcement before ranking
- define exact-match derivation rules where direct and higher-level memory preserve visibility by default
- make thread aggregation and consolidation accept visibility-aware candidate filtering hooks at the capability boundary
- add storage, retrieval, and trace support needed to debug missing-context, mixed-context, and privacy-leak scenarios
- add evaluation requirements for privacy leaks and fail-closed behavior in scope-aware packages
- document the later explicit shared-memory path in design docs without implementing cross-scope sharing in this slice

## Out of Scope

- shipping actual shared-memory publication across broader visibilities
- shipping one final access-control product integration
- hardcoding connector-specific concepts such as Slack channels or DMs into core contracts beyond the generic `limited` / `user` visibility kinds
- broad workspace-wide semantic grouping
- replacing existing locality refs with a new ontology
- making all existing packages immediately require visibility metadata
- cross-container memory behavior itself
- mixed-context derivation or widening local memory objects in place

## Done When

1. Pallium has a documented and implemented generic `visibility_context` abstraction that is independent of any one connector.
2. Scope-aware packages can attach `visibility_context` to source items and derived memory.
3. Retrieval enforces query visibility before ranking for scope-aware packages and fails closed when required visibility data is missing.
4. Direct and higher-level derivation preserve visibility by exact match in phase 1.
5. The capability and package boundaries are explicit about what core owns, what reusable capabilities own, and what semantic packages own for visibility handling.
6. Evaluation coverage includes missing-context, mixed-context, and privacy-leak cases.
7. The integration-readiness scenario and any later shared-memory work can build on this foundation instead of redefining privacy ad hoc.

## Notes

Status: completed with a generic `visibility_context` foundation in `core` and `capabilities`, scope-aware fail-closed enforcement in `agent_conversation_memory`, SQLite-backed visibility persistence, retrieval/debug visibility exclusion trace, and focused privacy regressions plus affected thread/consolidation/routing regression slices.

Current design direction:

- the consumer provides one current `visibility_context` on ingest and query; Pallium owns the built-in visibility expansion rules
- `container_ref`, `thread_ref`, `session_ref`, `actor_ref`, and `source_ref` stay descriptive unless a package maps them into visibility policy explicitly
- retrieval should first enforce visibility, then apply normal structured and ranked retrieval
- broader reuse should happen only through a later explicit shared-memory path, not by widening local memory objects in place
- phase-1 derivation compatibility should stay exact-match only; do not attempt generalized narrowing or intersection yet
- the full multi-phase design lives in `docs/designs/007-privacy-aware-scope-and-sharing.md`

