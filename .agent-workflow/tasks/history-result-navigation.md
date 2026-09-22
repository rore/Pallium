<!-- agent-workflow:start -->
**Outcome:**
An agent can inspect every retained high-count Session History result under the existing response budget without blind empty previews or losing lower-ranked candidates.

**Target:**
Pallium.

**Scope:**
Add stateless result-page continuation to both Session History MCP search tools in app/mcp/server.py; add focused and real MCP-to-HTTP tests; align docs/session-history.md and roadmap/features/fix-session-history-evidence-access.md for delivery slice 3.

**Constraints:**
Keep the 2,000-character search response cap, existing HTTP/core/storage/schema/dependencies, candidate membership and ordering, exact-work exactness, visibility/redaction/forgetting, response-local session labels, and historical-state warning unchanged. Do not alter ranking or candidate recovery. Retrieval alone must not update accessibility or ranking state. Finalize only the results delivered on each successful page. Never expose raw thread identity.

**Completion criteria:**
Each exposed hit has a recognizable preview or explicit stable expansion path; every retained candidate remains reachable in frozen order through bounded revision-checked pages; page telemetry matches delivered IDs; invalid and stale pages finalize nothing; existing History governance and semantics remain intact; required tests and workflow checks pass.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An agent can inspect every retained high-count Session History result under the existing response budget without blind empty previews or losing lower-ranked candidates.","scope":"Add stateless result-page continuation to both Session History MCP search tools in app/mcp/server.py; add focused and real MCP-to-HTTP tests; align docs/session-history.md and roadmap/features/fix-session-history-evidence-access.md for delivery slice 3.","constraints":"Keep the 2,000-character search response cap, existing HTTP/core/storage/schema/dependencies, candidate membership and ordering, exact-work exactness, visibility/redaction/forgetting, response-local session labels, and historical-state warning unchanged. Do not alter ranking or candidate recovery. Retrieval alone must not update accessibility or ranking state. Finalize only the results delivered on each successful page. Never expose raw thread identity.","completion_criteria":"Each exposed hit has a recognizable preview or explicit stable expansion path; every retained candidate remains reachable in frozen order through bounded revision-checked pages; page telemetry matches delivered IDs; invalid and stale pages finalize nothing; existing History governance and semantics remain intact; required tests and workflow checks pass."}

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies `app/mcp/server.py` as gray/watch with no boundary risk, which sets an Elevated floor. Engineering judgment raises this to High because optional continuation inputs and paging metadata change a caller-facing MCP contract. Moderate complexity covers shared compaction, two tools, delivery telemetry, lifecycle edges, and E2E proof.

**Discovery:**
`_compact_history` currently projects up to `limit` hits, then globally removes cues and shrinks excerpts to empty before dropping tail hits under the 2,000-character cap. Both broad and exact-work tools share it and finalize only its surviving IDs. Existing HTTP search already returns the bounded candidate window, so MCP-local stateless paging can preserve retrieval semantics. A live ten-hit History search on 2026-09-22 returned nine empty excerpts while expansion recovered the first source; the owning roadmap reports 16 blind expansions, useful evidence as low as ranks 9-10, and rejects merely lowering the limit. Existing Relay/source paging provides repository conventions. Redline found gray + `app/**` watch, no checkpoint or boundary violation; the MCP contract is not presently classified by policy.

**Material assumptions:**
- Revision-checked re-fetching can detect a changed bounded candidate window without retaining a server-side snapshot. The digest binds a versioned canonical request plus the complete ordered projected window. Disproof: an unchanged request/data set produces unstable membership or representation; action: stop and return to planning for a server-owned snapshot/token.
- A minimal navigation-only hit containing its source ID, explicit unavailable-preview marker, page lineage instructions, safety warning, available replacement guidance plus minimum historical status/replacement-status indicators, paging metadata, and placeholder lookup UUID fits the 2,000-character envelope. Optional update text/details may be removed. Disproof: the focused singleton boundary cannot fit; action: return a deterministic history_result_exceeds_response_budget at that offset without finalizing or skipping the candidate.
- The existing HTTP search returns the complete eligible candidate window up to the supported limit of 50 and deferred finalization accepts an ordered page subset. Disproof: the caller-surface E2E cannot recover all 50 or persisted delivery differs from the page; action: stop, expand scope, and reclassify before editing HTTP/core.

**Plan:**
1. Add red tests first for the observed ten-hit empty-preview failure, the supported 50-candidate boundary and rejected 51, and a real MCP-to-HTTP broad/exact journey that traverses at least three pages in order.
2. Give both tools strict limit 1-50 and strict result_offset inputs plus optional result_revision. Offset is a zero-based index in the eligible projected candidate window. Reject booleans, strings, fractions, negative offsets, malformed non-lowercase-hex revisions, and nonzero offsets without a revision. Validate any supplied revision at offset zero so a first-page retry detects change.
3. Compute a versioned SHA-256 digest over the canonical search mode, query, limit, effective container/thread/visibility, explicit actor filter, source/role/artifact filters, normalized work refs, request_source_item_id, and the complete ordered projected candidate representation. Exclude delivery-attempt and lookup IDs. This is revision-checked re-fetching, not a retained snapshot; any membership, order, request, or visible-representation change requires restart from offset zero.
4. Replace global multi-hit excerpt shrinking with deterministic paging. Greedily add complete 240-character preview hits while the full serialized envelope—including placeholder lookup UUID, safety warning, and paging metadata—fits. If the first candidate cannot fit, drop optional cues/work refs/role/occurred-at, trim existing update text/details, then binary-search its excerpt without making a non-empty preview empty. A genuinely empty/whitespace backend preview or a candidate that only fits navigation-only omits excerpt, sets preview_unavailable: true, and points to pallium_expand_source using that page's lookup_event_id. Navigation-only retains available replacement guidance and minimum historical status/replacement-status indicators while optional update text/details may be removed. If those mandatory safety fields prevent the minimal projection from fitting, return history_result_exceeds_response_budget without finalizing or skipping the candidate.
5. Expose effective_max_chars, result_offset, next_offset, has_more, total_count, and result_revision on non-empty and continuation pages. total_count counts source-ID-bearing candidates retained from the HTTP result within limit. Exact-end and over-end offsets normalize to total_count and return an empty terminal page with next_offset: null. Preserve the legacy initial no-candidate response and its 300-character cap because it has no continuation.
6. Finalize exactly the current page's ordered IDs. Every successful call—including empty terminal retries—mints a fresh lookup event; retry is content-stable but not audit-idempotent. Expansion of a hit uses the lookup ID from the page containing it. Validation/stale/fit errors detected before finalization record no delivered page; a finalization timeout remains uncertain and keeps the existing retryable: false check-status contract.
7. Keep broad/exact search, active-session grouping, replacement guidance, historical warning, visibility/redaction/forgetting, and accessibility/ranking state unchanged. Align user documentation and mark only delivery slice 3 complete. Stop if tests require ranking/candidate-selection changes or HTTP/core/storage/schema/dependency edits.

