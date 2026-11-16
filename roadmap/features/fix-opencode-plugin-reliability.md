---
id: fix-opencode-plugin-reliability
title: Fix OpenCode plugin lifecycle, wake liveness and responsiveness
status: active
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

At the 2026-10-07 review, that deployment mistake had been repaired: the normal
desktop and ordinary unmodified standalone CLI ran official 2.0.24 with default configuration/data
locations, direct native shortcuts, retained settings and 87 user sessions.
The desktop updater reported current/latest 2.0.24. This item must preserve the
native installation and update paths. It does not authorize another installation,
upgrade, database migration, live fault injection or application restart.

Related umbrella: [Add wake-first Relay delivery](add-wake-first-relay-delivery.md).
Its unfinished Codex recovery and shared native-wake incident remain separately
owned; do not absorb, reopen or claim them fixed here.

## Current disposition (2026-10-20)

OC-3's PR306 subsequently merged as `2ac9e2b66b9cd72ff7af9e7aeda9ecf061360b1f`, qualified head `37fc691380f86db307b2de8932b09948a736db12`, against actual PR297 main. Local full coverage passed 7,531 tests, package coverage passed 139 with seven existing skips, and real-HTTP plus isolated native OpenCode 2.0.24 checks passed. Required hosted checks passed after one independently reviewed Linux 3.12 retry; prior failures remain preserved. Actual logs and merge conditions received independent review. A private verification receipt is retained. No installed deployment occurred; remaining findings keep this item active.

PR297 merged as `178fea16e36946ffed68fb4bdd93da76056d5f73` from exact qualified head `07697ac2b8f74e8503534a6586fb13dbb30bdeb4`. Its final ordinary Linux 3.13 and Windows 3.12 retries passed; passing lanes were reused, actual results and main compatibility received independent review, and all four review threads were resolved. Earlier failures remain recorded. A private verification receipt is retained. This closes PR297's merge gate, not installed deployment or this broader reliability feature.

The findings below preserve the reviewed 2026-10-07 baseline and its reproduction
contracts. Their original line references and behavior descriptions are historical;
re-resolve them before implementing remaining work.

