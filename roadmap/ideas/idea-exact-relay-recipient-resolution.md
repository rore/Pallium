---
id: idea-exact-relay-recipient-resolution
title: Add bounded exact recipient resolution to Relay discovery
status: queued
priority: medium
commitment: uncommitted
milestone: pallium-relay
lane: investigation
---

## Summary

Recipient discovery only pages. `pallium_relay_recipients` (and the `/relay/sessions` route beneath it) exposes `runtime`, `include_inactive`, `container_ref`, and `offset` — no filter for an exact `session_ref`, and no way to target a container other than the caller-supplied listing scope. Finding one known dormant session by exact ref means paging the whole address book: a real dogfood run hit 1,011 records at 4 rows/page, ~253 page calls, which makes targeted cross-container coordination impractical.

The exact-lookup primitive already exists in storage — `_relay_session(db, container_ref=, runtime=, session_ref=)` backs `relay_name_session`. It is just not surfaced as a discovery/read operation.

## Proposed shape

Smallest fix: thread an optional `session_ref` filter through `relay_list_sessions` (storage) → `list_sessions` (core) → `/relay/sessions` route → `pallium_relay_recipients` tool, reusing the existing exact-lookup primitive when `session_ref` is supplied. Returns zero or one record. Pagination is unchanged when the filter is absent.

Authorization is preserved because resolution stays inside the caller-supplied `container_ref` scope — this adds no new cross-container read capability. Cross-container targeting remains whatever the shipped actor-scoped routing already permits; this item only removes the O(pages) scan within an already-authorized scope.

## Direction (decided)

Optional exact `session_ref` filter on the existing list path is the chosen smallest fix — not a dedicated `resolve` operation. Alias resolution is deferred; add it only if a concrete need appears. Keep this separate from Session History search-quality work.

## Questions before commitment

- Does exposing exact-membership presence within a scope leak anything the paged listing does not already reveal? (Expected no — same rows, fewer calls.)

## Validation if promoted

Caller-surface test: exact `session_ref` returns the single matching row; absent match returns empty; the filter respects `container_ref` scope and `include_inactive`; unfiltered listing behavior is unchanged; actor/container isolation still holds (no reaching a session outside the authorized scope).

## Done when

Discovering a known session by exact `session_ref` within an authorized scope is a single bounded call, or a written investigation rejects the surface change with a concrete alternative. Must not expand cross-container read authority beyond current routing rules.
