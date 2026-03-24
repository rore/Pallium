---
id: add-actor-scoped-memory-and-container-visibility-rules
title: Add actor-scoped memory and container-driven visibility rules
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

Enforce actor attribution and container-driven memory scoping so that personal statements in shared channels don't become other users' personal memories, and shared decisions don't get hidden behind actor filters.

## Problem

In a public or container (team) channel, multiple users post messages. When user A says "Chroma sounds interesting, I should check it", Pallium creates an `interest` memory with `visibility=public` and no actor scoping. When user B queries, they see user A's interest injected as generic "user expressed interest in Chroma" — as if it's their own.

Observed in chat-lite testing: starting a new container still showed memories from the old session because both used public visibility and there's no actor filtering.

## Design Principles

1. **Separate where the memory is stored from who the memory is about.** Container visibility controls where it's accessible. Actor ref controls who it's personal to.
2. **Container type drives the rules, not memory type.** Don't try to detect "I" vs "we" in content — it's unreliable.
3. **Personal memory types don't get created in shared containers.** Interest and constraint are inherently personal — in shared contexts they fall through to discussion_summary (shared evidence).
4. **Simplicity first.** No taxonomy matrices, no scope enums, no consent models. Just actor_ref (nullable) plus container-driven rules.

## Rules

### Write-time: role restrictions on memory types

These restrict which source roles can produce which memory types (enforced in `semantic/common.py:build_process_result()`):

| Memory type | User messages | Assistant messages | Notes |
|---|---|---|---|
| `interest` | yes | **no** | Already enforced (role guard from ce1c1f3) |
| `constraint_memory` | yes | **no** | New — add same role guard as interest |
| `decision` | yes | yes | Decisions can be stated/confirmed by either role |
| `investigation_outcome` | yes | yes | Findings can come from either role |
| `discussion_summary` | yes | yes | Just a summary of what was said |
| `thread_summary` | n/a | n/a | Built from thread aggregation, both roles |
| `task_checkpoint` | n/a | n/a | Built from thread aggregation, both roles |
| `pattern_memory` | n/a | n/a | Built from consolidation |
| `continuity_memory` | n/a | n/a | Built from consolidation |

### Write-time: actor_ref propagation

Add `actor_ref` field to MemoryObject (nullable). Set based on container visibility at creation time:

**Private container (`visibility = 'private'`):**
- All memory types: `actor_ref` = source item's `actor_ref` (the speaker)
- Everything is personal to the container owner

**Shared containers (`visibility = 'container'` or `'public'`):**
- `interest` → **not created**. Falls through to `discussion_summary`. Rationale: interest is inherently personal ("I want to check X"). In shared contexts, this becomes shared evidence ("User mentioned interest in X") via discussion_summary.
- `constraint_memory` → **not created**. Falls through to `discussion_summary`. Same rationale: personal requirements vs team constraints are ambiguous, safer to treat as shared evidence.
- `decision` → created, `actor_ref = null`. Decisions in shared channels are team decisions, not personal.
- `investigation_outcome` → created, `actor_ref = null`. Findings in shared channels are shared knowledge.
- `discussion_summary` → created, `actor_ref = null`. Shared evidence.
- `thread_summary` → created, `actor_ref = null`. Shared.
- `task_checkpoint` → created, `actor_ref = null`. Shared.

### Query-time: visibility filtering

Two filters applied in sequence:

**Filter 1 — Container visibility (already exists):**
- `private` → only visible within same container_ref
- `container` → only visible within same container_ref
- `public` → visible from any container_ref

**Filter 2 — Actor scoping (new):**
- Memory has `actor_ref` set → only show if querying actor matches that actor_ref
- Memory has `actor_ref = null` → show to anyone with container access (shared evidence)
- If no actor_ref is provided in the query → skip actor filtering (backward-compatible)

**Combined effect:**

| Querying from | What you see |
|---|---|
| Private container (your DM) | All your personal memories (actor_ref = you) from this container |
| Limited container (team channel) | Shared evidence only (actor_ref = null). No personal interest/constraint types exist here. |
| Public container | Shared evidence only (actor_ref = null). No personal interest/constraint types exist here. |
| Cross-container (new session) | Public shared evidence (actor_ref = null, visibility = public). No personal memories from other containers. |

### Thread aggregation behavior

Thread aggregation (`thread_summary`, `task_checkpoint`) always produces shared memories (`actor_ref = null`) regardless of container type. Thread summaries are about the conversation, not about an individual.

In private containers, thread summaries are still container-scoped — they're only visible within that private container, so the actor scoping is implicit.

## Implementation Changes

### 1. `core/models.py` — Add `actor_ref` to MemoryObject

