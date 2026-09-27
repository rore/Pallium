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

**Material assumptions:** Preserve the existing 86400-second lifecycle window and total semantics; if the lead requests a different cutoff or automatic removal, return to planning rather than silently diverge. Canonical Minimap reference is now supplied by authoritative lead-forwarded CLI output; optional own-session attachment is unavailable at the existing explicit-reference capacity and is not an implementation prerequisite. Current History coverage is per-turn and bounded, not guaranteed by registry membership.

**Plan:** 1. Invoke /agent-workflow, evaluate whole-change applicability, create this Work Record and classify before code edits. 2. Propose the minimal additive contract to the lead and align it; obtain independent technical plan review and separate human plan approval before implementation. 3. Reuse the existing shared lifecycle window and single batched aggregate for recent/dormant counts, preserve totals and request validation, and add only needed response metadata. 4. Extend the existing HTTP E2E file for lifecycle/cutoff, deduplication, alias/detach/close, Unicode/bounds/errors, read-only and single-query behavior; update the existing Relay documentation. 5. Focused tests, whole-change test selection, required full suite, independent result review plus human result review, fresh governance checks, PR/CI/inline closure, installed sync and health. No unrelated runtime work.

**Verification plan:**
When the frozen response clock crosses the cutoff, detail and batch shall agree for active and unreachable endpoints just before, exactly at, and just after the boundary; totals equal recent plus dormant and zero results retain metadata -> deterministic-clock HTTP E2E, including read-only aging, closed exclusion, and dormant-to-recent turn refresh.
When explicit/structural origins overlap, sessions detach/close/reopen, or names are reassigned, exact endpoint counts and captured History shall preserve the stated lifecycle and identity contract -> existing and extended HTTP lifecycle E2E with History readback through name reassignment.
When input is empty/max/over-max, malformed, Unicode, canonically duplicate, or storage fails, the request shall preserve existing normalization/bounds and complete-or-error semantics -> batch HTTP E2E.
When reading 1 or 200 keys with unrelated same-scope and unrelated-scope rows, the batch shall use one indexed aggregate and change no state -> SQL statement/EXPLAIN checks plus no-write/snapshot E2E; measure local loopback latency against the shipped median under 100 ms / p95 under 250 ms 200-key target, report conditions without an unmeasured speedup claim.
When delivering the slice, required verification shall pass -> selected full tests, independent/human reviews, CI, and installed health.

**Plan review:** Agent technical review: /root/participant_plan_review, 2026-09-27, clean revision 44b029218200f901a6f2719c458df958fdef7a48; approach sound with explicit clock, boundary/refresh, History reassignment, and indexed-query verification refinements now recorded. Lead aligned the exact unchanged additive contract in relay-reply-6414464a12be5356a5c7223bdb682bf0bca2fd969412480261b567a4347f77fc. Separate human plan approval received directly from Rotem on 2026-09-27; source and exact consent recorded in Approvals.

**Approvals:** Approved by user 2026-09-27: "if you need my approval , you have it". Rotem Hermon, source item d449065c-e203-417e-af1d-a60f31d80b33 in thread 01a08755-3cf7-7691-94c7-643c67e3f3ca. Consent directly follows the recorded gate for this reviewed concrete plan; forwarded immediately to the lead. Human result review remains required after verified implementation.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Source and coordination

Pallium Relay offer relay-msg-5f47ac48cb9c4aad83f156d9058d57cb, delivery relay-delivery-71189c04ed5f42dab0b39ebf2aac91a3. Accepted via atomic hook-delivery reply. Lead session codex:01a0d7cf-2c64-7bb2-a87c-724dd1c405a2 in git:github.com/rore/minimap coordinates API alignment and canonical roadmap ownership. Canonical pair is recorded below; optional attachment was skipped at capacity, with no eviction.

## Implementation

2026-09-27 bounded implementation: fresh pre-edit workflow check returned clean, exit 0. Added recent/dormant row counts and one UTC as_of/recent_seconds per batch or detail response; the existing service-owned inclusive window is passed to storage, including detail instead of its former local literal. The filtered indexed aggregate reads total and conditional distinct recent endpoints in one SQL statement; dormant is the nonclosed remainder. Existing bounds, normalization, ordering, zero rows, origin deduplication and complete-or-error semantics remain. No schema migration, service operation, or unrelated code change.

Focused HTTP E2E verification: tests/test_relay_work_ref_associations_e2e.py, final implementation rerun 19 passed (6.98 s), including new active/unreachable before/equal/after cutoff cases, a one-clock-call assertion for both surfaces, read-only aging and turn refresh, zero/detail metadata, close/reopen, actual History readback through alias reassignment, and 1/200-key single-read EXPLAIN checks with same-scope/unrelated-scope noise. Scoped docs clarify nonclosed totals, recent-not-working semantics, clock limits, and registry versus captured History/cleanup. Implementation handoff remains Ready to implement until the parent completes whole-change selection, required full suite, measured latency, independent and human result review, governance/PR/CI and installed delivery. No unmeasured performance improvement claim.

2026-09-27 approval transition: direct human consent clears the remaining pre-edit gate; forwarded to the lead as relay-msg-fcae62dad8f245c6bf1ca8549efca66d (saved, receipt not inferred). Existing alignment and independent technical review remain valid. Exact implementation targets are api/schemas.py (response fields), core/relay.py (one response clock and shared window), storage/sqlite_relay.py (indexed conditional aggregate and detail window), tests/test_relay_work_ref_associations_e2e.py (HTTP contract and preservation checks), docs/agent-relay.md (contract/limits), and this record. No unrelated cleanup. Next: fresh workflow validation, bounded implementation, verification and independent result review.

