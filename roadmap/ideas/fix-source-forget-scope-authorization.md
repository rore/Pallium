---
id: fix-source-forget-scope-authorization
title: Align raw-turn forgetting with the trusted-local boundary
status: done
priority: medium
commitment: uncommitted
---

## Completed alignment outcome

The earlier caller-scope change was removed after review: Pallium has no authentication or authorization layer, so self-asserted caller/container fields and a strict-mode switch were not a real security boundary. The product contract is explicitly trusted-local; connected callers may invoke raw-turn forgetting without pseudo-authorization. Pallium must not be exposed to untrusted or shared clients.

The underlying lifecycle remains intact: raw turns are soft-forgotten, idempotent, auditable on successful mutation, excluded from retrieval and source-context expansion, and missing targets retain their existing behavior. Source-context visibility enforcement from `45900c4` remains in place for anchors, neighbors, and supported memories.

This record is complete as an alignment/review correction; it does not claim that authentication shipped.
