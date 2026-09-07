<!-- agent-workflow:start -->
**Outcome:** When no semantic package is active, Pallium records raw Session History while automatic derived-memory injection is visibly off and creates no injection/skip or generic proactive-query audit telemetry.

**Target:** Pallium.

**Scope:** Disabled/source-only query telemetry, automatic `/item-and-query` and `/query` audit handling, `/status` and dashboard mode display, focused documentation/roadmap, and public-surface/E2E tests. No production hook rewrite is planned.

**Constraints:** Raw ingestion, Relay, explicit Session History search/expansion, visibility, and enabled-package behavior remain unchanged. No schema, migration, dependency, auth, or integration-install change. Preserve historical metrics. Coordinate with `pall-arc` before any installed-service restart.

**Completion criteria:** (1) With zero active packages, hook-driven ingest stores the raw turn but produces no injection/skip metric or generic query-audit row and makes no retrieval/model call. (2) Source-only history search remains functional and is not counted as a skipped injection. (3) `/status` and the dashboard clearly show derived memory off. (4) Enabling a package restores existing injection and abstention telemetry unchanged. (5) Codex, Claude Code, OpenCode-equivalent HTTP, session-start, failure-trigger, Unicode, empty, and restart/transition paths are covered through caller-facing tests.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is an API-contract red zone requiring `api-review`; the behavior spans core telemetry, runtime status, dashboard, and multiple integration triggers. No persistence/security boundary or import-boundary change is intended.

**Discovery:** Live status since restart showed 27 queries, 0 injections, and 27 skips: 26 `semantic_package_unavailable` plus one `source_only_search`. Codex and Claude UserPromptSubmit use `/item-and-query` to preserve raw ingest; session-start and Claude failure/pre-compact hooks use `/query`. `QueryExecutor` already exits before retrieval/model work when no plugin exists, but `QueryStats` treats every non-injection result—including source-only search—as a skip, and API routes still write generic query-audit rows. `/status` exposes no current derived-memory mode.

**Material assumptions:** (1) Disabled automatic queries and duplicate generic source-only audit rows have no required downstream consumer; disprove by finding an evaluator or API contract that requires them, then preserve them under a separate non-injection event. (2) “Injection off” means no retrieval/routing/model work and no injection telemetry; a cheap local ingest request may still reach the server. If the user requires zero HTTP requests, return to planning for an integration capability-cache design. (3) Existing persisted metrics remain immutable; only new events change.

**Plan:** 1. Reuse the existing plugin-unavailable and source-only branches; stop them from calling injection stats, and suppress generic query-audit writes for disabled automatic work and duplicate source-only search while retaining the dedicated historical-lookup event. 2. Add a derived-memory mode block to `/status`, computed from the already-resolved enabled package config; render a compact OFF/ON explanation in the existing Query Activity heading. 3. Keep explicit derived query responses and all raw-history behavior unchanged. 4. Add focused core/API/status/dashboard tests plus caller-surface lifecycle coverage for raw-only and enabled configurations across integration trigger shapes. 5. Update the vNext correction item/docs, run focused then full non-slow suites and workflow/redline checks, obtain required review labels, and close the PR. Key conventions: one server-side truth, no per-integration config parsing, no new endpoint/schema/storage object. Target files: `core/query.py`, `api/routes.py`, `app/main.py`, `app/dashboard.html`, focused tests, docs/roadmap. Stop and re-plan if disabled audit rows are required for evaluation or if production hook edits become necessary.

**Verification plan:** Zero-package hook ingest stores raw content with zero provider/retrieval/injection telemetry → HTTP + Codex/Claude hook E2E with spies and database assertions. Source-only search remains searchable and absent from injection counters → MCP/HTTP history-search E2E plus metrics assertions. Status/dashboard visibly say OFF → status contract and rendered DOM/browser test. Enabled package retains injections/skips → existing package-enabled E2E plus focused regression. Boundaries/errors/transitions → zero/one package restart-style app rebuilds, Unicode, short/empty trigger, invalid/missing package, and all supported automatic trigger origins. Final diff → full non-slow pytest, import-linter, workflow checker, redline, PR CI/review threads.

**Plan review:** Pending clean-context review.

**Approvals:** Approved by user 2026-09-07: "yes, i want you to work on this. work in isolation as other agents may do parallel work. be very budget conscious, so plan what you do as an expensive model and what you can delegate to cheap models to make this cost less."

**Exceptions:** —

**State:** Blocked
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

## Implementation

- Planning: isolated worktree created from `origin/main`; no production files edited. Pre-edit redline verdict is `API_CHANGE` because `api/routes.py` is red-zone; no boundary risk, persistence, or security checkpoint.

## Evidence

- Pending implementation.

## Result review

- Pending.
