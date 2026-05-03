# Privacy And Visibility

This document explains the current privacy model for Pallium's
`agent_conversation_memory` package.

The main point is simple: `container_ref` is the scope boundary, and
`visibility` controls who can see items across containers.

## One Concrete Scenario

Imagine two private channels discussing the same incident.

- both channels talk about the same production bug
- both channels might use copied text or very similar wording
- both channels might even use similar thread naming patterns

If you only relied on `thread_ref` or lexical similarity, it would be easy to
leak the wrong memory across scopes.

Pallium avoids that by enforcing `visibility` before ranking. A query
from one container only sees items from that container plus public items from
other containers.

## Container Visibility

Every item has a `visibility` value:

- `"public"` — visible to queries from any container
- `"container"` — visible only to queries from the same `container_ref`
  (group context such as a private channel)
- `"private"` — visible only to queries from the same `container_ref`
  (personal context such as a DM)

Default: `"private"`.

`container_ref` is the scope identity. Items in the same `container_ref` can
see each other. `visibility` controls whether items can also be seen
from other containers.

## Global Visibility

`"global"` is an actor-scoped visibility level for personal memory that follows
a user across all containers.

A global item is visible if and only if the query's `actor_ref` matches the
item's `actor_ref`. Container boundaries do not apply — the memory travels with
the person, not the workspace. Both `actor_ref` values must be non-null; if
either is missing the item is invisible (fail-closed).

Use global for memories that are genuinely about the person regardless of where
they work: tool preferences, workflow conventions, personal constraints. Do not
use it for project-specific decisions or team context — those belong at
`container` or `private` scope.

**Example:** A developer tells the agent in repo A that they prefer verbose test
output. The agent stores this with `visibility: "global"` and
`actor_ref: "user:alice"`. Later, in repo B, a query with
`actor_ref: "user:alice"` surfaces that preference — even though repo B is a
completely different container.

Global items are exempt from the container filter: they do not need a matching
`container_ref` to appear in results. They still pass through actor scoping and
routing like any other candidate.

## Retrieval Rules

- query from container X sees:
  - all `container` and `private` items where `container_ref` matches X
  - all `public` shared items from any container (`actor_ref = null`)
  - `public` personal items (`actor_ref` set) only if `container_ref` matches X
  - all `global` items where the query's `actor_ref` matches the item's
    `actor_ref` (regardless of container)
- query without `container_ref` sees `public` items and matching `global` items

Personal memories do not leak across containers. A `public` item with
`actor_ref` set is only visible from its own container. This prevents a
user's personal interest from a public channel appearing in a different
session's context. Shared knowledge like decisions and thread summaries
(`actor_ref = null`) flows freely across containers when public.

Global items are the exception to container scoping — they follow the actor, not
the workspace. The fail-closed requirement (both actor refs must be present and
match) ensures that global memory is never surfaced to anonymous or mismatched
queries.

The caller sends `container_ref`, `visibility`, and `actor_ref` on ingest and
query. Pallium applies the filtering rules.

## Actor Scoping

Container visibility controls where memory is accessible. The `actor_ref` field
controls who a memory is about.

The design principle: separate where the memory is stored from who the memory is
about.

`actor_ref` is a nullable string on `MemoryObject`. It is set from the source
item's `actor_ref` in private containers and is always `null` in shared
containers. Thread-level memories (`thread_summary`, `task_checkpoint`) always
have `actor_ref = null` because they describe the conversation, not an
individual.

**Example:** Alice and Bob both use a shared agent. Alice asks the agent in a DM
to remember she prefers dark mode. Bob asks in a different DM about display
settings. Alice's `interest` memory has `actor_ref = "alice"` and
`visibility = "private"` in her DM container. When Bob queries from his DM
container, Alice's preference is invisible — it fails both the container
visibility check and the actor scoping check. If they both work in a shared
channel and Alice mentions her preference there, it is not promoted to any
memory type (personal types are suppressed in shared containers), but the
source item remains as shared evidence visible to everyone in that channel.

Query-time filtering applies two filters in sequence:

1. **Container visibility** — scopes results by container access
2. **Actor scoping** — if the query provides `actor_ref` and the memory
   has a non-null `actor_ref`, they must match. Shared memories
   (`actor_ref = null`) always pass. Queries without `actor_ref` skip actor
   filtering entirely.

Personal memory types (`interest`, `constraint_memory`) are not created in
shared containers (`container` or `public`). The source items remain as
shared evidence, but no personal memory object is produced. This means personal
statements in shared channels do not become memory objects that could be
injected into another user's context.

| Container type | Memory created | actor_ref |
|----------------|----------------|-----------|
| private | all types | speaker from source item |
| container / public | interest and constraint suppressed | null (shared) |

This keeps the model simple: container type drives the rules, not content
analysis or memory type detection.

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

- the `visibility` contract
- retrieval enforcement before ranking
- visibility preservation through derivation
- visibility exclusion trace on the debug path

Your application owns:

- deciding what `visibility` a new item belongs to
- sending `container_ref` on ingest and query
- any user or tenant authorization outside Pallium

Pallium is not an authorization service for your app. It is the memory layer
that enforces the visibility boundary you provide.

## Practical Integration Rules

- always send `container_ref` with `agent_conversation_memory`
- use `visibility` to distinguish public channels, private channels,
  and DMs
- use `POST /query/debug` when results are missing and you need to see
  visibility exclusions

## What Is Not Implemented Yet

The current model does not yet ship:

- explicit shared-memory publication across broader visibilities
- generalized visibility narrowing or intersection logic
- organization-level memory scoping
- consent models for cross-user memory sharing
- routing demotion for global items (currently treated at equal weight to
  container-local results; future calibration may introduce a cross-container
  penalty)

Those are later design steps, not hidden behavior in the current package.
