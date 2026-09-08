<!-- agent-workflow:start -->
**Outcome:** Pallium starts and restores only the current Relay database format; retired one-time split and endpoint-identity upgrade code is gone.

**Target:** Pallium.

**Scope:** Relay SQLite initialization/schema metadata, paired snapshot restore and status reporting, migration-only tests, operations documentation, and the canonical cross-container Relay roadmap record.

**Constraints:** Preserve the current separate Relay database design, fresh current-schema creation, same-database test/development mode, paired-generation snapshot behavior, fail-closed partial-pair startup, and all current Relay routing/lifecycle contracts. Do not drop or rewrite any table, column, row, or installed database file; existing marker tables may remain inert. Do not change public Relay HTTP/MCP contracts.

**Completion criteria:** Fresh separate-DB and same-DB stores shall create and use the current Relay schema without a migration metadata table or upgrade pass; an existing one-file-only pair and an existing Relay schema missing any required current endpoint column shall fail before ordinary Relay use without modifying either database; the already-migrated installed database shall reopen without mutation or data loss; paired snapshot generations shall still validate and restore while legacy single-file-to-pair upgrade restore is unsupported; status/operations/roadmap surfaces shall no longer claim migration readiness or compatibility; current Relay E2E behavior shall remain green.

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline classifies `storage/sqlite_schema.py` as a red schema-as-code surface requiring persistence review. The deletion crosses storage initialization, snapshot restore, status, tests, and docs, but introduces no new dependency or algorithm.

**Discovery:** The installed Relay DB contains both `relay_split_v1` and `relay_endpoint_identity_v1`, all current message/delivery endpoint columns, and passes `PRAGMA quick_check`. Runtime compatibility is implemented by two startup migrations plus a marker model/table, Relay column ALTER helpers, legacy single-snapshot restore, migration readiness status, operations prose, and migration-only tests. Current schema creation and paired snapshots are independent of those compatibility paths. The roadmap still says the shipped feature is queued and requires legacy migration, which is now stale.

**Material assumptions:** The user is the only Pallium operator and the only deployed service is the inspected, already-migrated local database; evidence disproving this requires retaining compatibility or shipping a separate one-off converter. Existing current-schema databases contain every required Relay column; a missing column after removal is an unsupported old database and must fail at startup rather than be silently rewritten or fail on later Relay use. Leaving old marker tables on disk is intentional and non-destructive; no runtime code may depend on them after this change.

**Plan:** Before opening separate SQLite files, reject a marker-independent one-file-only pair while allowing both-files-absent bootstrap and same-database mode. Before pragmas or schema initialization can mutate an existing database, validate that every existing Relay table has the required current endpoint columns in both database modes. Delete the split-copy, endpoint backfill, verification, marker preservation, marker schema, and Relay column ALTER compatibility paths while keeping the current declarative Relay tables, indexes, locks, and runtime transaction helpers. Remove legacy single-file-to-pair snapshot restoration and marker inspection; treat any partial live pair as invalid and count only paired snapshot manifests in status. Remove the always-true migration readiness field and its lifecycle assertions. Replace migration-only tests with current-format assertions for fresh separate/same databases, both partial-pair directions with snapshots disabled, every missing endpoint column without mutation, paired restore, current endpoint routing, exact persisted Relay rows across restart, alias removal/unresolved binding preservation, and a claimed delivery through public status/ACK. Update operations docs and the canonical roadmap to state that only the current format is supported and the feature is done, citing the already-shipped implementation and installed witness rather than claiming cleanup proves all acceptance criteria. Stop if the installed DB cannot reopen current-schema without mutation, paired-generation restore regresses, or any current Relay caller requires a removed symbol.

