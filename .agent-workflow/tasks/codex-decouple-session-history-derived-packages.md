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

**State:** Ready for review

<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Raw-source vector slice will modify only core/indexing.py, core/vector_embed.py, core/vector_rebuild.py, core/rebuild_coordinator.py, semantic/agent_conversation_memory_embedding.py, and focused vector tests. It reuses existing lexical pagination and index-entry uniqueness APIs; no storage API change is planned.
- 2026-09-06: Implemented configuration-only activation decoupling in `app/config.py`; updated focused config coverage for defaults, TOML/env explicit activation, legacy/provider/model/prompt/alias/unrelated preservation, and mixed enabled/disabled packages.

- 2026-09-06: Established context, completed read-only discovery and pre-edit redline classification. No production or test code edited.
- 2026-09-06: First clean-context architecture review rejected the draft after finding package-dependent retention, unfiltered rebuild/finalizer paths, activation-precedence leaks, ambiguous stored-memory reads, and incomplete vector recovery. Verified each finding in code and returned to planning.
- 2026-09-06: Revised the plan to preserve static retention, require explicit activation, cancel disabled unfinished work, define stored-memory/explicit-note behavior, and specify raw-vector eligibility/backfill.
- 2026-09-06: V4 clean-context architecture review approved the final plan. Per user request, implementation remained paused for the plan briefing.
- 2026-09-06: User approved implementation and made two independent E2E modes release gates: raw-only with zero packages/model calls, and explicitly enabled derived memory with extraction, retrieval, rebuild, consolidation, and raw-history coexistence. Work moved to Ready to implement.

- 2026-09-06: Reviewed the integration follow-up: explicit VectorEmbedder enabled gating and existing-row reuse are covered; added no production changes. Added regressions for disabled vectors, provider-absent pending rows, paged Unicode backfill detection, empty/ineligible/already-vectorized false cases, and coordinator backfill idempotence.

- 2026-09-06: Added focused two-mode release-gate E2E coverage in `tests/test_decouple_session_history_e2e.py`: Gate A drives HTTP, hook, and MCP client surfaces with configured-but-disabled provider/model settings and asserts raw Unicode/work-ref retrieval, expansion, forgetting, visibility isolation, terminal processing, zero provider calls, zero package rows, and zero derived memories. Gate B explicitly enables `agent_conversation_memory` with a deterministic provider and asserts raw plus derived retrieval, provenance/evidence expansion, thread summaries, consolidation, and package-task persistence.

- 2026-09-06: Optimized raw-vector startup detection with a SQLite EXISTS/LIMIT join over lexical source rows and missing vector rows, retaining the paged fallback for generic/test storage. Replaced source-vector duplicate membership set copying with VectorIndex.contains(). Also fixed the coordinator IntegrityError import exposed during review.

- 2026-09-06: Added the two bounded vector optimizations only: SQLite raw-source detection now uses an EXISTS/LIMIT join with generic paged fallback; VectorIndex.contains avoids materializing full ID sets for single membership checks. Added direct-membership and real-SQLite bounded-query tests; fixed missing IntegrityError import in the existing coordinator catch.

## Plan review

V1 review: rejected by clean-context architect `/root/decouple_plan_architect`; all five blocking findings incorporated into the revised plan.

V2 review: rejected by clean-context architect `/root/decouple_plan_review_v2`; added a clean-restart contract, stale-claim CAS fencing, and an explicit startup vector-backfill trigger.

V3 review: rejected by clean-context architect `/root/decouple_plan_review_v3`; CAS success now gates provider entry and every derived follow-on side effect, with in-flight results discarded.

V4 review: APPROVED by fresh clean-context architect `/root/decouple_plan_review_v4`; no blocking findings.

