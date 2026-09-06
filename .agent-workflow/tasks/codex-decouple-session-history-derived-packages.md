<!-- agent-workflow:start -->
**Outcome:** Pallium starts and provides governed raw Session History with every semantic package disabled, while optional derived-memory processing runs only when explicitly enabled.

**Target:** Pallium.

**Scope:** Package defaults and service construction; raw ingest/index/search/expansion; package-processing claims; package-independent source vector text; focused docs, roadmap state, and HTTP/MCP/hook E2E tests.

**Constraints:** No new flag, dependency, schema migration, authorization layer, API shape, hook change, or silent privacy relaxation. Existing derived implementations and stored data remain intact. Relay surfaces are out of scope.

**Completion criteria:** With zero enabled semantic packages, public hook, HTTP, and MCP flows complete start → governed ingest under the existing redaction rules with structural work refs → lexical/vector broad and exact search → expansion → forget/delete/retention, with zero derived-model calls; explicit package opt-in restores only that package's processing; disabling a package safely cancels its unfinished derived work while preserving raw and completed derived data; all boundary/error/Unicode/idempotence/visibility cases pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline identifies `core/service.py` as a red architecture surface requiring architecture review; the remaining runtime/core/storage files are watched. No API, schema, security-policy, or boundary change is planned, but several coordinated runtime seams require expanded planning.

**Discovery:** `app/dependencies.build_service` rejects a missing active default plugin. `PalliumService.ingest_item` looks up that plugin before persisting raw history, though raw redaction and lexical indexing are otherwise core-owned. `QueryExecutor.query` looks up the default plugin before its source-only branch and borrows visibility behavior from it. Source vectors use semantic-package text in `core/vector_embed.py` and `core/vector_rebuild.py`. Package queues claim disabled-package rows and then fail them as unknown. Explicit memory writes are core-owned but have incidental semantic indexing imports; raw `artifact_kind=note` derivation remains package-owned. Existing HTTP/MCP/hook surfaces already funnel through these shared seams. Canonical requirement: `roadmap/features/decouple-session-history-from-derived-packages.md`.

**Material assumptions:** All governed raw SourceItems remain lexically searchable; no new event-kind allowlist is added. Raw vector eligibility preserves the current rule: only `message` and `assistant_output` items with at least 40 characters. Static retention policy for configured built-in package implementations remains in force even when processing is disabled. Disabling a package cancels its unfinished package and rebuild work as `skipped`; re-enabling processes new ingests only, while existing raw and completed derived data remain. With no active default package, normal derived query is unavailable; direct expansion/mutation remains available. When a default is enabled, existing retrieval may return stored objects created by disabled packages because storage is not package-filtered. Explicit remember/correct/supersede/forget/outcome writes remain core-owned. Package-free `artifact_kind=note` stores the existing verbatim raw note but performs no optional title/memory derivation.

**Plan:**
1. Keep `SemanticPackageConfig.enabled` as the only activation control. Set built-in derived packages off by default. Only an explicit package `enabled=true` setting enables processing; provider/model/prompt and legacy settings configure packages but never enable them accidentally. Preserve `enabled` through every config reconstruction and override path.
2. Let `build_service` construct a valid raw-history service without an active default plugin; do not add a placeholder plugin. At the composition root, merge package-declared static retention policies for configured implementations without constructing their providers, so disabling generation does not weaken retention/protection of existing data.
3. Make raw ingest independent: redact under the existing rules, preserve structural work refs, store the SourceItem, and create its lexical index before any optional package work. With no applicable active package, store no package ownership/rows and mark raw processing complete. With packages enabled, schedule only the selected active package plus active parallel packages. Preserve the explicit verbatim-note exception.
4. Move the existing raw-source vector eligibility/text rule and shared embedding schema fact into a core indexing seam used by ingest and rebuild. When vector indexing is enabled, persist the eligible raw vector entry independently of packages; embed immediately when no package worker will do it, otherwise reuse the existing background path. A persisted-but-unembedded entry survives provider failure for reconciliation. On startup with vectors enabled, a bounded storage existence check detects eligible lexical source entries lacking raw vector entries, marks rebuild needed, and the existing coordinator performs paged lexical-entry inventory/backfill before declaring vector availability.
5. Execute source-only history search before default-plugin lookup. Raw search always requires container plus visibility and reuses current filtering, redaction, forgetting, expansion, and audit behavior. A normal derived query with no active default returns a clear non-injecting unavailable result rather than raising; enabling a default preserves today's cross-package stored-result behavior. Retrieval must not update accessibility/ranking state.
6. Package activation changes take effect only at a clean service restart, after the supervisor has stopped its worker tree. At new service construction, atomically cancel unfinished work owned by disabled packages, including pending/failed/expired package rows and thread/container rebuild scopes; clear leases and make affected aggregate source status terminal without invoking a provider. Revalidate claim owner/status immediately before any package or rebuild provider call. Make result commit/complete/failure return a distinct compare-and-set outcome keyed by owner plus attempt/generation; only a successful outcome may run derived follow-on effects such as metadata/provenance updates, memory-vector embedding, workstream assignment, shadow extraction, or consolidation. A canceled claim starts no new model call; a model request already in flight may finish, but its result and every derived side effect are discarded. Do not retain a dormant backlog. Re-enable affects new ingests only; completed raw/derived data is untouched. Queue health and worker `--once`/drain terminate cleanly and still distinguish genuinely unknown package data.
7. Keep explicit memory-write lifecycle in core and remove only incidental semantic indexing imports needed for zero-package operation. Do not move optional note derivation into core.
8. Add two independent public lifecycle E2E release gates plus focused config, vector, queue, retention, and query tests. The first runs with zero enabled packages and proves raw Session History works without any derived-model call. The second explicitly enables a package and proves derived extraction, retrieval, rebuild, consolidation, and coexistence with raw history. Align the roadmap and design only after both modes are verified. Stop and return to planning if implementation requires schema/API changes, weakens visibility, changes the verbatim-note contract, or cannot cancel disabled work without touching completed data.

