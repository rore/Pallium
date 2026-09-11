---
id: idea-exact-relay-recipient-resolution
title: Add bounded exact recipient resolution to Relay discovery
status: done
priority: medium
commitment: committed
milestone: pallium-relay
lane: investigation
---

## Summary

Before this fix, recipient discovery only paged. The recipients tool and HTTP session-list route had no exact session_ref filter. Finding one known dormant session by exact ref meant paging the whole address book: a dogfood run hit 1,011 records at 4 rows per page, about 253 calls.

The existing exact composite lookup is now surfaced through the list path. A caller supplies runtime plus session_ref and receives zero or one result.

## Implemented shape

The implementation threads an optional `session_ref` filter through `relay_list_sessions` (storage) → `list_sessions` (core) → `/relay/sessions` route → `pallium_relay_recipients` tool, reusing the existing exact-lookup primitive when `session_ref` is supplied. Returns zero or one record. Pagination is unchanged when the filter is absent.

Authorization is preserved because resolution stays inside the caller-supplied container listing scope. Relay routing remains service-global; this filter adds no broader discovery authority and only removes the page scan within an already-authorized scope.

## Direction (decided)

Optional exact `session_ref` filter on the existing list path is the chosen smallest fix — not a dedicated `resolve` operation. Alias resolution is deferred; add it only if a concrete need appears. Keep this separate from Session History search-quality work.

## Security result

Exact lookup exposes only a row already available through the same scoped paged listing, so it adds no membership information or cross-container discovery capability.

## Validation

Caller-surface test: exact `session_ref` returns the single matching row; absent match returns empty; the filter respects `container_ref` scope and `include_inactive`; unfiltered listing behavior is unchanged; actor/container isolation still holds (no reaching a session outside the authorized scope).

## Outcome

Discovering a known session by exact session_ref within an authorized scope is now a single bounded call. The caller must also supply runtime, matching the persisted composite identity.
