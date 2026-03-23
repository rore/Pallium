---
id: idea-document-schema-evolution-strategy
title: Document schema evolution strategy
status: queued
priority: low
commitment: uncommitted
milestone: Idea
---

## Summary

Document Pallium's current schema evolution approach and clarify its support
boundary so integrators know what to expect.

## Why

Pallium currently evolves the SQLite schema via startup-time `ALTER TABLE`
checks in `storage/sqlite_schema.py`. This is pragmatic for a local-first
sidecar, but it is undocumented — an external reviewer flagged the absence of
versioned migrations as a production-readiness gap.

The goal is not to adopt Alembic or a full migration framework now, but to
make the current strategy explicit so integrators can make informed decisions.

## In Scope

- Document the current startup-time schema evolution approach in
  `docs/context/architecture.md` or a dedicated page
- Clarify that Pallium is a local-first sidecar, not a multi-instance service
- State the current backup/rollback expectation (delete and rebuild)
- Note when a formal migration system would become warranted (multi-instance
  deployment, remote storage backends, data that cannot be rebuilt from source)

## Out of Scope

- Adopting Alembic or another migration framework now
- Adding rollback support to the current schema checks
- Multi-backend storage support

## Done When

1. The schema evolution strategy is documented in a place integrators can find.
2. The support boundary (local sidecar, rebuildable data) is explicit.
