---
id: idea-generic-memory-lifecycle-signals
title: Generic memory lifecycle signals
status: queued
priority: medium
commitment: uncommitted
milestone: Idea
---

## Summary

Explore generic lifecycle signals for Pallium memory objects:

- lineage
- confidence
- decay

These are cross-cutting engine capabilities, not semantic memory kinds.

## Why

If Pallium is going to differentiate as derived knowledge memory for agents, it
needs a stronger generic lifecycle layer so knowledge stays traceable,
trustworthy, and less prone to stale dominance.

## In Scope

- generic lineage relations and provenance for how memory was formed and evolved
- generic confidence metadata and bounded trust signals
- generic decay / freshness influence at retrieval time
- keeping these concepts explainable and evidence-backed

## Out of Scope

- turning lineage, confidence, or decay into semantic package concepts
- broad opaque scoring systems with no debug surface
- memory deletion as the first decay mechanism
- displacing current near-term routing and evaluation hardening work

## Done When

1. The lifecycle concepts are concrete enough to split into one or more committed feature items.
2. The generic `core` / `capabilities` / `semantic` boundaries are clear.
3. The design can be justified against real product needs rather than only abstract elegance.

## Notes

This should remain an idea until the current product slice is more proven on
real interaction shape.

Sources: `docs/designs/009-derived-knowledge-memory-and-lifecycle-signals.md`, `docs/context/vision.md`
