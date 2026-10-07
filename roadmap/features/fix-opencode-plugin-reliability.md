---
id: fix-opencode-plugin-reliability
title: Fix OpenCode plugin lifecycle, wake liveness and responsiveness
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: integration
---

## Summary

Correct the reproducible OpenCode integration defects found in the 2026-10-07
independent review. Cover wake backlog liveness, stale asynchronous callbacks,
assistant-history ownership and idempotence, optional request latency, shutdown
latency and synchronous host blocking. This is an integration-scoped reliability
feature, not another runtime or installation mechanism.

The human requested a durable feature containing the full findings and manager
coordination to get all of them fixed with proper review. A passing happy-path
wake, aggregate test count, ACK or completed review checklist cannot close this
item. Each finding needs observable regression evidence and independent review.

## Why

The installed plugin at `f31ac14186943cdc60ce10dbb37e26c42a3496bc` passes its
existing tests but has lifecycle and failure-path gaps. Two independent reviewers
reproduced defects in isolated mocks or an in-memory backend. These are separate
from the developer-created pinned OpenCode launcher that caused an update loop.

That deployment mistake was repaired: the normal desktop and ordinary
unmodified standalone CLI now run official 2.0.24 with default configuration/data
locations, direct native shortcuts, retained settings and 87 user sessions.
The desktop updater reported current/latest 2.0.24. This item must preserve the
native installation and update paths. It does not authorize another installation,
upgrade, database migration, live fault injection or application restart.

Related umbrella: [Add wake-first Relay delivery](add-wake-first-relay-delivery.md).
Its unfinished Codex recovery and shared native-wake incident remain separately
owned; do not absorb, reopen or claim them fixed here.

## In Scope

- The V2 adapter, relevant shared helpers and their actual backend callers.
- Correct assistant capture ownership and single-instance idempotence.
- Safe wake-anchor liveness without inventing native completion or duplicate work.
- Cancellation/draining and authority revalidation across awaited callbacks.
- Bounded optional work during ordinary turns, startup and disposal.
- Removing synchronous Git subprocess work from the OpenCode server event loop.
- Focused V1 compatibility verification when shared helpers change.
- Caller-surface E2E regressions for every confirmed finding and related boundary.
- Explicit supported-version/loading guidance and accurate qualification claims.
- Independent plan, implementation and final verification-adequacy reviews.

## Out of Scope

- Changes to the user's everyday OpenCode installation, source, binaries,
  updater, launcher, shortcuts, PATH, global configuration, credentials, data
  locations or databases.
- Starting, stopping, restarting or reloading installed applications,
  integrations, Pallium or Minimap services without exact-scope human approval.
- Promoting an experimental/pinned launcher or isolated profile into everyday use.
- Broad core rewrites, a second delivery ledger, a new scheduler/broker, arbitrary
  callback credentials, speculative runtime support or extra dependencies.
- Treating optional memory/history as a prerequisite for ordinary OpenCode work.
- Repeating unrelated Codex incident work or deploying PR297 as a complete fix.

## Findings and Reproduction Evidence

Line references below are for the reviewed installed revision. Re-resolve them
against each implementation revision; preserve the reproduction contract.

### OC-1 — Delivered wake anchor can block automatic delivery indefinitely (P2)

**Location:** `integrations/opencode/.opencode/plugins/pallium-v2.mjs:72-78,91`;
`storage/sqlite_relay.py:379-389`.

**Trigger:** an admitted wake is ACKed, but its exact native terminal record
cannot be correlated. Compaction can remove the admitted input; a newer natural
user input before idle can also make `terminalAfter()` reject that idle.

**Current behavior:** the plugin correctly avoids guessing completion. However,
the backend only retires the anchor within the `wake.terminal` branch. A
delivered but nonterminal anchor remains selected; subsequent automatic wakes
cannot advance. A manual natural-turn fallback can retrieve the backlog without
repairing automatic activation.

