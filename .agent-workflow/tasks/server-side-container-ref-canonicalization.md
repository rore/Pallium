# server-side-container-ref-canonicalization

Container-ref casing (`git:github.com/rore/Pallium` vs `.../pallium`) was split before #43 added
`_canonicalize_container_ref` at the MCP boundary (`app/mcp/context.py`). But that fix lives in the MCP
server (a client of the core HTTP API) + the two integration hooks — the **core server never normalizes**,
so any direct API/dashboard/in-process caller can still write or query a non-canonical container and
silently split memory. This moves canonicalization to the core service boundary (one authoritative,
per-type helper) so every caller is covered, and merges the 4 memory objects stranded under the old
capital-`P` container.

Investigation (read-only, live DB `~/.pallium/data/pallium.db`): 2238 source_items all lowercase; 3970
memory_objects lowercase vs **4 under `git:github.com/rore/Pallium`** (created 2026-08-16..17, all before
#43); every capital-`P` lookup event predates #43. So the write path is already closed for current
clients; this is robustness (one chokepoint) + a 4-row cleanup.

<!-- agent-workflow:start -->
**Outcome:**
`container_ref` is canonicalized (github-only, per-type) at the core service boundary, so write scope
(`ingest_item`) and read scope (`query`, `get_source_context`, `forget_source`) always agree regardless of
caller — HTTP API, dashboard, MCP, or in-process (CLI/simulation). The MCP context reuses the same shared
helper instead of its private copy. The 4 memory objects under the legacy capital-`P` container are
re-pointed to the canonical lowercase container.

**Target:**
New `core/container_ref.py` (pure `canonicalize_container_ref`), `core/service.py` (normalize at the 4
container-accepting entry methods), `app/mcp/context.py` (import the shared helper, drop the private copy),
plus a one-off data-merge script for the 4 stranded rows (run against the live DB with the service
stopped or via a safe UPDATE).

**Scope:**
- Add `canonicalize_container_ref(value)` — GITHUB-ONLY: lowercases owner/repo of
  `git:github.com/owner/repo` (the exact rule now in `app/mcp/context.py:28-35`); returns every other
  value unchanged (`path:…`, `repo:<hash>`, other hosts). Pure, None-safe.
- Call it at the top of `ingest_item`, `query`, `get_source_context`, `forget_source` — reassign the
  local `container_ref` so all downstream uses (retrieval filters, funnel event writes, storage) see the
  canonical value.
- `app/mcp/context.py`: replace the private `_canonicalize_container_ref` body with a call to the shared
  helper (keep the name as a thin re-export so existing imports/tests don't break).
- One-off migration: re-point the 4 `git:github.com/rore/Pallium` memory objects to
  `git:github.com/rore/pallium`. Show the rows first; UPDATE by id.

**Constraints:**
- PER-TYPE: only `git:github.com/owner/repo` is lowercased. NEVER blanket-lowercase — `path:` and
  non-GitHub hosts can be case-sensitive; `repo:<hash>` is already stable.
- Behavior-preserving for already-canonical inputs (idempotent); no retrieval/injection logic change
  beyond scope normalization.
- The integration hooks keep their source-side lowercasing (separate process, can't import `core`); this
  is additive server-side defense, not a hook change.
- Do NOT change visibility/`is_visible` semantics; canonicalization happens before scoping.
- Live-DB merge is a targeted 4-row UPDATE by id — no bulk/destructive operation; rows shown before write.

**Completion criteria:**
1. A write under `git:github.com/rore/Pallium` and a read under `git:github.com/rore/pallium` resolve to
   the same container at the service layer (round-trip test).
2. Per-type: `path:Foo/Bar:hash`, `repo:ABC`, and a non-GitHub git ref pass through UNCHANGED.
3. The funnel lookup event written by `query` records the canonical container for a mixed-case input.
4. `app/mcp/context.py` uses the shared helper (no divergent second copy); existing MCP context tests pass.
5. The 4 stranded memory objects are merged to lowercase; post-merge there are 0 `Pallium` (capital)
   memory objects and the lowercase count increases by 4.
6. Full suite green (known `test_config` env-leak only).

**Risk:** High

**Complexity:** Moderate

**Reason:** Edits the guarded red path (`core/service.py`) at four entry points + a live-DB data merge.
Localized and behavior-preserving (a per-type normalization + a shared helper), so Moderate not Large.

**Discovery:**
- Service container-accepting entries: `ingest_item` (`core/service.py:261`), `query` (`:659`),
  `forget_source` (`:1079`), `get_source_context` (`:1463`). Memory objects inherit container from the
  source item during processing, so normalizing `ingest_item` covers derived memory.
- `api/routes.py` does NO container_ref normalization (grep). MCP (`app/mcp`) is a separate process that
  wraps the HTTP API; its `resolve_context` canonicalizes before calling core — so the core itself never
  does. In-process callers (`agent_simulation`, CLI) bypass MCP entirely → the service layer is the only
  chokepoint that covers them.
- Current per-type rule is correct and github-only (`app/mcp/context.py:28-35`); reuse verbatim.
- Live DB: 4 memory_objects under capital-`P`; 0 source_items; all pre-#43.

**Material assumptions:**
- *`ingest_item` is the sole write path that sets a source/memory container_ref.* If a separate
  create-memory service method takes container_ref directly, normalize it too. Action: grep before
  finalizing (explicit `remember` appears to route through ingest as a note).
- *The 4 capital-`P` memory objects have no relations/index rows keyed on the capital container that also
  need re-pointing.* Verify the merge doesn't orphan index entries (index entries key on target_id, not
  container, so re-pointing the memory row's container_ref is sufficient). Action: confirm in the script.

**Plan:**
1. `core/container_ref.py`: `canonicalize_container_ref(value)` — copy the github-only regex from
   `context.py`; None-safe; idempotent.
2. `core/service.py`: at the top of the 4 methods, `container_ref = canonicalize_container_ref(container_ref)`.
3. `app/mcp/context.py`: `from core.container_ref import canonicalize_container_ref`; keep
   `_canonicalize_container_ref = canonicalize_container_ref` (thin alias) so nothing else breaks.
4. Tests (below).
5. Data merge: a read-only preview of the 4 rows, then `UPDATE memory_objects SET container_ref=... WHERE
   id IN (...)`; re-verify counts. Run with care against the live DB.
Stop condition: if a container-bearing write path outside these 4 methods exists, pause and widen scope.

**Verification plan:**
- Criteria 1-3 → unit tests on the helper (per-type pass-through, idempotency) + a service round-trip test
  (write capital, read lowercase → same scope; funnel event canonical).
- Criterion 4 → assert `app/mcp/context.py` resolve_context canonicalizes via the shared helper; existing
  `tests/test_mcp_context.py` still green.
- Criterion 5 → the merge script prints before/after counts; a test simulating a stranded capital-`P`
  memory + running the same UPDATE logic asserts it moves.
- Criterion 6 → full `pytest tests/ -q`.
- redline + agent-workflow CI.

**Plan review:**
Clean-context agent review required (red path). Reference under `## Plan review` below.

**Approvals:**
Approved by user 2026-08-19: "go" — approving placement A (canonicalize at the core service boundary via a
shared per-type helper) and merging the 4 stranded memories, per the alignment agreed in the preceding
turns.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Plan review

(pending)

## Implementation

(pending)
