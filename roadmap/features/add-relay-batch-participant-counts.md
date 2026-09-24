---
id: add-relay-batch-participant-counts
title: Count Relay participants for a bounded set of exact work references
status: in-progress
priority: high
commitment: committed
milestone: pallium-relay
lane: product-surface
---

## Summary

Add one read-only Relay request that returns participant counts for a caller-supplied,
bounded list of exact work references. This lets a roadmap board show where
sessions are attached without enumerating a scope or making one request per item.
Minimap's companion item is `show-board-work-presence`; its UI behavior stays in
Minimap.

## Contract

`POST /relay/work-refs/participant-counts` accepts `references`, an ordered list of
1–200 unique canonical `{scope_ref, local_ref}` pairs. It returns
`contract: relay-work-ref-counts/v1` and one `{scope_ref, local_ref,
participant_count}` row per requested pair, in request order, including zero.
Canonical validation rejects invalid, duplicate, empty, and over-limit input with
422. A failed or incomplete read is an error, never a fabricated zero or partial
success. The existing per-reference participants read remains the detail path.

Count distinct nonclosed Relay endpoints attached to each exact pair, regardless
of explicit or structural origin or container. Dormant and unreachable endpoints
remain attached participants; the count does not claim activity, ownership, or
completion. Reads must not mutate endpoint, message, activity, History, or memory
state and must not disclose session details or unrelated references.

## Boundaries and Verification

Use the existing exact work-reference normalization, Relay registry, and
`idx_relay_work_refs_lookup` index. Filter the supplied keys in one SQL read
before grouping; do not add scope enumeration, N+1 reads, schema changes, or a
new framework. Verify the query plan at one and 200 keys against same-scope and
unrelated-scope data, and record local loopback endpoint latency. The predeclared
200-key target is median under 100 ms and p95 under 250 ms on an installed-like
Windows host; report actual measurements and conditions rather than claiming an
unmeasured speedup.

HTTP end-to-end tests cover exact matching, input bounds and Unicode, zero and
multiple participants, explicit/structural overlap, close/reopen and detach,
read-only behavior, and complete-or-error failures. Preserve the existing
association and access boundaries. The Minimap consumer excludes completed items
from automatic board batches, handles an empty selection without a request, and
shows errors/unrequested items as unknown; those client changes are not in this
Pallium feature.