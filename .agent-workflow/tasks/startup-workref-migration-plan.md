# Startup work-reference migration plan

Owner: Relaydev. Assignment: pallium manager, chat `01a0d7ce-83c6-77e2-90f7-d413894059e1`, 2026-10-08. Planning only. Reuse accepted diagnostic revision `61295cd84a2120630e117bbfd2860206ca93cb25`; no additional reproduction runs. Manager owns roadmap and unresolved outage incidents.

<!-- agent-workflow:start -->
**Outcome:** Prepare a reviewed minimal production plan that avoids unnecessary startup work-reference rebuilds while preserving initialization, upgrade, incremental updates, repair and failure safety.

**Target:** Pallium.

**Scope:** Plan the startup backfill change in storage/sqlite_schema.py and its bounded regression/E2E coverage; only this Work Record may change during the current planning assignment.

**Constraints:** No implementation or test execution, new migration registry/config flag, native/synthetic reproduction runs, full suite, installed database/cache/service/config changes, PR #307 changes or protected-contract weakening. Use existing migration/version authority where suitable and inspect all backfill, synchronization and repair callers first. Historical outage cause and accept failure remain open.

**Completion criteria:** The plan identifies exact files, existing migration/repair authority, atomic rollback and concurrent-startup behavior, observable before/after tests through caller read paths, risk and required approvals; clean-context persistence technical review is complete before handoff for human High-risk approval.

**Requirement baseline:**
{"source":"pallium-manager:01a0d7ce-83c6-77e2-90f7-d413894059e1:2026-10-08","outcome":"Prepare a reviewed minimal production plan that avoids unnecessary startup work-reference rebuilds while preserving initialization, upgrade, incremental updates, repair and failure safety.","scope":"Plan the startup backfill change in storage/sqlite_schema.py and its bounded regression/E2E coverage; only this Work Record may change during the current planning assignment.","constraints":"No implementation or test execution, new migration registry/config flag, native/synthetic reproduction runs, full suite, installed database/cache/service/config changes, PR #307 changes or protected-contract weakening. Use existing migration/version authority where suitable and inspect all backfill, synchronization and repair callers first. Historical outage cause and accept failure remain open.","completion_criteria":"The plan identifies exact files, existing migration/repair authority, atomic rollback and concurrent-startup behavior, observable before/after tests through caller read paths, risk and required approvals; clean-context persistence technical review is complete before handoff for human High-risk approval."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Intended production path storage/sqlite_schema.py is RED and persistence-review required. Migration completion, partial failure and concurrent startup govern persisted derived state; bounded but meaningful multi-lifecycle uncertainty.

**Discovery:** Pending read-only discovery on fresh origin/main.

**Material assumptions:** Existing migration/version authority can express one-time initialization and recovery. If absent or insufficient, report the exact gap rather than introduce another registry or silently broaden scope. Accepted diagnostics prove unconditional rebuild writer exclusion, not historical outage causality or natural duration.

**Plan:**
1. Invoke agent-workflow, create this Work Record and classify before any code edit. Planning only; no implementation authorized.
2. Trace existing migrations, every backfill caller, incremental metadata synchronization, repair and forget/correction semantics; inspect caller-read E2E fixtures and relevant protected contracts.
3. Define the smallest atomic guarded backfill using current migration authority, exact files and bounded coverage; classify changed startup behavior explicitly.
4. Obtain clean-context persistence technical plan review and address findings. Handoff to manager for the separate human High-risk plan approval; stop before implementation.

**Verification plan:** Read-only source and accepted evidence review now. Future implementation validation must prove fresh/upgrade backfill only when needed, zero derived-table DELETE/rewrite on unchanged reopen, preserved incremental metadata/correction/forget behavior, atomic failure rollback/retry, safe concurrent startup and explicit repair through existing authorized surfaces, using E2E caller/read paths. No tests run in this planning allocation.

**Plan review:** Agent technical review: pending; clean-context non-implementer required.

**Approvals:** Pending separate human High-risk approval of the concrete plan; manager is the designated requester. Current assignment authorizes planning only.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Recovery

Branch: feat/startup-workref-migration-plan. Current scope is plan preparation, not implementation. Next: source discovery, precise plan and independent persistence review, then manager requests exact human approval. Existing diagnostic and PR #307 checkouts/evidence are retained unchanged. No canonical roadmap identity supplied; manager owns incident/roadmap reconciliation.

## Implementation

2026-10-08: Work Record created before discovery. No production/test edit or execution. High-risk approval gate applies to future implementation, not this authorized plan preparation.
