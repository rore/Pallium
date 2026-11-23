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

**Plan:** Invoke the /agent-workflow skill to create the Work Record and classify risk, before any code edit. Done; retain Elevated/Moderate. The exact combined source, interaction and focused adequacy review is accepted. Correct only verification mapping metadata and reuse the unchanged nine E2E and 51 caller passes. Preflight the previously qualified normal private runtime for this checkout, then run one contained fail-fast non-slow attempt. Publish a normal two-parent merge commit to the existing draft only if that attempt completes, static checks do not block, no failure connects to the combined change and both remote heads remain exact. Parent owns final acceptance and merge.

**Verification plan:** Parent body and guard preservation -> exact six-file parent-union and function/decorator identity proofs. Caller recovery and rejection -> reuse nine focused E2Es and 51 direct common/V2 cases, each already below 240 seconds including drain. Current checkout runtime identity -> normal and Hermes-equivalent scrubbed imports using the previously qualified private interpreter and dependency hashes, without PYTHONPATH or PYTHONHOME. Whole-change governance -> current-main seven-path selector, Redline and Workflow checks. Required non-slow validation -> one selector-command fail-fast attempt capped at 3600 seconds including drain, with explicit failure and source/runtime receipts. Conditional published candidate -> exact two parents, preserved reviewed blobs, unchanged remote heads, personal attribution, privacy checks and one ordinary hosted CI event. Every failed or incomplete outcome remains evidence; no unchanged retry or fixture-plan implementation.

**Plan review:** Agent technical review: SHA2567abd3a84e0d5cd14d218496034ee9da6297145817615b4a86a8d59b19996ef02, independent architect plan-review evidence retained by the task owner. Reviewed plan SHA256c71960e78b2f413658c4fd6b079a29bf5015f43ae8f6401ba719b45859c2be67 received narrow plan/verification-adequacy GO on2026-11-17. Result review is recorded below.

**Approvals:** The coordinator accepts the actual independent combined source/interaction/focused-adequacy GO and releases only this record correction, runtime preflight and one contained non-slow attempt. After a completed attempt and clean static checks, a normal merge commit with exactly original PR head 57a384a1 and main 56ea7a44 as parents, normal fast-forward push to existing draft PR416 and one ordinary CI event are authorized only if no connected failure exists and both remote heads still match. A changed-path full failure or blocking governance stops publication. At publication, verify personal attribution, exact source/blobs and public privacy; observe useful application CI once at intervals of at least 60 seconds for at most 1800 seconds, then read hosted governance. No amend/rebase/force push, manual CI retry/dispatch, fixture-plan implementation, dependency/runtime campaign, product/test/docs correction, live service/host/queue operation, settings change, new agent or cleanup. Parent retains final acceptance/merge.

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

## Current-main reconciliation — 2026-11-23

Resume source/public PR head: `57a384a1769adda70f3ad41d77db190787e71a18`.
Fetched main: `56ea7a44ea62b6f3c31d081e607f9235112f386d`, which contains merged
PR417. The public PR remains draft and conflicting before reconciliation.
The original requirement baseline and prior review/evidence are unchanged.
Both old CI attempts remain failed; the four-file prerequisite plan is deferred.
Its complete private evidence, including both required reservation witnesses,
is retained without implementation or another unchanged-head CI attempt.

The reconciliation checkpoint remained Blocked pending combined-delta review
and later required validation. It produced no commit or push.
The canonical wake-first item's owner retains broader acceptance.

### Reconciled source and focused evidence

The no-commit merge produced one conflicted file: the native-wake E2E module.
Both parents insert independent blocks at the same base location. Resolution
keeps the complete original 711-line ACK insertion followed by the complete
375-line context-recovery insertion. No scenario or harness was interleaved.
Every parent Python function, decorator and assertion is preserved exactly.
The common helper, V2 source, both Node test files, README and Python E2E file
match the exact union of the two parent deltas. Automatic merges were checked,
not merely accepted because Git reported no conflict.

Relative to current main, only the original seven ACK paths differ. The
context-recovery enrollment/current-owner/final-attachment fences and the ACK
receipt timing/rendered-custody/flight fences remain unchanged. The two recovery
mechanisms remain distinct. There is no authored behavior change beyond the
already reviewed ACK contribution now combined with current main.
Main's CI pin, governance test, both PR417 records, lock and policies are intact.

Focused private checks on that union:

- Nine caller E2E cases passed: two actual-interval ACK recovery cases, six
  same-input context-recovery cases and the preserved obsolete-wake control.
  Pytest took 44.58 seconds; outer invocation took 57.498 seconds.
- Direct common/V2 selection passed all 51 cases: 11 ACK caller cases,
  38 context-recovery caller cases and two common transport checks.
  Outer invocation took 10.603 seconds.
- The first Node invocation used incorrect checkout-relative file paths and
  stopped before loading tests. Its exit 1 and 2.483-second receipt remain.
  Only the invocation paths were corrected; no source or assertion changed.