**Evidence:** independent in-memory SQLite reproduction: enroll; send W; poll;
admit; claim context; ACK W; send X; poll 20 times at ten-second increments.
All polls over 200 seconds retain delivered W with terminal=false and never
select X. A newer natural turn receives X; the following poll still retains W.
This proves the backend state behavior, not a live-host incident.

**Required outcome:** distinguish safe activation-anchor retirement from proof
of downstream task completion. Recover subsequent automatic delivery after a
verified supersession/lifecycle boundary while retaining exact scope, owner,
generation, native-input and claim/ACK fences. Missing history, bare idle,
elapsed time or a successful ACK alone must not authorize guessed completion,
blind new IDs or repeated execution of the original payload.

**Regression:** ACKed/unclaimed/claimed original variants; compaction and explicit
newer user input; original plus backlog longer than two; application/plugin/
Pallium restart; delivery expiry; scope move; lost readback; later natural fallback
followed by another automatic wake. Assert original receipt count, selected
native IDs, model-bound payloads and delivery/readback state.

### OC-2 — In-flight callback attaches and ACKs after disposal finishes (P2)

**Location:** `integrations/opencode/.opencode/plugins/pallium-v2.mjs:175-233`,
especially the awaited turn at 201 and attachment/ACK at 223-225.

**Trigger:** pause a natural-context Relay response, complete plugin disposal,
then let the response arrive.

**Evidence:** an isolated mock reproduction awaited disposal and then released
the response. The old callback appended Relay content to the user message and
invoked ACK afterward. An entry-time `disposed` check does not fence resumed
asynchronous work. This was not reproduced against the user's running app.

**Required outcome:** disposal/reload must cancel or drain in-flight work before
reporting completion. Retired callbacks cannot attach, ACK, enroll, close,
ingest or mutate successor state after disposal completes. Revalidate native
location/session and current ownership where an await can cross a move, delete
or reload. Retain uncertainty and normal lease recovery when cancellation occurs
after admission/claim; do not ACK an unattached payload or interrupt newer work.

**Regression:** dispose before request, during headers/body, after claim but
before attachment, after attachment but before ACK, and during native submission/
wait. Cover changed directory, deleted session, successor owner, repeated
dispose and cancellation/response races. Observe state after disposal completes,
not only a successful return from the cleanup function.

### OC-3 — Concurrent assistant callbacks duplicate History writes (P2)

**Location:** `integrations/opencode/.opencode/plugins/pallium-v2.mjs:123-139`;
the existing V1 reservation-before-POST pattern is in `pallium.mjs:253-289`.

**Trigger:** overlapping completion/failed-execution and compaction callbacks
read the same assistant before either HTTP write completes.

**Evidence:** independent isolated mock reproductions emitted two `/items`
requests for one assistant ID. Each uses a newly generated `ocSourceId()`,
so the records have distinct source identities. `lastAssistant` updates only
after the awaited write and cannot exclude the second caller.

**Required outcome:** one successful capture for each intended native assistant
turn even with overlapping callbacks; retry remains possible after failed or
ambiguous capture under an explicitly reviewed idempotence contract. Reuse the
existing reservation pattern or native identity rather than a new capture
framework. PR297's location-ownership guard does not fix this race.

**Regression:** duplicate concurrent completion/compaction, delayed write,
precommit failure, committed response loss, repeated events, plugin reload,
tool-plus-text multi-step turn, identical text with different native IDs,
Unicode, empty/max/over-max content, and same-directory sibling sessions. Verify
stored source receipts and History expansion; search deduplication cannot prove
one underlying write.

### OC-4 — Optional requests stack delays on ordinary turns (P2)

**Location:** `pallium-v2.mjs:160-166,201-205`;
`pallium-common.mjs:25,432-485`. V1 has the same aggregate-latency class.

**Trigger:** the local daemon accepts a connection but stalls rather than refusing
it immediately. Multiple awaited optional requests exhaust independent
six-second timers.

