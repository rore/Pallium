# Task: add-raw-history-governance (re-scoped → user-requested raw-turn forgetting)

Pallium vNext P0. Execution context: `docs/designs/015-vnext-historical-work-execution.md` (P0 contract).

> **Re-scope decision (2026-08-13, pending user confirmation):** investigation showed
> the original broad governance ticket is mostly a *straddle* — its mechanics attach to
> P1 search/expansion paths that don't exist yet, reuse redaction/visibility that already
> exist, or depend on the unbuilt P3 sharing/grant contract. This task is therefore
> narrowed to the **one standalone-buildable, testable-now P0 piece: user-requested
> forgetting of raw source turns.** The other pieces are folded into P1 items or deferred
> to P3 (see "Roadmap re-scope actions" below). See "Investigation findings" for evidence.

<!-- agent-workflow:start -->
**Outcome:**
A user can request that specific raw source turns (or a raw-turn scope) be forgotten, and thereafter those turns no longer appear in retrieval (query `source_hit`s) or source-context expansion. Distinct from `pallium_forget` (memory objects only) and from the existing TTL hard-delete retention job. This is a soft, auditable forget — not a hard delete.

**Target:**
pallium

**Scope:**
`storage/` (add a soft-delete/`forgotten` field to `source_items` + inline migration; exclude forgotten rows in index search); `core/filters.py` (exclude forgotten source items in `source_item_matches_filters`, parallel to the memory `lifecycle == "active"` gate); `core/service.py` (a `forget_source`/scope-based raw-forget entrypoint); `api/` + `app/mcp/` (raw-forget tool/endpoint); `tests/`. Plus roadmap re-scope edits (see below). NOT: redaction (already exists at ingest+read barriers), the P1-attached governance mechanics, shared-raw revocation (P3).

**Constraints:**
Do not alter `pallium_forget` (memory-object soft-delete). Forgetting is soft (auditable), not the TTL hard-delete. Retrieval must **fail-closed** exclude forgotten source items (both lexical + vector paths). Visibility semantics unchanged. `api-stays-thin` (api imports only core). No internal/external product names in committed docs/tests.

**Completion criteria:**
1. When a user forgets a raw turn (by `source_item_id`, and by a bounded scope e.g. thread/container), subsequent `/query` returns no `source_hit` for it and expansion does not surface it → E2E test.
2. Forgetting is idempotent and distinct from memory-object `pallium_forget` (memory forget does not forget source turns and vice-versa) → tests.
3. Forgotten state is recorded (auditable: who/when/why), not a hard delete → test asserts the row persists with a forgotten marker.
4. Visibility/exclusion is fail-closed (a forgotten item is never returned) → test.

**Risk:** High

**Complexity:** Moderate

**Reason:**
Persistence surface — new `source_items` soft-delete column + migration → `persistence-review`; `core/service.py` red → `architecture-review`. High per persistence/contract-surface clause. Moderate: storage + core + api + mcp + tests, one coherent slice. NOTE: redline pre-edit verdict must be run as the first implementation step to confirm (classification may be raised, not lowered).