## Evidence
- 2026-09-06: Added AI Core final-boundary cancellation coverage in `tests/test_providers_llm_aicore.py`: token acquisition flips the guard, deployment lookup completes, inference transport receives zero requests, and `ModelCallCancelledError` is raised.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_providers_llm_aicore.py -n 0` — 13 passed.
- 2026-09-06: Opted in only derived-processing fixtures across integration readiness, narrow-target eval shared builder, observability queue test, thread near-duplicate tests, and standalone extraction tests; raw-history fixtures remain untouched.
- 2026-09-06: Focused regression rerun covering those fixtures passed: 25 tests, 1 existing warning.

- 2026-09-06: Added provider guard tests covering retry cancellation before a second request, guard reset after exceptions, and stale-guard blocking in the redaction wrapper. No production changes.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_providers_llm.py tests/test_redacting_llm_wrapper.py -n 0` — 32 passed.
- 2026-09-06: Re-verified config contracts with `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_config.py -n 0` — 36 passed. Packages default disabled, explicit activation is preserved, incomplete enabled packages fail fast, and disabled built-ins retain static policy without provider construction.
- 2026-09-06: `build_semantic_plugins` now raises a clear `ValueError` for explicitly enabled provider-backed packages missing `llm_provider` or `model`; disabled packages continue to skip construction.
- 2026-09-06: Added focused missing-provider and missing-model tests; `uv run python -m pytest -q tests/test_config.py -k 'enabled_package or disabled_builtin or skips_disabled' -n 0` — 4 passed, 32 deselected.
- 2026-09-06: Added `test_disabled_builtin_keeps_retention_policy_without_provider` covering disabled built-in static retention (durable decision/note, working thread summary, orphan-delete turn summary) and asserting provider construction is not attempted.
- 2026-09-06: `uv run python -m pytest -q tests/test_config.py::test_disabled_builtin_keeps_retention_policy_without_provider -n 0` — 1 passed.
- 2026-09-06: Updated only derived-behavior test config builders in `tests/test_canonical_key_text_anchored.py`, `tests/test_decision_supersession_rebuild.py`, `tests/test_thread_summary_accumulation.py`, and the local fixture in `tests/test_incremental_fact_extraction.py` with explicit `enabled=True`.
- 2026-09-06: `uv run python -m pytest -q tests/test_canonical_key_text_anchored.py tests/test_decision_supersession_rebuild.py tests/test_incremental_fact_extraction.py -n 0` — 47 passed.

- 2026-09-06: Scoped config implementation changed `app/config.py` and `tests/test_config.py` only. Built-in semantic packages and `SemanticPackageConfig` now default disabled; enabled is preserved through legacy, prompt/model-role, and ordinary env reconstruction; package `ENABLED` env override is explicit.
- 2026-09-06: `uv run python -m pytest -q tests/test_config.py -n 0` — 33 passed. `pytest` executable itself was unavailable/denied, so the equivalent module invocation was used. `apply_patch` failed with Windows process error 1327; deterministic fallback was used.


- 2026-09-06: Raw vector decoupling implemented in scoped core/semantic files: eligibility/text/schema/provider constants now live in core/indexing.py; semantic source helper remains compatible via re-export; VectorEmbedder persists eligible rows without plugin/provider/index and updates provider metadata after recovery; RebuildCoordinator inventories lexical entries in bounded pages and backfills missing raw vectors before counting. Focused checks: tests/test_source_item_embedding.py — 23 passed; tests/test_vector_self_healing.py tests/test_vector_startup.py — 21 passed, 15 skipped; targeted backfill/compatibility selection — 5 passed. Full rebuild coordinator module remains unverified because this environment lacks optional usearch (ImportError); apply_patch failed with Windows process error 1327, so deterministic replacements were used.

- 2026-09-06: Follow-up focused checks: tests/test_source_item_embedding.py — 24 passed; selected tests/test_rebuild_coordinator.py — 2 passed; combined requested selection — 7 passed. No production issue found in the reviewed vector diff.

- 2026-09-06: `uv run python -m pytest -q tests/test_decouple_session_history_e2e.py -n 0` — 2 passed. MCP protocol-tool assertions are conditional because `mcp` is not installed in this environment; the live `PalliumMcpClient` ASGI path is exercised.
- 2026-09-06: `apply_patch` hit the machine-local Windows process failure; subsequent edits used narrowly scoped deterministic replacements only in the new test module and Work Record.