2026-09-27: Reused the clean completed-task checkout; isolated branch feat/participant-lifecycle-counts starts from current origin/main. Whole-change intended-path applicability required a Work Record, with red API/persistence/architecture checkpoints. Discovery only; waiting for contract alignment and required plan reviews. Next action: send exact proposed contract and preservation/History limitations to the lead, then review it before edits.

Contract proposal sent through Relay as relay-msg-f97e91bac7814fcc8338f7b6f60819ee to the freshly revalidated @minimap-manager role. Saved/pending is not receipt or agreement. Proposed additive fields: per row recent_participant_count and dormant_participant_count, existing participant_count unchanged and equal to their sum; top-level as_of UTC and recent_seconds=86400 on batch and detail. Closed excluded from counts; unreachable included by last-seen age; equality at cutoff is recent. Counts use one aggregate with distinct endpoint conditional counts; detail/counts receive the same existing service-owned cutoff and per-response clock. Preserve all-or-error 1–200 unique-reference semantics, order, canonical normalization and zero rows; subset/refresh/completed-item presentation belongs to Minimap. No runtime edits before alignment/reviews.

Historical participation gaps reported before proposing larger History work: no retroactive tagging/backfill, per-turn association lookup can fail, bounded five-reference capture can omit registry references, and registry membership proves neither History coverage nor access. Existing tests prove alias reassignment preserves the old exact-session association, close/reopen retains registry rows/associations, and explicit detach changes future snapshots but not captured History; the plan adds History readback through reassignment itself. Operator association cleanup may target closed endpoints but still removes only explicit origin; structural removal needs its producer refresh. Separate source-forget is explicitly authorized, soft and auditable: retrieval/expansion excludes the marked raw turn while row/index entries persist; point-in-time container/thread scope affects no future ingests. Hard deletion belongs to separate TTL retention. Neither is an inactivity or nameless-session cleanup mechanism. No cleanup operation was performed.

## Plan review

Agent technical review: /root/participant_plan_review, clean revision 44b029218200f901a6f2719c458df958fdef7a48. High/Simple is appropriate. The additive contract and conditional distinct counts are sound after the verification refinements above. Capture one UTC as_of per response and pass it plus RELAY_RECENT_SECONDS to storage for both detail and counts; as_of is the classification time, not a distributed or cross-request database snapshot. Between-refresh clock/registry changes are expected and must remain visible honestly. Existing completed roadmap/features/add-relay-batch-participant-counts.md supplies the preserved indexed-query and latency obligations, not the new extension's status. Correct the existing docs' misleading "every active participant" wording to nonclosed within scoped documentation. No code edits or test runs occurred during plan review.

Lead Relay follow-up relay-reply-a4494f6d119f89af7c7faeee631e843638400402f96d46399b6e79fc33ffd4c5 confirms no new cutoff or independent Minimap timestamp classification, no working-now claim and no snapshot machinery. Review refinements and precise cleanup limits returned as relay-reply-563fae6275484e06191e92e447b781927e9de6c6a13283e86b2f9e47147a6bd1. Next action: receive field alignment and exact human-plan approval through the lead, then validate Ready-to-implement before any production edit.

## Canonical work reference

Authoritative CLI output forwarded in relay-msg-07b8de7f617d41019fd02420231d202e:
- scope_ref: roadmap:v1:git:github.com/rore/minimap#roadmap
- local_ref: item:v1:distinguish-recent-dormant-participants
- work_ref: work:v1:7e384e1e66782b48c1a7622d977c8b5b0f25f4cddd29201d7fa63d7ddcfcd935

Owner-managed canonical file: C:\Dev\rore\minimap\roadmap\features\distinguish-recent-dormant-participants.md, Minimap-dev sole writer. No roadmap edit here. Own successful Relay work-ref list on 2026-09-27 showed three existing explicit references and this pair absent. Capacity prevents attachment; skipped without mutation or eviction. Therefore this task claims no successful own-session association, participant evidence, or automatic History capture for the canonical pair. The exact key is known and preserved, not reconstructed. Capacity limitation reported to the lead; it does not block implementation. No production code edited.

## Aligned contract and remaining gate

Lead alignment relay-reply-6414464a12be5356a5c7223bdb682bf0bca2fd969412480261b567a4347f77fc confirms the exact proposed fields, unchanged v1 total, shared inclusive 86400-second cutoff, as_of/recent_seconds metadata and detail semantics. No Minimap mutation endpoint or larger History subsystem. No material scope or approach change; valid technical review is reused.

Only remaining pre-edit gate is separate human consent to the presented High-risk plan, not a second scope authorization or a capacity issue. Exact source: .agents/skills/agent-workflow/templates/checkpoints/plan-and-review.md, High row: "Clean-context agent technical review plus separate human plan review and approval. Stop until both are complete; record human approval verbatim in Approvals." Same file allows ordinary consent to the presented plan with no magic words and preserves unchanged approval. The forwarded broad task authorization precedes this concrete plan and expressly requires applicable approvals; it is not claimed as separate human plan review. The lead remains sole requester: forward an existing exact consent/reference covering this plan, or request one consent to the already-reviewed additive plan. No production edit while pending. Recovery revision before this update: 165ea495387e76a721e49f511d84c2609f6c6d15.
