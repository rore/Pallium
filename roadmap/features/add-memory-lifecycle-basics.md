---
id: add-memory-lifecycle-basics
title: Add basic memory lifecycle handling
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Add minimal lifecycle handling for promoted memory so stale or superseded knowledge can be managed safely as agent events accumulate.

## Why

Now that Pallium accepts repeated event streams and assistant artifacts, memory quality is not only about extraction. It also depends on how the system handles updates, contradictions, and superseded conclusions.

## In Scope

- introduce a minimal lifecycle model for promoted memory objects
- support at least active vs superseded semantics
- make lifecycle visible in retrieval and tests
- define the first maintenance path for replacing stale memory without deleting evidence

## Out of Scope

- complex human review workflows
- deep merge or rewrite logic across many memory objects
- historical backfill migration of all existing demo data

## Done When

1. Promoted memory can represent at least active and superseded states.
2. Retrieval avoids surfacing superseded memory as if it were current by default.
3. Tests cover a simple supersession path without losing evidence references.

## Notes

Completed on 2026-03-09.
The first maintenance path is internal and code-driven rather than exposed as a public API.