- 2026-09-06: Tightened release gates after review: Gate A reasserts zero provider calls, derived memories, and package rows after MCP ingest; Gate B drains `process_next_source_item` then explicitly exhausts `process_next_thread_rebuild`, asserting rebuild provider prompts and at least one rebuild run. Serial module remains 2 passed.
- 2026-09-06: Added Gate C clean-restart E2E over one SQLite DB (enabled → disabled → re-enabled). Gates A/B pass; Gate C currently fails on a production lifecycle gap: re-enable processing creates a `thread_summary` linked to the raw-only middle source, despite zero package row/provider call during its disabled ingest.
- 2026-09-06: Added tests-only disabled-package cancellation coverage in tests/test_multi_package_processing.py. Parameterized pending, retryable-failed, processing, and expired package states; verified both thread/container scopes, claim/backoff clearing, completed package+memory preservation, and idempotent cancellation. Serial module: .venv\\Scripts\\python.exe -m pytest -q tests/test_multi_package_processing.py -n 0 — 26 passed.

- 2026-09-06: Scoped vector/storage files compile and diff-check cleanly. Full focused pytest execution is currently blocked by an unrelated concurrent syntax error in forbidden storage/sqlite_queue.py line 290 (IndentationError); prior focused vector tests passed before that concurrent edit. No uv.lock or cancellation/provider/E2E files were changed by this slice.

- 2026-09-06: Scoped optimization files/tests compile and diff-check cleanly. Focused pytest rerun is blocked by concurrent unrelated IndentationError in forbidden storage/sqlite_queue.py line 290 while importing app.main; no cancellation/provider/E2E/uv-lock files were changed by this slice.


- 2026-09-06: Strengthened `tests/test_decouple_session_history_e2e.py` only: Gate A now checks active cross-container privacy, persisted `forgotten_at` plus post-forget retrieval hiding, unconditional MCP tool execution with explicit `PALLIUM_BASE_URL`, and post-MCP zero provider/memory/package-row state. Gate B enables exactly `agent_conversation_memory`, configures an isolated deterministic embedding/vector index, exhausts worker-facing rebuilds, and requires public vector-labelled derived retrieval alongside raw hits.
- 2026-09-06: Serial verification `uv run python -m pytest -q tests/test_decouple_session_history_e2e.py -n 0` — 1 passed (Gate C), 2 failed by strict release checks: Gate A cannot import `mcp` for the mandatory tool (`ModuleNotFoundError`); Gate B logs optional `usearch` missing and fails the required vector retrieval-source assertion. No skips/workarounds were added; no production files or `uv.lock` were changed in this slice.

- 2026-09-06: Re-ran the strengthened release-gate module with the requested interpreter `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_decouple_session_history_e2e.py -n 0` — 3 passed, 1 existing pydantic incomplete-forward-reference warning. Mandatory MCP tool execution and Gate B deterministic vector retrieval both pass in the repository root environment. No test or production defect demonstrated; no Relay/hook/`uv.lock` edits.
- 2026-09-06: Optimization review rerun with `C:\Dev\rore\Pallium\.venv\Scripts\python.exe`: `tests/test_vector_self_healing.py tests/test_source_item_embedding.py -n 0` — 35 passed; `tests/test_vector_index.py tests/test_vector_index_lifecycle.py tests/test_vector_rebuild.py -n 0` — 40 passed; focused coordinator backfill selection — 3 passed. Scoped compileall and `git diff --check` passed. `tests/test_vector_startup.py -n 0` was stopped after hanging after 11 tests without a failure; no scoped regression observed. No production edits or commits made in this review.


