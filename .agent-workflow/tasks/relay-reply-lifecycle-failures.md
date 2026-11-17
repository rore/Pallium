# Explain and repair safe Relay reply-after-delivery failures

<!-- agent-workflow:start -->
**Outcome:** Agents can finish long-running work and reply once after verified Relay delivery, while stale or unowned copies remain refused and actual reply failures have evidence-supported dispositions.

**Target:** Relay delivery-to-reply lifecycle at observed source0fe69525e2ab3c037e694c100e0ad4f2b68f46b1; on-disk source does not prove a running host loaded that revision.

**Scope:** Trace and repair reusable delivery-to-reply custody failures across OpenCode model-bound hooks, registered MCP identity/scope resolution and generic Relay core/storage lifecycle, with caller-surface coverage and owning roadmap alignment.

**Constraints:** Preserve receipt, lease, recipient, scope, runtime identity, claim-token secrecy, payload custody and idempotence guards. Do not equate status-page reads with claimed/emitted custody, replay uncertain work, relax guards/timeouts, or change unrelated installations, settings, queues or data. Keep distinct incidents and existing owners separate.

**Completion criteria:** Each actual reply failure has a precise timeline, expected contract and evidence-supported stage/cause or named missing observation. A minimum reusable correction is covered through caller-visible delivery/ACK/reply/readback journeys, including long work, scope changes, unknown ACK/response loss, idempotence, stale copies, Unicode and later-message progress, without unsafe replay.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md; current task-owner request to investigate actual reply failures","outcome":"Agents can finish long-running work and reply once after verified Relay delivery, while stale or unowned copies remain refused and actual reply failures have evidence-supported dispositions.","scope":"Trace and repair reusable delivery-to-reply custody failures across OpenCode model-bound hooks, registered MCP identity/scope resolution and generic Relay core/storage lifecycle, with caller-surface coverage and owning roadmap alignment.","constraints":"Preserve receipt, lease, recipient, scope, runtime identity, claim-token secrecy, payload custody and idempotence guards. Do not equate status-page reads with claimed/emitted custody, replay uncertain work, relax guards/timeouts, or change unrelated installations, settings, queues or data. Keep distinct incidents and existing owners separate.","completion_criteria":"Each actual reply failure has a precise timeline, expected contract and evidence-supported stage/cause or named missing observation. A minimum reusable correction is covered through caller-visible delivery/ACK/reply/readback journeys, including long work, scope changes, unknown ACK/response loss, idempotence, stale copies, Unicode and later-message progress, without unsafe replay."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Elevated / Moderate remains unchanged. Common/V2 modules, package tests and integration README are GRAY; root tests and this record are BLUE. Receipt timing/cancellation requires independent result review. No core/API/storage/protected-contract edit is approved. The same architect approved the exact successor plan; generated boundary/Workflow/Redline evidence must now be produced using supported commands.

**Discovery:** Prior reply-lease diagnosis and Relay error/scope-transition records describe delivered historical corrections, not this new incident. The canonical umbrella retains a distinct receipt-required409 and later scoped404 observations; none has an established shared cause. The latest supported reply returned409 expired lease, and the parent later observed the original delivery still claimed. No present record assigns another worker this exact new custody-chain investigation.

**Material assumptions:** The reproduced precommit ACK gap is sufficient to plan the correction; historical first409 telemetry is not a gate. New ordinary POST responses contain newly acquired tokens, proven by eligible selection/fresh mutation; cached/restored authority cannot get a new issuance anchor. Exact monotonic formulas, timestamp forms, clock assumptions and server final authority are in the H1–H4 successor. Existing claim.acked means all RENDERED results succeeded, not all cached deliveries; maintenance must not redefine rendering. Historical loaded-revision/identity/ACK claims remain unknown.

**Plan:** Invoke the /agent-workflow skill to create the Work Record and classify risk, before any code edit. Done. Implement the approved H1–H4 successor: original NEW-claim monotonic timing, one original receipt disposition, context-owned rendering and session maintenance flight reserved before native await. Preserve initial500ms ACK, existing2.5-second interval, original lease and exact claim/token/attempt/scope/cancellation fences. Add runnable policy and two actual-interval caller E2Es in the seven listed paths, preserving all prior bodies/assertions and accepted evidence. Generate real governance evidence, run bounded focused/affected checks and one isolated full non-slow suite, then return once for same-architect independent result/adequacy review. No live changes, other agents, publication or rollout.

