# Global Visibility Design

**Date:** 2026-05-03  
**Status:** Proposed  
**Author:** Rotem Hermon (with Claude)

## Problem

Pallium currently scopes all memories to a container (derived from git remote URL, Slack channel, etc.). A user working in repo A who says "never force-push on any project" or "always use tabs" has that stored in container A. It never surfaces when they work in container B.

There is no way to express "this memory should follow me across all my projects."

## Background: Current Visibility Model

### Two Independent Axes

**Visibility level** (on candidate items and queries) — a scope/sensitivity classification:
- `public` — broadest scope, eligible for widest reach
- `container` — medium scope, within this container's boundary
- `private` — narrowest scope, most restricted

**Actor ownership** (`actor_ref`) — who this belongs to, independent of visibility level.

These are orthogonal. An item can be `public` AND have an `actor_ref`.

### Candidate Visibility (what access level is needed to see this item)

| Candidate visibility | Within same container | Cross-container |
|---------------------|----------------------|-----------------|
| `public` | Visible to all query levels | Eligible to cross (subject to actor_ref policy) |
| `container` | Visible to `container` and `private` queries | Never crosses |
| `private` | Visible only to `private` queries | Never crosses |

### Query Visibility (what clearance level does the querier have)

| Query visibility | What it can see |
|-----------------|----------------|
| `"public"` | Only `public` items with `actor_ref=None` (lowest privilege) |
| `"container"` | `public` (no actor) + `container` items in same container |
| `"private"` (or None) | Everything in same container + cross-container `public` (no actor) |

### Actor_ref Cross-Container Policy (separate layer, commit 2886cdf)

For an item to be visible cross-container, it must be `public` AND `actor_ref = None`.

This prevents: a user expresses interest in something in a public channel → that personal interest (which is `public` because the channel is public, and has `actor_ref` because the user said it) shouldn't follow them into unrelated containers.

This is NOT part of the definition of `public`. It's an additional access gate for cross-container reach.

### Why Existing Values Don't Cover Global Memory

- `public + actor_ref=None` — crosses containers but has no owner. Team knowledge, not personal preference.
- `public + actor_ref=user` — deliberately blocked from crossing containers (commit 2886cdf) to prevent accidental leakage from public contexts.
- `container` / `private` — container-bound by definition.

## Design: Add `"global"` Visibility

### Semantics

`global` is a **special actor-scoped visibility** meaning "personal memory that follows this actor across all containers." It is not a fourth level in the `public/container/private` containment hierarchy — those form a scope hierarchy within a container. `global` is orthogonal: it expresses "actor-wide personal scope" regardless of container.

| Value | Meaning | Same container | Cross-container |
|-------|---------|---------------|-----------------|
| `public` | Broadest shared scope | Visible to all query levels | Crosses (if actor_ref=None) |
| `container` | Container-shared | Visible to container+ queries | Never |
| `private` | Most restricted | Visible to private queries only | Never |
| `global` | Actor-wide personal | Visible (same actor) | Crosses (same actor only) |

A `global` item:
- **Always has `actor_ref`** — it belongs to a specific person
- Is visible in **any container** where `query_actor_ref == candidate_actor_ref`
- Records `container_ref` as **provenance** (where it originated) but is not confined there
- Is **only created by explicit user request** (MCP `pallium_ingest` or equivalent), never by automatic extraction

### Visibility Check

New `is_visible()` logic (inserted before existing checks):

```python
if candidate_visibility == "global":
    return (
        candidate_actor_ref is not None
        and query_actor_ref is not None
        and candidate_actor_ref == query_actor_ref
    )
```

**Fail-closed:** If either actor is missing, `global` memories are invisible. Single-user integrations must derive a stable actor (e.g., `git config user.name` or `"local"`) and pass it explicitly.

### Ingest Shape

```json
{
  "visibility": "global",
  "actor_ref": "Rotem Hermon",
  "container_ref": "git:github.com/rore/pallium",
  "content": "Never force-push on any project",
  "source_type": "claude-code",
  "..."
}
```

`container_ref` records provenance (where the memory was created) but does not bound retrieval.

## Implementation Changes

### 1. Type Definition

Add `"global"` to the `Visibility` literal in `core/visibility.py`:

```python
Visibility = Literal["public", "container", "private", "global"]
```

### 2. `is_visible()` — Add `query_actor_ref` Parameter