**Discovery:**
(from three read-only investigations, 2026-08-13 — see "Investigation findings" prose for full detail)
- Redaction ALREADY applied at ingest (`core/service.py:325-328`, incl. `source_item.content`) and read (`_redact_query_result` at `core/service.py:701`; expand barrier `core/service.py:1338-1350`), with a `note` artifact carve-out. Single-file `redaction/__init__.py` (secrets/credentials only, not general PII, not configurable). → "redaction on search+expansion" is REUSE, not new code.
- Per-neighbor visibility ALREADY the pattern: `get_memory_expand` runs `is_visible` per evidence item (`core/service.py:1333-1344`). → source expansion mirrors it.
- `get_memory_expand` is UNBOUNDED (no item/token cap, `core/service.py:1326`). → bounded-window is a real gap, belongs in P1 `add-source-context-expansion`.
- `source_items` have NO lifecycle/forgotten/soft-delete/expires field (`storage/sqlite_schema.py:23-51`; `core/models.py:33-59`). Contrast memory objects: `lifecycle`, `is_soft_deleted`, `soft_deleted_at`, `soft_delete_reason` (`sqlite_schema.py:63,89-91`).
- `pallium_forget` acts ONLY on memory objects (`app/mcp/server.py:305-323` → `core/service.py:1019-1025` → `storage/sqlite.py:466-494` `soft_delete_memory`). No `delete_source_item` exists anywhere.
- A TTL retention job hard-deletes source items after 3/30/45 days with protection for items backing active memory objects (`storage/sqlite_retention.py:323-366,649-692`; TTLs `core/retention.py:13-17`). This is automated cleanup, NOT user-requested forgetting.
- Retrieval does NOT filter source items by any lifecycle (`core/filters.py:10-24` checks only source_type/role/artifact_kind/container/thread/actor; the memory branch gates `lifecycle != "active"` at `filters.py:59`).
- NO access-audit table records which source items were RETURNED by a query. `query_audit_log.source_item_id` is the *triggering* turn; `injected_blocks_json` has no source_item_id field (only `result_id` prefix-encodes it for injected blocks). → "access audit for raw reads" == the SAME exposed-source-ids recording that P0 telemetry deferred to P1. Build once, in P1.
- NO sharing/grant/revoke substrate anywhere (only OAuth `grant_type` + "shared source item" = two memories on one source). → shared-raw revocation depends entirely on the unbuilt P3 grant contract.

**Material assumptions:**
1. The re-scope (narrow this ticket to raw-turn forgetting; fold mechanics into P1; defer revocation to P3) is approved. Disproof: user wants the full governance item standalone now. Action: re-plan to build the P1-attached mechanics as scaffolding + define a sharing stub for revocation.
2. Soft-delete (auditable forgotten marker) is the right forgetting semantic, not hard delete. Disproof: user wants hard delete / GDPR-erasure semantics. Action: add a hard-erase path (ties into the TTL cascade `_delete_source_item_cascade_in_session`).
3. Forgetting is testable now via existing `/query` source hits (source hits already appear in the mixed pool today). Disproof: source hits are not returned by `/query` in the test harness config. Action: test via the storage/filter layer directly + add the raw-search path test in P1.
4. Access-audit exposures are built ONCE in P1 (serving both reuse funnel + governance access audit), not duplicated here. Disproof: governance needs a read audit before P1. Action: add a minimal raw-read audit here.

**Plan:**
Sequence:
1. Run redline pre-edit verdict (first implementation step, via `/agent-workflow`) to confirm High + checkpoints.
2. `storage/sqlite_schema.py`: add `forgotten`/`forgotten_at`/`forgotten_reason` (or reuse a soft-delete shape) to `SourceItemRecord` + `_SOURCE_ITEM_MIGRATIONS` inline ALTER. Update `core/models.py` SourceItem.
3. `storage/` index search (`sqlite_search.py` + vector path): exclude forgotten source items at the candidate level (fail-closed), parallel to how visibility/filters are applied.
4. `core/filters.py`: exclude forgotten source items in `source_item_matches_filters`.
5. `core/service.py`: `forget_source(source_item_id=..., scope=...)` writing the forgotten marker (auditable), distinct from `forget_memory`.
6. `api/` + `app/mcp/server.py`: an MCP tool + endpoint for raw-turn forgetting (naming distinct from `pallium_forget`).
7. `tests/`: E2E (forget by id + by scope → gone from `/query` source hits + expansion; idempotent; distinct from memory forget; fail-closed; row persists with marker).
Key conventions: inline ALTER migration pattern (`sqlite_schema.py:432-452`); soft-delete shape mirrors memory-object soft-delete; `api-stays-thin`; anonymized tests; label eval numbers per `docs/context/lessons.md`.
Deviations: re-scope of a committed roadmap item (documented above + roadmap edits below).
Stop conditions: if forgetting needs to interact with the TTL retention protection logic in a way that risks data loss → stop, reconcile. If redline flags a boundary violation → stop, escalate.

