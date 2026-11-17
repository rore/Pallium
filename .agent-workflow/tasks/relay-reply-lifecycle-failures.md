# Explain and repair safe Relay reply-after-delivery failures

<!-- agent-workflow:start -->
**Outcome:** Agents can finish long-running work and reply once after verified Relay delivery, while stale or unowned copies remain refused and actual reply failures have evidence-supported dispositions.

**Target:** Relay delivery-to-reply lifecycle at source0fe69525e2ab3c037e694c100e0ad4f2b68f46b1. This contribution is limited to OpenCode V2 ordinary-turn emitted-receipt recovery.

**Scope:** Trace and repair reusable delivery-to-reply custody failures across OpenCode model-bound hooks, registered MCP identity/scope resolution and generic Relay core/storage lifecycle, with caller-surface coverage and owning roadmap alignment.

**Constraints:** Preserve receipt, lease, recipient, scope, runtime identity, claim-token secrecy, payload custody and idempotence guards. Do not equate status-page reads with claimed/emitted custody, replay uncertain work, relax guards/timeouts, or change unrelated installations, settings, queues or data. Keep distinct incidents and existing owners separate.

**Completion criteria:** Each actual reply failure has a precise timeline, expected contract and evidence-supported stage/cause or named missing observation. A minimum reusable correction is covered through caller-visible delivery/ACK/reply/readback journeys, including long work, scope changes, unknown ACK/response loss, idempotence, stale copies, Unicode and later-message progress, without unsafe replay.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md; current task-owner request to investigate actual reply failures","outcome":"Agents can finish long-running work and reply once after verified Relay delivery, while stale or unowned copies remain refused and actual reply failures have evidence-supported dispositions.","scope":"Trace and repair reusable delivery-to-reply custody failures across OpenCode model-bound hooks, registered MCP identity/scope resolution and generic Relay core/storage lifecycle, with caller-surface coverage and owning roadmap alignment.","constraints":"Preserve receipt, lease, recipient, scope, runtime identity, claim-token secrecy, payload custody and idempotence guards. Do not equate status-page reads with claimed/emitted custody, replay uncertain work, relax guards/timeouts, or change unrelated installations, settings, queues or data. Keep distinct incidents and existing owners separate.","completion_criteria":"Each actual reply failure has a precise timeline, expected contract and evidence-supported stage/cause or named missing observation. A minimum reusable correction is covered through caller-visible delivery/ACK/reply/readback journeys, including long work, scope changes, unknown ACK/response loss, idempotence, stale copies, Unicode and later-message progress, without unsafe replay."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Common/V2 modules, package tests and integration README are GRAY; root tests and this record are BLUE. Receipt timing and cancellation need independent review. No V1/wake/core/API/storage/MCP/protected-contract policy change is part of this contribution.

**Discovery:** Caller characterization reproduced model-bound emission followed by an uncommitted ACK. A committed ACK with response loss had a different outcome. This establishes a reusable custody gap, not a shared cause for distinct historical409/404 or obsolete-wake reports.

**Material assumptions:** A new ordinary POST acquires fresh claim authority; cached/restored responses do not get a new age anchor. Original monotonic request timing bounds recovery. Server authority checks remain final under clock/suspend anomalies. Existing claim.acked means all rendered results succeeded, not all cached deliveries. Maintenance must not redefine rendering.

**Plan:** Invoke the /agent-workflow skill to create the Work Record and classify risk, before any code edit. Done. Implement the reviewed original-age, single-disposition, context-owned-rendering and pre-await-flight policy in the seven approved paths. Preserve initial500ms ACK, existing2.5-second lifecycle, original token/attempt/scope/lease and cancellation guards. Add caller coverage without weakening old assertions. Reuse the completed independent source review. Publish one draft PR for ordinary existing CI; do not merge or start another local full campaign.