All focused invocations were below 240 seconds including drain, with zero
owned survivors and unchanged source hashes. Detailed evidence and exact parent/
diff/function identity proofs remain private. Collection corrections changed
neither an application test result nor a reviewed body.

The historical four-file CI prerequisite plan remains deferred and unchanged,
including the required designated empty/reserve branch and the single forced
prepared/reconcile variant. Existing failed/capped CI and local outcomes remain
failed or incomplete. These focused passes do not waive required full validation,
close historical causes or qualify the installed host.

### Governance and next disposition

The fresh whole-change selector reports FULL. Because HEAD is still the original
public PR head during this no-commit merge, its conservative local path union
contains 11 paths, including the already-merged PR417 files. The actual candidate
diff against exact current main contains only the original seven ACK paths.
Redline and Workflow used that complete seven-path diff, not a selected subset.
No full run was started.

Initial reconciliation Redline returned advisory exit 1: GRAY, no checkpoints or boundary violations,
and no API, schema, security, runtime-configuration or protected-contract change.
Workflow returned advisory exit 1 with zero blocking failed predicates. Its sole
failed advisory is the verification-plan mapping syntax; no label or approval
was fabricated. These are local governance results, not new required CI.

No unresolved Git conflict remained at that checkpoint. HEAD and public PR were
still the original `57a384a1`, with exact main `56ea7a44` as the pending parent.
No merge commit had been created. Detailed evidence remains retained.

That checkpoint requested narrow review of the additive conflict resolution and
combined recovery interaction, reusing the existing ACK and context-recovery
source reviews. The accepted review and validation continuation follow below.
There is no current evidence that the deferred four-file CI prerequisite plan
is needed on this combined candidate. It must not be implemented for disconnected
historic failures or used to waive a live red gate. Broader roadmap acceptance
remains with the canonical item's owner.

## Accepted combined review and validation release — 2026-11-23

The same independent architect accepted combined SOURCE / INTERACTION /
FOCUSED ADEQUACY with no blocking source finding. Review checked all six actual
LF hashes, shared transport argument positions, ordinary-versus-wake ACK paths,
enrollment and final-attachment fences, joint retirement, independent timer
flights and intact E2E splice boundaries. Prior body reviews and the existing
nine E2E / 51 caller results are reused, not rerun. Its sole nonblocking record
finding is corrected in the mapped Verification plan above.

Full validation and release acceptance are not supplied by that technical GO.
This release permits one preflighted normal-private-runtime non-slow attempt,
with a 3600-second total cap including owned-job drain. If safe preflight blocks,
report the gap without replacing the runtime or starting a dependency campaign.
Publication remains conditional as recorded in Approvals. Historic failures and
the four-file prerequisite plan, including both required reservation witnesses,
remain intact and deferred. No new application, test or README edit is allowed.

### Completed local validation and conditional draft update

The runtime preflight passed for this checkout in both normal and
Hermes-equivalent scrubbed nested imports, without import-path environment
overrides. Existing runtime and dependency artifacts match their qualification.
No shared installation or configuration was changed.

The single full non-slow fail-fast invocation completed successfully:
**9,249 passed, 48 skipped and two xfailed** in 727.08 seconds pytest,
731.473 seconds including drain, zero owned survivors. All 1,950 tracked-file
hashes remained unchanged during the attempt. The six reviewed product/test/
README files still match the accepted exact parent union. Both SDK1 Hermes
cases passed; absent SDK2 cases remain skips, not qualified passes.

Fresh mapped Workflow checks pass with no failed predicates. Redline remains
GRAY/advisory with no triggered checkpoints or boundary violations. The selector
remains FULL. The completed full result discharges this local attempt only.
It does not rewrite earlier failed or incomplete outcomes, explain their
physical causes, or replace required current-head hosted CI.

The draft update is a normal merge of original PR head
`57a384a1769adda70f3ad41d77db190787e71a18` and main
`56ea7a44ea62b6f3c31d081e607f9235112f386d`. All reviewed source and assertions
are preserved. The existing CI pin and records from merged PR417 are unchanged.
Only the original seven ACK paths differ from current main.
The draft remains Blocked pending actual hosted validation and owner acceptance.
No merge to main, installation or live rollout is included.

Draft PR: [#416](https://github.com/rore/Pallium/pull/416).

### Historical hosted results retained

Both attempts of [the original CI run](https://github.com/rore/Pallium/actions/runs/44142852990)
remain failed at original head `57a384a1`.
Attempt 1: Linux 3.12 had 4,223 passes and one failure at initial disposal
readiness; Linux 3.13 had 3,456 passes and one initial registration `503`.
Windows smoke and original governance passed.
Attempt 2: Linux 3.13 completed 9,190 passes, 106 skips and two xfails.
Linux 3.12 stopped with 1,674 passes, two failures, 27 skips and one xfail:
changed-registration denial and legacy identity-read setup.
The aggregate remained failed. Reused Windows/selector results were not new runs.

Those failures remain separate from the passing current local full report.
Their physical causes are not established by later passing cases. The deferred
four-test-file plan is not implemented, and no third unchanged-head attempt,
assertion weakening, fixture repair or policy waiver was used.
