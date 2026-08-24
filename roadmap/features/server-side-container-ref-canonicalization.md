---
id: server-side-container-ref-canonicalization
title: Canonicalize container references server-side
status: done
priority: high
commitment: committed
milestone: Done
---

## Outcome

The core service now canonicalizes GitHub container references for all callers, keeping read and write scope aligned; the legacy stranded rows were backfilled.

## Evidence

Shipped in commit `2e7e4d0` ([Work Record](../../.agent-workflow/tasks/server-side-container-ref-canonicalization.md)).

