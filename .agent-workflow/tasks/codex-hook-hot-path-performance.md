<!-- agent-workflow:start -->
**Outcome:** Pallium's installed Claude and Codex integrations stop doing known zero-value work on prompt-critical paths while preserving durable Session History, live work context, and exact-scope Relay behavior.

**Target:** Pallium integration hot paths.

**Scope:** Claude setup reconciliation; Claude/Codex session identity helpers and hot hook callers; `/item-and-query` semantic-unavailable fast abstention; focused caller-surface, setup, session-state, API, and cross-platform tests.

**Constraints:** User-message ingestion remains unconditional for eligible prompts. Mutable branch, Work Record, and explicit work refs remain live rather than session-cached. Relay ordering, scope isolation, wake behavior, public response shape, and unrelated hooks remain unchanged. No production timing instrumentation, new dependency, or PR 2 deadline/audit work.

**Completion criteria:** With PostTool triggers disabled, setup removes only Pallium's managed PostToolUse entry and no Python hook runs after tools; enabling and rerunning setup installs it once. Within a long same-project session, repeated prompt/Stop identity resolution avoids Git subprocesses while cwd/repository-configuration changes invalidate container identity and live work-ref changes remain observable. When no semantic package is active, `/item-and-query` persists the user item exactly once and returns the existing abstention contract without runtime-context, retrieval, or audit work. Focused caller-surface tests and before/after local measurements demonstrate the reductions without adding slow sleeps to the standard suite.

**Risk:** High

**Complexity:** Moderate

**Reason:** Pre-edit redline reports red API contract (`api/routes.py`) and red core orchestration (`core/service.py`) surfaces requiring API and architecture review. High is required because the API/hook lifecycle is a contract surface; the change spans setup, two integrations, service routing, and E2E verification.

**Discovery:** The disabled Claude PostToolUse hook is installed unconditionally and costs 350-408 ms per no-op process. Prompt identity uses Git subprocesses repeatedly (~240 ms measured for container plus actor); container pinning already exists but does not retain cwd/actor and mutable work refs are inexpensive file-derived signals. Live query evidence showed 63/65 semantic-package-unavailable decisions and one 5.63 s zero-result query. The existing executor abstention occurs only after `/item-and-query` ingestion and runtime-context resolution. Existing session files are atomic but must not lose pending Relay-close state. Claude architect review confirmed the route-level gap and that ingestion must remain durable. Redline found no intended boundary violation and requires `api-review` plus `architecture-review`.

**Material assumptions:** Default semantic-package availability is configuration-owned and independent of runtime context; source inspection confirms `QueryExecutor` selects it from `_semantic_plugins[_default_use_case]`, so the service may abstain before thread stats while retaining executor-owned result/stat recording. Session cache writes require a portable per-session lock because hook processes can overlap; failure to acquire or parse state must bypass caching and recompute rather than use stale scope. Setup can identify only its own managed PostToolUse command; if ownership is ambiguous, preserve the entry and return to planning. Stable API response fields and query statistics must remain unchanged; if focused contract tests disprove that, return to planning.

**Plan:** 1. Reconcile the exact Pallium-managed Claude PostToolUse command conditionally on `PALLIUM_POSTTOOL_TRIGGERS=1`, preserving unrelated/malformed entries and enable-disable idempotence. 2. Replace session-state writes with one bounded per-session read-merge-atomic-replace under stdlib `fcntl`/`msvcrt` locking (OS releases on process death); use unique temporary files, preserve unknown/legacy fields and `pending_relay_closes`, and fail open to fresh Git identity when lock/state validation fails. Store normalized cwd, repository-config fingerprint, container, and actor; seed/refresh on SessionStart or project/config change, reuse in UserPromptSubmit/Stop, and never cache mutable work refs. 3. Expose the executor's existing default-package availability as a read-only check; let `PalliumService.query` return the executor-owned unavailable result/stat before runtime-context resolution, with an optional just-ingested item exclusion used only when context is needed. Remove the route's eager context read while keeping ingestion first. 4. Add deterministic managed-entry, concurrent/interleaved session-state, legacy/malformed/Unicode/project-switch, API, and real caller-surface regressions; compare focused before/after measurements outside the permanent suite. Stop on stale-scope evidence or enabled-package behavior drift. Key conventions: exact scope, existing query decision/stat path, no new dependency, and no production timing. Target files are `app/cli/setup_claude_code.py`, Claude/Codex hook common and hot entrypoints, `api/routes.py`, `core/service.py`, the minimal availability accessor in `core/query.py`, and focused tests; schemas, persistence, wake semantics, and PR 2 hooks remain excluded.