**Evidence:** actual production AbortSignal timers with mocked hung HTTP and an
isolated home measured V2 prompt 6,375 ms and prompt plus context 12,740 ms.
V1 ordinary prompt measured 12,761 ms. These are reproduction observations,
not CI timing thresholds. The request timer already covers response-body reads;
a missing body timeout was investigated and is not a finding.

**Required outcome:** ordinary user work remains fail-open under timeout,
partial/stalled body, 4xx/5xx and malformed response. The implementation plan
must name an aggregate optional-work deadline, its start/end surface, and
request/session/global bounds. Spending the budget on one request cannot start
another full timeout on the same turn. Preserve valid pending Relay and history
retry behavior; do not discard or ACK unseen messages to meet the budget.

**Regression:** connection refused, accepted-but-silent, partial headers/body,
invalid JSON, transient errors, budget exhaustion before each request, many
sessions and recovery after outage. Assert observable model dispatch proceeds
within the approved aggregate budget and payload/claim state remains correct.
Use controlled synchronization; avoid flaky wall-clock-only assertions.

### OC-5 — Shutdown waits serially for every registered session (P2)

**Location:** `pallium-v2.mjs:291-292`; detach calls at 63 and wakeRequest at 38-40.

**Trigger:** daemon hangs on detach while multiple sessions are registered.

**Evidence:** isolated two-session disposal measured 12,355 ms. Detach requests
started serially, and none of the three hook registrations was disposed during
either request. Registrations were disposed only after both six-second aborts.

**Required outcome:** local hooks/event streams/timers retire promptly; best-effort
remote detach cannot make shutdown take six seconds per session. Specify and
verify an overall cleanup bound, cancellation/drain ordering, and lease-expiry
fallback. Independent detaches may run together within a bounded operation;
do not add an unbounded retry/shutdown worker.

**Regression:** zero/one/many sessions, hung detach, mixed success/failure,
event-stream termination, active context/capture/wake work, owner-lease expiry,
successor enrollment and repeated disposal. Confirm no later callback and no
resurrection of retired state after cleanup reports completion.

### OC-6 — Synchronous Git subprocesses block the host event loop (P2 operational limitation)

**Location:** `pallium-common.mjs:32-61`, especially `execFileSync` at 46.

**Trigger:** scope/actor discovery runs Git inside the long-lived OpenCode
server. The three-second subprocess timeout is per call, not a whole-hook
deadline; repeated failed discovery can stack calls.

**Evidence:** a bounded isolated mock with synchronous Git failures delayed an
unrelated event-loop heartbeat. Source trace for an unpinned V1 turn includes
remote discovery twice and root discovery once; without an actor override,
actor discovery adds another call. This establishes host blocking and a
potential nine-to-twelve-second cumulative bound for that path, not a measured
live stall. V2 also uses the shared synchronous discovery helpers.

**Required outcome:** no synchronous Git subprocess on the OpenCode server
event loop. Avoid repeating discovery within a callback; preserve exact
repository/scope/actor derivation, explicit pins and fail-closed work-reference
rules. Use existing/native asynchronous mechanisms with explicit bounds.

**Regression:** slow/missing Git, non-repository directory, linked worktree,
missing remote, Unicode paths, cwd changes, dirty/untracked files, cancellation
and simultaneous sessions. Assert unrelated native API/event work remains
responsive while discovery is delayed. Preserve V1 compatibility and caller
identity; do not change the user's Git configuration.

### OC-7 — Existing cross-folder assistant ownership defect (PR297 dependency)

**Location:** `pallium-v2.mjs:123`. The installed adapter does not verify
`owned(id)` before assistant capture.

**Trigger/impact:** multiple active native locations can process the same
assistant callback and write duplicate or incorrectly scoped Pallium History
records. Earlier native negative-control evidence produced five records with
the guard removed.