**Verification plan:** H1 runnable parser/lag/UTC/nullTTL/clock/full-slot/header-body cases; H2 sequential/overlapping dispositions and late callbacks; every H3 exact output/token row; H4 held ownership, independent poll/wake, retirement/recreation and fair three-entry selection. TWO additive real-hook/HTTP/storage/registered-MCP actual-interval no-next-prompt E2Es. Preserve prior bodies/assertions and accepted1+2 evidence. Exact focused/package invocations capped240 seconds including drain; normal actual RED→GREEN permitted, no unchanged-failure reruns. Recompute whole-change selector and run affected/governance checks plus ONE full non-slow invocation capped1200 seconds. Installed runtime bytes only, private child environment/homes/temp/DB/Git config, fake providers/vector disabled, owned loopback/processes and proved teardown. No live service19836, host, credentials, installs or OS-sandbox claim.

**Plan review:** Agent technical review: build/reply-lifecycle-20261117/architect-h1h4-plan-go.md. Same architect issued narrow PLAN / VERIFICATION-ADEQUACY GO for successor SHA256 c71960e78b2f413658c4fd6b079a29bf5015f43ae8f6401ba719b45859c2be67, closing H1–H4 at plan level. The full verdict and parent implementation release were read through their final pages. Initial HOLD and original packet remain preserved. Plan GO is not an implementation pass or result acceptance. Same architect's independent result/adequacy review is still required.

**Approvals:** User steering: "those failures are part of what we should investigate". Parent accepted diagnostics and1+2 controls, then released implementation and bounded validation of the reviewed successor in exactly seven paths. Supported governance reporting and a minimal local baseline/Work Record commit if needed are allowed after identity/privacy checks; no push. This is parent delegation, not a human quote. No other agents, live/protected changes, receive/ACK/replay, CI/PR/merge/rollout or worktree cleanup. Optional9f stays frozen/unrun. Stop only for concrete unsafe prerequisites, protected caller-contract change or scope expansion.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Ownership and continuity

## Implementation — released H1–H4

The parent released the approved successor on 2026-11-17. Implementation starts
from source `0fe69525e2ab3c037e694c100e0ad4f2b68f46b1` in the same branch.
Approved paths are the common/V2 modules, common/V2 tests, existing Python caller
test, integration README and this record, listed below. No implementation or
new check has run yet. Earlier planning-only limits below describe prior phases;
the current release supersedes them only within this exact scope.
Canonical roadmap state is parent-owned and already reflects the plan GO/release.

Implementation now covers the approved common header/outcome seam and V2 ordinary
cached receipts, with original monotonic bounds and context-owned rendering.
No V1/wake/core/API/storage/MCP/protected source changed. Runnable H1–H4 fixtures
and the two additive actual-interval caller nodes are authored. README states
limits and the retained omitted-sibling continuation behavior.

Actual initial RED failed on repeated-context duplicate ACK. Focused policy
checks passed10. The two new caller nodes passed2 in11.18s (outer14.61s), with
real public delivered/attempt1 and registered late reply. Boundary reporting
passed using the supported import-linter adapter. Initial runner admission lacked
an optional process package; no application ran then and nothing was installed.
The runner instead uses stdlib Windows Job accounting for owned-tree drain.

The first package invocation completed under240s:239 passed,5 failed,7 skipped;
all681 Job-owned processes drained. Preserve that outcome. Three old failures
showed non-Git temp fixtures inheriting the checkout's Git remote/author because
the private temp directory was inside the repository. The runner now places
private fixture homes/temp outside Git ancestry. One new pin test incorrectly
expected a retired cached lifetime to remain cached after the existing poll
detached it; that new subcase was removed, retaining real retirement/replacement
and scope guards. The old uncertain-terminal supersession timing failure remains
under investigation; its body/assertions are unchanged. No unchanged-failure
automatic retry or green package claim.

The corrected private-temp run passed the three Git-isolation failures and
the corrected new missing-authority/no-slot case. The old `newer-candidate`
supersession failure persists. An exact source0fe snapshot independently failed
the same unchanged old test/assertion, so it is baseline behavior on this runtime,
not evidence against receipt recovery. Its wake policy remains unchanged.
Final-source additive caller validation passed2 in9.78s, outer12.38s, with all42
Job-owned processes drained. No repeat of unchanged passing evidence is needed.