**Verification plan:**
- When the ten-hit reproducer is paged, every retained ID shall be reachable once in order and no compaction-created empty excerpt shall appear → focused presentation regression that fails on current main.
- When the supported maximum 50 candidates and rejected 51 are requested, 50 shall remain reachable across bounded pages and 51 shall fail validation without HTTP delivery → strict FastMCP boundary tests plus real MCP-to-HTTP paging E2E.
- When Unicode/escaped text, oversized optional role data, and genuine empty/whitespace excerpts are paged, each response shall fit 2,000 characters and each hit shall have a preview or explicit expansion path; navigation fallback with outdated/current-replacement metadata shall retain replacement guidance plus minimum status indicators, and an impossible singleton shall fail at its offset without finalizing or skipping → focused serialization and singleton-fit tests.
- When request-bound continuation changes query, limit, mode, any filter, request_source_item_id, candidate membership/order, or an equal-length visible representation, the old revision shall fail and finalize nothing; unchanged first/later-page retries shall be content-stable apart from fresh lookup lineage → focused tool tests and caller-surface E2E.
- When offset/revision boundaries are exercised, strict malformed/negative/missing/exact-end/over-end cases shall be deterministic; initial empty search shall retain the legacy 300-character contract and terminal retries shall mint empty delivery events → FastMCP validation and persisted audit assertions.
- When a later-page hit is expanded, its page lookup ID shall parent the expansion; successful page audits shall contain exactly that page's ordered IDs, while pre-finalization errors and backend-rejected finalization shall expose none and timeout shall retain uncertain-finalization guidance → real MCP-to-HTTP lifecycle E2E.
- When a previously nonempty candidate window changes—including becoming empty after forgetting—the supplied revision shall fail stale before empty/terminal handling and finalize nothing; upstream authorization errors shall retain fail-closed behavior, while an unchanged valid revision at or beyond the end may return an empty terminal page and finalize an empty delivery → three-page broad/exact lifecycle E2E with persisted state/audit reads.
- When existing History paths run, broad/exact scope, visibility, forgetting, replacement, grouping, warning, and expansion behavior shall remain unchanged → existing presentation, work-contract, MCP server/integration, and visibility/lifecycle suites.
- Before review, all required checks shall pass → focused nodes, affected History subsystem files, pytest --lf --lfnf=none -q -n 0, one full pytest tests/ -x -q, agent-workflow checker, redline report, and git diff --check.

**Plan review:**
Clean-context reviewer /root/result_navigation_plan_review rejected the initial hits-only revision and underspecified fit/lineage plan. The request-bound revision, deterministic singleton/navigation fallback, explicit cursor/empty/terminal semantics, fresh-per-page lookup lineage, and 50/51 caller-surface matrix above resolve its five blocking findings; final focused follow-up approval pending.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: api-review

What is changing: add optional result-page continuation inputs and explicit paging metadata to both Session History MCP search tools while keeping the 2,000-character response cap.

Why: high-count searches currently compact previews to empty strings and can hide lower-ranked retained candidates, forcing blind expansions and rewritten searches.

Affected contract / model / boundary: additive MCP tool input/result semantics in `app/mcp/server.py`; no HTTP, core, storage, schema, visibility, or dependency change is planned.

Compatibility / migration risk: medium — existing calls remain valid, but new callers may depend on revision, terminal-page, and per-page delivery semantics.

Verification plan: tests-first focused compaction boundaries, strict FastMCP validation, real MCP-to-HTTP broad/exact lifecycle journeys, exact delivery audit assertions, affected suites, full suite, workflow, and redline checks.

## Plan review

Clean-context reviewer /root/result_navigation_plan_review rejected the initial plan. It required the revision to bind the canonical request and every projected candidate; a deterministic fit policy for unbounded optional fields and genuinely empty previews; exact offset/revision/empty/terminal behavior; honest fresh lookup-event semantics on retries and terminal pages; and caller-surface coverage at the supported 50-candidate maximum plus rejected 51. The revised marker-block plan incorporates each requirement and keeps the implementation MCP-local.

## Implementation

Discovery, classification, and initial clean-context review complete. The first plan was rejected and returned to planning; all five blockers are now incorporated for follow-up review. No production or test files changed. The sandboxed patch helper later failed with the documented Windows CreateProcessWithLogonW 1327 condition, so this exact-file deterministic replacement was used.

## Evidence

Pending tests-first baseline.

## Result review

Pending.
