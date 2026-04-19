# Memory Flag Suppression

**Date:** 2026-04-17
**Status:** Draft
**Scope:** New feedback endpoint, memory lifecycle extension, flag storage

## Problem

Pallium sometimes extracts bad memories — fragments, stale transient state, context-dropped vagueness, meta-extraction loops where triage commentary gets re-ingested as new memories. These bad memories persist indefinitely and get injected on every turn, crowding out useful memories.

The integrating agent already detects bad memories: its LLM judges injected memories and flags them via structured tags. But the flags go to operator notifications — Pallium never hears about them. There is no feedback endpoint, no update API, and no mechanism to suppress a memory based on external quality signals.

Observed failure modes from live triage (14 flagged memories in a single session):

| Mode | Count | Example |
|------|-------|---------|
| Fragment extraction | 3 | Table cell `"\| Can do \|"` stored as investigation outcome |
| Meta-extraction loop | 2 | Triage commentary about a bad memory re-ingested as a new memory |
| Transient state → durable fact | 5 | "Daemon running old code" — true for 15 minutes, stored permanently |
| Context-dropped vagueness | 5 | "user is concerned about a change being safe" — no specificity |
| Ranking overpromotion | 1 | One garbage fragment injected on 8/12 turns regardless of topic |

## Solution

Add a flag endpoint that records quality feedback from integrating agents. After repeated independent flags, suppress the memory — exclude it from retrieval.

Two modes:
- **Threshold-based suppression** for conversational LLM flags (needs consensus from multiple independent sessions)
- **Immediate suppression** for human-reviewed triage (already confirmed bad, no consensus needed)

### Design Principles

- **Conservative suppression.** Two independent sessions must agree before a memory is suppressed. One flag from one session is not enough — it could be contextual disagreement, not intrinsic quality failure.
- **Session dedup.** Multiple flags from the same session count as one voice. A chatty session that flags the same memory on every turn doesn't inflate the count.
- **Time-bounded.** Only flags from the last 30 days count toward the threshold. Old flags stay in storage for audit but don't contribute to suppression decisions.
- **Non-blocking for callers.** The endpoint is designed for best-effort calls. If the integrating agent can't reach Pallium, it logs and moves on.

## New Lifecycle State: `suppressed`

The `lifecycle` field on `MemoryObject` gains a third value:

| State | Meaning | Retrieval |
|-------|---------|-----------|
| `active` | Normal | Included |
| `superseded` | Replaced by a newer memory | Excluded |
| `suppressed` | Flagged as bad by external feedback | Excluded |

Retrieval already filters by `lifecycle == "active"`. Adding `suppressed` requires no retrieval logic changes — it's excluded by the same filter that excludes `superseded`.

Retention: suppressed memories follow the same TTL as superseded memories (7 days via `SUPERSEDED_MEMORY_TTL` in the cleaner). The cleaner's query must be widened from `lifecycle == "superseded"` to `lifecycle.in_(["superseded", "suppressed"])`. After TTL, suppressed memories are deleted along with their evidence and flags.

**Flagging a superseded memory:** Accepted and recorded for audit, but lifecycle stays `superseded`. A superseded memory is already excluded from retrieval — suppression adds nothing.

## Flag Storage

```sql
CREATE TABLE memory_flags (
    id TEXT PRIMARY KEY,
    memory_object_id TEXT NOT NULL REFERENCES memory_objects(id),
    reason TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    flagged_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_memory_flags_memory_id ON memory_flags(memory_object_id);
```

Each row is one flag event. The `source_ref` identifies who flagged it (e.g., `agent-session:f890d298` or `triage-review:2026-04-17T14:00:00Z`). Dedup counts distinct `source_ref` values, not rows.

Flags are not deleted when the memory is suppressed — they remain for audit. They're cleaned up when the memory itself is deleted by retention.

## API Endpoint

```
POST /memory/{memory_object_id}/flag
```

**Request body:**