Current Redline is GRAY advisory, with no boundary/protected-contract changes.
Workflow now has real versioned evidence, but reports missing committed baseline
and its required technical-review marker. This record now carries the exact
review evidence reference. The parent-authorized minimal local record commit is
needed to establish baseline history; no product commit or push is released.
Focused governance passed53 and failed1 because its private PATH cannot locate
PowerShell. The full invocation has not started; validation remains incomplete.

Branch `fix/relay-reply-lifecycle-failures` starts at exact0fe. The existing
optional-budget checkout/candidate `9f206ece` is untouched. Its exact same-architect
source GO was accepted by the parent; tests remain unrun and execution frozen.
No installed integration was moved or replaced.
The canonical umbrella and roadmap edits remain parent-owned.

Before creating this record, inspected the canonical failure list and existing
`relay-reply-lease-diagnosis`, `relay-error-diagnosis`,
`codex-relay-hook-reply-scope` and saved receiptless-reply notes.
The lease diagnosis classified different MCP-receive attempts as genuinely late
and delivered an original-message-TTL check and guidance. The older error task
delivered transport/error reporting and endpoint-fenced scope transitions.
Do not reimplement either. The receipt-required409 and historical qualification
owners remain separate. Exact participation reads show the parent and older
participants; membership alone does not prove current ownership or availability.

## Evidence boundary

Latest expired-lease409 and earlier scoped404 are separate cases. Exact message,
delivery, session, container and tool receipts stay in ignored private evidence.
The source task must establish what was actually emitted to the model, what ACK
was attempted and returned, and which exact identity/scope the reply resolved.
A normal-looking native fallback pointer or successful status read does not
establish hook emission or ACK authority. Parent recovery of the native final
means the completed result was recovered; it does not repair the failed reply.

## Implementation and diagnostic result

Source-only investigation is complete at `0fe69525e2ab3c037e694c100e0ad4f2b68f46b1`.
Private `build/reply-lifecycle-20261117/report.md` and `evidence.json` retain
timelines, provenance limits, caller/source trace and a bounded isolated E2E
proposal. No product or test file was changed, imported, collected or run.

- Expired-lease409 is consistent with an expired claimed row. The source was
  later naturally reclaimed and ACKed on attempt2. That progress does not
  establish why the first claim lacked committed ACK.
- The retained earlier404 tool target differs from the intended source message's
  recorded, promptly ACKed delivery. The failed target still reads not-found.
  The generic error text does not prove a wrong-container cause.
- Parent subsequently reported the user's screenshot of a visible failed wake:
  `Pallium internal wake has no current Relay work`. At the inspected source,
  null, empty or mismatched context responses reach that safety rejection.
  No exact wake binding or context HTTP result accompanied the report.
  This is a real visible failure, not a successful wake or proof of no queue.

The three incidents and older receipt-required409 remain separate. No actual
incident supports a specific production correction yet. Preserve all guards.

## Blockers and next action

The initial diagnostic phase was accepted by the parent. The same source-only
task continued with its private native addendum; earlier report/evidence remain
unchanged. The delta is `build/reply-lifecycle-20261117/native-ordering-delta.md`.
Historical evidence limits remain below. They are not a reason to defer the
reproduced generic ACK handling fix: the parent accepted its failure class and
released concrete planning. The current implementation gate is the same
architect's plan/adequacy review and subsequent parent release, not historical
telemetry or another human approval.

1. First-claim model-bound context admission and ACK attempt/result correlated
   to its original input and claim generation.
2. The earlier404's submitted-target mismatch is now native-confirmed. Why the
   different target was selected or whether it existed remains unknown.
3. The screenshot wake is now native-bound. Its delivery was durably ACKed about
   65 seconds before the native wake input, followed by the matching error
   423 milliseconds later. Its exact context HTTP result and the earlier ACK's
   originating claim path remain unknown. This does not explain the first409.

Parent should first reuse existing native evidence. This worker has no native
session-message read tool and used no shell/HTTP substitute. The parent separately
permits necessary exact retained reads through the supported authenticated native
API command; none was needed for this delta. No broader scan or probe is released.

Source shows a concrete compatible journey: a reserved wake does not own an
ordinary turn's claim. Ordinary delivery/ACK does not set wake claim-attempt
custody or settle its activation. Poll retains a nonterminal reservation.
Delivered continuation requires matching wake-owned attempts; otherwise context
returns no delivery and the visible guard rejects it. The native record alone
does not select that branch over transport/binding failure or terminal/budget
rejection, and input creation time does not establish prompt-call start time.