**Verification plan:** Original timing and bounded recovery → common/V2 parser, body/header, full-slot, context-concurrency and lifecycle tests. Rendering/token authority → exact partial-batch/budget cases. Caller-visible recovery and reply → two actual-interval production-hook/HTTP/storage/registered-MCP E2Es. Compatibility → existing V1/wake/default-helper and affected HTTP/MCP/parity controls. Whole change → selector FULL, supported boundary/Redline/Workflow checks and required ordinary PR CI. Failed/capped local outcomes remain disclosed; no full/package green claim or required-gate waiver.

**Plan review:** Agent technical review: SHA2567abd3a84e0d5cd14d218496034ee9da6297145817615b4a86a8d59b19996ef02, independent architect plan-review evidence retained by the task owner. Reviewed plan SHA256c71960e78b2f413658c4fd6b079a29bf5015f43ae8f6401ba719b45859c2be67 received narrow plan/verification-adequacy GO on2026-11-17. Result review is recorded below.

**Approvals:** The task owner authorized investigation. The coordinator released the reviewed seven-path implementation and bounded validation. After preserving the incomplete local full outcomes, the coordinator separately authorized a normal nonforce branch push and ONE DRAFT PR for existing automatic CI. This is delegated publication authority, not merge or release acceptance. No manual dispatch, new workflow, live operation, source correction, new agent or cleanup is authorized.

**State:** Blocked
<!-- agent-workflow:end -->

## Contribution

Branch: `fix/relay-reply-lifecycle-failures`.
Source base: `0fe69525e2ab3c037e694c100e0ad4f2b68f46b1`.
The requirement baseline was committed separately at `5775e426`.
The canonical item remains `roadmap/features/add-wake-first-relay-delivery.md`;
its designated owner retains broader roadmap and acceptance decisions.

Approved paths:

- `integrations/opencode/.opencode/plugins/pallium-common.mjs`
- `integrations/opencode/.opencode/plugins/pallium-v2.mjs`
- `integrations/opencode/tests/common.test.mjs`
- `integrations/opencode/tests/v2-plugin.test.mjs`
- `tests/test_opencode_native_wake_e2e.py`
- `integrations/opencode/README.md`
- this Work Record

The shared helper only adds optional header/outcome observation.
V2 ordinary turns retain one disposition per originally emitted receipt.
Repeated contexts do not restart or join ACK attempts.
The existing interval can confirm due receipts without another prompt.
It reserves the whole maintenance flight before native ownership awaits and
rotates eligible receipts fairly.

The original request issuance/body-return anchors are cached once.
Strict UTC/offset/naive-UTC timestamp parsing and conservative rounding preserve
the original lease/TTL bound. Retry-After only tightens the not-before time;
invalid nonempty hints stop recovery. A full500ms slot must fit strictly before
the original deadline after ownership is rechecked.

Background work never changes model text, response contents or claim.acked.
The existing all-rendered-success continuation rule remains, including the
omitted-sibling quirk. Continuation does not grant an omitted sibling ACK
authority. An already emitted pending sibling remains maintenance-eligible.
No claim, payload, native input or completed action is replayed by maintenance.

## Plan review

Agent technical review: SHA2567abd3a84e0d5cd14d218496034ee9da6297145817615b4a86a8d59b19996ef02

Independent review closed the four plan findings: original-age/Retry-After
math, sequential and overlapping dispositions, rendering versus confirmation,
and synchronous whole-flight reservation. No protected requirement change was
approved.

## Result review

Agent technical review: SHA256b4db3adb16c5b2f3d0a753e45d70df48dec249398941013b0979d2120f2ae9b3

Reviewed revision: source0fe69525 plus common SHA2565c8e21dc98c521496c656de62152911cf86f06b2d4c1f5ba35acf9cbc609757d and V2 SHA256e32fd1017a75b53934e0e46e7926d8cb2c43019869577573de059f253ad05ba7; reviewed implementation diff SHA256c28e5cfdb80ffa448cde97b7bb0596cbd581c79d39d932ee01554e6190c13dff.

Verification adequacy: SOURCE GO and bounded changed-feature ADEQUACY GO; overall validation/release HOLD.