Add nullable `actor_ref: str | None = None` field to `MemoryObject`. This stores who the memory is about (not who created it — that's in evidence).

### 2. `storage/sqlite_schema.py` — Add `actor_ref` column

Add `actor_ref` column to `memory_objects` table. Nullable. Add migration for existing data (set to null for all existing memories).

### 3. `semantic/common.py` — Write-time rules

In `build_process_result()`:

**a. Role guard for constraint_memory** (same pattern as interest):
```
if source_item.role and source_item.role.lower() != "user":
    # skip constraint_memory, fall through to discussion_summary
```

**b. Container-driven interest/constraint suppression:**
```
if source_item.visibility in ('container', 'public'):
    # Do not create interest or constraint_memory
    # Fall through to discussion_summary
```

**c. Actor_ref propagation:**
```
if source_item.visibility == 'private':
    actor_ref = source_item.actor_ref  # personal memory
else:
    actor_ref = None  # shared evidence
```

### 4. `semantic/llm_agent_memory.py` — Prompt update (optional)

Update prompt variants to note that interest extraction may be skipped for shared containers. The code guard is the enforcement layer, but the prompt can avoid wasting LLM effort extracting interest from shared content if desired.

### 5. `storage/sqlite_search.py` — Actor filtering at query time

In `_matches_filters()`, add actor_ref check:
```
if filters.actor_ref is not None and memory_object.actor_ref is not None:
    if memory_object.actor_ref != filters.actor_ref:
        return False
```

This means: if the query specifies an actor AND the memory has an actor, they must match. Shared memories (actor_ref=null) always pass.

### 6. `retrieval/vector.py` — Same actor filter

Apply the same actor_ref filter in vector retrieval's `_matches_filters()`.

### 7. `core/models.py` — Add `actor_ref` to QueryFilters

Add optional `actor_ref: str | None = None` to QueryFilters. Agents pass this to scope queries to their user.

### 8. `api/routes.py` — Accept `actor_ref` in query API

Add optional `actor_ref` field to the query request schema. Pass through to QueryFilters.

### 9. Tests

- **Constraint role guard**: assistant message with constraint language should not create constraint_memory (same as interest test)
- **Shared container interest suppression**: user message with interest language in a public container should create discussion_summary, not interest
- **Actor_ref propagation**: memory created from user message in private container should have actor_ref set; in public container should be null
- **Actor query filtering**: query with actor_ref=A should see A's personal memories + shared memories; should NOT see actor_ref=B memories
- **Cross-container isolation**: new container should not see personal memories from old container even if both are public
- **Backward compatibility**: query without actor_ref should work as today (no actor filtering)

### 10. Documentation updates

**`docs/how-it-works.md`** — Add section on memory scoping:
- Explain private vs container vs public container behavior
- Explain that personal memory types (interest, constraint) are only created in private containers
- Explain that shared containers produce shared evidence only

**`docs/privacy-and-visibility.md`** — Update with actor scoping rules:
- Explain actor_ref field and what it means
- Explain the two-filter model (container visibility + actor scoping)
- Explain that personal statements in shared channels become shared evidence, not personal memories for others
- Document the design principle: "separate where the memory is stored from who the memory is about"

**`docs/http-api.md`** — Update query API docs:
- Document the new optional `actor_ref` field on query requests
- Explain query-time actor filtering behavior

**`docs/agent-integration.md`** — Update integration guidance:
- Explain when to pass actor_ref in queries
- Explain container visibility selection guidance for different scenarios (DM, team channel, public channel)

**`docs/context/architecture.md`** — Add actor scoping to architecture truths:
- "Personal memory types (interest, constraint_memory) are only created in private containers"
- "actor_ref on memory objects tracks who the memory is about, not who created it"
- "Query-time actor filtering prevents personal memories from being injected into other users' contexts"

**`docs/context/decisions.md`** — Record the design decision:
- Container type drives scoping, not memory type detection
- Interest and constraint suppressed in shared containers (fall through to discussion_summary)
- Actor_ref propagated from source item only in private containers

## Out of Scope

- Organization-level memory scoping (no org entity exists yet)
- Consent models for cross-user memory sharing
- LLM-based detection of "I" vs "we" (explicitly rejected — too unreliable)
- Interest extraction during thread aggregation (separate feature: investigate-thread-level-interest-and-threadless-aggregation)
- Storage_scope / subject_scope taxonomy (over-engineered for current needs)

## Dependencies

- `add-interest-memory-kind` (done) — interest type exists
- Current role guard for interest (done, ce1c1f3) — pattern to follow for constraint

## Done When

1. `constraint_memory` has role guard — assistant messages cannot create it
2. `interest` and `constraint_memory` are not created in container/public containers
3. `actor_ref` field exists on MemoryObject and is set correctly per container visibility
4. `actor_ref` filtering works at query time for both lexical and vector retrieval
5. Query API accepts optional `actor_ref`
6. All documentation updated (how-it-works, privacy, API, agent-integration, architecture, decisions)
7. Tests cover: role guard, container suppression, actor propagation, actor filtering, cross-container isolation, backward compatibility
8. Existing test suite passes with no regressions