The single reserved-wake → ordinary claim/ACK → delayed native context →
exact failed terminal → later backlog characterization has now passed and been
accepted. The paired ACK controls below also pass and distinguish precommit
refusal from committed response loss. They do not fill the historical branch
observation or demonstrate an avoidable cleanup/reconciliation defect.
Never turn delivery/ACK into terminal proof, grant unowned continuation or
silence genuine empty-wake rejection. Any such caller-behavior departure needs
exact task-owner requirement approval, not agent approval.

## Proposed minimum ACK fix — H1–H4 delta recheck

**Actual proposed paths:** common/V2 production modules
`integrations/opencode/.opencode/plugins/pallium-common.mjs`,
`integrations/opencode/.opencode/plugins/pallium-v2.mjs`;
package tests `integrations/opencode/tests/{common,v2-plugin}.test.mjs`;
caller E2E `tests/test_opencode_native_wake_e2e.py`; integration
`integrations/opencode/README.md`; this Work Record.
Integration paths are GRAY under current policy; root tests/record are BLUE.
No deterministic red-zone checkpoint is triggered by those intended paths.
Required Elevated clean-context plan/result reviews still apply; parent assigns
the same architect, including adequacy. No agent was spawned.

The immutable initial source/caller packet is
`build/reply-lifecycle-20261117/emitted-ack-fix-plan.md`, digest
`1e056adab39c395b3c8e4b57123f943feaa294e426ce8231f530b3a53ffb1573`.
Its actual checks file is `emitted-ack-fix-plan-checks.json`, not `checks.json`.
Current successor is `build/reply-lifecycle-20261117/emitted-ack-fix-plan-h1h4.md`;
separate `emitted-ack-fix-plan-h1h4-checks.json` pins its actual new digest.
Initial packet/checks and accepted1+2 passes are retained unchanged.

- **H1:** Capture original NEW ordinary request issuance `m0` and body-return
  `m1` on the cached claim, never on reentry/emission. Source proves fresh-token
  acquisition. With C rounded up, L/E down, immutable recovery deadline is
  `D=m0+min(L-C,E-C)`; explicit null TTL contributes infinity. Only due recovery
  with `now+500<D` can dispatch, rechecked after ownership and before send.
  Exact timestamp grammar/UTC-naive meaning, clock assumptions and server
  authority are in the successor. Header not-before merges by MAX and survives
  body failure; strict numeric grammar/date anchor are explicit. Nonempty invalid
  header latches recovery-disabled.
- **H2:** One original cached-claim receipt disposition binds claim/delivery/
  token/attempt: initial-flight → pending/confirmed/stopped. First emitted
  context awaits its ONE legacy500ms attempt. All repeated contexts return the
  observed disposition immediately: no join/sleep/fresh attempt, even when due.
  Confirmed/stopped tombstones remain until claim retirement. Header/final
  callbacks cannot reset bounds, revive stops or affect same-ID replacement.
- **H3:** Background NEVER changes `claim.acked`, response, budget or rendering.
  Keep current all-RENDERED-success context transition and existing formatters,
  including omitted-sibling continuation behavior. Context reads confirmed as
  synthetic success, pending/stopped as nonconfirmed, without repeat HTTP.
  A true legacy flag never suppresses an already registered pending receipt.
  Exact before/after envelope/token table covers partial AB, omitted B, changed
  budget, all confirmed and terminal B. No new exactly-once/replay policy.
- **H4:** Existing2.5-second interval reserves ONE session maintenance flight
  synchronously BEFORE selection/first native await. It covers circular fair
  selection → ownership → final guards → one ACK → identity-guarded finally,
  independently of busy poll/native wait. Cursor advances on selection: busy A
  cannot starve B/C. Held get across ticks creates one flight, not a burst.
  Retirement/disposal aborts/fences without awaiting an unabortable SDK get.
  Late completion cannot clear or mutate successor flight/receipt/cursor.

Shared transport stays one-shot with optional header/outcome observation.
V1 and V2 wake/admission/continuation defaults remain unchanged. Only verified
ordinary fresh-rendered emission registers a receipt: never an omitted packet
or token-free continuation. No new claim, model token, implicit ACK, reply
retry, deadline/lease extension, durable queue or new timer.

