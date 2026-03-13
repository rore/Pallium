# Privacy And Visibility

This document explains the current privacy model for Pallium's
`agent_conversation_memory` package.

The main point is simple: locality is not privacy. `thread_ref` and
`container_ref` help correlate events, but `visibility_context` is the actual
memory boundary.

## One Concrete Scenario

Imagine two private rooms discussing the same incident.

- both rooms talk about the same reservation-ordering bug
- both rooms might use copied text or very similar wording
- both rooms might even use similar thread naming patterns

If you only relied on `thread_ref`, `container_ref`, or lexical similarity, it
would be easy to leak the wrong memory across scopes.

The current Pallium package avoids that by requiring explicit
`visibility_context` and enforcing visibility before ranking. A query in one
limited scope should only see `public` plus that exact limited scope.

## Why Visibility Exists

Without an explicit visibility contract, local memory can easily become broader
than the evidence that created it.

Pallium avoids that by making `visibility_context` a first-class part of:

- ingest
- storage
- retrieval
- evidence packaging
- thread aggregation
- higher-level consolidation

## Consumer Contract

Use the same shape on ingest and query:

```json
{
  "visibility_context": {
    "kind": "public" | "limited" | "user",
    "id": "..." | null
  }
}
```

Rules:

- `public`
  - globally visible inside the current Pallium deployment
  - `id` must be `null`
- `limited`
  - visible inside one bounded shared context such as a private room or channel
  - `id` is required
- `user`
  - visible only inside one user-private context
  - `id` is required

## Query Expansion Rules

Current phase-1 visibility semantics are built into Pallium:

- query in `public` sees:
  - `public`
- query in `limited:X` sees:
  - `public`
  - `limited:X`
- query in `user:U1` sees:
  - `public`
  - `user:U1`

The caller supplies the current visibility boundary. Pallium applies the built-in
expansion and filtering rules.

## Fail-Closed Behavior

For `agent_conversation_memory`, retrieval is fail closed.

Current behavior:

- missing query visibility returns no normal results
- debug trace reports `query_visibility_context_required`
- ingest without visibility can still be stored
- ingest without visibility is not promoted into memory for the scope-aware
  package
- items with missing visibility are excluded from normal scoped retrieval

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

## Locality Metadata Is Separate

These fields are still valuable:

- `container_ref`
- `thread_ref`
- `session_ref`
- `actor_ref`
- `source_ref`

But they are descriptive context, not the privacy model.

## What Pallium Owns vs What The App Owns

Pallium owns:

- the `visibility_context` contract
- phase-1 expansion rules
- retrieval enforcement before ranking
- visibility preservation through derivation
- visibility exclusion trace on the debug path

Your application owns:

- deciding what visibility boundary a new item belongs to
- passing the current visibility context on query
- any user or tenant authorization outside Pallium

Pallium is not an authorization service for your app. It is the memory layer
that enforces the visibility context you provide.

## Practical Integration Rules

- always send `visibility_context` with `agent_conversation_memory`
- do not rely on `container_ref` or `thread_ref` as a privacy shortcut
- do not expect Pallium to widen local memory for broader reuse
- use `POST /query/debug` when results are missing and you need to see
  visibility exclusions

## What Is Not Implemented Yet

The current model does not yet ship:

- explicit shared-memory publication across broader visibilities
- cross-container shared memory
- generalized visibility narrowing or intersection logic
- connector-specific privacy models inside the core

Those are later design steps, not hidden behavior in the current package.