**Verification plan:** When a fresh store starts, it shall expose current Relay columns/tables without migration metadata → schema/isolation tests. When either file of an existing separate pair is missing, startup with snapshots disabled shall reject it before creating the other file → pair-state tests. When any required endpoint column is missing, startup shall reject it without adding columns or changing rows → parameterized schema-validation tests. When the installed migrated store is reopened from a backup, it shall preserve complete Relay rows and schema plus pass integrity checks → backup-based local reopen smoke. When current-format data restarts, removed aliases, unresolved endpoint bindings, claim tokens, receipts, and delivery state shall remain exact, and a claimed delivery shall finish through public status/ACK → current-format restart E2E. When snapshots restore, only a complete valid paired generation shall be accepted → snapshot tests. When status and service lifecycle run, they shall report current storage health without migration readiness → health and Windows/Linux lifecycle tests. When agents use Relay, current exact/alias/cross-container send, receive, ACK, reply, takeover, and restart behavior shall remain unchanged → focused Relay HTTP/MCP/hook E2E suites and CI.

**Plan review:** Approved on repeat clean-context architecture review after adding marker-independent partial-pair rejection, pre-mutation validation of every required endpoint column, complete persisted-value restart coverage, retained alias/restart behavior, and accurate paired-generation snapshot semantics.

**Approvals:** Approved by user 2026-09-08: "there's no need for the db migration beyond my own service because no one else is using pallium at the moment, so we can remove that code"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Deleted both one-time Relay migrations, migration marker model/table creation, endpoint-column ALTER helpers, and all runtime marker dependencies.
- Added pre-mutation validation: separate file pairs reject either missing side; an existing active Relay database must have the complete current tables and endpoint columns; same-database mode validates any existing Relay schema. Dormant legacy Relay tables in the separate main database remain inert and are not treated as the active schema.
- Removed legacy single-file-to-pair snapshot restore and legacy snapshot status counting. Paired-generation restore and the generic single-database snapshot API remain unchanged.
- Removed `relay_migration_ready` and its unused storage status helper; both current database sizes remain reported.
- Replaced migration-only tests with current-format schema, partial-pair, incomplete-schema, no-mutation, full-row restart, unresolved-binding, alias removal, claimed-delivery ACK/status, dormant-main, and unsupported legacy-snapshot coverage. Existing writer isolation, fan-in, HTTP, and Relay caller-surface coverage was preserved.
- Updated worker fixtures to create the separate Relay database from their first storage open instead of depending on the removed implicit same-to-separate migration.
- Updated operations guidance to current-format-only support and aligned the shipped cross-container roadmap item to done without changing global names, takeover, actor isolation, or the no-broadcast boundary.

## Evidence

- Focused persistence/snapshot/status/lifecycle verification: 75 passed; final isolation delta after the installed-database correction: 13 passed.
- Cross-container HTTP, hook, and MCP Relay E2E: 153 passed.
- Complete non-slow repository suite on the implementation candidate: 4,640 passed, 32 skipped, 2 expected failures. The subsequent one-line narrowing removed only validation of dormant main-DB Relay remnants; its dedicated final regression passed.
- Import boundaries: 8 contracts kept, 0 broken across 146 files and 505 dependencies.
- Installed-database backup smoke: 32 main tables and 5 Relay tables reopened; all 3,168 Relay rows, both retained marker rows, both schemas, main row counts, and `PRAGMA quick_check` results were unchanged. The first smoke correctly exposed over-broad validation of dormant main-DB remnants before commit; validation was narrowed to the active Relay file and the repeated smoke passed.
- No live database was opened by feature-branch code. The 408 MB temporary backup directory was verified under the isolated worktree and removed after the smoke.
- `git diff --check` passed; only expected Windows line-ending notices were emitted.
- Machine-local edit fallback: after the required pply_patch attempt failed with Windows error 1327, deterministic replacements were limited to this Work Record and the explicit storage/sqlite.py validation correction; delegated edits remained limited to their named files.

## Plan review

- First clean-context review verdict: revise. Findings incorporated into constraints, completion criteria, plan, and verification above.
- Repeat clean-context review verdict: approve at commit `98392988`; no remaining blocker. Reviewer emphasized that schema validation must precede pragmas and schema initialization.

## Result review

- Pending.