```json
{
  "reason": "Outdated: PR was merged hours ago",
  "source_ref": "agent-session:f890d298",
  "immediate": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `reason` | string | yes | — | Why the memory is bad |
| `source_ref` | string | yes | — | Identifies the flag source, used for dedup |
| `immediate` | bool | no | `false` | When `true`, suppress immediately without threshold |

**Response:** `200 OK`

```json
{
  "memory_object_id": "a8efd630-2a64-497f-a80d-c238825981d3",
  "flag_count": 2,
  "unique_sources": 2,
  "suppressed": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `flag_count` | int | Total flags on this memory (all time, not just within window) |
| `unique_sources` | int | Distinct `source_ref` values within the 30-day window |
| `suppressed` | bool | Whether the memory is now suppressed (may have been suppressed before this call) |

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Unknown `memory_object_id` |
| `422` | Missing required fields |

**Idempotent behavior:** If the memory is already suppressed, the endpoint returns the current state without error. Subsequent flags are still recorded for audit.

## Suppression Logic

```python
def flag_memory(memory_object_id: str, reason: str, source_ref: str, immediate: bool = False) -> FlagResult:
    # 1. Record the flag
    store_flag(memory_object_id, reason, source_ref)

    # 2. Check if already suppressed (or superseded — don't change lifecycle)
    memory = get_memory_object(memory_object_id)
    if memory.lifecycle in ("suppressed", "superseded"):
        return current_state(memory)

    # 3. Immediate mode — suppress now
    if immediate:
        set_lifecycle(memory_object_id, "suppressed")
        return current_state(memory)

    # 4. Threshold check — count unique sources within window
    unique_sources = count_unique_sources(
        memory_object_id,
        window_days=FLAG_WINDOW_DAYS  # 30
    )
    if unique_sources >= FLAG_SUPPRESSION_THRESHOLD:  # 2
        set_lifecycle(memory_object_id, "suppressed")

    return current_state(memory)
```

## Configuration

Defined in service-level config (not hardcoded):

```python
FLAG_SUPPRESSION_THRESHOLD = 2   # unique sources needed to suppress
FLAG_WINDOW_DAYS = 30            # rolling window for counting flags
```

Both are tuning knobs. Start conservative, adjust based on observed false-suppression rate.

## MCP Tool

A new `pallium_flag_memory` tool is exposed alongside the existing query/ingest/evidence tools:

```python
@server.tool()
async def pallium_flag_memory(
    memory_object_id: str,
    reason: str,
    source_ref: str,
    immediate: bool = False,
) -> str:
    """Flag a Pallium memory as bad. Use when an injected memory is incorrect, outdated, a meaningless fragment, or contradicts known facts. Pass the memory_object_id from the [ref: ...] annotation on the memory block. After enough independent flags, the memory is suppressed and stops being injected."""
```

The tool proxies to `POST /memory/{memory_object_id}/flag` via the existing `PalliumMcpClient` pattern. Same context resolution (base URL from env), same error handling.

This enables both programmatic feedback from the integrating agent's infrastructure layer and direct flagging by the LLM when it has MCP tool access.

## Files Changed

1. **`core/models.py`**
   - `MemoryObject.lifecycle`: add `"suppressed"` to allowed values
   - New model: `MemoryFlag` (id, memory_object_id, reason, source_ref, flagged_at)

2. **`storage/sqlite.py`**
   - New table: `memory_flags` (migration)
   - New method: `store_memory_flag(memory_object_id, reason, source_ref)`
   - New method: `count_unique_flag_sources(memory_object_id, window_days) -> int`
   - New method: `list_memory_flags(memory_object_id) -> list[MemoryFlag]`

3. **`storage/sqlite_retention.py`**
   - Modified: superseded memory retention query widened to include `"suppressed"` lifecycle
   - Modified: `_delete_memory_object_cascade_in_session` deletes associated `memory_flags` rows

4. **`storage/sqlite_schema.py`**
   - New ORM record: `MemoryFlagRecord` (auto-created by `Base.metadata.create_all()`)

5. **`core/service.py`**
   - New method: `flag_memory_object(memory_object_id, reason, source_ref, immediate) -> FlagResult`

6. **`api/routes.py`**
   - New route: `POST /memory/{memory_object_id}/flag`

7. **`api/schemas.py`**
   - New request schema: `FlagMemoryRequest(reason, source_ref, immediate)`
   - New response schema: `FlagMemoryResponse(memory_object_id, flag_count, unique_sources, suppressed)`

8. **`app/mcp/server.py`**
   - New tool: `pallium_flag_memory(memory_object_id, reason, source_ref, immediate)`

9. **`app/mcp/client.py`**
   - New method: `flag_memory(memory_object_id, reason, source_ref, immediate)`

10. **`docs/context/architecture.md`**
    - Update lifecycle section to include `suppressed`
    - Update MCP endpoint section to list new tool

11. **`docs/context/decisions.md`**
    - Narrow the open "Memory lifecycle" decision to note that lifecycle expansion is now partially addressed

## What Doesn't Change

- **Retrieval path.** Already filters `lifecycle == "active"`. Suppressed memories excluded by existing logic.
- **Existing MCP tools.** `pallium_query`, `pallium_query_debug`, `pallium_ingest`, and `pallium_get_evidence` are unchanged.
- **Supersession.** Unaffected. Supersession replaces a memory with a better one. Suppression removes without replacement. Orthogonal mechanisms.
- **Extraction/ingestion.** This design doesn't change how memories are created — it adds a post-hoc quality signal.
- **Query audit log.** Continues to record injection decisions as before.
- **Envelope confidence field.** Not used by this design. Remains available for future use.

## What This Doesn't Do (Intentionally)

- **No severity categories.** All conversational flags are equal weight. Complexity not justified by current data.
- **No correction/replacement.** Suppression only. If a bad memory needs replacing with a better version, use existing supersession.
- **No unflag/restore mechanism.** If a good memory is falsely suppressed, manual DB fix for now. Add a restore endpoint if false suppressions become a real problem.
- **No contextual awareness.** A flag counts globally, not per-query-type. The concern that "a memory might be correct in another context" hasn't manifested in practice — all 14 triage flags were intrinsically bad.
- **No confidence scoring.** Binary: active or suppressed. Continuous confidence decay is more complex to reason about and not needed at this stage.

## Validation Plan

1. **Unit tests:**
   - Flag stored correctly, returned in list
   - Dedup: two flags from same `source_ref` → `unique_sources = 1`, not suppressed
   - Threshold: two flags from different `source_ref` within 30 days → suppressed
   - Window: one flag from 31 days ago + one from today → `unique_sources = 1` within window, not suppressed
   - Immediate mode: one flag with `immediate: true` → suppressed
   - Idempotent: flag already-suppressed memory → 200 OK, flag recorded, lifecycle unchanged
   - Flag superseded memory → 200 OK, flag recorded, lifecycle stays `superseded`
   - 404 on unknown memory ID
   - Retention: suppressed memory deleted after TTL, flags cleaned up with it
   - MCP tool: `pallium_flag_memory` proxies correctly and returns structured result

2. **Integration test:**
   - Create memory → flag it twice from different sources → query returns empty (memory suppressed)

3. **Manual validation:**
   - Deploy, run a session, observe flag DMs, verify suppressed memories stop appearing in injection
