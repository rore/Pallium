<!-- agent-workflow:start -->
**Outcome:** Minimap can distinguish recent from dormant exact-work participants without treating durable association or a name as evidence of current work.

**Target:** Pallium.

**Scope:** api/schemas.py, core/relay.py, storage/sqlite_relay.py, tests/test_relay_work_ref_associations_e2e.py, docs/agent-relay.md, and this Work Record.

**Constraints:** Keep existing total/count request bounds and detail lifecycle semantics backward-compatible; one read-only aggregate per batch; no automatic cleanup, presence service, scheduler, ownership system, schema migration, or History backfill. Align the contract through the lead before implementation.

**Completion criteria:** Batch responses distinguish recent/dormant nonclosed endpoints consistently with detail, preserve total and origin deduplication, and handle lifecycle/cutoff/closed/detach/name reassignment transitions and validation/errors without partial or invented zeros. Explain registry versus History preservation and explicit cleanup limits. Independent reviews, focused/full tests, CI, and installed delivery pass.

**Requirement baseline:**
{"source":"relay-msg-5f47ac48cb9c4aad83f156d9058d57cb","outcome":"Minimap can distinguish recent from dormant exact-work participants without treating durable association or a name as evidence of current work.","scope":"api/schemas.py, core/relay.py, storage/sqlite_relay.py, tests/test_relay_work_ref_associations_e2e.py, docs/agent-relay.md, and this Work Record.","constraints":"Keep existing total/count request bounds and detail lifecycle semantics backward-compatible; one read-only aggregate per batch; no automatic cleanup, presence service, scheduler, ownership system, schema migration, or History backfill. Align the contract through the lead before implementation.","completion_criteria":"Batch responses distinguish recent/dormant nonclosed endpoints consistently with detail, preserve total and origin deduplication, and handle lifecycle/cutoff/closed/detach/name reassignment transitions and validation/errors without partial or invented zeros. Explain registry versus History preservation and explicit cleanup limits. Independent reviews, focused/full tests, CI, and installed delivery pass."}

**Behavior changes:** []

**Risk:** High

**Complexity:** Simple

**Reason:** Redline requires API, persistence, and architecture review for the additive public response and Relay query surfaces. High is the API/persistence contract floor; this is one bounded slice.

**Discovery:** Detail already classifies recent/dormant/closed with an inclusive 24-hour last-seen cutoff. Batch totals count distinct nonclosed endpoints and intentionally include dormant/unreachable endpoints. Explicit/structural origins deduplicate. Alias transfer changes routing only; close retains associations; detach removes explicit origin only and immutable captured History remains. Existing HTTP E2E coverage handles these lifecycle and History behaviors. No production edit yet.

**Material assumptions:** Preserve the existing 86400-second lifecycle window and total semantics; if the lead requests a different cutoff or automatic removal, return to planning rather than silently diverge. Canonical Minimap feature reference is pending and will not be guessed. Current History coverage is per-turn and bounded, not guaranteed by registry membership.

**Plan:** 1. Invoke /agent-workflow, evaluate whole-change applicability, create this Work Record and classify before code edits. 2. Propose the minimal additive contract to the lead and align it; obtain independent technical plan review and separate human plan approval before implementation. 3. Reuse the existing shared lifecycle window and single batched aggregate for recent/dormant counts, preserve totals and request validation, and add only needed response metadata. 4. Extend the existing HTTP E2E file for lifecycle/cutoff, deduplication, alias/detach/close, Unicode/bounds/errors, read-only and single-query behavior; update the existing Relay documentation. 5. Focused tests, whole-change test selection, required full suite, independent result review plus human result review, fresh governance checks, PR/CI/inline closure, installed sync and health. No unrelated runtime work.

**Verification plan:** Consistent count/detail lifecycle and cutoff transitions -> deterministic-clock HTTP E2E. Totals, deduplication, closed/detach/name reassignment and historical preservation -> existing and extended lifecycle HTTP E2E. Empty/max/over-max, malformed/Unicode/duplicate, storage failure and no partial zeros -> batch HTTP E2E. Efficient read-only aggregate -> SQL statement count and no-write/snapshot E2E assertions. Delivery -> selected full tests, independent/human reviews, CI, and installed health.

**Plan review:** Pending contract alignment and clean-context technical review.

**Approvals:** Pending separate human review of the aligned High-risk plan. Lead is the single approval requester; the forwarded broad task authorization is not claimed as review of the concrete contract.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Source and coordination

Pallium Relay offer relay-msg-5f47ac48cb9c4aad83f156d9058d57cb, delivery relay-delivery-71189c04ed5f42dab0b39ebf2aac91a3. Accepted via atomic hook-delivery reply. Lead session codex:01a0d7cf-2c64-7bb2-a87c-724dd1c405a2 in git:github.com/rore/minimap coordinates API alignment and canonical roadmap ownership. No Minimap pair supplied yet; no association attempted or invented.

## Implementation

2026-09-27: Reused the clean completed-task checkout; isolated branch feat/participant-lifecycle-counts starts from current origin/main. Whole-change intended-path applicability required a Work Record, with red API/persistence/architecture checkpoints. Discovery only; waiting for contract alignment and required plan reviews. Next action: send exact proposed contract and preservation/History limitations to the lead, then review it before edits.