**Existing correction:** [PR297](https://github.com/rore/Pallium/pull/297) adds
the ownership guard and has separate source/native review evidence. It remains
unmerged and undeployed, subject to its CI dependency and the human's current
environment-protection directive. Verify its live status before reuse.

**Required outcome:** reconcile and reuse that smallest guard without overlapping
ownership or claiming it fixes OC-3. Verify same-repository different folders,
different repositories, exact ownership lookup failure, moves, completion and
compaction through the native caller surface.

### OC-8 — Deletion-event authority concern requiring native qualification

**Location:** `pallium-v2.mjs:250-258`.

A mock `session.deleted` event without `location.directory` can reach
`/relay/sessions/close` and remove a foreign session's pin without recorded
ownership validation. The event-envelope's production reachability is unverified.

First establish the actual supported native event shape and subscription scope.
If reachable, require recorded ownership before destructive lifecycle actions
(getting a session after deletion may legitimately fail) and add native E2E.
If unreachable by contract, retain the native evidence and document why no
production defect is claimed. Do not silently promote this concern to a proven
bug or discard it without evidence.

## Done When

1. Every OC finding has a reviewed disposition: implemented and verified;
   independently proven non-reachable with retained native evidence; or explicitly
   accepted by the human with exact limitation and consequence. No silent deferral.
2. Each confirmed defect has a regression that fails on the relevant pre-fix
   revision and passes after the fix. Keep bug IDs in this planning document;
   test scenarios/fixtures remain anonymized and domain-generic.
3. Real caller-surface E2E covers the full lifecycle, Unicode, empty/max/over-max,
   errors/permissions/conflicts, idempotence, cross-state combinations, chains
   longer than two, restart/reload/compaction, concurrency and controlled outages.
   Unit mocks alone do not close native-host authority or lifecycle claims.
4. Independent clean-context plan review checks state/authority and simplicity
   before implementation; final result review checks all modified callers and the
   full acceptance matrix. A separate verification-adequacy pass actively looks
   for missing failure/race cases. Resolve every actionable finding.
5. Run the repository's whole-change test selector, affected lanes, required
   full non-slow suite and protected behavior contracts under Agent Workflow.
   Reuse reliable unchanged evidence; passing unrelated test counts are not
   evidence for these new regressions.
6. Qualify each claimed supported OpenCode version/surface in isolated native
   fixtures. Historical 2.0.22 and isolated/live 2.0.24 evidence must remain
   distinguished; do not claim arbitrary multiple-version compatibility.
7. Align the feature, umbrella, integration documentation and actual code.
   Keep source completion, merge, installed deployment and live qualification
   as distinct states.
8. No live environment mutation occurs without explaining exact changes/impact
   and obtaining explicit approval for that scope. Any approved deployment must
   preserve work/data/settings, include rollback and verify native launch/update
   behavior and the actual deployed version.

## Manager Coordination and Review Gates

- The Pallium manager accepted management and owns canonical queue/order,
  cross-task assignments, independent acceptance review and completion.
  @pal-dev1 accepted implementation ownership; no overlapping developers are
  assigned. Implementation has not started: the first concrete slice still
  requires the applicable plan/risk reviews.
- Authorize repository fixes and isolated tests under the user's request; use
  Agent Workflow before any implementation edits. Classify the actual combined
  change and trigger architecture/API/persistence review for any wake-authority
  or persisted transition change. This feature document is not an approved
  concrete implementation plan or a substitute for required review.
- Reconcile PR297 and relaydev's independent Codex CI/registration incident work.
  Do not create competing ownership fixes or restart the shared backend.
- Prefer one accountable implementation owner with bounded helpers where useful.
  Distinct reviewers must assess their actual scopes, and the lead must reconcile
  combined behavior rather than treating individual approvals as acceptance.
- Before implementation, record an acceptance matrix mapping each OC finding to
  the failing baseline, corrective contract, caller-surface E2E, supported native
  version/surface and reviewer. Include adjacent callers and failure boundaries.
- Before merge/result approval, reviewers assess the changed code AND whether
  verification could have missed the same failure classes as the prior review.
  Show unresolved limitations and exact deployment impact to the human.
- Status stays queued while the first concrete implementation slice is being
  prepared and reviewed; move to active when its owner begins authorized work.
  Do not mark fixed merely because the feature, a patch, a test or a review exists.
- Canonical feature identity: `roadmap/features/fix-opencode-plugin-reliability.md`.
  The manager reviews the combined documentation before publication; temporary
  checkout and branch coordination stays in the private handoff.
- First bounded planning slice: OC-2 plus OC-5, which share disposal/lifecycle
  callers. OC-1 safe anchor retirement gets a separate contract review, concurrently
  at planning only; no guessed completion or ACK-only retirement. OC-3 capture
  idempotence follows; then OC-4 and OC-6 optional I/O and event-loop latency.
  Reconcile OC-7 with PR297 and qualify OC-8 natively in an isolated fixture.
  Slice boundaries are proposed sequencing, not a fixed architecture decision.

## Notes and Evidence Baseline

Original commands and reviewer outputs are retained privately in the existing
review/PR evidence checkout under `build/opencode-plugin-review-20261007/`.
These ignored artifacts are not part of the public documentation commit. The
implementation owner holds custody; the manager has the exact checkout mapping
in the private handoff. Do not clean up or archive that checkout until the bundle
is copied to retained evidence and the manager verifies the handoff. Public
regressions must use anonymized fixtures, not private transcripts or host paths.

| Findings | Retained runnable command artifact |
|---|---|
| OC-1 | `build/opencode-plugin-review-20261007/wake-anchor.ps1` |
| OC-2, OC-3, OC-8 | `build/opencode-plugin-review-20261007/context-capture-deletion.ps1` |
| OC-3 independent confirmation | `build/opencode-plugin-review-20261007/capture-concurrency.ps1` |
| OC-4 V1 | `build/opencode-plugin-review-20261007/v1-request-latency.ps1` |
| OC-4 V2, OC-5 | `build/opencode-plugin-review-20261007/v2-latency-disposal.ps1` |
| OC-6 | `build/opencode-plugin-review-20261007/git-event-loop.ps1` |

The same directory contains `correctness-review.md`, `failure-review.md`,
`original-repro-outputs.json` and `manifest.json` with source-call provenance and
baseline `f31ac14186943cdc60ce10dbb37e26c42a3496bc`. Commands were recovered from
the original tool calls without execution. To replay, first review each retained
command and replace its baseline checkout/runtime paths with an isolated checkout
at that revision; then run `pwsh -NoProfile -File <artifact>` from that checkout.
The commands use in-memory SQLite or mocked HTTP with temporary profiles; they
are reproduction evidence, not a new test framework or native E2E qualification.

- Review date: 2026-10-07. Reviewers: `opencode_plugin_correctness_review` and
  `opencode_plugin_failure_review`; parent reconciled duplicate reports.
- Reviewed installed commit:
  `f31ac14186943cdc60ce10dbb37e26c42a3496bc`.
- Existing shipped checks during review: 68 package tests passed, 7 platform
  skips; 25 wake API E2E passed. Prior unchanged native 2.0.24 lifecycle:
  1 passed in 41.01 seconds. None of those tests covered all new reproductions.
- All new review reproductions used mocks, temporary profiles or in-memory
  SQLite. No live Pallium/OpenCode request, paid model, installed config,
  application/service restart or repository code change occurred during review.
- User's standing directive: **Do not mess with my working environment.**
  Generic implementation, feature or PR approval does not authorize undescribed
  live changes. Reuse approval only for its exact previously described scope.
- The pinned-launcher incident is a completed deployment correction, not an
  unresolved plugin/updater patch. Preserve native update paths as a requirement.
