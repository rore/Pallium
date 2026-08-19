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
  value unchanged (`path:…`, `repo:<hash>`, other hosts). Pure, None-safe, idempotent.
- Call it as the FIRST body statement of EVERY `core/service.py` method that accepts `container_ref`
  (reassign the local so all downstream uses see the canonical value). Enumerated (11): `ingest_item`
  (:274), `query` (:667), `run_consolidation_pass` (:760), `record_memory_feedback` (:839),
  `remember_memory` (:946), `supersede_memory` (:1021), `forget_source` (:1083),
  `record_procedure_outcome` (:1138), `write_query_audit` (:1199), `get_memory_expand` (:1408),
  `get_source_context` (:1467). Applying to all is safe because the helper is a github-only pass-through.
- `app/mcp/context.py`: replace the private `_canonicalize_container_ref` body with a call to the shared
  helper (keep the name as a thin alias so existing imports/tests don't break).
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
- Telemetry writers (`record_memory_feedback`, `write_query_audit`) persist query-CONTEXT container, not a
  home scope; normalize them too so audit/feedback joins stay consistent with canonical containers (the
  helper is harmless on non-github values).

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
- *CORRECTED (plan review): `ingest_item` is NOT the sole container-bearing write.* The explicit W3
  memory writes — `remember_memory` (:946→create_memory_object), `supersede_memory` (:1021),
  `record_procedure_outcome` (:1138) — set `container_ref` on a `MemoryObject` directly and bypass
  `ingest_item`. This is almost certainly how the 4 rows were stranded (pre-#43 `pallium_remember`).
  Resolution: normalize all 11 container-accepting methods, not 4.
- *Reassign-at-top is safe (no earlier pre-canonical capture).* Verified by plan review for the read/write
  methods: the only downstream uses (retrieval filters, funnel/expansion event dicts, gates) read the same
  local, no separate copy captured before the reassignment.
- *Re-pointing `memory_objects.container_ref` alone is sufficient.* Relations/index_entries key on the
  object id, not container; sibling container-bearing rows (audit/feedback/funnel) record query-context,
  not home scope, so must NOT be re-pointed. Confirmed by plan review.

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

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Clean-context Explore reviewer (2026-08-19). Verdict: **needs changes** — mechanism sound (helper +
reassign-at-top + github-only regex + 4-row merge all verified safe), but the method list under-scoped.
Applied:

- **Missed writes**: `remember_memory` (:946), `supersede_memory` (:1021), `record_procedure_outcome`
  (:1138) build `MemoryObject(container_ref=…)` and call `create_memory_object` directly — bypass
  `ingest_item`. This is the exact split path (likely origin of the 4 stranded rows). → now normalized.
- **Missed reads/scope**: `get_memory_expand` (:1408, cross-container gate) and `run_consolidation_pass`
  (:760) → now normalized.
- **Telemetry** `record_memory_feedback` (:839) + `write_query_audit` (:1199): normalize too (join
  consistency; helper harmless on non-github). Decision recorded in Constraints.
- **Reassign-at-top safe** for all: no method captures a pre-canonical copy before the reassignment
  (funnel/expansion event dicts and filters read the same local).
- **Regex safe to copy verbatim**; `path:`/`repo:`/non-github pass through (asserted by
  `tests/test_mcp_context.py:96-106`). Aliasing the private name keeps those tests green.
- **Merge**: relations/index_entries key on object id (not container); only `memory_objects.container_ref`
  needs re-pointing. Verify no feedback row exists for the 4 ids (unlikely, pre-#43).

## Implementation

- **Helper** `core/container_ref.py`: `canonicalize_container_ref` — github-only, None-safe, idempotent
  (the exact rule extracted from `app/mcp/context.py`).
- **Service** `core/service.py`: normalize `container_ref` as the first body statement of all 11
  container-accepting methods (`ingest_item`, `query`, `run_consolidation_pass`, `record_memory_feedback`,
  `remember_memory`, `supersede_memory`, `forget_source`, `record_procedure_outcome`, `write_query_audit`,
  `get_memory_expand`, `get_source_context`). Reassign-at-top → all downstream uses (filters, funnel/
  expansion event writes, gates, MemoryObject construction) see the canonical value.
- **MCP** `app/mcp/context.py`: `_canonicalize_container_ref` is now a thin alias of the shared helper
  (imports removed the private regex copy); existing name kept for `tests/test_mcp_context.py`.
- **Data merge** `scripts/backfill_container_ref_canonical.py`: dry-run-by-default, idempotent, github-only.
  Re-points only `memory_objects.container_ref`. Ran against the live DB: 4 rows
  `git:github.com/rore/Pallium` → `.../pallium`; post-merge capital-P memory count = 0.

## Evidence

`pytest tests/ -q` → **3623 passed, 15 skipped, 2 xfailed, 1 failed** (pre-existing `test_config`
env-leak, unrelated). New: `tests/test_container_ref.py` (github lowercased; path/repo/gitlab/non-2-seg
pass through; idempotent; None-safe) + a service round-trip E2E (write under capital, read under
lowercase → hit; funnel event records canonical). Live-DB merge verified read-only: 0 capital-`P`
memory objects remain.
