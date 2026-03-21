# Privacy And Visibility

This document explains the current privacy model for Pallium's
`agent_conversation_memory` package.

The main point is simple: `container_ref` is the scope boundary, and
`container_visibility` controls who can see items across containers.

## One Concrete Scenario

Imagine two private channels discussing the same incident.

- both channels talk about the same production bug
- both channels might use copied text or very similar wording
- both channels might even use similar thread naming patterns

If you only relied on `thread_ref` or lexical similarity, it would be easy to
leak the wrong memory across scopes.

Pallium avoids that by enforcing `container_visibility` before ranking. A query
from one container only sees items from that container plus public items from
other containers.

## Container Visibility

Every item has a `container_visibility` value:

- `"public"` — visible to queries from any container
- `"limited"` — visible only to queries from the same `container_ref`
  (group context such as a private channel)
- `"private"` — visible only to queries from the same `container_ref`
  (personal context such as a DM)

Default: `"private"`.

`container_ref` is the scope identity. Items in the same `container_ref` can
see each other. `container_visibility` controls whether items can also be seen
from other containers.

## Retrieval Rules

- query from container X sees:
  - all `public` items (from any container)
  - all `limited` and `private` items where `container_ref` matches X
- query without `container_ref` sees only `public` items

The caller sends `container_ref` and `container_visibility` on ingest and
query. Pallium applies the filtering rules.

## Fail-Closed Behavior

For `agent_conversation_memory`, retrieval is fail closed.

Current behavior:

- query without `container_ref` returns only public results
- ingest without `container_ref` is not promoted into memory for the
  scope-aware package
- the debug trace reports visibility exclusion reasons

This is intentional. Pallium prefers "return nothing" over "quietly leak a
candidate."

## Derivation And Consolidation Rules

Visibility is preserved by exact match in the current implementation.

That means:

- direct memory preserves the visibility of its evidence
- thread aggregation does not merge items across visibility boundaries
- higher-level consolidation does not group memory across visibility boundaries
- local memory is not widened into broader shared memory in place

This exact-match rule applies even if two items share the same `thread_ref` or
topic.

## What Pallium Owns vs What The App Owns

Pallium owns:

- the `container_visibility` contract
- retrieval enforcement before ranking
- visibility preservation through derivation
- visibility exclusion trace on the debug path

Your application owns:

- deciding what `container_visibility` a new item belongs to
- sending `container_ref` on ingest and query
- any user or tenant authorization outside Pallium

Pallium is not an authorization service for your app. It is the memory layer
that enforces the visibility boundary you provide.

## Practical Integration Rules

- always send `container_ref` with `agent_conversation_memory`
- use `container_visibility` to distinguish public channels, private channels,
  and DMs
- use `POST /query/debug` when results are missing and you need to see
  visibility exclusions

## What Is Not Implemented Yet

The current model does not yet ship:

- explicit shared-memory publication across broader visibilities
- cross-container shared memory
- generalized visibility narrowing or intersection logic

Those are later design steps, not hidden behavior in the current package.
