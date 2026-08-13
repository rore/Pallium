# Task: add-source-context-expansion

Pallium vNext P1. Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
Part of the overnight P1 run (auto-merge when green; resolve blockers with best judgment).

<!-- agent-workflow:start -->
**Outcome:**
Given a raw `source_item_id` (e.g. from `pallium_search_history`), a caller can fetch a bounded neighborhood of surrounding raw turns in the same thread to act on the hit — visibility-enforced per neighbor, redaction-aware, forgotten-excluded. Derived memories the source supports are returned only behind an explicit opt-in, as a separate field. An expansion can carry a `parent_lookup_id` linking it back to the lookup that produced the id.

**Target:**
pallium

**Scope:**
`core/service.py` (new `get_source_context`, mirroring `get_memory_expand`); `storage/sqlite.py` (new bounded windowed neighbor query by `thread_position` range with a LIMIT push-down — avoids loading the whole thread); `api/routes.py` (`GET /source/{id}/context`); `api/schemas.py` (`SourceContextResponse` + neighbor item shape); `app/mcp/client.py` + `app/mcp/server.py` (client method + `pallium_expand_source` tool); `tests/`. NOT: summarizing/packaging expanded context (Phase 2); cross-thread/cross-container expansion; recording an exposed-source-ids audit table (that is the deferred telemetry item — `parent_lookup_id` here is echoed, not stored); mixing supported memories into the default payload.

**Constraints:**
Bounded window is a GOVERNANCE property, not just UI: neighbor count AND a size cap, pushed into SQL (never an unbounded transcript walk). Per-neighbor `is_visible` with the anchor-derived effective scope — never widen to the whole thread. Carry the P0 forgotten-source gate explicitly (direct-fetch path, not via `matches_filters`): skip forgotten neighbors, and a forgotten/invisible ANCHOR yields no context (404, fail-closed). Redaction with the `note` carve-out, mirroring `get_memory_expand`. Supported memories opt-in only + separate field + each visibility-filtered. Pass `query_actor_ref` (do NOT copy the `/memory/{id}/expand` gap that omits it). `api-stays-thin`. No internal/external product names in committed docs/tests.

**Completion criteria:**
1. Given a `source_item_id`, a caller retrieves neighbor raw turns within a bounded window (count + size cap), with per-neighbor visibility enforcement; supported memories returned only when explicitly requested, as a separate field → tests.
2. lookup → expand chains end to end, with `parent_lookup_id` echoed on the expansion → test.
3. Expansion honors visibility fail-closed (0 violations) per neighbor and respects the window/size bound → tests (mixed-visibility thread; oversized thread capped).
4. Forgotten turns excluded: a forgotten neighbor is omitted; a forgotten anchor yields no context (404) → tests.

**Risk:** High

**Complexity:** Moderate

**Reason:**
`core/service.py` red → architecture-review; `api/routes.py` + `api/schemas.py` red → api-review; new storage read path. High per contract-surface + new API endpoint. Moderate: service + storage + api + schemas + mcp + tests, one coherent slice. Redline pre-edit verdict runs first (may raise).

**Discovery:**
(from a read-only investigation, 2026-08-13 — file:line cited)
- Mirror `get_memory_expand` (`core/service.py:1357-1411`): container gate (`:1378` → KeyError/404), `effective_container = container_ref or parent.container_ref` (`:1377`), forgotten skip (`:1391-1392`), per-item `is_visible` (`:1394`), `note` carve-out (`:1398`), per-item redaction (`:1399-1403`). UNBOUNDED — the new path adds the bound. `effective_actor_ref = query_actor_ref or parent.actor_ref` (`:1393`).
- Neighbors: `thread_position` is a monotonic 1-based per-thread sequence set at ingest (`create_source_item` `storage/sqlite.py:162-173`; packages variant `:213-226`). `list_source_items_for_thread` (`:248-258`) returns the WHOLE thread ordered by `created_at` — no window variant. → ADD a windowed query `WHERE container_ref=? AND thread_ref=? AND thread_position BETWEEN ? AND ? ORDER BY thread_position LIMIT ?` (bound pushed into SQL; slicing the full list in Python reintroduces the unbounded read).
- Reverse `supported_by` ALREADY exists: `list_memory_objects_for_source_item(source_item_id, ...)` (`storage/sqlite.py:739-766`), plus a batch variant (`:768-805`) — filters soft-deleted + lifecycle. No new storage method for this. Still must `is_visible`-filter each returned memory (they can be global/other-container).
- `SourceItem.forgotten` is a derived property (`core/models.py:62-70`).
- Existing `/memory/{id}/expand` route (`api/routes.py:628-658`) passes only `container_ref`, NOT `query_actor_ref` (`:631`) — do not copy this gap. Response schemas `MemoryExpandResponse` (`api/schemas.py:201-208`), items `MemoryEvidenceItemResponse` (`:189-198`). Source-route precedent: `POST /source/forget` + `ForgetSourceRequest/Response`.
- `parent_lookup_id`: NO column/table/consumer exists anywhere (only specs/roadmap). Measurement contract: P0 "schema specified", P1 "recorded on expansion"; exposed-source-ids audit explicitly separate/deferred. → echo in the response now; no table (additive-migration pattern exists if ever needed).
- `is_visible` (`core/visibility.py:24-57`), `redact_sensitive`/`_redact_ingest_value` reusable verbatim.
- MCP: mirror `pallium_search_history`/`pallium_expand`; tests skip when mcp absent (`tests/test_mcp_integration.py` importorskip) → cover via HTTP/service + a standalone client test.

