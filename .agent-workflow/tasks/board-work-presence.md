<!-- agent-workflow:start -->
**Outcome:** Minimap can read attached-session counts for an entire roadmap scope in bounded pages without one Pallium request per card.

**Target:** Pallium Relay.

**Scope:** Add a read-only exact-scope count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.

**Constraints:** Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no cross-scope leakage, no false completeness, and no new dependencies.

**Completion criteria:** An exact roadmap-scope read returns each nonclosed associated session once per local reference, excludes other scopes and closed sessions, and caps output with explicit completeness; invalid requests fail; Minimap can distinguish complete empty from incomplete/error; focused and full tests plus review pass.

**Requirement baseline:**
{"source":"Minimap show-board-work-presence item and architect Relay assignment 2026-09-24","outcome":"Minimap can read attached-session counts for an entire roadmap scope in bounded pages without one Pallium request per card.","scope":"Add a read-only exact-scope count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.","constraints":"Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no cross-scope leakage, no false completeness, and no new dependencies.","completion_criteria":"An exact roadmap-scope read returns each nonclosed associated session once per local reference, excludes other scopes and closed sessions, and pages with explicit completion; invalid requests fail; Minimap can distinguish complete empty from incomplete/error; focused and full tests plus review pass."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline marks HTTP route/schema and SQLite index migration red with API/persistence checkpoints; several layers and the Minimap consumer contract are involved.

**Discovery:** Existing `GET /relay/work-refs/participants` requires exactly one work reference and pages sessions, so board use would fan out per card. Associations are keyed by exact scope/local pair and can have both explicit and structural origins. Closed sessions are excluded by default. The existing index leads with hashed work_ref, not scope_ref. Minimap `show-board-work-presence` requests attached-session counts, not participant detail. Redline found no inherent import-boundary violation.

**Material assumptions:** Counts-only suffices for board cards; Minimap owner confirmation would validate this, and a request for full participant rows would return the plan to review. One capped read fits the current board; if `has_more=true`, Minimap must not infer zero for omitted items. Consumer and architect confirmation are pending.

**Plan:** Pending consumer/architect confirmation. Add read-only `GET /relay/work-refs/participant-counts?scope_ref=<exact>&limit=200` (default/max 200), response `contract=relay-work-ref-counts/v1`, canonical scope, ordered `counts: [{local_ref, participant_count}]`, and `has_more`. One grouped, indexed SQL statement fetches `limit+1` local references; count distinct endpoint IDs across association origins and containers, excluding only closed sessions. A valid unmatched scope is complete empty; invalid scope is 422; unsupported storage and transport remain errors. Preserve exact-item detail API. Add `(scope_ref, local_ref, endpoint_id)` index via Relay migration. HTTP E2E covers lifecycle, duplicate origins, cross-container/scope isolation, Unicode, validation, cap/completeness, and read-only behavior; migration tests cover reopen/repeat/shared/separate DB and EXPLAIN query plan. Document count semantics and Minimap's unknown-on-truncation/error handling. Target `api/routes.py`, `api/schemas.py`, `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, `tests/test_relay_work_ref_associations_e2e.py`, related SQLite migration test, `docs/agent-relay.md`, and one roadmap item. Stop if consumer contract or validation assumptions fail.

**Verification plan:** When associations span origins and sessions, scope counts are distinct and exact -> HTTP E2E. When a session closes, reopens, or detaches, counts update while another scope remains separate -> HTTP E2E. When results exceed the cap, `has_more=true` and omitted refs remain unknown; at/below cap, `has_more=false` -> HTTP E2E. When input is invalid or Unicode, validation and identity remain correct -> HTTP E2E. Existing item-detail contract remains unchanged -> existing association E2E. New index is used and migrates repeatably in shared/separate DB modes -> SQLite migration test and EXPLAIN. Run focused subsystem, workflow check, and full pytest before PR.

**Plan review:** Clean-context review by `/root/board_presence_plan_review` on 2026-09-24; see section below. Revised plan awaits owner confirmation and human approval.

**Approvals:** Pending task-specific human approval after reviewed plan.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Isolated branch `feat/board-work-presence` in a Codex-managed worktree at base `8155891eb877c1d3e9d31ff95ded8b1748eb7a97`. No product code edited. Waiting on Minimap/architect contract confirmation and human approval.

## Evidence

Minimap source item: `C:/Dev/rore/minimap/roadmap/features/show-board-work-presence.md`. Authoritative item-ref CLI returned `scope_ref=roadmap:v1:git:github.com/rore/minimap#roadmap`, `local_ref=item:v1:show-board-work-presence`. Relay association attempt failed 409 `association_limit` (three pre-existing explicit refs); no unrelated ref was detached. Redline pre-edit verdict: High risk / Moderate complexity, API and persistence checkpoints, no inherent boundary violation.

## Plan review

Independent reviewer confirmed counts-only matches Minimap's board requirement but rejected offset pagination: a detach between pages can skip a remaining local reference and create false zero. The accepted correction is one capped grouped read with has_more as an explicit completeness signal; truncation means missing refs are unknown. Reviewer required concrete wire/error semantics, exact scope and population E2E, and migration/index-plan verification. Those points are incorporated in the Plan and Verification plan above. No product edit may begin until consumer and human approval.
