<!-- agent-workflow:start -->
**Outcome:** When no semantic package is active, Pallium records raw Session History while automatic derived-memory injection is visibly off and creates no injection/skip or generic proactive-query audit telemetry.

**Target:** Pallium.

**Scope:** Disabled/source-only query telemetry, automatic `/item-and-query` and `/query` audit handling, `/status` and dashboard mode display, focused documentation/roadmap, and public-surface/E2E tests. No production hook rewrite is planned.

**Constraints:** Raw ingestion, Relay, explicit Session History search/expansion, visibility, and enabled-package behavior remain unchanged. No schema, migration, dependency, auth, or integration-install change. Preserve historical metrics. Coordinate with `pall-arc` before any installed-service restart.

**Completion criteria:** (1) With zero active packages, hook-driven ingest stores the raw turn but produces no injection/skip metric or generic query-audit row and makes no retrieval/model call. (2) Source-only history search remains functional and is not counted as a skipped injection. (3) `/status` and the dashboard clearly show derived memory off. (4) Enabling a package restores existing injection and abstention telemetry unchanged. (5) Codex, Claude Code, OpenCode-equivalent HTTP, session-start, failure-trigger, Unicode, empty, and restart/transition paths are covered through caller-facing tests.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is an API-contract red zone requiring `api-review`; the behavior spans core telemetry, runtime status, dashboard, and multiple integration triggers. No persistence/security boundary or import-boundary change is intended.

**Discovery:** Live status since restart showed 27 queries, 0 injections, and 27 skips: 26 `semantic_package_unavailable` plus one `source_only_search`. Codex and Claude UserPromptSubmit use `/item-and-query` to preserve raw ingest; session-start and Claude failure/pre-compact hooks use `/query`. `QueryExecutor` already exits before retrieval/model work when no plugin exists, but shared `QueryStats` treats every non-injection result—including source-only search—as a skip. Both `/query` and `/item-and-query` still write generic query-audit rows. Source-only search also creates its intentional dedicated `HistoricalLookupReuseEventRecord`; that event and its returned lookup id must remain. No evaluator or public contract requires the disabled/source-only generic rows. `/status` exposes no current derived-memory mode.

**Material assumptions:** (1) Disabled automatic queries and duplicate generic source-only audit rows have no required downstream consumer; disprove by finding an evaluator or API contract that requires them, then preserve them under a separate non-injection event. (2) “Injection off” means no retrieval/routing/model work and no injection telemetry; a cheap local ingest request may still reach the server. If the user requires zero HTTP requests, return to planning for an integration capability-cache design. (3) Existing persisted metrics remain immutable; only new events change.

**Plan:** 1. Add a backward-compatible `source_only` keyword to `QueryStats.record_query`; centrally return before counters or persistence for every source-only call or exact `semantic_package_unavailable` result. Pass the query mode at every `QueryExecutor` stats call so a fail-closed source-only request is also excluded, while the same `visibility_context_required` result remains a real skip for derived queries. 2. At both generic audit sites (`/query` and `_maybe_write_query_audit` for `/item-and-query` including debug), write only when auditing is enabled, the request is not source-only, and the result is not `semantic_package_unavailable`. Preserve the dedicated historical-lookup event and response id. 3. Add `derived_memory` to `/status`, using the actually built `service._semantic_plugins` as runtime truth; render a compact OFF/ON explanation in the existing Query Activity heading. 4. Keep responses, raw ingestion/search/expansion, and enabled-package behavior unchanged. 5. Extend existing core/API/status/dashboard and caller-surface E2E tests; no new harness or production hook edit. 6. Update the vNext correction item/docs, run focused then full non-slow suites and workflow/redline checks, obtain required review labels, and close the PR. Key conventions: one server-side truth, no per-integration config parsing, no new endpoint/schema/storage object. Target files: `core/observability.py`, `api/routes.py`, `app/main.py`, `app/dashboard.html`, focused tests, docs/roadmap. Stop and re-plan if disabled audit rows are required for evaluation or if production hook edits become necessary.

**Verification plan:** On a clean zero-package app with query auditing enabled, `/item-and-query` stores Unicode raw content while non-source-only `/query` leaves QueryStats, query metrics, and generic query audit at zero and calls no provider/retrieval path. Successful and fail-closed source-only lookups create no generic audit/stat event; a successful lookup creates exactly one dedicated historical-lookup event. `/status` and the rendered dashboard say OFF. A one-package control proves ordinary injection/abstention stats and audit remain unchanged and status says ON. Existing caller tests cover Codex/Claude/OpenCode-equivalent trigger shapes; extend only the smallest hook E2E where needed. Reuse existing boundary, visibility, forgotten-source, limit, idempotence, and lifecycle tests rather than duplicate them. Final diff → focused tests, full non-slow pytest, import-linter, workflow checker, redline, PR CI/review threads.

**Plan review:** APPROVED by a clean-context high-reasoning architecture review. A follow-up edge-case review required passing `source_only` explicitly into shared `QueryStats` so failed raw-history searches are never counted as injection attempts; normal derived visibility failures remain counted.

**Approvals:** Approved by user 2026-09-07: "yes, i want you to work on this. work in isolation as other agents may do parallel work. be very budget conscious, so plan what you do as an expensive model and what you can delegate to cheap models to make this cost less."

**Exceptions:** —

**State:** Ready to implement
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- Planning: isolated worktree created from `origin/main`; no production files edited. Pre-edit redline verdict is `API_CHANGE` because `api/routes.py` is red-zone; no boundary risk, persistence, or security checkpoint.

## Evidence

- Pending implementation.

## Result review

- Pending.