```python
def is_visible(
    candidate_visibility: str | None,
    candidate_container_ref: str | None,
    query_container_ref: str | None,
    candidate_actor_ref: str | None = None,
    query_visibility: str | None = None,
    query_actor_ref: str | None = None,  # NEW
) -> bool:
    # Global: visible to same actor in any container, fail-closed
    if candidate_visibility == "global":
        return (
            candidate_actor_ref is not None
            and query_actor_ref is not None
            and candidate_actor_ref == query_actor_ref
        )

    # ... existing logic unchanged ...
```

### 3. Thread `query_actor_ref` Through Retrieval

Both retrieval providers call `is_visible()` — they need to pass `query_actor_ref`:

- `retrieval/base.py` — `RetrievalProvider.query()` interface gains `query_actor_ref` parameter
- `storage/sqlite_search.py` — `search_index_entries()` gains `query_actor_ref`, passes to `is_visible()`
- `retrieval/vector.py` — `VectorRetrievalProvider.query()` gains `query_actor_ref`, passes to `is_visible()`
- `retrieval/composite.py` — `CompositeRetrievalProvider.query()` passes through to both sub-providers
- `core/query.py` — `QueryExecutor.query()` passes `actor_ref` to retrieval as `query_actor_ref`; also threads it through the debug candidate loader (`_make_debug_candidate_loader`, line 200)
- `core/service.py` — `get_memory_evidence()` (line 702) passes `query_actor_ref` to `is_visible()`

Call chain: `QueryExecutor.query()` → `RetrievalProvider.query(query_actor_ref=...)` → `search_index_entries(query_actor_ref=...)` / `VectorRetrievalProvider.query(query_actor_ref=...)` → `is_visible(..., query_actor_ref=...)`

### 4. Exempt `"global"` in `core/filters.py` Container Filter

In `core/filters.py` lines 17 and 34, the container filter currently only exempts `"public"`:

```python
if filters.container_ref is not None and source_item.visibility != "public" and source_item.container_ref != filters.container_ref:
    return False
```

**This will silently exclude global memories from retrieval** when queried from a different container (the primary use case). The filter runs *before* `is_visible()`, so global memories would never reach the visibility check.

Fix: extend the exemption:

```python
if filters.container_ref is not None and source_item.visibility not in ("public", "global") and source_item.container_ref != filters.container_ref:
    return False
```

This applies to both `source_item_matches_filters` and `evidence_matches_filters`.

### 5. Processing Gate Adjustment

`core/service.py:149` currently skips processing when `container_ref is None or visibility is None`. For `global` items, `container_ref` will always be present (provenance), so no change needed — the existing gate passes.

### 6. Routing/Scoring Consideration

Global memories compete with container-scoped ones in every query. The routing layer should apply a demotion factor (e.g., 0.7–0.8× score) so container-specific memories win when both match a query. A global preference like "use tabs" should yield to a repo-specific coding convention memory.

**Status: Deferred.** The demotion factor requires live usage data to calibrate. The core visibility gate is implemented; scoring tuning will follow once global memories are in use and retrieval quality feedback is available.

### 7. Integration Layer — Claude Code

**Hook changes (for global memories to surface in queries):**

- `integrations/claude-code/hooks/user_prompt_submit.py` — Add `"query_actor_ref": actor_ref` to the `/item-and-query` payload. Currently `actor_ref` is sent for the ingest side but not threaded to the query as `query_actor_ref`. Without this, global memories are invisible in the hook's query response.
- `integrations/claude-code/hooks/session_start.py` — Add `derive_actor_ref()` call and `"actor_ref": actor_ref` to the `/query` payload. Currently queries without actor_ref, so global memories will never appear at session start.
- `integrations/claude-code/hooks/pre_compact.py` — Same fix as session_start.
- `integrations/claude-code/hooks/stop.py` — No change. Hardcodes `visibility: "private"` for assistant turn ingestion. Must never produce global memories.

**Agent instruction changes:**

- `integrations/claude-code/claude_md_block.py` — Update the `pallium_ingest` instructions. Currently says:
  ```
  - `visibility`: "private" (all memories in this integration are private)
  ```
  Change to explain two valid paths:
  - Default: `visibility: "private"` — project-scoped memory (normal case)
  - Global: `visibility: "global"` — only when user explicitly asks to remember something across all projects. Requires `actor_ref` to be set. `container_ref` still required (provenance).

### 8. Integration Layer — Codex

Same structural changes as Claude Code:

- `integrations/codex/hooks/user_prompt_submit.py` — Add `"query_actor_ref": actor_ref` to `/item-and-query` payload.
- `integrations/codex/hooks/session_start.py` — Add `derive_actor_ref()` and `"actor_ref": actor_ref` to `/query` payload.
- `integrations/codex/hooks/stop.py` — No change.
- `integrations/codex/AGENTS.md` — Update ingest instructions to document `visibility: "global"` path alongside default `visibility: "private"`.
- `integrations/codex/skills/pallium-memory/SKILL.md` — Add "For global storage" sub-case explaining when and how to use `visibility: "global"`.

### 9. MCP Layer

**No code changes needed.** The MCP server (`app/mcp/server.py`) accepts `visibility: str | None` with no validation — values are forwarded to the HTTP API where Pydantic validates against the `Visibility` literal. Once `core/visibility.py` adds `"global"` to the literal, MCP calls with `visibility="global"` will pass through cleanly.

**Documentation concern:** The env var `PALLIUM_ACTOR_REF` (read in `app/mcp/context.py` via `resolve_context()`) becomes critical for global memory. If not set, `actor_ref` will be `None` in the MCP context, and any global memory ingested via MCP will be permanently invisible (fails the `candidate_actor_ref is not None` check). Integration setup docs should document this requirement.

### 10. Query `actor_ref` Dual Purpose

The `/query` endpoint currently has a single `actor_ref` field that serves as both a filter (in `QueryFilters.actor_ref`) and will now also serve as the `query_actor_ref` for visibility gating. The `/item-and-query` endpoint already has a separate `query_actor_ref` field.

For the `/query` endpoint: the existing `actor_ref` parameter serves double duty — it both restricts results to a specific actor (filter) and identifies the querier for global visibility checks. This is acceptable because:
- In single-user integrations, the querier IS the actor being filtered for
- In multi-user scenarios, you'd only want to see your own global memories anyway

No API schema change needed — just thread the existing `actor_ref` value through to `is_visible()` as `query_actor_ref`.

## Feature Interactions

### Thread Rebuild

Source items ingested with `visibility="global"` will **not** participate in thread aggregation. The `visibility_matches_exact` guard in thread rebuild (`core/thread_rebuild.py`) requires exact visibility match between source item and thread scope. Since thread scopes are typically `"private"`, global source items are excluded.

This is correct behavior: global memories are standalone, explicitly-created items. They don't belong to the conversational flow of a thread. A user saying "remember this globally" is a meta-instruction, not part of the thread's content.

### Consolidation

Global memories will **not** be consolidation candidates with memories from other containers. The consolidation policy has `same_container_required=True` by default, and global memories carry their provenance `container_ref`. Two identical global preferences stated in different repos will not consolidate.