Two additive real-plugin/HTTP/registered-MCP journeys still require ACTUAL
interval callbacks during held long work and NO next prompt: transient busy
recovers before original expiry, or committed response loss confirms the same
receipt; public delivered/attempt1 permits late receiptless reply. Accepted
timer-disabled/obsolete-wake tests stay verbatim. Targeted H1–H4 fixtures and
source proof are in the successor; no runtime matrix/new host campaign.
No production/test edits or app execution occurred in this revision.

Limits remain explicit: one background request/session/tick adds bounded load,
not hook wait. Immediate pre-confirmation reply can still409. Host stalls,
outage, late emission, long Retry-After or expiry can prevent recovery; no
cross-restart/unconditional eventual guarantee. Same-architect delta review
and parent release are implementation gates; missing historical telemetry is NOT.

The canonical umbrella remains parent-owned and open. Parent accepted the
completed initial diagnosis and supplied the native evidence for this
continuation. Report the delta for owning-roadmap reconciliation without
marking the broader feature or repair complete.

## Evidence and recovery

### Current characterization release

The single characterization below is accepted and frozen. The paired ACK phase
is complete and accepted by the parent. The existing registered-tool binding
`tests/test_relay_mcp_tools.py::bind_asgi_post` accepts an async ASGI post
callback for the same app, so no new MCP transport or runtime identity machinery
is needed. The added test uses that exact binding, the current isolated storage
clock pattern and the accepted HTTP/owned-child shapes. The next genuine context
means a new native ordinary input, not an automatic retry of the completed task.
Before test edits, phase/risk/coverage-only obligation was updated here.

### Paired ACK-control result

Added only the `precommit` and `postcommit` parameters of
`test_emitted_ack_faults_preserve_registered_reply_and_progress` in the same
test file. Removing this new function and its decorator/separators restores the
previously executed module's exact byte hash, including mixed line endings.
The accepted characterization and every prior assertion are unchanged and were
not rerun. No production or protected-contract path changed.

One serial focused invocation selected exactly those two nodes: **2 passed,
0 failures/errors/skips**, pytest/JUnit 6.979 seconds, total invocation through
pytest teardown 9.778 seconds under the 240-second cap. Same installed runtime
hashes as the accepted earlier run; no retries or other application execution.

- Precommit: actual model mutation preceded the first owned ACK. The fixture
  returned structured503 `relay_busy` before calling the route; public state
  remained claimed/attempt1. Real registered MCP receiptless reply returned
  receipt-required409, then expired-lease409 after only the isolated storage
  clock advanced61 seconds. Public readback showed no saved deterministic reply.
  A genuinely new hook input reclaimed attempt2 with redelivery metadata and
  ACKed through production. The fixture skipped its already-completed stand-in
  action; a later independent message delivered on attempt1.
- Postcommit: actual emission preceded the real ACK route, which returned200
  and committed delivered/attempt1. The fixture dropped that HTTP response;
  the hook observed an actual transport error. Public delivered state still
  permitted one late registered receiptless Unicode reply after the same clock
  advance. A new hook did not reclaim/reemit the delivered anchor. Later
  independent delivery reached context and ACK on attempt1.

The registered tool uses production registration/scope forwarding and the
existing ASGI post binding to the same real app. This is not full MCP wire
transport or installed-host proof. No receipt or model runtime/session fields
were supplied to reply. Redelivery metadata supports the fixture's decision to
skip a completed action; it does not prove product-level exactly-once task work.

Both owned Node roots exited0/reaped, both plugin instances disposed, all14
owned Git children reached close, both HTTP listeners closed and server threads
joined. Pytest root exited0/reaped after client-fixture teardown; source bytes
matched before/after. Raw output, JUnit, fault-stage/HTTP/MCP/public observations,
runtime hashes and cleanup are in
`build/reply-lifecycle-20261117/ack-controls-once/`; summary is
`build/reply-lifecycle-20261117/ack-controls-result.md`.

This demonstrates the precommit custody gap's observable consequences, while
confirming correct reply refusal, genuine next-turn lease recovery and
postcommit late-reply behavior. It does not attribute the historical first409
or justify an implicit ACK, guard change or blanket retry. If further correction
is justified, the shared ACK outcome boundary after model mutation is the
relevant seam, not the storage receiptless-reply guard. No correction policy was
qualified or implemented. Claim-response loss and same-input context retries
remain separate, unreleased follow-ups. Parent reviews this result and owns the
next bounded step; no human approval loop was started.