**Material assumptions:**
1. Window params: `before`/`after` neighbor counts (defaults small, hard-capped) + a char-based size cap (token proxy, no tokenizer dep). Disproof: reviewer wants a real token count. Action: swap the char cap for a token count via the embedding tokenizer.
2. Forgotten/invisible anchor → 404 (fail-closed, don't reveal existence). Disproof: reviewer wants an empty-200. Action: return 200 with empty items. (404 is the safer default.)
3. `parent_lookup_id` echoed, not stored (no reader exists; audit is the deferred telemetry item). Disproof: measurement needs it persisted now. Action: additive column on `query_audit_log` via the existing `_ensure_*_columns` pattern.
4. Neighbor item reuses a source-turn shape (excerpt + occurred_at + thread/actor + source_item_id + thread_position). Disproof: reviewer wants full content, not excerpt. Action: return content (still redacted + size-capped).

**Plan:**
1. Redline pre-edit verdict (via `/agent-workflow`).
2. `storage/sqlite.py`: `list_source_items_in_thread_window(container_ref, thread_ref, start_position, end_position, limit)` → ORDER BY thread_position, LIMIT.
3. `core/service.py`: `get_source_context(source_item_id, *, container_ref=None, query_actor_ref=None, before=N, after=N, max_chars=..., include_supported_memories=False, parent_lookup_id=None)`. Fetch anchor; 404 if missing/forgotten/not visible; derive effective scope; fetch window around anchor.thread_position (hard-cap before/after); per-neighbor forgotten-skip + is_visible + redaction/note carve-out + cumulative size cap; optional supported memories (reverse query, is_visible-filtered, separate); return anchor + neighbors + supported + echoed parent_lookup_id.
4. `api/schemas.py`: `SourceContextResponse` + `SourceContextItemResponse` (thread_position, excerpt/content, occurred_at, actor/thread, source_item_id, forgotten never true).
5. `api/routes.py`: `GET /source/{id}/context` query params (container_ref, query_actor_ref, before, after, max_chars, include_supported_memories, parent_lookup_id); 404 on unknown/forgotten/invisible anchor.
6. `app/mcp/client.py` + `server.py`: `get_source_context` client method + `pallium_expand_source` tool (accepts source_item_id + window + include_supported_memories + parent_lookup_id).
7. Tests: bounded window (oversized thread capped to before/after + size); per-neighbor mixed-visibility drop (fail-closed); forgotten neighbor omitted + forgotten anchor 404; supported memories only when opted in + separate field + visibility-filtered; parent_lookup_id round-trip; lookup→expand chain (source_item_id from search feeds expand).
Stop conditions: if a bounded SQL window can't be expressed cleanly against thread_position → reconsider (fallback: fetch thread + slice with a hard LIMIT, documented). If reverse-supported leaks cross-container memories despite is_visible → stop, reconcile.

**Verification plan:**
1. Bounded window: an oversized thread returns only the capped neighborhood → test.
2. Per-neighbor visibility fail-closed (0 violations) in a mixed-visibility thread → test.
3. Forgotten neighbor omitted; forgotten/invisible anchor → 404 → tests.
4. Supported memories opt-in + separate + visibility-filtered → test.
5. parent_lookup_id echoed; lookup→expand chains → test.
6. Full suite green → `python -m pytest tests/ -q` (real interpreter).

**Plan review:**
Clean-context agent review completed (2026-08-13). Findings adopted:
- SEV-1 (cross-container leak): the anchor visibility gate MUST use the caller's `container_ref`, mirroring `get_memory_expand` (`core/service.py:1378`). Source items have no `"global"` — the carve-out is `visibility == "public"`. Gate: `if container_ref is not None and anchor.visibility != "public" and anchor.container_ref != container_ref → 404`. Only then use `effective_container = container_ref or anchor.container_ref`; every neighbor re-checked with `is_visible(..., query_container_ref=effective_container)` (caller scope), never widened to `anchor.container_ref`.
- SEV-2 (thread_position unreliable): retention hard-deletes source items (`storage/sqlite_retention.py:684`) and `thread_position = COUNT(*)+1` (`sqlite.py:171,222`) with NO unique constraint (`sqlite_schema.py:50`) → gaps + duplicate positions. Do NOT use `BETWEEN thread_position`. Use a two-sided window on `(created_at, id)` (always set, dup-safe): preceding = rows `< (anchor.created_at, anchor.id)` ORDER BY created_at DESC,id DESC LIMIT before; following = rows `> ...` ORDER BY created_at ASC,id ASC LIMIT after. Deterministic tiebreak, matches `list_source_items_for_thread` ordering.
- SEV-3 (parent_lookup_id): contract lists it under P1 "recorded on expansion", distinct from the deferred exposed-source-ids audit. ECHO it now (no query_audit_log column/reader exists; expansions aren't lookups — conflating them is wrong modeling). Persistence belongs to the deferred exposures audit. Documented in code + PR for user sign-off; not a blocker under the auto-merge mandate.
- SEV-3b (size cap): anchor is ALWAYS included and exempt from the cap; neighbors filled nearest-first outward, farthest dropped when the char budget is hit; length measured AFTER redaction.
- SEV-4 (reverse-supported): `list_memory_objects_for_source_item` pre-filters soft-deleted + lifecycle but NOT container/actor → each supported memory MUST pass `is_visible` with the caller scope before return (a global same-actor memory is kept; an other-container non-public one dropped).
- Tests added beyond the original set: (1) cross-container caller anchor gate → 404 (adversarial, the contract's 0-violations proof); (2) anchor-always-included (before=after=0 → anchor only; tiny max_chars still returns anchor); (3) size-cap truncation drops farthest; (4) neighbor window robust after a mid-thread deletion; (5) supported-memory scoping (global kept, other-container dropped).

**Approvals:**
Approved by user 2026-08-13: "yes, auto merge if all green" — overnight mandate to complete all P1 work, auto-merging each PR when CI + review are fully green. Blocker policy: "try to resolve blockers if you can, only break if you really need me."

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Shipped (branch `feat/add-source-context-expansion`):
- `storage/sqlite.py`: `list_source_item_neighbors(container_ref, thread_ref, *, anchor_created_at, anchor_id, before, after)` — two-sided `(created_at, id)`-ordered window with SQL LIMIT per side (dup/gap-safe; not thread_position).
- `core/service.py`: `get_source_context(...)` mirroring `get_memory_expand` — fail-closed anchor gate (forgotten → 404; caller-vs-container gate with `"public"` carve-out; is_visible), per-neighbor forgotten-skip + is_visible(caller scope) + redaction/note carve-out, anchor always included + exempt from the char cap, nearest-first fill dropping farthest, opt-in supported memories via `list_memory_objects_for_source_item` each is_visible-filtered, echoed `parent_lookup_id`.
- `api/schemas.py`: `SourceContextItemResponse`, `SupportedMemoryResponse`, `SourceContextResponse`.
- `api/routes.py`: `GET /source/{id}/context` (query params incl. `query_actor_ref` — does NOT copy the `/memory/{id}/expand` omission); 404 on missing/forgotten/cross-container anchor; items chronological with the anchor flagged.
- `app/mcp/client.py` + `server.py`: `get_source_context` client method + `pallium_expand_source` tool (scope/actor from ctx).
- `integrations/claude-code/claude_md_block.py` + `integrations/codex/AGENTS.md`: reach-for + required-params entries for `pallium_expand_source`.
- `tests/test_source_context.py`: 10 tests — bounded window + anchor flag + chronological, before=after=0 anchor-only, size-cap keeps anchor/drops farthest, forgotten neighbor omitted, forgotten anchor 404, cross-container anchor gate 404, unknown anchor 404, parent_lookup_id echo, supported memories opt-in+separate, supported-memory visibility filtering (public kept / other-container private dropped).

Verification: `pytest tests/test_source_context.py` → 10 passed. Full `pytest tests/` → 3408 passed, 1 pre-existing failure (`test_config.py::test_prompt_variants_legacy_fallback_unaffected`, fails on main, unrelated), 15 skipped, 2 xfailed.

Open item flagged for sign-off: `parent_lookup_id` is echoed, not persisted — persistence belongs to the deferred exposed-source-ids audit (the telemetry item), not `query_audit_log` (expansions are not lookups).

(previously: in progress — overnight P1 run)
