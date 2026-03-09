---
id: choose-runtime-stack-and-initial-scaffold
title: Choose the runtime stack and initial scaffold
status: done
priority: high
commitment: committed
milestone: Phase 0
---

## Summary

The initial runtime, storage approach, and module scaffold are now in place for the first executable slice.

## Why

Picking a simple stack early made the first code cuts concrete and kept the walking skeleton coherent.

## In Scope

- choose the initial Python web stack
- choose the initial storage approach
- choose the initial project layout for API, core, semantic layer, storage, retrieval, and jobs
- scaffold the first module boundaries without overbuilding them

## Out of Scope

- production-scale infrastructure
- connector framework work
- advanced deployment topology

## Done When

1. The initial runtime and storage choices are explicit.
2. The repo has the first implementation-oriented scaffold in place.
3. The scaffold aligns with Pallium's generic-core, local-first, and walking-skeleton direction.

## Notes

Status: completed with FastAPI, SQLAlchemy, SQLite, pytest, and a repo-local venv workflow.

Sources: roadmap/scope.md, docs/context/vision.md, docs/context/architecture.md