This is acceptable for now:
- Global memories are created by explicit user request, which naturally deduplicates (users won't say "use tabs" in every repo)
- If duplicate globals become a problem, a future `GlobalDeduplicationStrategy` could use `visibility="global"` as a grouping axis instead of `container_ref`
- Not in scope for this design

### Retention

No special retention behavior needed. Global memories participate in the existing retention lifecycle:
- Flag-based suppression works (same flag endpoint, same thresholds)
- `lifecycle` transitions (`active` → `superseded` → `suppressed`) apply normally
- If a retention policy needs to target globals specifically, it can filter on `visibility="global"`

### `query_visibility` Interaction

The `global` check short-circuits at the top of `is_visible()`, before `query_visibility` logic is evaluated. This means:
- `query_visibility="public"` with matching `query_actor_ref` **will** see global memories
- `query_visibility="container"` with matching `query_actor_ref` **will** see global memories

This is intentional: `global` is an actor scope orthogonal to the containment hierarchy. The user's personal global preferences should be visible regardless of what clearance level the query claims. Access is gated solely by actor identity.

### `query_container_ref is None` Semantics

The existing convention: when `query_container_ref is None`, `is_visible()` returns `True` for all visibility levels (line 31-32). The new `global` check is placed *before* this passthrough, which creates an exception: `global + missing query_actor_ref` returns `False` even when `query_container_ref is None`.

This is a deliberate break from the convention. The "see everything" passthrough exists for the case where no container context is available (unscoped queries). But global memories are actor-scoped by definition — without knowing WHO is asking, we cannot verify access. Fail-closed is correct here. Administrative/debug tooling that needs to see all memories should pass a `query_actor_ref`.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Noise: global memories surface everywhere | Routing demotion factor (applied in `semantic/agent_conversation_memory_routing_scoring.py`); injection slot cap in `_selection.py` (e.g., max 1-2 global blocks per query, consuming normal slots) |
| Accidental global: user doesn't mean "everywhere" | Only explicit ingest creates global; automatic extraction never does |
| Missing actor_ref: query without actor sees globals | Fail-closed: both `candidate_actor_ref` and `query_actor_ref` must be non-None |
| Stale globals: preference changes, old memory persists | Flag-based suppression works regardless of visibility; retention policy can target globals |
| Actor_ref collision: two users with same git user.name | Global memories from one user would be visible to the other. This is an existing limitation of string-based actor identity (not introduced by this spec), but global amplifies the blast radius since it's cross-container. Mitigation: integrations should derive stable unique actor_refs (email or qualified name). Not blocking for single-user deployments. |
| `matches_filters` excluding globals | Exemption added in `core/filters.py` (see section 4) |

## Non-Goals

- Multi-user access control changes (existing `public/container/private` hierarchy is unchanged)
- Automatic detection of "this should be global" from conversation content
- Global memories with no actor (team-wide globals) — use existing `public + actor_ref=None` for that
- Cross-container consolidation of global memories (dedup handled by explicit user intent; future work if needed)
- Thread participation for global source items (they are standalone meta-instructions, not conversational content)

## Testing Plan

### Unit Tests (`tests/test_visibility_scope.py`)

New `is_visible()` test cases:

1. `test_is_visible_global_same_actor_any_container` — `visibility="global"`, `candidate_actor_ref="alice"`, `query_actor_ref="alice"`, different containers → `True`
2. `test_is_visible_global_same_actor_same_container` — same as above but same container → `True`
3. `test_is_visible_global_different_actor` — `query_actor_ref="bob"` → `False`
4. `test_is_visible_global_missing_query_actor` — `query_actor_ref=None` → `False` (fail-closed)
5. `test_is_visible_global_missing_candidate_actor` — `candidate_actor_ref=None` → `False`
6. `test_is_visible_global_no_container_ref_no_actor` — `query_container_ref=None`, `query_actor_ref=None` → `False` (breaks the "no container = see everything" convention intentionally)
7. `test_is_visible_global_no_container_ref_with_actor` — `query_container_ref=None`, `query_actor_ref="alice"`, matching → `True`

### Unit Tests (`tests/test_actor_scoped_memory.py`)

Filter tests for `core/filters.py` exemption:

1. `test_source_item_matches_filters_global_crosses_container` — global source item in container A, filter with `container_ref=B` → passes filter (not excluded)
2. `test_evidence_matches_filters_global_crosses_container` — same for evidence path
3. `test_source_item_matches_filters_private_still_blocked` — confirm `private` items are still rejected cross-container (regression guard)

### Integration Tests (`tests/test_api.py` or new file)

End-to-end API tests:

1. `test_ingest_global_memory_and_query_cross_container` — ingest with `visibility="global"` + `actor_ref` + `container_ref=A`, process, query from container B with same `actor_ref` → memory appears in results
2. `test_global_memory_invisible_without_actor_ref_on_query` — same ingest, query without `actor_ref` → empty results
3. `test_global_memory_invisible_to_different_actor` — same ingest, query with different `actor_ref` → empty results
4. `test_global_memory_visible_in_same_container` — query from container A with same `actor_ref` → visible
5. `test_global_does_not_appear_in_extraction` — ingest a user message, drain processing, verify no `global` visibility memories are created (only explicit ingest creates them)

### MCP Tests (`tests/test_mcp_server.py`)

1. `test_ingest_with_global_visibility_forwards_to_client` — call `pallium_ingest` with `visibility="global"` and `actor_ref`, verify the HTTP payload includes both values correctly

### Eval Invariant Updates (`evals/generated_exploratory/invariants.py`)

**Existing invariants to update:**

- **INV-01 (`check_no_cross_container_leak`)** — Currently exempts `visibility == "public"`. Must also exempt `"global"` results **but only when** `result.actor_ref == query_actor_ref`. A global result from a mismatched actor IS a leak.
- **INV-04 (`check_no_visibility_violation`)** — Same pattern: exempt `"global"` with actor match, flag `"global"` with actor mismatch as a violation.

**New invariants to add:**

- **INV-14 (`check_no_global_memory_without_actor`)** — Any result with `visibility="global"` must have `actor_ref != None`. A global memory without actor indicates a storage bug.
- **INV-15 (`check_no_global_cross_actor_leak`)** — When query specifies `actor_ref=A`, no result with `visibility="global"` should have `actor_ref=B`.
- **INV-16 (`check_global_absent_without_actor_ref`)** — When query has no `actor_ref`, no global memories should appear (fail-closed guard).

### Eval Scenarios (`evals/generated_exploratory/scenarios/`)

New scenario file: `global_visibility_batch.json`

| # | Scenario | Validates |
|---|----------|-----------|
| 1 | `global-cross-container-recall` — Ingest global memory in container A (`actor_ref=X`), query from container B (`actor_ref=X`) → global memory appears | INV-14, INV-15, positive recall |
| 2 | `global-actor-isolation` — Ingest global for actor A, query with `actor_ref=B` → not visible | INV-15 |
| 3 | `global-no-actor-invisible` — Ingest global, query without `actor_ref` → not visible | INV-16 |
| 4 | `global-same-container-visible` — Ingest global in container A, query from container A with matching actor → visible | Basic positive case |
| 5 | `global-does-not-suppress-local` — Ingest global + local private on same topic, query from local container → private ranks at least as high as global | Demotion behavior |
| 6 | `global-coexists-with-public` — Ingest global (actor=X) + public shared (no actor) on overlapping topic, query from different container with `actor_ref=X` → both appear | Verifies global and public cross-container paths are independent |

### Test Priority

**P0 (must pass before merge):**
- All unit tests for `is_visible()` with global
- Filter exemption tests
- End-to-end ingest + cross-container query test
- INV-14, INV-15, INV-16
- Scenarios 1, 2, 3

**P1 (should pass for quality):**
- INV-01/INV-04 updated exemptions
- Scenarios 4, 5, 6
- MCP forwarding test
- Routing demotion test (once scoring is implemented)

## Summary of All Changed Files

### Core (must change to unblock):
- `core/visibility.py` — Add `"global"` to literal, add `query_actor_ref` param, add global short-circuit
- `core/filters.py` — Exempt `"global"` from container_ref filter (lines 17, 34)
- `core/query.py` — Thread `query_actor_ref` through to retrieval + debug candidate loader
- `core/service.py` — Thread `query_actor_ref` through `get_memory_evidence()`

### Retrieval (must change for global to be retrievable):
- `retrieval/base.py` — Add `query_actor_ref` to `RetrievalProvider.query()` interface
- `retrieval/composite.py` — Pass `query_actor_ref` through to sub-providers
- `retrieval/vector.py` — Accept and pass `query_actor_ref` to `is_visible()`
- `storage/sqlite_search.py` — Accept and pass `query_actor_ref` to `is_visible()`

### Integrations (must change for end-to-end):
- `integrations/claude-code/hooks/user_prompt_submit.py` — Add `query_actor_ref`
- `integrations/claude-code/hooks/session_start.py` — Add `actor_ref` to query
- `integrations/claude-code/hooks/pre_compact.py` — Add `actor_ref` to query
- `integrations/claude-code/claude_md_block.py` — Update agent instructions
- `integrations/codex/hooks/user_prompt_submit.py` — Add `query_actor_ref`
- `integrations/codex/hooks/session_start.py` — Add `actor_ref` to query
- `integrations/codex/AGENTS.md` — Update agent instructions
- `integrations/codex/skills/pallium-memory/SKILL.md` — Add global storage instructions

### No change needed:
- `app/mcp/server.py` — Already accepts `str | None`, no validation
- `app/mcp/client.py` — Already passes through `_scope_params()`
- `api/schemas.py` — Auto-fixed when `Visibility` literal is updated
- `integrations/claude-code/hooks/stop.py` — Hardcodes `"private"`, correct
- `integrations/codex/hooks/stop.py` — Same

### Tests and evals to add/update:
- `tests/test_visibility_scope.py` — 7 new unit tests
- `tests/test_actor_scoped_memory.py` — 3 new filter tests
- `tests/test_api.py` (or new file) — 5 integration tests
- `tests/test_mcp_server.py` — 1 new test
- `evals/generated_exploratory/invariants.py` — Update INV-01, INV-04; add INV-14, INV-15, INV-16
- `evals/generated_exploratory/scenarios/global_visibility_batch.json` — 6 scenarios
