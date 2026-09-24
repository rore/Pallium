<!-- agent-workflow:start -->
**Outcome:** Minimap can read attached-session counts for an entire roadmap scope in bounded pages without one Pallium request per card.

**Target:** Pallium Relay.

**Scope:** Add a read-only exact-scope count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.

**Constraints:** Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no cross-scope leakage, no false completeness, and no new dependencies.

**Completion criteria:** An exact roadmap-scope read returns each nonclosed associated session once per local reference, excludes other scopes and closed sessions, and pages with explicit completion; invalid requests fail; Minimap can distinguish complete empty from incomplete/error; focused and full tests plus review pass.

**Requirement baseline:**
{"source":"Minimap show-board-work-presence item and architect Relay assignment 2026-09-24","outcome":"Minimap can read attached-session counts for an entire roadmap scope in bounded pages without one Pallium request per card.","scope":"Add a read-only exact-scope count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.","constraints":"Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no cross-scope leakage, no false completeness, and no new dependencies.","completion_criteria":"An exact roadmap-scope read returns each nonclosed associated session once per local reference, excludes other scopes and closed sessions, and pages with explicit completion; invalid requests fail; Minimap can distinguish complete empty from incomplete/error; focused and full tests plus review pass."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline marks HTTP route/schema and SQLite index migration red with API/persistence checkpoints; several layers and the Minimap consumer contract are involved.

**Discovery:** Existing `GET /relay/work-refs/participants` requires exactly one work reference and pages sessions, so board use would fan out per card. Associations are keyed by exact scope/local pair and can have both explicit and structural origins. Closed sessions are excluded by default. The existing index leads with hashed work_ref, not scope_ref. Minimap `show-board-work-presence` requests attached-session counts, not participant detail. Redline found no inherent import-boundary violation.

**Material assumptions:** Counts-only suffices for board cards; Minimap owner confirmation would validate this, and a request for full participant rows would return the plan to review. Grouped local_ref pagination can be consumed under Minimap's existing bounded deadline; if not, revisit the contract before implementation.

**Plan:** Pending consumer confirmation. Tentative: add a GET exact-scope count endpoint with bounded ordered pages and explicit has_more/next_offset; validate scope with existing work-reference rules; query grouped distinct endpoint IDs, excluding closed sessions; add `(scope_ref, local_ref, endpoint_id)` index; preserve exact-item endpoint; add HTTP E2E for lifecycle, duplicate origins, multiple refs/scopes, Unicode, bounds and paging; document count semantics and Minimap error/completeness handling. Target `api/routes.py`, `api/schemas.py`, `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, `tests/test_relay_work_ref_associations_e2e.py`, `docs/agent-relay.md`, and one roadmap item. Stop if consumer contract or validation assumptions fail.

**Verification plan:** When associations span origins and sessions, scope counts are distinct and exact -> HTTP E2E. When a session closes or detaches, counts update while another scope remains separate -> HTTP E2E. When results exceed a page, continuation yields the full set and explicit completion -> HTTP E2E. When input is invalid or Unicode, validation and identity remain correct -> HTTP E2E. Existing item-detail contract remains unchanged -> existing association E2E. Run focused subsystem, workflow check, and full pytest before PR.

**Plan review:** Pending clean-context review after Minimap confirms contract.

**Approvals:** Pending task-specific human approval after reviewed plan.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Isolated branch `feat/board-work-presence` in a Codex-managed worktree at base `8155891eb877c1d3e9d31ff95ded8b1748eb7a97`. No product code edited. Waiting on Minimap contract confirmation, then clean-context plan review and human approval.

## Evidence

Minimap source item: `C:/Dev/rore/minimap/roadmap/features/show-board-work-presence.md`. Authoritative item-ref CLI returned `scope_ref=roadmap:v1:git:github.com/rore/minimap#roadmap`, `local_ref=item:v1:show-board-work-presence`. Relay association attempt failed 409 `association_limit` (three pre-existing explicit refs); no unrelated ref was detached. Redline pre-edit verdict: High risk / Moderate complexity, API and persistence checkpoints, no inherent boundary violation.
