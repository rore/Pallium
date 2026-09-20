# Exact work-reference index

<!-- agent-workflow:start -->
**Outcome:** Exact work-reference history searches use an indexed candidate lookup and no longer scan all vector entries or source items.

**Target:** Pallium.

**Scope:** SQLite source-item work-reference association schema, source create/update/delete and offline secret-purge synchronization, exact lexical/structural/vector reads, and focused/E2E tests.

**Constraints:** Preserve public APIs, normalization/Unicode/legacy semantics, visibility and lifecycle revalidation, result ordering, and non-work-reference search behavior. No new dependency or cache.

**Completion criteria:** Exact work-reference reads use the new work-reference index; existing databases are backfilled; source create/update/delete keep associations consistent; focused edge-case and HTTP E2E tests pass; the live incident query returns the same five results within the 30-second MCP deadline and materially faster than the current 3–5 seconds.

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline classifies the intended diff as SCHEMA_CHANGE with persistence-review required. This is a combined additive schema, data backfill, and index change spanning persistence writes and two read paths.

**Discovery:** Live profiling attributes about 87% of the 3–5 second request to get_source_item_vector_candidates scanning about 21,000 vector rows and invoking JSON normalization per row to return six candidates. A live read-only benchmark showed forced source-first remains O(12,401 sources) at about 100 ms fresh, while an indexed normalized association returns the same six candidate rows in 7–159 microseconds. SQLite cannot index normalized elements of a JSON array or reproduce Python Unicode casefold with built-ins. Existing create paths are in storage/sqlite.py; metadata mutation has two independent paths in storage/sqlite_queue.py (failure metadata_updates and the generic patch helper); retention deletion is in storage/sqlite_retention.py. Result review found the official offline app/tools/secrets_purge.py apply/undo paths also rewrite authoritative metadata directly and must synchronize the derived association atomically.

**Material assumptions:** The association is a derived index, so rebuilding it from source_items.metadata_json is lossless. This is disproved if any required work-reference state exists only outside source metadata; if found, stop and return to planning. Startup backfill cost is acceptable only if measured on the current 12,401-row live corpus and remains bounded; otherwise stop and redesign migration batching.

**Plan:** Add one source_item_work_refs table with composite source/ref identity and a work_ref-leading lookup index in storage/sqlite_schema.py. Under the startup schema lock and before provider exposure, replace its contents transactionally from source_items metadata projected through core.work_ref.work_refs_from_metadata, preserving list-only, secret-filtering, MAX_WORK_REFS, Unicode normalization, and canonical dedup semantics. Add one shared association-sync helper and invoke it from both source create paths, both independent metadata mutation paths (including fail_source_item_processing metadata_updates), and retention deletion. Make offline secret purge/undo recompute affected associations in the same SQLite transaction when the derived table exists. Replace JSON/UDF predicates in storage/sqlite.py and storage/sqlite_search.py with deduplicated indexed association lookups: blank structural search starts from the work-ref index; lexical FTS uses indexed EXISTS membership; vector search starts association -> source PK -> idx_index_entries_target_lookup. Preserve projection fields and blank/BM25/vector ordering, visibility, filters, and final revalidation. Capture the actual production SQL at runtime and EXPLAIN those exact statements for all three shapes; add a true upgrade journey that drops the association table, seeds raw legacy Unicode/separator/malformed/secret metadata, reopens SQLiteStorageProvider, and asserts indexed search. Add lifecycle tests through both metadata mutation surfaces, purge/undo, retention, and multi-ref dedup/order. Stop if parity changes, implemented startup rebuild is materially slow on the copied live DB, or a forbidden storage dependency appears. Key conventions: reuse core.work_ref.work_refs_from_metadata and existing SQLite session/transaction/index-migration patterns; keep the table a derived storage detail. Target files: storage/sqlite_schema.py, storage/sqlite.py, storage/sqlite_search.py, storage/sqlite_queue.py, storage/sqlite_retention.py, app/tools/secrets_purge.py, tests/test_exact_work_ref_search.py, tests/test_secrets_purge.py, tests/test_vector_retrieval.py, and focused storage tests only if needed.