**Verification plan:** Disabled/enabled setup shall remove/install exactly the managed hook while preserving neighboring configuration -> setup integration tests. Same-session identity shall avoid repeat Git and shall refresh on cwd/repository configuration change while work refs remain current -> Claude/Codex session-state unit plus caller-surface tests. Semantic-unavailable item/query shall ingest once and skip runtime context/query/audit while enabled semantic behavior remains unchanged -> HTTP E2E through `/item-and-query` and storage/public response assertions. Relay/project-switch behavior shall remain exact-scope and pending-close safe -> existing Relay hook/E2E suites plus new cache transition cases. Performance claims shall be evidenced by focused local before/after commands with no wall-clock sleep added to CI.

**Plan review:** See `## Plan review` (clean-context High-risk review; accepted).

**Approvals:** Approved by user 2026-09-07T13:47:16+03:00: "ok, so you can drive those two prs"

**Exceptions:** —

**State:** Ready to implement

<!-- agent-workflow:end -->

## Implementation

- Established context and completed focused discovery from the live timeout incident, source paths, tests, Claude architect review, and pre-edit redline classification.
- Resolved the clean-context review blocker in the plan with portable per-session locking, fail-open cache reads, and a single executor-owned semantic availability path; re-review accepted the revision and implementation is ready to begin.

## Plan review

Clean-context review (2026-09-07):

- **Blocker — session identity cache/state is not yet fail-safe cross-process.** `pin_container` currently performs an unlocked read/modify/write pattern at its callers and then atomically replaces the session file; adding cached cwd/repository-configuration identity alongside `pending_relay_closes` can still overwrite a close written by another hook process. The implementation must use a lock-safe merge (or equivalent retry/compare-and-preserve update), preserve unknown/legacy fields, and fail open on malformed or changed state. Tests must exercise interleaved SessionStart/UserPromptSubmit/Stop updates and prove no stale container scope and no lost pending close. Until that design is explicit, the material assumption is unproven.
- **Required contract check — semantic fast abstention.** The route currently resolves runtime context before `service.query`, while package selection in `QueryExecutor` is based on the configured default use case. The plan must name the single service-level availability check/result path used before runtime-context resolution, prove enabled packages still take the existing path, and preserve the existing `semantic_package_unavailable` response plus zero-query-stat/zero-audit behavior. Do not make `api/routes.py` duplicate package-selection policy.
- **Required ownership check — managed PostToolUse reconciliation.** Conditional setup must match the exact Pallium-managed command/entry it owns, remove only that entry when disabled, preserve unrelated PostToolUse entries and malformed/unknown entries, and remain idempotent across enable/disable cycles. Add the disabled/enabled preservation assertions before implementation.

**Re-review (2026-09-07):** Accepted. The revised plan explicitly specifies a bounded portable per-session lock (`fcntl`/`msvcrt`, released by the OS on process death), read-merge-atomic-replace with unique temporary files, preservation of unknown/legacy and `pending_relay_closes` fields, and fail-open recomputation on lock/state failure. It also assigns semantic-unavailable detection to an executor-owned availability/result path exposed through `PalliumService.query`, before runtime-context resolution, while retaining the existing response, zero-query-stat, and zero-audit contract. The managed-hook ownership and preservation checks remain explicit. No blocker remains; scope stays within PR1.

## Evidence

Pending implementation.

## Result review

Pending implementation.