**Verification plan:**
1. When a raw turn is forgotten (by id and by scope), `/query` returns no `source_hit` for it and expansion omits it → HTTP E2E.
2. When memory `pallium_forget` is called, source turns are unaffected, and vice-versa → unit/integration.
3. When a forget is repeated, it is idempotent; the row persists with an auditable forgotten marker → unit.
4. When retrieval runs, a forgotten item is never returned on lexical OR vector paths (fail-closed) → integration.
5. Full suite unchanged → `python -m pytest tests/ -q` (real interpreter per `~/.claude/python-on-windows.md`).

**Plan review:**
Pending — clean-context agent review (High risk).

**Approvals:**
Pending — human approval required (High risk). Re-scope also pending explicit user confirmation.

**Exceptions:**
—

**State:** Blocked
<!-- Blocked: awaiting re-scope confirmation + clean-context plan review + High-risk approval before implementation. -->
<!-- agent-workflow:end -->

## Investigation findings (full — 2026-08-13, three read-only subagents)

**Redaction subsystem** (`redaction/__init__.py`, single 663-line file; exports `redact_sensitive`, `redact_command`, `redact_probable_secrets`, `is_sensitive_artifact`):
- Ingest write barrier: `core/service.py:325-328` redacts `content` + `metadata` before `SourceItem` construction (skips `artifact_kind == "note"`). LLM-response barrier `providers/llm/redacting_wrapper.py:94-96`. Operational-fact + reconnaissance field redaction.
- Read barriers: `PalliumService.query` → `_redact_query_result` (`core/service.py:701`, redacts injectable_blocks title/text + results excerpt/payload); `get_memory_expand` (`core/service.py:1338-1350`, redacts each evidence SourceItem content/metadata + match_text + payload). `note` carve-out on both.
- Retroactive CLI purge `app/tools/secrets_purge.py`. Secrets/credentials only (Tier A patterns + Tier B entropy), NOT general PII, NOT configurable.

**Memory-expand pattern** (`get_memory_expand`, `core/service.py:1303-1351`; route `api/routes.py:623`):
- Two visibility gates: coarse whole-memory container guard (`:1324-1325`) + per-item `is_visible` (`:1333-1344`, drops failing items silently). Redaction applied per item. NO item/token cap (unbounded). Route never passes `query_actor_ref` (arrives None; falls back to memory's actor_ref).
- NO share/grant/revoke substrate anywhere in the codebase.

**Source lifecycle/forgetting/audit:**
- `source_items` has no lifecycle/forgotten/deleted/expires field (schema + model). `pallium_forget` → `soft_delete_memory` (memory objects only). No `delete_source_item` method exists.
- TTL retention job hard-deletes source items (3/30/45 day TTLs) with active-memory protection (`storage/sqlite_retention.py`).
- Retrieval has no source-item lifecycle filter. No audit table records returned source ids.

## Roadmap re-scope actions (to do as part of this task — board management)

1. **This ticket** (`roadmap/features/add-raw-history-governance.md`): narrow scope to user-requested raw-turn forgetting/retention; move the other In-Scope bullets out (see below); keep `id` stable; note the moves in the ticket.
2. **`add-source-context-expansion`** (P1): add acceptance criteria for (a) bounded expansion window + token cap [genuine gap], (b) per-neighbor visibility [mirror `get_memory_expand`], (c) redaction [reuse read barrier].
3. **`add-raw-historical-search-mode`** (P1): add acceptance criteria that raw search routes through the existing redaction read barrier and visibility enforcement (reuse, verify with tests).
4. **Access-audit exposures**: note in the P1 items that the exposed-source-ids recording (deferred from `add-historical-lookup-funnel-telemetry`) doubles as the raw-read access audit — build ONCE.
5. **Shared-raw revocation → P3**: move to an idea/feature under P3, dependent on `idea-visibility-vocab-reconciliation` (the grant contract). Update `roadmap/board.md` groupings accordingly.

## Implementation

(not started — awaiting re-scope confirmation + plan review + approval)
