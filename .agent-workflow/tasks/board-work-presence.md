<!-- agent-workflow:start -->
**Outcome:** Minimap can read attached-session counts for up to 200 exact visible roadmap item references in one request, without per-card calls.

**Target:** Pallium Relay.

**Scope:** Add a read-only exact-pair batch count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.

**Constraints:** Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no unrelated association disclosure, no partial success or false zero on failure, and no new dependencies.

**Completion criteria:** A request of 1..200 unique exact pairs returns exactly one ordered count per pair, including zero, counting nonclosed sessions once across origins; other references are never returned; invalid/oversized requests fail; transport/storage errors remain errors; focused and full tests plus review pass; a representative indexed query plan and repeated endpoint/query timing evidence meet the stated interactive target or the measured miss is reported and addressed.

**Requirement baseline:**
{"source":"Minimap show-board-work-presence item and architect Relay assignment 2026-09-24","outcome":"Minimap can read attached-session counts for an entire roadmap scope in bounded pages without one Pallium request per card.","scope":"Add a read-only exact-scope count projection through Relay HTTP, core, and SQLite; focused E2E coverage, contract docs, and roadmap alignment.","constraints":"Preserve exact work-reference semantics and existing item-detail API. No inferred ownership or activity, no writes from the read, no cross-scope leakage, no false completeness, and no new dependencies.","completion_criteria":"An exact roadmap-scope read returns each nonclosed associated session once per local reference, excludes other scopes and closed sessions, and pages with explicit completion; invalid requests fail; Minimap can distinguish complete empty from incomplete/error; focused and full tests plus review pass; a representative indexed query plan and repeated endpoint/query timing evidence meet the stated interactive target or the measured miss is reported and addressed."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline marks HTTP route/schema red with an API checkpoint; core and storage are gray/watch. High because the API contract changes; Moderate because several layers and the Minimap consumer are involved. No persistence schema change is planned.

**Discovery:** Existing `GET /relay/work-refs/participants` requires one exact work reference and pages sessions. The existing `(work_ref, endpoint_id)` index supports bounded exact-key batch lookup. A session can have both explicit and structural association rows, so counts must deduplicate endpoints. Minimap requested exact visible refs, not scope discovery; successful batch reads can be complete without pagination, while over-limit requests fail rather than truncate.

**Material assumptions:** Minimap confirmed read-only POST and a 200-pair cap; its current board has 157 item files and will mark any unqueried cards unknown if it grows beyond 200. Architect confirmation that complete-or-error exact batch satisfies the original pagination/completeness intent remains pending.

**Plan:** Minimap confirmed the exact-batch contract; architect confirmation and human approval remain pending. Add read-only `POST /relay/work-refs/participant-counts` with JSON `references:[{scope_ref,local_ref}]` (1..200, unique after canonical NFC validation). Respond `contract=relay-work-ref-counts/v1`, `counts:[{scope_ref,local_ref,participant_count}]` in request order, exactly one per pair including zero; never include session details or unrelated refs. One SQL query filters requested hashed work_ref keys using existing `(work_ref,endpoint_id)` index, joins sessions, excludes only closed state, and counts distinct endpoint IDs across explicit/structural origins and containers. Invalid/duplicate/oversized input yields 422; unavailable storage or transport remains an error, never empty success. Preserve per-item GET detail. Target `api/routes.py`, `api/schemas.py`, `core/relay.py`, `storage/sqlite_relay.py`, `tests/test_relay_work_ref_associations_e2e.py`, `docs/agent-relay.md`, and one roadmap item; no schema migration or new dependency. Before measuring, target local-loopback 200-key median under 100 ms and p95 under 250 ms on an installed-like Windows host. Verify EXPLAIN and repeated query/endpoint timings on realistic same-scope, unrelated-scope, multi-origin, and near/over-cap data; report dataset, environment, median, and tail without a flaky CI timing gate. Check concurrent attach/detach reads and avoid any read-side writes. Stop if consumer contract changes or query plan reveals a full association scan.

**Verification plan:** When 1..200 exact pairs are requested, HTTP returns one ordered count per pair (including zero), no unrelated refs or session details -> HTTP E2E. When origins overlap, sessions share refs, containers differ, or scopes reuse a local ref, counts remain distinct and exact -> HTTP E2E. When a session closes/reopens or an origin detaches, counts reflect current nonclosed associations -> HTTP E2E. Invalid, duplicate, empty, over-cap, secret/control, and Unicode identities obey validation -> HTTP E2E. Storage failure remains an error and reads do not mutate association state -> HTTP E2E. Existing item-detail contract remains unchanged -> existing association E2E. Query uses existing index at 1 and 200 requested keys without whole-registry scan -> EXPLAIN on representative data. Repeated local-loopback endpoint and SQL timings meet the predeclared target or drive an indexed correction -> measured median/p95 report, not CI wall-clock assertion. Concurrent attach/detach reads are coherent and read-side writes absent -> focused E2E/read-only audit. Run focused subsystem, workflow check, and full pytest before PR.

**Plan review:** Clean-context exact-batch review by `/root/exact_batch_plan_review` on 2026-09-24 approved the technical plan with no blocking findings; see section below. Consumer/architect confirmation and human approval remain pending.

**Approvals:** Pending task-specific human approval after reviewed plan.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Isolated branch `feat/board-work-presence` in a Codex-managed worktree at base `8155891eb877c1d3e9d31ff95ded8b1748eb7a97`. No product code edited. Exact-batch technical review passed. Waiting on architect contract confirmation and human approval; Minimap confirmed POST/max 200 through app fallback after its Relay wake omitted required scope.

## Evidence

Minimap source item: `C:/Dev/rore/minimap/roadmap/features/show-board-work-presence.md`. Authoritative item-ref CLI returned `scope_ref=roadmap:v1:git:github.com/rore/minimap#roadmap`, `local_ref=item:v1:show-board-work-presence`. Relay association attempt failed 409 `association_limit` (three pre-existing explicit refs); no unrelated ref was detached. Redline pre-edit verdict: High risk / Moderate complexity, API checkpoint, no inherent boundary violation; no schema migration in the revised plan.

## Plan review

Independent reviewer confirmed counts-only matches Minimap's board requirement but rejected offset pagination: a detach between pages can skip a remaining local reference and create false zero. The accepted correction is one capped grouped read with has_more as an explicit completeness signal; truncation means missing refs are unknown. Reviewer required concrete wire/error semantics, exact scope and population E2E, and migration/index-plan verification. Those points are incorporated in the Plan and Verification plan above. No product edit may begin until consumer and human approval.

## Requirement revision

Minimap's Relay message relay-msg-26f926171512481880b75e090dbb569a clarified that the board needs a batch over only exact visible item references, not a scope-wide association inventory. This narrows disclosure and reuses the existing work-ref index. The previous scope-wide plan and its review are superseded; owner confirmation and new review are pending.

## Exact-batch plan review

The independent Astra reviewer approved the bounded read-only POST over exact pairs. It confirmed canonical NFC duplicate rejection, service-global distinct nonclosed endpoint counts, zero-fill only after one successful query, and reuse of the existing work-ref index. Verification must include EXPLAIN for one and 200 requested keys amid unrelated associations, 200/201 boundary, NFC-equivalent duplicates, case-sensitive identities, dormant/unreachable sessions, dual-origin detach, close/reopen, unsupported storage, and database errors. No migration or additional boundary is needed. The review does not replace Minimap/architect confirmation or human approval.
## Performance acceptance

Architect relayed the user's explicit requirement in `relay-msg-89dcf9351492439a959e7b21ae63791c`. The exact-key filter must happen in SQL before aggregation; LIMIT or a bounded response alone does not prove bounded query work. Use the existing work-ref index if the measured plan supports it; justify an index only if evidence requires one. Test one and 200 keys, near/over-cap groups, realistic same-scope cardinality, many unrelated scopes, duplicate origins, and concurrent attach/detach. Record endpoint and SQL medians/p95 on repeated runs with dataset/environment and a predeclared local-loopback target; do not add a benchmark framework or wall-clock CI assertion.
## Consumer contract confirmation

Minimap developer confirmed through Codex app fallback that read-only POST with at most 200 unique exact pairs, request-order complete counts, and no `complete:true` field meets the board need. Minimap will validate exactly one count per requested pair and show unknown on missing/malformed entries or for unqueried cards beyond 200. It reports 157 current roadmap item files. The app fallback was necessary because its wake lacked required Relay scope; the Relay response was preserved and not resent.