# lookup-and-expansion-active-attribution

Historical-lookup reuse telemetry can't be attributed to the *requesting* session/agent. The lookup
event copies `session_id`/`actor_ref` from optional MCP params that the default install never supplies
(→ NULL). The expansion event is worse: it copies the **historical anchor's** `thread_ref`/`actor_ref`
(`core/service.py:1611,1613`), so a lookup done in session B is recorded as activity in old session A.
Both break per-session, cross-session, and cross-agent reuse analysis even when retrieval is correct.

This is external-review register items 2 + 3 (High). Telemetry contract only — NOT authorization
(Pallium is trusted-local; no actor-auth machinery — that path was reverted in #42).

<!-- agent-workflow:start -->
**Outcome:**
Every lookup/expansion reuse event records the identity of the session/agent that **made the request**,
never the retrieved source's. An expansion carries the requesting session as active identity, the
anchor's session as `source_session_ref`, and links to its parent lookup. When the caller supplies no
session identity the event is written `unattributed` (session_id NULL) and is excluded from the reuse
KPI while counted in a data-quality tally — never a silent NULL that inflates or deflates the KPI.

**Target:**
`core/service.py` (the two `write_historical_lookup_event_row` call sites — lookup + expansion),
`storage/sqlite_schema.py` (new nullable column + a new `_ensure_historical_lookup_columns()` method
registered in the schema orchestrator at ~`:854` — column migrations are NOT auto-applied from a declared
dict), the expansion request path so the requesting session reaches the write:
`api/routes.py` (GET `/source/{id}/context` route), `app/mcp/client.py` (`get_source_context` client),
`app/mcp/server.py` (`pallium_expand_source` tool — optional `thread_ref`), and the reuse-KPI
reconstruction (`evals/historical_lookup_measurement.py`) to add an unattributed data-quality count.

**Scope:**
- Add nullable column `source_session_ref` to `historical_lookup_reuse_event` (SQLAlchemy model +
  `_HISTORICAL_LOOKUP_*_MIGRATIONS` ALTER, nullable/no-backfill like every prior column add).
- Lookup write: keep `session_id` = active requesting session (already the `thread_ref` param);
  `source_session_ref` stays NULL (a lookup exposes many sources, no single source session).
- Expansion write: `session_id` = requesting session (**explicit active identity only — NEVER inherited
  from the parent lookup or anchor**; parent is linkage only), `actor_ref` = requesting actor,
  `source_session_ref` = `anchor.thread_ref`. Stop attributing to the anchor.
- Expansion resolves `parent_lookup_id` for chain LINKAGE only (existence check at most; on any
  actor/container mismatch, do NOT deny — attribute to the requester and keep the link. Denying on
  parent-actor/container mismatch = the #42 pseudo-auth trap; out of scope).
- Missing-identity contract: session_id NULL ⇒ `unattributed`. Reuse-KPI numerator already excludes NULL
  session_id implicitly (eligible-session set never contains NULL); this PR ADDS a visible data-quality
  count of NULL-session lookup events so a zero KPI is never silently a data gap.
- Thread the requesting session into the expansion path end-to-end: MCP tool (`thread_ref`) → client →
  route → service `active_session_ref`, mirroring how the lookup path already threads `thread_ref`.

**Constraints:**
- Telemetry only — NO authorization, NO actor-authentication, NO cross-actor/​cross-container deny gates
  (reverted as pseudo-auth in #42). Identity fields are for measurement attribution.
- Event writes stay best-effort: a telemetry/parent-resolution failure must NEVER fail the query or the
  expansion (the existing `try/except … warning` contract).
- `exposed_json` post-redaction/post-gate invariant unchanged; no new content persisted on the event.
- NO `query_text` on the event in this PR — persisting raw query text on the unconditional event is a
  privacy decision owned by `fix-continuous-eval-lookup-population` (why `query_audit_log` defaults off).
- No new `agent_ref` column: `actor_ref` is Pallium's self-asserted agent/actor identity; do not invent a
  parallel field.
- Migration is additive + nullable; existing rows and the fresh-DB `create_all` path stay valid.

**Completion criteria:**
1. Source ingested in session A, `source_only` search from session B → lookup event `session_id=B`,
   `source_session_ref` NULL, correct actor/container.
2. Lookup→expansion chain (both from session B, parent linked): expansion event `session_id=B`,
   `source_session_ref=A` (anchor's session), `parent_lookup_id` = the lookup, `actor_ref`=B's actor. No
   field labels A as the active/requesting session.
3. Cross-agent: agent B expanding agent A's material yields an event attributed to B, not self-reuse by A.
4. Missing-identity: a call with no session identity writes `session_id` NULL; the reuse-KPI
   reconstruction excludes it from eligible/reuse and counts it in a data-quality tally (no silent NULL).
5. Best-effort preserved: a forced telemetry write exception logs and still returns results.
6. Existing historical-lookup + measurement tests still pass; migration applies on a pre-column DB.

**Risk:** High

**Complexity:** Moderate

**Reason:** Edits a guarded red path (`core/service.py`) and adds a schema column on the always-on
telemetry event — measurement-integrity change warranting clean-context plan review + recorded approval.
Localized (two write sites + one signature + one migration + KPI exclusion), so Moderate not Large.

**Discovery:**
- Lookup write `core/service.py:710-745`: `session_id=thread_ref`, `actor_ref=actor_ref` — active
  identity IS wired via params; it lands NULL only because `app/cli/setup_codex.py` never injects
  `PALLIUM_THREAD_REF`/`PALLIUM_ACTOR_REF` and `app/mcp/context.py:51-52` falls back to those env vars.
  So the lookup fix is the missing-identity contract, not a new param.
- Expansion write `core/service.py:1599-1618`: `session_id=anchor.thread_ref`,
  `effective_actor_ref = query_actor_ref or anchor.actor_ref` — the real bug: requester identity is lost,
  anchor identity substituted. `get_source_context` signature (`:1456-1468`) has no active-session param.
- Schema `storage/sqlite_schema.py:333-350`: columns present are session_id/container_ref/actor_ref/
  trigger_origin/parent_lookup_id/exposed_json/visibility. No source_session_ref, no agent_ref, no
  query_text. Write is generic `HistoricalLookupReuseEventRecord(**row)` (`storage/sqlite.py:1319-1327`).
- Migration mechanism = per-table `_*_MIGRATIONS` dict of `ALTER TABLE … ADD COLUMN` (nullable/no
  backfill), e.g. `_SOURCE_ITEM_MIGRATIONS` (`sqlite_schema.py:503`). Need the event table's dict (or add
  one) + confirm the apply loop covers it.
- MCP layer threads container_ref/actor_ref via `resolve_context` (`app/mcp/context.py:37-54`); the
  expansion tool must pass the same active session through to the new service param.

**Material assumptions:**
- *actor_ref is the agent identity (no separate agent_ref needed for the event).* Disproved if the event
  or KPI must distinguish agent from actor with a dedicated field → add `agent_ref` column + thread it.
  Action: re-open scope, bump toward Large.
- *A new per-table `_*_MIGRATIONS` dict is auto-applied.* **DISPROVED by plan review** — schema evolution
  is a hard-coded sequence of named `_ensure_*` calls (`sqlite_schema.py:836-855`); the event table only
  gets `_ensure_historical_lookup_indexes()` (index-only). Resolution: add
  `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` + `_ensure_historical_lookup_columns()` (PRAGMA table_info +
  ALTER, mirroring `_ensure_query_audit_log_columns:1051`) AND register the call at ~`:854`.
- *Requesting session reaches expansion without a protocol break.* CONFIRMED — additive optional
  `thread_ref` tool param + `active_session_ref` through client/route/service; env fallback
  (`PALLIUM_THREAD_REF`) already populates `ctx.thread_ref`.

**Plan:**
1. Schema: add `source_session_ref = Column(String, nullable=True)` to the event model; add
   `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS = {"source_session_ref": "ALTER TABLE historical_lookup_reuse_event
   ADD COLUMN source_session_ref VARCHAR"}` + `_ensure_historical_lookup_columns()` + register it in the
   orchestrator (~`:854`). Confirm it applies on an existing pre-column DB.
2. Lookup call site: no field change; NULL `session_id` flows through (missing-identity path).
3. Expansion: add `active_session_ref: str | None = None` to `get_source_context`; the write sets
   `session_id = active_session_ref or None` (**no parent/anchor fallback**),
   `actor_ref = query_actor_ref or None`, `source_session_ref = anchor.thread_ref`,
   `parent_lookup_id` = the incoming id (linkage only, best-effort, never raises).
4. Thread `thread_ref`/`active_session_ref` end-to-end: `app/mcp/server.py` tool (optional `thread_ref`,
   default `ctx.thread_ref`) → `app/mcp/client.py` `get_source_context` → `api/routes.py` GET route →
   service param.
5. KPI reconstruction (`evals/historical_lookup_measurement.py`): NUMERATOR exclusion of NULL session is
   already implicit (eligible set skips NULL; loader is lookup-only, `event_type='lookup'`). ADD a
   NULL-session lookup data-quality counter in `_load_reuse_events` (~`:453`), thread it through
   `load_events_from_storage` return (~`:471`,`:522`) into the `compute_reuse_rollup` output dict (~`:232`).
   Expansion attribution does NOT feed the reuse numerator — its fix is event-record correctness for
   cross-agent/visibility analysis, so criterion 4's data-quality count is scoped to lookups.
6. Tests covering completion criteria 1-6.
Stop condition: if threading the session needs a protocol/tool-signature break, pause and record it.

**Verification plan:**
- Criteria 1-3 → new tests asserting event field attribution (active vs source session, cross-agent);
  expansion `session_id` = requester even when parent belongs to another session (the plan-review C case).
- Criterion 4 → test that NULL-session lookup events appear in the data-quality count and don't inflate
  the KPI.
- Criterion 5 → monkeypatch the event write to raise; assert results still returned + warning. (The
  expansion stores `parent_lookup_id` as linkage only and performs no parent read, so there is no
  parent-resolution failure path to test.)
- Criterion 6 → full `pytest tests/ -q` (expect only the known pre-existing `test_config` env-leak
  failure); a migration test opening a pre-column DB and asserting the ALTER applied via the orchestrator.
- Concurrency → the two-thread test above. redline + agent-workflow CI predicates.

**Plan review:**
Clean-context Explore agent, 2026-08-18 — verdict "needs changes", all applied (migration orchestrator
registration, expansion precedence no-parent-fallback, added client/route targets, KPI data-quality-count
only + lookup-only scope, explicit DoD dispositions). See `## Plan review` below.

**Approvals:**
Approved by user 2026-08-18: "yes, go" — approving the design "persist the missing fields (query text +
attribution ...) on the funnel event at write time in core/service.py". Scope REDUCED post-discovery:
query_text deferred to `fix-continuous-eval-lookup-population` (privacy decision on the unconditional
event); this PR persists attribution only. Reduction is conservative; no scope added beyond the approval.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## DoD dispositions

From the full ticket matrix, how each item was handled:

- **Expansion idempotency (item 5):** moot for the KPI — expansions aren't in the reuse numerator and
  lookup reuse dedups by session (set). A retried expansion just writes another well-formed event; no
  double-count possible. No dedup machinery added.
- **Concurrency (item 3):** the write path uses only per-call locals + a fresh `anchor` read — no
  server-global mutable state. Covered by a two-thread test asserting distinct events with the correct
  active session; no new locking.
- **Invalid-chaining foreign-actor / foreign-container / "expired" parent "rejected" (ticket wording):**
  DECLINED as authorization — parent handling is existence/linkage only; a mismatch attributes to the
  requester, never denies (#42 boundary). Recorded, not silently dropped.

## Plan review

Clean-context Explore reviewer (2026-08-18). Verdict: **needs changes**. Findings applied to the plan:

- **A (migration):** column migrations are NOT auto-applied. Orchestrator `sqlite_schema.py:836-855`
  calls named `_ensure_*` methods; the event table only has `_ensure_historical_lookup_indexes()`
  (index-only). Must add a column-migration method + register it at ~`:854`, else the ALTER silently
  never runs on an existing DB (criterion 6). → Plan step 1 updated.
- **B (threading):** session reachable, no protocol break, but the param crosses `app/mcp/client.py`
  (`:138-170`) and `api/routes.py` (`:672-695`) too — both were missing from Target. → Target + step 4.
- **C (precedence — the real bug):** `active_session_ref or parent.session_id` recreates the
  mis-attribution (session B expanding A's lookup would record A). Correct: explicit active identity only,
  NEVER inherit active session/actor from parent; parent is linkage. → Constraints + step 3 fixed.
- **D (KPI):** numerator exclusion of NULL session already implicit (`:455` membership filter,
  eligible set skips NULL `:347`); loader is lookup-only (`event_type='lookup'` `:434`), so expansion
  attribution doesn't touch the reuse KPI. New work = a data-quality COUNT only. → step 5 corrected.
- **E (dropped DoD):** idempotency moot, concurrency needs one cheap test, foreign-parent "rejected"
  declined as authz — all now recorded under DoD dispositions rather than dropped silently.
- **F (pseudo-auth):** the ticket's "reject expansion attached to another actor/container's lookup"
  wording is the #42 trap; kept parent handling existence/linkage-only, never deny. → Constraints.

## Implementation

- **Schema** (`storage/sqlite_schema.py`): added `source_session_ref` (nullable) to the event model +
  `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` + `_ensure_historical_lookup_columns()`, registered in
  `_initialize_schema` right after the index-ensure (the orchestrator is a hard-coded call list — a
  declared dict alone is not applied, per plan review A).
- **Expansion write** (`core/service.py`): `session_id = active_session_ref` (new param, requester only —
  NO parent/anchor fallback), `actor_ref = query_actor_ref`, `source_session_ref = anchor.thread_ref`.
  `effective_actor_ref` still drives the visibility gates (unchanged); only the EVENT attribution changed.
- **Lookup write**: unchanged attribution (session_id already = active `thread_ref`); added explicit
  `source_session_ref: None`.
- **Threading**: `pallium_expand_source` tool gained optional `thread_ref` → `resolve_context` →
  `PalliumMcpClient.get_source_context` sends `active_session_ref` from `ctx.thread_ref` → route
  `/source/{id}/context` forwards `active_session_ref` to the service. All additive/optional — no break.
- **KPI** (`evals/historical_lookup_measurement.py`): NULL-session numerator exclusion was already
  implicit; added `count_unattributed_lookups()` + `compute_reuse_rollup(unattributed_lookups=…)` →
  `data_quality.unattributed_lookup_events` in the report; runner computes + passes it. Did NOT change
  `load_events_from_storage`'s 2-tuple return (unpacked in ~20 call sites).
- **DoD dispositions honored**: concurrency covered by a real two-thread service test; expansion
  idempotency is moot for the KPI (lookup-only numerator, session-deduped) — asserted well-formed retry;
  foreign-parent "rejection" declined as #42 pseudo-auth (parent = linkage only, never a deny gate).

## Evidence

`pytest tests/ -q` → **3614 passed, 15 skipped, 2 xfailed, 1 failed**. The single failure is the
pre-existing env-leak `test_config.py::test_prompt_variants_legacy_fallback_unaffected` (global
config/env order dependence; touches none of this change's files). Affected slices
(`test_historical_lookup_funnel_e2e`, `_storage`, `_measurement`, `test_lookup_event_id_e2e`,
`test_mcp_server`) → 84 passed, 1 skipped. New tests: requester-vs-anchor attribution,
unattributed-not-anchor, best-effort write failure, two-thread concurrency, pre-column-DB migration,
unattributed count + KPI exclusion.