**Verification plan:** Gate A: zero-package startup and public hook/HTTP/MCP start → ingest → broad/exact search → expansion → forget/delete/retention → E2E with structural refs, Unicode, visibility isolation, duplicate identity, empty/max/over-max bounds, and a provider spy proving zero extraction/rebuild/consolidation/routing calls. Gate B: explicitly enable one package and drive public ingest → extraction → derived retrieval → thread rebuild → consolidation → raw-history retrieval, using a deterministic fake provider and asserting generated rows, vector indexing, provenance, and raw/derived coexistence through public read surfaces. Config defaults/precedence → TOML, environment, legacy, alias, unrelated override, one-active/one-disabled tests proving only explicit `enabled=true` activates. Vector lifecycle → disabled, enabled, missing/failing/recovered provider, short/empty/tool/command/note/Unicode, duplicate ingest, persisted-entry reconciliation, startup detection plus disabled→enabled paged backfill, and live/rebuild text consistency while lexical search remains available. Package lifecycle → pending/failed/expired/actively leased package and thread/container work cancelled on clean restart, canceled claims start no provider call, stale in-flight package/rebuild results are rejected by owner+generation CAS with no derived rows, vector entries, metadata/provenance changes, workstream assignment, shadow extraction, or consolidation; completed data preserved, worker drain terminates, queue health is honest, and three disable/re-enable transitions process only new enabled work. Derived/explicit behavior → no-default normal query returns unavailable; expansion and remember/correct/supersede/forget/outcome remain governed; enabling a default can retrieve stored cross-package objects; package-free note is raw verbatim only. Retention → disabled packages preserve static durable/working/orphan rules and normal TTL can prune terminal raw items. Final gate → focused tests, full non-slow suite, explicit slow E2Es, import-linter/redline/workflow checks, PR CI, clean-context result review, and all review threads resolved.

**Plan review:** Approved by fresh clean-context architect `/root/decouple_plan_review_v4` after V1–V3 findings were incorporated; no blocking findings remain.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement

<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Established context, completed read-only discovery and pre-edit redline classification. No production or test code edited.
- 2026-09-06: First clean-context architecture review rejected the draft after finding package-dependent retention, unfiltered rebuild/finalizer paths, activation-precedence leaks, ambiguous stored-memory reads, and incomplete vector recovery. Verified each finding in code and returned to planning.
- 2026-09-06: Revised the plan to preserve static retention, require explicit activation, cancel disabled unfinished work, define stored-memory/explicit-note behavior, and specify raw-vector eligibility/backfill.
- 2026-09-06: V4 clean-context architecture review approved the final plan. Per user request, implementation remained paused for the plan briefing.
- 2026-09-06: User approved implementation and made two independent E2E modes release gates: raw-only with zero packages/model calls, and explicitly enabled derived memory with extraction, retrieval, rebuild, consolidation, and raw-history coexistence. Work moved to Ready to implement.

## Plan review

V1 review: rejected by clean-context architect `/root/decouple_plan_architect`; all five blocking findings incorporated into the revised plan.

V2 review: rejected by clean-context architect `/root/decouple_plan_review_v2`; added a clean-restart contract, stale-claim CAS fencing, and an explicit startup vector-backfill trigger.

V3 review: rejected by clean-context architect `/root/decouple_plan_review_v3`; CAS success now gates provider entry and every derived follow-on side effect, with in-flight results discarded.

V4 review: APPROVED by fresh clean-context architect `/root/decouple_plan_review_v4`; no blocking findings.

## Evidence

Pending.

## Result review

Pending.