| Finding | Current disposition |
|---|---|
| OC-1 wake-anchor liveness | Open; no verified closure recorded. Preserve the activation/completion distinction and native qualification gates. |
| OC-2 retired callbacks | Implemented, independently reviewed and merged in [PR302](https://github.com/rore/Pallium/pull/302), merge `e9eb3956ce4990f9dc15d0a24520f40d67246883`. Installed deployment is not established by that merge. |
| OC-3 capture idempotence | Independently reviewed, qualified and merged in [PR306](https://github.com/rore/Pallium/pull/306), merge `2ac9e2b66b9cd72ff7af9e7aeda9ecf061360b1f`. Installed deployment remains separate. |
| OC-4 aggregate optional latency | Open; preserve the caller-visible budget and fail-open requirements below. |
| OC-5 bounded disposal | Implemented, independently reviewed and merged with OC-2 in PR302. Its isolated native 2.0.22/2.0.24 evidence does not establish installed deployment or arbitrary-version support. |
| OC-6 synchronous discovery | Open; synchronous Git discovery remains in the shared helper. |
| OC-7 directory ownership | Independently reviewed, qualified and merged in [PR297](https://github.com/rore/Pallium/pull/297), merge `178fea16e36946ffed68fb4bdd93da76056d5f73`. Installed deployment remains separate. |
| OC-8 deletion authority | Native reachability/qualification question remains open; do not promote the mock concern to a confirmed native defect. |

### Current qualification boundary (2026-10-22)

PR404 contribution (2026-11-14): the discovery-only correction is independently
source-reviewed and qualified on exact `3402450b8b2fa21ce129edb80160bc6b76ee5f0d`
by [run 43621847373](https://github.com/rore/Pallium/actions/runs/43621847373).
Expected baseline RED and corrected focused GREEN were observed. Package coverage
is 175 cases / zero failures / seven existing skips, with all nine new cases
individually passed. The released 2.2.7 native witness passed unskipped with all
nine lifecycle checks true, unchanged source/binary bookends and normal/final drain.
The manager independently accepted the actual artifact and combined disposition.
Full Python 3.12, Windows and governance passed; the unrelated Python 3.13
acquisition-deadline failure and all earlier failed attempts remain preserved in
the [owning Work Record](../../.agent-workflow/tasks/opencode-automatic-delivery-recovery.md).
PR404 merged as `479b9aa2db8fdd5ee872fdc9bfadf5c941bdb52e`. Development and
stable installed source were aligned to that commit with a verified paired backup
and the supported service restart. Health, readiness, embedding and queue checks
passed; existing work and configuration were preserved. The active OpenCode host
was not reloaded. [Rollout evidence](https://github.com/rore/Pallium/pull/404#issuecomment-6882031037)
does not establish loaded-host recovery, historical cause or broader reliability.
This item stays active.

### Confirmed OC-1 incident (2026-11-14)

Read-only scheduling and native-history evidence now confirms this failure class
in two active OpenCode sessions. Both retain a delivered, admitted, nonterminal
anchor while their polling ownership remains live. In one session, a newer
ordinary input precedes the first successful idle after the wake. Compaction
later removes the wake from active context. The plugin rejects the intervening
input's idle, then returns when the admitted wake is missing. The backend keeps
the old anchor and cannot select a new automatic wake.

A later request was saved at 20:35 UTC and claimed only with a manual prompt at
20:42 UTC. Native input history contains no automatic wake between those times.
The manager session has the same stuck-fence state. Hermes monitor reports were
saved and subsequently delivered; their receipt does not establish timely wake.
This is not evidence of a short idle timeout, dead polling or message loss.

OC-1 is the immediate functional priority. The existing architect completed the
bounded source investigation against official OpenCode 2.2.7. Native idle covers
coalesced inputs, so an outcome-bearing terminal can settle a visible exact wake
despite intervening input. Bare `wait()` does not prove consumption or success.
The supported plugin API cannot reread old messages outside active context.
That blocks retrospective correlation, but is **not** a blanket recovery blocker.
The existing architect's pinned-source reassessment supports a fresh causal
boundary: the supported adapter records admission only after the exact wake is
promoted into native visible history and its inbox row is consumed. If that
admitted generation is already known before a genuinely new ordinary prompt,
the adapter can witness that new input's native promotion and a later settled
outcome-idle, then revalidate the complete owner/scope/generation binding before
using the existing terminal operation. Queue acceptance or a new steer alone
does not supply this proof.

The root fix uses one ephemeral witness in existing session state,
not another persistent ledger or backend transition. Before the new ordinary
input is observed promoted, its absence means not ready and retains that same
frozen witness. After promotion, missing or changed proof invalidates it.
Another input, shutdown, revert, move, reload or disposal must invalidate it.
It cannot retrospectively bless completed manual turns, clear arbitrary
admission flags or claim downstream task success. This corrects the earlier
overstatement that historical listing is always necessary. It is source/design
evidence, not runtime qualification or observed recovery.

The existing developer owns the root correction in
`.agent-workflow/tasks/opencode-wake-anchor-retirement.md`. Its corrected plan
passed technical review, and the task owner's human approval carries forward.
Root source was independently reviewed and published as
`f7fb80e47a307f9ab41509ec6ab1c11a4de09085` in draft
[PR #410](https://github.com/rore/Pallium/pull/410). Its test source adds 12 named
root cases to the 31 required Node entries and a
mandatory 13th native check. That check requires four distinct sequential new
automatic wakes after recovery, with frozen post-recovery counters; earlier
traffic, manual fallback and batched messages cannot supply acceptance.
The sixth attempt passed the full package but failed the first native delivery
prerequisite. The later root recovery journey remains unreached and unqualified.
The task owner prioritizes
the actual local failure, including already-compacted anchors. Reviewed bounded
diagnostic hunks were integrated without replacing the root inventories or
publishing raw logs. The original diagnostic checkout/evidence remain preserved.
All six execution budgets are closed. No seventh attempt, unchanged retry,
additional root-source push, relabel, merge or live change is authorized.
Full recovery and the local incident remain open.
Preserve the OC-1 outcome and regression matrix below. Activation settlement is
not downstream task completion.
No live rows were cleared, messages replayed, or installed applications restarted
to hide the incident. Private evidence remains local; no fix or recovery is yet
qualified. PR404's discovery-only acceptance remains unchanged.

The first qualification attempt on `b2acf606` is **failed, not qualified**.
Exact baseline RED and focused GREEN passed, as did 205 package cases with zero
failures and seven existing skips. All 31 required cases passed. The 60-second
HTTP/workflow phase timed out without test-level progress; its cause is unknown.
Native validation was skipped and all 12 native checks remain unobserved.
Unchanged source/binary bookends and successful drain do not prove native coverage.
Both ordinary Linux lanes stopped at a new fixture error: four backlog seconds
plus a 12-second jump exceeded the unchanged 15-second owner lease before renewal.
Windows smoke and governance passed, but full-suite coverage is incomplete.

The second campaign failed its expired-state fixture readback after completing
the narrowed HTTP selection: wake operations used synthetic time, but public
status received real UTC. Its native phase was skipped. The third campaign ran
native validation first; that unskipped journey failed and the qualification's
HTTP phase was skipped. Its sanitized diagnostic lost the precise assertion
location, so that native failure's predicate and cause remain unknown. None of
the three campaigns qualifies the contribution, and the first timeout's cause
remains unknown.

Ordinary third-campaign Python 3.13 did complete: 9,140 passed, 106 skipped and
two xfails, including all 46 HTTP-file cases and all 25 workflow-contract cases.
The shared-clock fixture correction therefore has ordinary-CI evidence, distinct
from the failed native qualification. Python 3.12 still failed in unchanged Codex
cases; their causes are unresolved. Windows smoke and governance passed. Preserve
the [first](https://github.com/rore/Pallium/pull/410#issuecomment-6885286594),
[second](https://github.com/rore/Pallium/pull/410#issuecomment-6885852162) and
[third](https://github.com/rore/Pallium/pull/410#issuecomment-6886277488) receipts as
failed campaigns, not new execution authority. No OC-1 merge, installed change
or incident recovery is claimed.

The fourth, corrected-root [qualification](https://github.com/rore/Pallium/actions/runs/43691537059)
failed at package validation. Both exact legacy/root baseline assertions were
observed as expected, and both candidate focused cases passed. Actual extractor
and replay-oracle checks passed before the package ran. Package results were
217 cases, two failures and seven existing skips; 41 of 43 required entries passed.
The failures were `fresh supersession requires observed producer promotion before
admission` (actual 0, expected 1) and `fresh supersession fences lifecycle and
backend changes during settlement` (`final-poll/admitted`, actual 1, expected 0).
No Node file/line was retained. Product-versus-fixture causes are not established;
source investigation continues without weakening either assertion.

Native and qualification HTTP were skipped: zero native 13-check or qualification
HTTP25 evidence. Source/binary bookends and owned drain passed, but do not prove
recovery. In [ordinary CI](https://github.com/rore/Pallium/actions/runs/43691371959),
Python 3.12 passed the full non-slow suite: 9,142 passed, 106 skipped, two xfails,
including all 46 HTTP-file, 27 workflow and 19 protected-contract cases. Python
3.13 stopped at an unchanged dashboard test returning HTTP 503 instead of 200;
its cause, independence and flakiness remain unproved. Windows smoke and governance
passed; aggregate CI failed. The [same result receipt](https://github.com/rore/Pallium/pull/410#issuecomment-6886277488)
preserves all earlier evidence. Independent actual-result review completed with
HOLD / NOT QUALIFIED; the manager accepted that failed-result disposition.
No source retry, merge, live change or incident recovery is accepted.

The fifth [qualification](https://github.com/rore/Pallium/actions/runs/43700268471)
at `55d61d3f` also failed at package validation. Its non-record source is identical
to independently source-reviewed `9ba27e98`. Both exact baseline RED and candidate
focused GREEN gates passed. Both actual extractor/oracle preflights passed before
the package ran. Package results were 217 recorded cases, one failure and seven
existing skips. All 43 required entries passed, including the two fourth-attempt
failures, but the whole package still failed. The unchanged caller test
`replaced scope generation fences an older response inside the same entry`
received unexpected Relay context on an ordinary input expected to stay unchanged.
Its Node runtime locator is missing; a source reference is not a retained runtime
file/line or proof of an exclusive cause. The unchanged test remains mandatory.

Native and qualification HTTP were skipped: zero observed native 13-check journey
or qualification HTTP25 evidence. Compaction/restore, fresh ordinary recovery,
original-payload non-replay and four distinct sequential NEW automatic wakes have
not passed. Official OpenCode 2.2.7 pins, all seven source hashes, unchanged
source/binary bookends and normal/final drain were verified, but cannot substitute
for that journey. The inspected safe qualification artifact is `14155604687`.

Fifth [ordinary CI](https://github.com/rore/Pallium/actions/runs/43700194523)
also failed overall. Python 3.13 passed the full non-slow suite: 9,142 passed,
106 skipped and two xfails. Python 3.12 stopped at 6,750 passed, one failure,
37 skipped and two xfails. Its failure was
`test_modeled_summary_turn_refuses_real_writer_contention[sqlite-semantic]`:
the prerequisite admission audit reported started 0, expected 1. Its later
contention assertions were not established. The files are unchanged and the same
case passed in current Python 3.13; cause, independence and flakiness remain unknown.
Both Linux artifacts passed all 46 HTTP-file cases, the exact 25 required HTTP
names, 27 workflow and 19 protected-contract cases, plus the extractor/oracle checks.
The historical dashboard case passed both current lanes; its earlier 503 cause is
still unresolved. Windows smoke and all three governance runs passed. All owned
jobs completed within their original caps, without cancellation, retry or a
remaining observer. These partial passes do not make aggregate CI green.

Independent fifth actual-result/evidence review completed with HOLD / NOT QUALIFIED.
The manager accepts the evidence as a failed result, not recovery. The
[same receipt](https://github.com/rore/Pallium/pull/410#issuecomment-6886277488)
retains all five histories. A clean result-only successor remains unpushed; draft
PR410 remains at `55d61d3f`. No root fix has merged or reached the installed host.

The existing developer has adopted a source-only continuation for the failed
registration contract. Source tracing shows the new shared wake-response guard
rejecting a higher scope before the existing `remember()` reset can abort older
requests. This identifies a correction direction, not a recovered runtime locator
or exclusive campaign diagnosis. Restore valid monotonic registration invalidation
through the existing reset path without accepting an old request's wake body under
the new scope. Preserve the original test's unchanged-context, zero-ACK and
future-poll-scope assertions, cache revisions, stale-response rejection, witness
fences and replacement-flight isolation. The existing architect completed the
bounded read-only compatibility comparison. It confirmed that the omitted reset
also fences ordinary claims, context and assistant captures. Registration freshness
must be checked separately from wake-cache freshness: intervening same-binding
wake/null progress must not hide valid higher-scope invalidation. Discard that old
request's wake body after reset; only a fresh new-scope request can obtain wake
authority. Keep revision protection for all same-scope wake acceptance. The manager
accepted and forwarded these findings for consolidation, not as source or runtime
GO for the evolving correction. The unpublished correction now separates those
freshness checks and fences stale rejection effects as well as wake acceptance.
Both-writer caller schedules are authored but unexecuted. The same independent
reviewer completed narrow SOURCE / CONTRACT GO at exact unpublished `f80df956`.
The manager read and accepted that source disposition. Registration compatibility
and ordering source gates are closed. That source-only disposition did not itself
release another campaign. The local automatic-wake incident remains open.

### Bounded finish continuation (2026-11-16)

The task owner requested continuation to finish the fix. The manager released one
new, sixth hosted attempt for exact source-reviewed `f80df956` or a record-only
successor with identical non-record source. The existing developer has adopted
that scope. It permits one normal fast-forward to the existing PR410 branch,
one automatic ordinary-CI round and one existing qualification-label cycle at the
same immutable head. It does not permit another product or workflow edit.

The existing package-first gates and acceptance remain unchanged: whole package
including the original scope-replacement test, all 43 required entries, unskipped
native 13-check compaction/recovery/non-replay/four-NEW-wake journey, and exact
HTTP25. Caps remain 900 seconds for qualification, 120 for package, 120 for native,
60 for HTTP and 12 minutes for ordinary CI observation. The existing owner observes
only that round, stops on failure and cancels owned active jobs at their cap.
No unchanged retry, seventh attempt, cap extension, raw-log download, local
application execution, new runner or worker is released. The same independent
reviewer must review the actual sixth result before manager acceptance and merge.
The actual result below closes this budget; the five earlier failed histories
remain unchanged.

Ordinary coordination found the desktop-managed CLI directory now at 2.3.0.
This is not proof of a loaded plugin version or native recovery. The hosted
campaign stays pinned to reviewed OpenCode 2.2.7. The existing architect completed
the bounded source-applicability comparison against official 2.3.0 commit
`a6b15d33daf6ab7d35569f6d711fdb630b9f04e7` and returned SOURCE APPLICABILITY GO:
no concrete changed premise requiring an `f80df956` adaptation was found.
Promotion, context/compaction and same-session settlement assumptions remain
applicable. Metadata propagation, descendant reporting and incomplete-assistant
replay have changes that still need runtime evidence. The manager accepts this
source-only disposition, not blanket compatibility or installed recovery.
It does not retarget or block the current qualification. Actual 2.3.0 qualification,
loaded runtime/plugin identity and the exact installation/restart/reload scope
remain separate. No live-environment change or cleanup is authorized here.

### Sixth actual result (2026-11-16)

Exact published `f7fb80e4` has the same non-record source as reviewed `f80df956`.
[Qualification](https://github.com/rore/Pallium/actions/runs/43855605873)
failed at native validation, not package validation. Both exact baseline RED and
candidate GREEN gates and both extractor/oracle preflights passed. The full package
recorded 217 cases: 210 passed, zero failed and seven existing skips. All 43 required
entries passed, including the unchanged scope-replacement contract.

The selected native case ran unskipped and failed at
`tests/test_opencode_native_wake_e2e.py:611`, `assert delivered(original)`, through
the wrapper at line 190. The preceding blocked-provider event was observed, but
the immediate public Relay readback was not delivered. Subsequent admission,
ordinary-input coalescing, compaction/restore, non-replay and four NEW sequential
automatic wakes were not reached. Cause, ACK failure, timing and flakiness remain
unestablished. Of the 13 native fields, only host-version verification and owned
drain are true; the other 11 are unestablished, not proven contract violations.
Qualification HTTP25 was skipped.

[Ordinary CI](https://github.com/rore/Pallium/actions/runs/43855585214) passed.
Both Linux versions completed 9,142 passed, 106 skipped and two xfails. Both passed
all 46 HTTP-file cases, exact HTTP25 names, 27 workflow and 19 protected-contract
cases, plus both extractor/oracle checks. Windows smoke and all three governance
runs passed. Previous capacity and dashboard cases passed in both current lanes;
their historical causes remain unknown. All owned runs completed within the
original caps without cancellation, timeout, retry or a remaining observer.

The inspected safe qualification artifact is `14220892839`; source hashes, official
2.2.7 pins, unchanged source/binary bookends and normal/final drain passed.
Package and ordinary passes do not replace the failed native journey.
The [same receipt](https://github.com/rore/Pallium/pull/410#issuecomment-6886277488)
retains all six results. The result-only record remains local and unpushed; PR410
stays draft and unqualified. The same independent reviewer completed the actual-sixth
evidence review with HOLD / NOT QUALIFIED and no material reporting error. The manager
accepts that failed-result disposition; no source or earlier result review is repeated.

Read-only discovery now checks the exact delivery prerequisite: the fixture sets
its provider-entry event for every provider POST, but that alone does not identify
the original Relay model request. The completed source comparison confirms that
title generation can reach the provider before primary context/ACK completion.
It also confirms that 2.2.7 omits stored metadata from primary hook messages while
2.3.0 preserves it; the current internal-wake classifier requires that metadata.
Even a correlated primary request proves callback return, not successful ACK.
The public delivered assertion must remain an independent immediate oracle.
These source findings do not establish which request or ACK outcome caused the
sixth failure.

The task owner clarified the expectation: a minimum supported version and compatible
later releases, not an exact-version lock. Binary pins make qualification repeatable.
The existing developer prepared a narrow plan for an API-based minimum
(2.3.0 for the current internal-wake metadata path, subject to runtime evidence),
clear minimum-versus-tested-version documentation, and a correct primary-request
observation boundary. Historical 2.0.24 and 2.2.7 evidence limits and the passive V1
path remain unchanged; no blanket compatibility with unseen releases is claimed.
The existing architect reviewed record-only `5cc5ce77` and returned PLAN HOLD on
three narrow points: exact one-use completed-context/FIRST-primary pairing,
auxiliary responses bypassing the primary gate, and executable checks of the actual
observer's negative and failure-safe cleanup paths. The API floor, explicit-title
precondition and need for at most one fixture observer are supported.

The owner amended those three points in record-only `a0e9af4b` and requested
the same architect's narrow closure; that disposition remains pending.
After exact PLAN GO, the manager's conditional
source-only release permits the existing README, qualification workflow, native
fixture, workflow contracts and Work Record changes without another routine
approval stop. Production plugin/helper/backend/API/package caller source stays
exact `f80df956`. Independent patch review still follows. No source edit is released
while PLAN HOLD remains, and no seventh run, publication, timeout increase,
assertion weakening, diagnostic expansion or live change is authorized.
Full recovery remains open.

### Additional live empty-wake report (2026-11-16)

A downstream session reported `Pallium internal wake has no current Relay work`.
Read-only existing trace/status evidence confirms one delivery attempt and a
durable ACK. The activation receipt was recorded later; that is not proof of
native execution ordering or an exclusive overtaken-wake cause. Exact identifiers,
scope and evidence remain private; no downstream project payload is copied here.

The caller contract already expects this visible refusal for an empty committed
wake and requires newer ordinary work to remain usable. Do not weaken that guard
merely to remove the error. The user reports uncertain message recognition, not
confirmed task interruption. The supplied status excerpt is only the final body
page; it does not establish whether earlier pages were available or read.
Receipt, complete body availability, understanding and task completion remain
separate facts. Error-to-generation correlation, loaded identity and actual task
effect are unresolved. No resend, manual receive/ACK, live change or expansion of
the current fixture-only source scope is authorized by this report.

[PR #340](https://github.com/rore/Pallium/pull/340) remains draft and unqualified
at published `9188720f4f15e3ac918105c6c0efb5392c37927e`. Automatic CI
[39695623972](https://github.com/rore/Pallium/actions/runs/39695623972) and
governance passed, but complete manual
[39695648270](https://github.com/rore/Pallium/actions/runs/39695648270) failed
all four platform/version profiles. All eight changed cases passed once in their
normal selections; those rows cannot qualify failed profiles, and no passing
complete Windows profile is established for this contribution.

A local-only OpenCode clock-origin fixture correction at `7d2340d` (record
`9efe1da`) received independent RED-one/GREEN-two review. It proves the bounded
fixture mechanism, not the historical hosted failure's exclusive cause, product
repair or complete qualification; it is not published or full-qualified.
Shared availability remains unresolved. OC-1, OC-4, OC-6 and OC-8 remain open.

The serial-full proposal was rejected because its estimated five-to-nine-hour
cost and cross-test topology remained uncertain. The explicit test-mechanics
replan retains the actual mandatory local full run and PR checks; broader Windows
reliability and separate PR #325 qualification remain open.

The one corrected-source local full run at `79040c4e` failed after 2,421 passes,
one failure, three skips and one xfail. In
`test_codex_wake::test_relay_transport_timing_is_bounded_and_dashboard_projected[unavailable-30000]`,
the second `record_wake_event` returned false before later assertions. The
missing branch/exception evidence supports no fix or historical-cause claim.
Record-only repair `9c135ecc` received independent GO and checker exit zero; it
does not qualify application behavior, and the original prelaunch checker exit
two remains preserved. Next: resolve the failed mandatory qualification's
evidence-supported disposition before any new execution or supported fix is
proposed. The clean owner checkout/private environment remain retained with no
execution running. Evidence: `build/pr340-test-mechanics-full-20261022` and the
prior `build/opencode-lease-clock-origin-20261022/qualification-reassessment.md`.
No test, internal concurrency, mandatory check or time limit is weakened; this
roadmap amendment authorizes no application execution, diagnostics or CI edits.

PR302's accepted result and evidence are recorded in
[OpenCode disposal reliability](../../.agent-workflow/tasks/opencode-disposal-reliability.md).
Its package, full Python and isolated native results supersede the pending
first-slice verification notes below. They do not close the remaining findings.
The V2 activation foundation is already merged in
[PR292](https://github.com/rore/Pallium/pull/292); its happy-path and isolated
version-specific witnesses are distinct from this feature's reliability closure.

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
the ownership guard and merged as `178fea16e36946ffed68fb4bdd93da76056d5f73`
after qualification and independent review. Installed deployment remains separate
under the human's environment-protection directive.

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
  assigned. The human-approved OC-2/OC-5 disposal slice completed independent
  technical and verification-adequacy review and merged in PR302. Final evidence
  records 96 package passes with seven Windows skips, 6,332 Python passes with
  45 skips and two expected failures, and isolated native 2.0.24/2.0.22 checks.
  These results supersede the earlier 93-test/source-only checkpoint; installed
  deployment is not established here. OC-1/4/6/8 remain open; OC-3 and OC-7 are
  qualified and merged in PR306 and PR297, with installed deployment separate.
- Authorize repository fixes and isolated tests under the user's request; use
  Agent Workflow before any implementation edits. Classify the actual combined
  change and trigger architecture/API/persistence review for any wake-authority
  or persisted transition change. This feature document is not an approved
  concrete implementation plan or a substitute for required review.
- Reuse merged PR297's ownership guard and reconcile relaydev's independent Codex CI/registration incident work.
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
- Status is active because authorized implementation has begun.
  Do not mark fixed merely because the feature, a patch, a test or a review exists.
- Canonical feature identity: `roadmap/features/fix-opencode-plugin-reliability.md`.
  The manager reviews the combined documentation before publication; temporary
  checkout and branch coordination stays in the private handoff.
- The first bounded slice, OC-2 plus OC-5, is merged; do not reimplement it.
  Reuse the merged OC-3/OC-7 slices and reviewed evidence in PR306/PR297 without duplicating
  their work. OC-1 safe anchor retirement needs its separate contract review;
  no guessed completion or ACK-only retirement. OC-4/OC-6 optional I/O and
  event-loop latency remain open, and OC-8 needs isolated native qualification.
  Remaining slice boundaries are proposed sequencing, not a fixed architecture.

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
