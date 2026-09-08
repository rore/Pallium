<!-- agent-workflow:start -->
**Outcome:** Pallium starts and restores only the current Relay database format; retired one-time split and endpoint-identity upgrade code is gone.

**Target:** Pallium.

**Scope:** Relay SQLite initialization/schema metadata, paired snapshot restore and status reporting, migration-only tests, operations documentation, and the canonical cross-container Relay roadmap record.

**Constraints:** Preserve the current separate Relay database design, fresh current-schema creation, same-database test/development mode, paired snapshot behavior, and all current Relay routing/lifecycle contracts. Do not drop or rewrite any table, column, row, or installed database file; existing marker tables may remain inert. Do not change public Relay HTTP/MCP contracts.

**Completion criteria:** Fresh separate-DB and same-DB stores shall create and use the current Relay schema without a migration metadata table or upgrade pass; the already-migrated installed database shall reopen without mutation or data loss; paired snapshots shall still restore atomically while legacy single-file upgrade restore is unsupported; status/operations/roadmap surfaces shall no longer claim migration readiness or compatibility; current Relay E2E behavior shall remain green.

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline classifies `storage/sqlite_schema.py` as a red schema-as-code surface requiring persistence review. The deletion crosses storage initialization, snapshot restore, status, tests, and docs, but introduces no new dependency or algorithm.

**Discovery:** The installed Relay DB contains both `relay_split_v1` and `relay_endpoint_identity_v1`, all current message/delivery endpoint columns, and passes `PRAGMA quick_check`. Runtime compatibility is implemented by two startup migrations plus a marker model/table, Relay column ALTER helpers, legacy single-snapshot restore, migration readiness status, operations prose, and migration-only tests. Current schema creation and paired snapshots are independent of those compatibility paths. The roadmap still says the shipped feature is queued and requires legacy migration, which is now stale.

**Material assumptions:** The user is the only Pallium operator and the only deployed service is the inspected, already-migrated local database; evidence disproving this requires retaining compatibility or shipping a separate one-off converter. Existing current-schema databases contain every required Relay column; a missing column after removal is an unsupported old database and must fail rather than be silently rewritten. Leaving old marker tables on disk is intentional and non-destructive; no runtime code may depend on them after this change.

**Plan:** Delete the split-copy, endpoint backfill, verification, marker preservation, marker schema, and Relay column ALTER compatibility paths while keeping the current declarative Relay tables and indexes. Remove legacy single-file-to-pair snapshot restoration and marker inspection; treat any partial live pair as invalid and count only paired snapshot manifests in status. Remove the always-true migration readiness field and its lifecycle assertions. Replace migration-only tests with focused current-format assertions for fresh separate/same databases, paired restore, current endpoint routing, and installed-database reopen. Update operations docs and the canonical roadmap to state that only the current format is supported and the feature is done. Stop if the installed DB cannot reopen read-only/current-schema, paired restore regresses, or any current Relay caller requires a removed symbol.

**Verification plan:** When a fresh store starts, it shall expose current Relay columns/tables without migration metadata → schema/isolation tests. When the installed migrated store is reopened, it shall preserve counts and pass integrity checks without schema writes → backup-based local reopen smoke. When snapshots restore, only a complete valid pair shall be accepted → snapshot unit/E2E tests. When status and service lifecycle run, they shall report current storage health without migration readiness → health and Windows/Linux lifecycle tests. When agents use Relay, current exact/alias/cross-container send, receive, ACK, reply, takeover, and restart behavior shall remain unchanged → focused Relay HTTP/MCP/hook E2E suites and CI.

**Plan review:** Pending clean-context review.

**Approvals:** Approved by user 2026-09-08: "there's no need for the db migration beyond my own service because no one else is using pallium at the moment, so we can remove that code"

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit risk classification complete. No production file has been edited; implementation waits for clean-context plan review.

## Evidence

- Installed `pallium-relay.db`: split and endpoint markers present; current endpoint columns present; `PRAGMA quick_check` returned `ok`.

## Plan review

- Pending.

## Result review

- Pending.
