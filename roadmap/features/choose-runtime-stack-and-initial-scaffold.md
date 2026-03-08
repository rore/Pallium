---
id: choose-runtime-stack-and-initial-scaffold
title: Choose the runtime stack and initial scaffold
status: queued
priority: high
commitment: committed
milestone: Phase 0
---

## Summary

Pick the initial runtime and storage stack, then scaffold the first repo modules around that choice.

## Why

The repo is still pre-implementation. Picking a simple local-first stack early will make the first code cuts concrete and reduce thrash in storage, provider abstraction, and API wiring.

## In Scope

- choose the initial backend runtime
- choose the initial storage approach
- choose the initial project layout for core, storage, pipeline, retrieval, providers, and API
- scaffold the first module boundaries without overbuilding them

## Out of Scope

- production-scale infrastructure
- connector framework work
- advanced deployment topology

## Done When

1. The initial runtime and storage choices are explicit.
2. The repo has the first implementation-oriented scaffold in place.
3. The scaffold aligns with Pallium's generic-core and local-first direction.

## Notes

Sources: `roadmap/scope.md`, `docs/context/vision.md`
