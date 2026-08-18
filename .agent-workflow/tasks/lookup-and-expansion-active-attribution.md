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
`storage/sqlite_schema.py` (one new nullable column + migration), `storage/sqlite.py` if the write needs
it, the expansion service signature + its MCP caller so the requesting session reaches the write, and the
reuse-KPI reconstruction (`evals/historical_lookup_measurement.py`) to exclude/​count unattributed rows.

**Scope:**
- Add nullable column `source_session_ref` to `historical_lookup_reuse_event` (SQLAlchemy model +
  `_HISTORICAL_LOOKUP_*_MIGRATIONS` ALTER, nullable/no-backfill like every prior column add).
- Lookup write: keep `session_id` = active requesting session (already the `thread_ref` param);
  `source_session_ref` stays NULL (a lookup exposes many sources, no single source session).
- Expansion write: `session_id` = requesting session (from the expansion call's active identity, resolved
  from its persisted parent lookup when the call omits it), `actor_ref` = requesting actor,
  `source_session_ref` = `anchor.thread_ref`. Stop attributing to the anchor.
- Expansion resolves/validates `parent_lookup_id` against the persisted lookup event for chain integrity
  (nonexistent → treat as no-parent; NOT an authz gate).
- Missing-identity contract: session_id NULL ⇒ `unattributed`. Reuse-KPI reconstruction excludes NULL
  `session_id` events from the eligible/reuse counts and reports them in a data-quality count.
- Thread the requesting session into the expansion path from the MCP layer (`app/mcp`) as it already
  threads `container_ref`/`actor_ref`.

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
5. Best-effort preserved: a forced write/parent-resolution exception logs and still returns results.
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
- *The `_*_MIGRATIONS` apply loop iterates every declared per-table dict.* Disproved if the loop is
  hard-coded per table → register the event table's dict in the loop. Action: pin during Implement.
- *Requiring the requesting session on expansion via a new optional param (default resolves from parent
  lookup) needs no MCP protocol/tool-signature break.* Disproved if the expansion tool can't access the
  active session → source it from `resolve_context`/env like the lookup path.

**Plan:**
1. Schema: add `source_session_ref = Column(String, nullable=True)` to the event model + a migration ALTER
   entry; confirm it's applied on an existing DB.
2. Lookup call site: no field change; confirm NULL `session_id` flows through (missing-identity path).
3. Expansion: add `active_session_ref: str | None = None` to `get_source_context`; the write sets
   `session_id = active_session_ref or (parent lookup's session_id) or None`,
   `actor_ref = query_actor_ref or (parent lookup's actor_ref)`, `source_session_ref = anchor.thread_ref`.
   Resolve parent by `parent_lookup_id` (best-effort read; failure ⇒ no inherited identity, never raises).
4. MCP expansion tool passes the resolved active session (from `resolve_context`) into the new param.
5. KPI reconstruction (`evals/historical_lookup_measurement.py`): exclude events with NULL `session_id`
   from eligible/reuse; add a `unattributed`/data-quality count in the returned summary.
6. Tests covering completion criteria 1-6.
Stop condition: if the expansion tool cannot reach the active session without a protocol change, pause and
record it (assumption 3) rather than widening scope silently.

**Verification plan:**
- Criteria 1-3 → new tests in the historical-lookup service/measurement test module asserting event
  field attribution (active vs source session, cross-agent).
- Criterion 4 → test that NULL-session events are excluded from the KPI and appear in the data-quality
  count.
- Criterion 5 → monkeypatch the write / parent-read to raise; assert results still returned + warning.
- Criterion 6 → full `pytest tests/ -q` (expect only the known pre-existing `test_config` env-leak
  failure); a migration test opening a pre-column DB and asserting the ALTER applied.
- redline + agent-workflow CI predicates.

**Plan review:**
Clean-context agent review required (red path). Reference recorded under `## Plan review` below.

**Approvals:**
Approved by user 2026-08-18: "yes, go" — approving the design "persist the missing fields (query text +
attribution ...) on the funnel event at write time in core/service.py". Scope REDUCED post-discovery:
query_text deferred to `fix-continuous-eval-lookup-population` (privacy decision on the unconditional
event); this PR persists attribution only. Reduction is conservative; no scope added beyond the approval.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

(pending — plan review first)