- 2026-09-06: Added focused legacy queue/stale-claim coverage in `tests/test_multi_package_processing.py`: pending/failed/processing/expired untracked source rows cancel to terminal skipped on disable; completed legacy source+memory remain usable; canceled rows are not claimed or rebuilt after re-enable; stale legacy commit/fail reject mismatched worker/attempts without memory, index, metadata, or rebuild-scope effects. Strengthened stale package commit assertions for the same side-effect fence.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_multi_package_processing.py tests/test_async_worker.py -n 0` — 58 passed. No production, Relay, hook, or `uv.lock` changes.
- 2026-09-06: Follow-up fixed the identified startup fallback hang with one scoped list-result guard in core/rebuild_coordinator.py; the affected test passed and tests/test_vector_startup.py -n 0 completed — 25 passed, 1 skipped. Final combined focused vector/index/backfill selection — 75 passed, 28 deselected. Scoped compileall and git diff --check passed. No Relay/hooks/uv.lock edits or commits.


- 2026-09-06: Added two bounded independent-provider BEGIN IMMEDIATE race tests in `tests/test_queue_concurrent_claim.py`: package commit vs disable cancellation and thread rebuild commit/complete vs cancellation. Both synchronize starts without holding a writer lock; either legal winner yields terminal/coherent state, while cancellation-first rejects derived writes and commit-first preserves complete derived data.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_queue_concurrent_claim.py::test_two_provider_package_commit_vs_disable_is_coherent tests/test_queue_concurrent_claim.py::test_two_provider_thread_rebuild_commit_vs_disable_is_coherent -n 0` — 2 passed. No production, dependency, Relay, hook, or `uv.lock` changes.
- 2026-09-06: Updated only the seven requested canonical docs: README.md, docs/session-history.md, docs/derived-memory.md, docs/configuration.md, docs/context/state.md, docs/context/architecture.md, and docs/http-api.md. Documented package-independent raw history/default-off packages, explicit enabled=true plus provider/model for provider-backed packages, preservation of stored derived data on disable, source-only availability, and semantic_package_unavailable. Grep audit found no stale planned/provider-activation claims; git diff --check passed.


- 2026-09-06: Fixed two test-only regressions: `tests/test_search_history_tool.py` now supplies the required container context alongside public visibility for fail-closed source-only lookup; `tests/test_vnext_perf_count_gate.py` seeds its in-memory source-only expected count three below the current measurement, preserving regression detection after the intentional optimized-count change without rewriting the committed baseline.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_search_history_tool.py tests/test_vnext_perf_count_gate.py -n 0` — 6 passed, 1 existing pydantic incomplete-forward-reference warning.
- 2026-09-06: Extended tests/test_decouple_session_history_e2e.py only. Gate A now covers empty-query 422 validation, missing container/visibility fail-closed responses, invalid explicit package rejection without a raw row, duplicate source identity idempotence, and limit 0/50/51 boundaries. Gate C now covers a second disabled-to-enabled transition and proves disabled-period raw-only state plus newly enabled derivation. Root .venv run: tests/test_decouple_session_history_e2e.py -n 0 — 3 passed, 1 warning. No production, Relay/hook, docs, roadmap, or uv.lock edits.

- 2026-09-06: Corrected `evals/vnext_perf_harness.py` source-only measurements to send the required `container_ref` and `visibility`, regenerated `evals/vnext_perf_baseline.json` from the valid scoped corpus, and added a strict nonempty seeded-hit assertion before count comparison in `tests/test_vnext_perf_count_gate.py`. The harness test now reflects the existing batch-prefetch contract: candidate windows grow while source-only round-trips remain bounded; no production code, Relay/hooks, or `uv.lock` changes.
- 2026-09-06: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest -q tests/test_vnext_perf_count_gate.py tests/test_vnext_perf_harness.py -n 0` — 2 passed, 1 deselected, 1 warning; explicit slow run `-m slow tests/test_vnext_perf_harness.py -n 0` — 1 passed, 1 warning. `git diff --check` passed.

- 2026-09-06: Final focused release checks after the cancellation-boundary, transition, and performance-harness corrections: provider guards — 45 passed; async workers — 27 passed; package-free/derived-enabled lifecycle E2E — 3 passed; performance count gate — 2 passed; explicit slow performance E2E — 1 passed. The raw-only gate verifies zero provider calls, and the derived-enabled gate verifies generated memory through public retrieval.
## Result review

Fresh clean-context release architect /root/decouple_release_architect reviewed
the complete diff and approved it after three P2 corrections: startup telemetry now
reports only active packages and Gate A asserts the persisted empty list; the
configuration guide names the real default and explicitly enables demo mode; the
derived-memory and vNext design docs distinguish raw notes from optional title
derivation and mark the Session History core slice shipped. The reviewer found no
P0/P1 issue in package-free operation, CAS fencing, cancellation races, visibility,
vector recovery, or final model transport guards.

Final verification: full non-slow suite — 4,528 passed, 15 skipped, 2 expected
failures; explicit slow performance E2E — 1 passed; final startup/lifecycle focus —
11 passed; import-linter, compileall, and git diff --check passed. Redline and
agent-workflow checks have no blocking findings; the architecture checkpoint is
advisory until the PR receives its review label.