The released characterization is complete and accepted. Implementation now
awaits the consolidated H1–H4 plan recheck and parent release, NOT historical
telemetry. Full-suite/governance obligations remain before PR. Existing bridge:
`test_assistant_ownership_retirement_through_http_and_history`
and capture retry HTTP bridge in the same file. Existing native gates:
V2 `callerFixture`; existing child-close ownership: `withGitProcess` in the
package tests. Reuse these local shapes without changing shared fixtures.
The phase/risk/behavior obligation was updated before the test edit.

### Characterization result

Added only
`tests/test_opencode_native_wake_e2e.py::test_ordinary_delivery_before_delayed_wake_preserves_custody_and_progress`.
All pre-existing test bodies/assertions are unchanged. No production or
protected-contract file changed.

One exact serial slow-marked invocation: **1 passed, 0 failures/errors/skips**,
pytest 4.73 seconds; total invocation including pytest teardown 11.10 seconds
under the 240-second cap. No retry, subsystem/full suite or second application
execution was performed.

The actual production V2 prompt/context hooks and runner crossed the isolated
real HTTP service. Public readback showed ordinary emitted/ACKed anchor at
attempt1 before native promotion. Delayed same-marker context returned HTTP200
with no deliveries/restoration and raised the original visible guard without
payload/extra claim/ACK. The production runner observed the fixture-native
failed terminal, committed its exact fenced terminal request, and the next poll
released the anchor. A new independent message then reached model context,
ACK and terminal on attempt1. Anchor state remained unchanged.

This PASSES current-behavior characterization. It does not reproduce a
reconciliation defect, prove the historical cause or qualify an installed host.
The native queue/promotion/idle boundary is controlled, not a released host.
No speculative production patch follows from this result.

Evidence: `build/reply-lifecycle-20261117/characterization-once/` contains exact
diff, raw output, JUnit, invocation/exit/duration, installed-runtime and source
hashes, caller/HTTP trace and teardown receipts. Tested source bytes matched
before/after the invocation. The owned Node root exited successfully and was
reaped; native jobs joined, all six Git children closed, plugin hooks disposed,
HTTP listener closed and server thread joined. Existing client-fixture cleanup
completed before the successful pytest process exit. No installed service,
provider credentials or nonfixture network was used.

Fresh whole-change selector now chooses **full**, because the test file changed.
The full suite is required before PR validation but is outside this bounded
release and was not run. Fresh Redline still stops on its missing required
import-linter artifact. Do not call the whole change green or PR-ready.

Earlier source-only static checks at the same source revision:

- Whole-change selector: `governance`; only this untracked Work Record is in
  the complete publishable change set. Its suggested governance pytest command
  was not run because the source-only release excludes tests and collection.
- Static JSON, baseline-to-current field equality, public-record privacy,
  exact changed-path allowlist and ignored private-evidence checks passed.
- Redline reporter could not emit a verdict: required
  `build/import-linter-report.json` is absent. The import-linter backend was
  not run and policy was not weakened to bypass it.
- Workflow checker returned blocking exit2. Record shape, fields, State,
  relationships and baseline presence passed. Missing Redline verdict and
  behavior-contract evidence block it. Baseline history verification also
  lacks both PR refs; the record remains uncommitted, not a verified PR head.
  These are unavailable governance evidence, not application test failures.

Full command outputs and selection are in the ignored evidence directory.
The continuation's `native-ordering-delta-checks.json` records fresh exact-path,
baseline/current-field, privacy, whitespace, timing and unchanged-old-report
checks. Existing blocked governance evidence is reused for the unchanged path,
policy and checker scope; it is not a fresh gate pass. No tests/imports ran.
The Work Record and characterization are uncommitted; no commit is authorized.
No push, CI, installation, restart, live queue/database mutation or worktree
cleanup was performed. Only the owned isolated test used and closed test state.
Retain this worktree for its uncommitted test/record and private evidence.
The optional-budget candidate `9f206ece` remains untouched and frozen.
The exact umbrella association is confirmed present and retained during parent
review of this result, alongside the optional-budget association. Neither is
evidence that either broader feature is complete.

One independent completed-investigation result is authorized to the current
manager name. Do not reply to expired incident copies. If denied, leave the
substantive result and artifact pointers in the native final without retry.