The same independent architect reviewed the complete implementation, H1–H4
caller cases, both actual-interval E2Es and retained failure evidence.
No blocking production defect or source correction was identified in this slice.
The six reviewed product/test/README paths stay frozen during publication.
Review evidence is retained by the task owner; these attestations do not replace
required CI or authenticate repository authority.

The E2Es use controlled native SDK boundaries and registered MCP through ASGI.
They are not installed-host or full MCP-wire qualification.
Server-time advancement establishes the caller contract, not actual61-second
host scheduling. Do not advertise every failure mode as real-wire E2E coverage.

## Validation evidence and unresolved outcomes

| Check | Actual outcome |
|---|---|
| Existing diagnostic controls | One characterization and two ACK controls passed; old bodies/assertions retained. |
| Final-source recovery E2Es | Two passed in9.78s. Actual existing interval, production hooks, real HTTP/storage and registered MCP; no next prompt. |
| Policy/lifecycle cases | Focused timing, headers/body timeouts, concurrency, exact rendering/token inventory, ownership, fairness and retirement checks passed. |
| Node package | Original run:239 passed,5 failed,7 skipped. Correction passes resolve three fixture Git-ancestry faults and a faulty new pin subcase. One unchanged old wake failure remains; this is not a clean package run. |
| Affected HTTP/MCP/parity |495 passed,2 runner path-length failures. The exact two nodes passed after a short-path correction. Preserve both outcomes. |
| Focused governance |53 passed,1 runner PATH prerequisite failure. The exact failed node passed after the child-only PATH correction. |
| Import boundaries / governance | Supported import-linter reported no violations; Redline GRAY advisory; Workflow passed with State Blocked. Fresh publication checks remain required. |
| Initial full non-slow attempt | Collection stopped because declared pyte0.8.2 was absent. No runnable full-suite result. |
| Authorized replacement full | Child-only locked wheel resolved the prerequisite without a shared install. The run was capped at1185.358s including drain, near44% quiet progress. No completed summary/JUnit, final pass count or known active node. All owned processes drained. |

The two recovery journeys distinguish transient precommit503 from committed
response loss. Both confirm the original token on attempt1 during held work,
leave model context unchanged and permit one Unicode receiptless reply beyond
the original lease. Later independent messages also progress.
The actual RED before the fix reproduced a repeated-context duplicate ACK.
All earlier failures and available source/runtime receipts remain preserved;
missing earlier per-invocation diff snapshots were not backfilled.

### Open baseline wake finding

`fresh supersession consumes uncertain terminal without stale follow-up` in
`integrations/opencode/tests/v2-plugin.test.mjs` retains the
`newer-candidate` actual1/expected2 failure. The same unchanged assertion also
fails against exact source0fe.

Independent review found that it exercises newer-prompt/terminal reconciliation,
not emitted-receipt maintenance. Keep it OPEN as a separately scoped wake-progress
finding. This is not a proven root cause, absence of every interaction, weakened
requirement or waiver of any failing REQUIRED check. No wake repair is included.

## Draft publication and next gate

The coordinator reviewed the capped result and authorized changing validation
venue, not coverage or acceptance. Publish one DRAFT PR on the same branch to
current main. Let the existing PR workflow select FULL and run its ordinary
Linux3.12/3.13, Windows-smoke and governance checks. Collect exact-head results
once for at most30 minutes; retain first failures and report pending checks.
Do not manually dispatch, rerun until green, add jobs, merge or deploy.

State remains Blocked until actual required checks and owner disposition permit
advancement. Keep the PR draft while those gates are open.
An unchanged local baseline failure cannot waive a failing required CI check.

Fast pre-confirmation replies may still409. Sustained outage, expiry, host stalls,
clock anomalies and cross-restart recovery remain limits.
Historical409/404/obsolete-wake cause closure and the separate optional-budget
candidate are not part of this contribution.
No live installation, service, provider, queue or data change is authorized.