**Verification plan:** When blank structural, lexical, and vector exact search run, tests shall capture their actual executed production SQL and EXPLAIN those exact statements, proving idx_source_item_work_refs_lookup/composite PK/idx_index_entries_target_lookup usage and excluding full source/vector scans -> runtime capture regressions plus live benchmark. When a legacy DB without the association table opens, invalid/scalar/object/secret metadata is excluded and normalized Unicode/separator variants are searchable -> provider reopen migration test. When metadata changes through either public mutation path, offline purge/undo, or source deletion, associations shall be recomputed atomically -> lifecycle tests. When exact blank, lexical, and vector HTTP searches run, results/order/visibility shall match current behavior -> focused E2E tests. The implemented provider startup on a copied live DB shall measure the full locked delete/repopulate/index maintenance cost. The final coherent change shall pass affected subsystem tests, agent-workflow/redline checks, full pytest, smart independent review, CI, and live service verification.

**Plan review:** Clean-context gpt-5.6-sol high re-review approved the expanded purge/undo synchronization and production-SQL/migration test plan; see Plan review below.

**Approvals:** Approved by user 2026-09-21: "i approve, no need to ask every time" — standing authorization applied to the reviewed material scope expansion.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification completed.
- Added the derived `source_item_work_refs` table and `(work_ref, source_item_id)` index; startup performs a locked transactional full replacement from `core.work_ref.work_refs_from_metadata`; source creates, both metadata mutation paths, and retention deletion use one shared sync helper; structural, lexical, and vector exact reads use indexed association membership with deduplication.
- Smart-review follow-ups: planner regressions now EXPLAIN statements captured from production calls; added a true pre-index upgrade/backfill test; `secrets_purge` atomically recomputes only affected associations on apply/undo and skips cleanly when the table is absent.

## Evidence

- Files changed: `storage/sqlite_schema.py`, `storage/sqlite.py`, `storage/sqlite_search.py`, `storage/sqlite_queue.py`, `storage/sqlite_retention.py`, `app/tools/secrets_purge.py`, `tests/test_exact_work_ref_search.py`, and `tests/test_secrets_purge.py`.
- Focused verification: final exact/vector/secrets-purge/snapshot run — 114 passed; independent smart-review rerun — 30 passed; `git diff --check` clean.
- Full verification: `5044 passed, 34 skipped, 2 xfailed in 194.87s`.
- Windows fallback: `apply_patch` failed with CreateProcessWithLogonW error 1327; edits used the narrowly scoped deterministic fallback required by AGENTS.md.
- Live py-spy profile: 87% of request wall time in the candidate SQL execute/fetch path.
- Read-only live corpus benchmark: current query 255–300 ms fresh; source-first 87–116 ms; indexed association 7–159 microseconds after a 134 ms build over 11,614 associations.

## Checkpoint: persistence-review

What is changing: Add and backfill a normalized source-item work-reference association and route exact reads through its index.
Why: JSON-array membership plus Python normalization forces full scans and caused 30-second MCP timeouts.
Affected contract / model / boundary: SQLite schema and derived index consistency; no package boundary change.
Compatibility / migration risk: Medium — additive combined schema/data/index change; the live corpus is 12,401 sources and the measured full association build is 134 ms. SQLite cannot build indexes concurrently, so startup holds the existing schema lock during this bounded rebuild.
Verification plan: Backfill/lifecycle/query-plan tests, exact HTTP/vector parity tests, full suite, isolated live-corpus benchmark, and installed-service smoke.
Forward recovery: Dropping the derived table/index rolls back reads to the prior JSON path in a compensating change; source metadata remains authoritative and no user data is deleted or rewritten.

## Plan review

Expanded-plan re-review approved: recompute only affected purge/undo associations inside the existing raw SQLite transaction, no-op when the table is absent; EXPLAIN exact captured runtime SQL with selective assertions; validate a true pre-index provider-reopen migration. Standing human approval recorded in the marker block.
The clean-context reviewer withheld initial approval because the plan missed `fail_source_item_processing(..., metadata_updates=...)` and did not split query-plan protection across structural, lexical, and vector SQL shapes. The revised plan now routes both metadata mutation paths through one association sync contract and requires separate indexed/deduplicated plans with ordering assertions. Non-blocking guidance on transactional full replacement, canonical safe projection, legacy fixtures, and implemented startup benchmarking is incorporated above. Re-review confirmed both blockers closed and approved implementation.

## Result review

Initial smart result review withheld approval: production SQL was reimplemented in planner tests, startup backfill lacked a real provider-reopen migration journey, and offline secret purge/undo bypassed association synchronization. All three findings were fixed and independently rechecked. Final smart re-review found no remaining correctness, migration, planner, purge-atomicity, or complexity findings; its sole workflow finding was to reconcile this Work Record with the completed verification, now addressed.
