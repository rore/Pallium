<!-- agent-workflow:start -->
**Outcome:**
Produce a bounded, reviewable design and validation plan for exact Relay-name history lookup across successor sessions.

**Target:**
Pallium Relay and Session History.

**Scope:**
Discovery and design only for `roadmap/features/add-persistent-role-history.md`; no product, test, or roadmap edits.

**Constraints:**
Preserve source-time attribution, existing access/redaction/deletion checks, exact name semantics, and current APIs until reviewed. No role registry, guessed historical backfill, scope expansion, runtime changes, installs, or dependencies.

**Completion criteria:**
When this task is handed off, the parent has the exact current/public surface, temporal capture boundaries, compatibility gaps, candidate files/schema only where justified, and focused E2E/real-acceptance plan for review before implementation.

**Requirement baseline:**
{"source":"parent assignment; roadmap/features/add-persistent-role-history.md; clarification c7bca648","outcome":"Produce a bounded, reviewable design and validation plan for exact Relay-name history lookup across successor sessions.","scope":"Discovery and design only for roadmap/features/add-persistent-role-history.md; no product, test, or roadmap edits.","constraints":"Preserve source-time attribution, existing access/redaction/deletion checks, exact name semantics, and current APIs until reviewed. No role registry, guessed historical backfill, scope expansion, runtime changes, installs, or dependencies.","completion_criteria":"When this task is handed off, the parent has the exact current/public surface, temporal capture boundaries, compatibility gaps, candidate files/schema only where justified, and focused E2E/real-acceptance plan for review before implementation."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Routine

**Complexity:** Moderate

**Reason:** The only changed path is the Work Record under the policy's blue `.agent-workflow/**` rule. The bounded design spans several existing Relay, history, API, and integration surfaces with material temporal and compatibility uncertainty.

**Discovery:**
At verified main `5d1679364d8404601b0be14216746d2b8fe2f286`, `pallium_relay_address` in `app/mcp/server.py` validates the integration's runtime/session against the current Relay endpoint and returns an optional `alias_selector`; a valid response without it means confirmed unnamed, while an error or invalid/missing identity is unavailable. `storage/sqlite_relay.py` already includes the current `alias` in the `relay_turn` session view and clears the former holder on takeover; it stores only current ownership, not binding history. Codex and Claude turn-start hooks call `relay_turn`, but their injected text omits the alias. Claude's `pre_compact` hook does not call Relay; Codex has no pre-compact hook. Hermes exposes both address and history tools through its plugin, with no promise of host-managed compaction refresh.

History is `pallium_search_history` (`app/mcp/server.py`) → `POST /query` (`api/routes.py`, `api/schemas.py`) → `PalliumService.query` and the `source_only` retrieval path. It already has exact source-thread filtering, visibility checks, source-item forgetting checks, and lookup/expansion provenance. `SourceItemRecord` / `SourceItem` have `container_ref`, `thread_ref`, role and actor fields but no Relay name. Codex/Claude hooks capture user source items at prompt submission and assistant source items at stop; both currently omit Relay name. An assistant item may be ingested after takeover, so reading the current owner at stop would misattribute the source turn. The existing dedupe key is `(source_type, source_id)`, so retries return the original item rather than relabeling it.

Material design constraint: source-time name must travel with the turn context captured before delayed assistant ingestion. Adding a history filter alone is insufficient. Old rows and new captures whose identity is unavailable must remain distinguishable from confirmed-unnamed captures; exact-name results must surface incomplete coverage when eligible rows have unknown/unavailable attribution. Keep all search under the caller's current container and visibility scope; a global Relay address is not history authorization. No code or tests were changed.

**Material assumptions:**
The named roadmap item and clarification c7bca648 remain the current approved scope; if they conflict with current main, stop and report the discrepancy before proceeding.

**Plan:**
Return the candidate public contract and focused validation plan to the parent. Before any implementation, coordinate the turn-context snapshot with the existing Codex source-lifetime owner; `api/routes.py` is also shared with the Hermes parity close-guard owner if the history filter is added. Existing `core/relay.py` / `storage/sqlite_relay.py` behavior appears sufficient for name discovery and takeover; do not change those to invent an alias registry. Stop pending parent and astra-reviewer contract review.

**Verification plan:**
The handoff names existing and proposed caller-facing surfaces, what can be attributed at source time, old-record behavior, security boundaries, and observable E2E cases including named/unnamed/unavailable recovery, external takeover, old-holder resume, delayed ingestion, and both compaction timings. No application tests are run for this read-only discovery handoff.

**Plan review:** self-review for this bounded discovery assignment; parent and astra-reviewer contract review required before any implementation.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Blocked -->
**State:** Blocked — discovery handoff awaits parent and astra-reviewer contract review before implementation.
<!-- agent-workflow:end -->

## Implementation
- Created the Work Record before discovery; branch `feat/role-history`, based on verified `origin/main` / remote `main` commit `5d1679364d8404601b0be14216746d2b8fe2f286`.
- Completed focused read-only discovery; no product, test, or roadmap files changed.

## Evidence
- No Pallium work association was attached because the exact injected container/thread identity needed by Minimap's association procedure is unavailable in this assignment context.
