---
id: add-wake-first-relay-delivery
title: Add wake-first Relay delivery
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: capability
---

## Current execution status (reconciled 2026-10-04)

On 2026-10-04, one live Relay delivery's Codex queue wake timed out at
05:59:36 UTC and the message expired at 06:09:05 with attempts=0. Later,
same-target cold→idle and another idle probe both ACKed with attempts=1.
Subsequent service health, status, queue, and embedding checks were healthy. No
resend or service/config change occurred during the investigation. The native
timeout cause remains unproved. Timeout diagnostics improve evidence only; this
does not establish delivery reliability. See
`.agent-workflow/tasks/codex-queue-timeout-evidence.md`.

A follow-up review confirmed a narrower pre-start recovery defect: when thread
start and durable release both fail, a local schedule marker blocks the surviving
prepared reservation. The fix covers worker-start failure and retained prewrite
deferral. Both HTTP failure-to-ACK regressions and 324 affected tests passed;
full validation passed 5,955 tests with 34 skipped and 2 expected failures.
Independent review and CI passed. PR #281 merged at `8422e988`; both clean clones
were synchronized and the installed restart wrapper exited successfully.
Independent health, embedding and queue checks passed. The implementation record
is `.agent-workflow/tasks/codex-wake-worker-start-recovery.md`. Existing submitted
or uncertain reservations remain fenced.

PR #277 merged at `d993f639`; required CI passed and the installed service was
updated and healthy. Real dogfooding then exposed unfinished recovery behavior:
an abandoned unclaimed wake reservation blocks later notifications, and a native
timeout followed by lost retained custody defers other recipients. These incidents
affect the reliability claim despite the successful idle/unloaded witnesses below.
Reservation recovery shipped in PR #280 at `01213c1d`; its record is
`.agent-workflow/tasks/codex-wake-reservation-recovery-v2.md`. Both clean clones
were synchronized, the installed wrapper exited successfully, and independent
health, embedding and queue checks passed. Local full validation passed 5,953
tests with 34 skipped and 2 expected failures. Final CI and independent review
passed. One unchanged Claude hook test encountered a busy ACK in Python 3.12 CI;
its exact local test and the single failed-job rerun passed, with no speculative
Claude code change. The original record preserves connection-repair history.
The connection repair shipped in PR #279 at `9454dd80`. Both clean clones were
synchronized and the installed wrapper exited successfully; independent health,
embedding and queue checks passed, and authenticated retained registration was
observed after restart. Local validation passed 5,949 tests with 34 skipped and
2 expected failures; CI and independent review passed. One existing hook test
failed in the initial Python 3.13 CI run, passed locally, and passed on the single
failed-job rerun; its cause remains unconfirmed. No speculative hook change was made.
The workflow-manager notice was acknowledged on its first claim at
2026-10-02 14:22:30 UTC, after the older reservation naturally expired and before
the PR #280 deployment. No reset or resend was used; ACK proves receipt, not action.
The user renewed approval for reservation recovery on 2026-10-02. Independent
plan review accepted recovery of new durable prepared generations, with an exact
atomic fence before either native wake path writes. Implementation and regression
validation, review and merge passed. Legacy reserved rows remain fenced until
their existing receipt or expiry reconciliation; this change never relabels them.
Database inspection distinguishes pending/expired delivery from confirmed hook ACK;
neither a native submission nor a healthy HTTP service proves message receipt.

One bounded Windows trial proved the full retained authenticated MCP path:
service-owned wake of a supported `notLoaded` Codex target, hook payload emission,
and one claim/ACK. The target returned a marker supplied only through the Relay
payload. Cleanup restored normal service health. This establishes that the path
works; it does not establish general connection lifetime or busy-turn safety.

Product integration shipped in PR #277 from `feat/codex-retained-wake-product`.
The approved behavior is default automatic wake on supported Windows Desktop
for registered Codex recipients across sender runtimes: check fresh Desktop state, select existing queue delivery
for loaded-idle targets or retained MCP for unloaded targets, and defer working
or unknown targets through the existing recovery loop. Never try the other path
after an uncertain attempt. The
check/send race makes non-interruption best-effort. Reuse the current scheduler,
durable reservation and hook ACK path; no new message store or scheduler.
Final focused regressions passed 74 cases, including both actual payload hooks and ACK.
Affected-test isolation failures were corrected and replayed; native validation had
one isolated transport failure that passed its exact rerun.
Normal default-on idle and unloaded paths both passed live payload-only marker
and hook ACK checks on one attempt, at 16:03 and 16:22 UTC respectively. The
unloaded check used ordinary authenticated source activity and a service-owned
wake, without a manual target wake or finite trial procedure. Latest validation:
115 retained-feature cases, 2 protected contracts, 4 setup checks, and 15 hook
deadline/lifecycle cases passed; independent reviews accepted the changes.
The initial product slice shipped in PR #277. Both Linux CI versions passed
5,902 tests with 72 skipped and 2 expected failures; Windows smoke and required
checks passed. The subsequent recovery fixes and remaining follow-up are recorded
above. New test chats use `pallium-test`.

An earlier 16:06 unloaded attempt claimed without ACK and expired. Its exact
cause remains unknown. A real delayed-response regression independently exposed
the arbitrary two-second hook cap; removing it within the existing eight-second
budget preserves emission/ACK reserves. The subsequent unloaded witness passed.
This does not prove universal transport reliability or atomic busy exclusion.
Broader platform/recovery roadmap work remains open. Earlier entries below are
historical checkpoints, including blockers that the successful trial resolved.

### Earlier shipped checkpoints

[PR #273](https://github.com/rore/Pallium/pull/273) merged the separately armed
unloaded-target trial at `9ad54da4d622030147b8e8161c92dec604f68592`. It binds
runtime-owned caller identity, suppresses ordinary native dispatch for the enrolled
endpoint, and spends a durable one-call fence before the Desktop write. The approved
trial can retain a live source; post-source-exit lifetime remains a separate claim.
Independent review and final-head CI passed. Both clean checkouts include the merge
at `dc78a30368299ead3d18d6ac971681c53211f59b`; the required installed wrapper and
health/status/queue/embedding checks passed.

The delegated target bootstrap returned not registered and exact discovery found
no endpoint. SessionStart explains its saved identity; no UserPromptSubmit marker
update, registration intent, or prompt-hook context was observed. The host's exact
reason is unknown. One interactive composer turn in the same disposable target is
needed to check registration before the timed trial. No trial authority was enabled
or payload sent. Genuine unloaded-target payload receipt, post-exit lifetime,
zero-child startup, and general busy-turn safety remain unproved.

[PR #270](https://github.com/rore/Pallium/pull/270) merged test-helper isolation
at `5ed3cf96342d61ff4d3740e800a86e0232f8c28b`. Claude hook tests now rebind wake
directories to temporary state and block unmocked HTTP on a helper-local copy;
installed bindings and process-global HTTP helpers remain unchanged. Caller
red/green coverage, independent review, final-head CI and a disposable-profile
Windows full run (5,771 passed, 34 skipped, 2 expected failures) support the fix.
Earlier intermittent test failures remain unexplained. Both checkouts were
synchronized; the required installed restart and health/status/queue/embedding
checks passed. This is test isolation, not live unloaded-wake qualification.

[PR #269](https://github.com/rore/Pallium/pull/269) merged the native `tools/list`
request correction at `0d82bffbbca551448389d12060854de5c7e0a331`: omit the empty
`params` object so Desktop uses its default. A private-pipe regression reproduced
the invalid-request error before the edit; independent review and final-head CI
passed. This corrects the identified request mismatch; live inventory lifetime
and genuine unloaded delivery remain unproved.

[PR #268](https://github.com/rore/Pallium/pull/268) merged advisory stale-message
reconciliation guidance at `7f4079274c1c7cd83ce17ca945caa7697aa47be5`.
Installed Codex and Claude skill copies match the bundled 3,054-byte guidance;
configuration was preserved. The bounded synthetic comparison demonstrated no
semantic reconciliation improvement, so this is instruction clarification, not
automatic stale-message recovery or completed unloaded-wake qualification.

The wake architecture review in [PR #258](https://github.com/rore/Pallium/pull/258),
sanitized native failure diagnostics in [PR #259](https://github.com/rore/Pallium/pull/259),
and SQLite wake authority in [PR #260](https://github.com/rore/Pallium/pull/260)
are merged and installed at `936f20aedf2a6bb7cd7b136cb5b1cc24a801529f`.
The required service wrapper drained the old owner before verified database and
legacy-file backups, then imported and verified all six reservations (four accepted,
two uncertain), preserving the legacy bytes. Restart, service, queue and embedding
health checks passed. This replaces reservation-file writes with transactional
SQLite authority; conservative native retry behavior is unchanged.
[PR #261](https://github.com/rore/Pallium/pull/261) subsequently shipped duplicate-aware
hook/MCP envelopes at `a91dac91d54941a91f0a04711e78a79061e2f27d`, with the required
installed restart and health checks passing. Claim-attempt metadata and stable-ID
guidance fit existing budgets; previews may shorten, with continuation preserved.
These fields do not prove prior emission or completed actions.
[PR #262](https://github.com/rore/Pallium/pull/262) shipped wake-health reporting in
the status API and existing dashboard Relay panel at
`2311fe0159553c113d1728b0aabf30c4e6a81e51`. The installed wrapper and service,
queue and embedding checks passed. Scheduler health and uncertain deliveries are
reported separately; this does not establish recipient reachability.
[PR #263](https://github.com/rore/Pallium/pull/263) adds a 24-hour default for new
messages and replies, explicit null for durable delivery, and dashboard age counts
at `f940e02b6abf9bf174658e6aa8fffc6cae2bfaf3`. Existing assignments and expiry
values remain unchanged, including idempotent retries. Physical history retention
and disposition of old durable backlog remain separate work; no purge is included.
[PR #264](https://github.com/rore/Pallium/pull/264) safeguards the existing trace
cleaner at `e9eaefee9a6efd3df91f160a689950ee7fc4e3fc`: an attempt with active,
reserved, missing or mismatched delivery references is retained. Eligible terminal
diagnostics keep the existing 30-day/cap policy and 64-row batch. Message payloads
and stable IDs remain untouched. Earlier discovery incorrectly said no time-based
trace cleanup existed; the shipped Work Record now records that correction.
The one-lifetime-rescue retry proposal was deferred because its permanent state
offers limited recurring recovery. Retry behavior is unchanged.
[PR #266](https://github.com/rore/Pallium/pull/266) adds fixed diagnostic stages
for individual inventory-response validation checks. Response acceptance,
authority, custody and public failure behavior remain unchanged. Both Linux CI
suites and Windows smoke passed; the installed service wrapper and health,
queue and embedding checks passed. A bounded trial localized rejection to the
first response envelope. [PR #267](https://github.com/rore/Pallium/pull/267)
adds fixed labels for two exact known error envelopes without accepting either
response or changing authority. It is merged and installed at
`dfcd35abc5690cfb88f91bf7a7646cc3b6871c1f`; required CI, independent review,
installed restart, and service, queue and embedding checks passed. The actual
Desktop error branch remains unproven. The next bounded diagnostic trial must
verify the registration tool through discovery before arming; model self-report
alone does not establish catalog absence.
Unloaded-session delivery and the source-child lifetime witness
remain unproven; this rollout makes neither claim.

The Windows/Linux Claude wake foundation, loaded-task Codex wake, Codex first-run
setup, MCP recovery integration, and live no-manual-turn reply/remediation journey
are shipped. RW-024 removed unsafe unattended Codex cold resume: unloaded tasks
retain Pallium's pending next-turn delivery instead. PR #209 added exact-delivery
hook-start, payload-emission, ACK, and bounded-failure evidence. An installed
busy-to-idle witness then delivered and ACKed once after one native submission;
that proves the normal safe-turn path, not recovery from uncertain native failure.
RW-031 diagnostics are shipped. The reviewed supported public CLI and app-server
surfaces still lack owner-routed cold activation and caller-idempotent admission/
readback for uncertain public-CLI submissions. Replaying an execution descriptor
would start another runtime, not wake the Desktop-owned task. A private Desktop
owner bridge is now experimentally feasible: one combined native-plus-owner cold
trial delivered through the trusted hook once, without proving loading causality
or busy-safe admission. Its integration is separate from the supported public-path
limit and does not change shipped loaded-task behavior. RW-034 separately reduces avoidable
hook response timeouts for exact loaded-task wakes; it does not change native
uncertainty or make cold activation automatic. Session-to-work associations are
complete. RW-035 has a shipped forward exact-claim fence fix; the
umbrella remains queued for other runtime and platform qualification below.

The optional Codex MCP Desktop bridge **inert lifecycle foundation** shipped in
[PR #252](https://github.com/rore/Pallium/pull/252) and was installed at
`bce09405353f7c9d968d12f3c57c260db993f0a9` on 2026-09-27. Installed service,
queue and embedding health passed. It remains off by default and makes zero
Desktop/service bridge calls. This milestone is not automatic unloaded delivery.

The Windows **shadow-only enrollment and observation** slice shipped in
[PR #255](https://github.com/rore/Pallium/pull/255), merged at
`2e3f9316f20fdbb6d6c81f18f967f679ef6321c7`. It adds a protected local pipe,
one explicitly approved pair, finite process-local enrollment and read-only Relay
observations. Real stdio-to-native-pipe-to-SQLite coverage and Linux/Windows CI
passed; the final local suite passed 5,461 tests. It remains off by default.
A finite shadow-only policy was provisioned for the supervised trial below and
then revoked and removed; no wake action was enabled. Actual native
anchors remain held because their trace correlation is insufficient. Desktop
child lifetime and zero-child bootstrap remain unqualified. Trusted-child
assertions use the documented trusted-local boundary, not Desktop attestation
or isolation from compromised same-user code.

The first supervised 2026-09-28 trial reached one genuine user turn in the existing
disposable Desktop chat. Neither dedicated shadow tool was exposed, so the chat
stopped without enrollment, status calls or retries. This result alone does not
distinguish project trust, cached configuration or an MCP launch failure. Existing
trial logs did not establish the cause. Subsequent source inspection and the
fresh-chat trial below established a usable configuration-loading path; do not
repeat the existing-chat experiment or assume a per-server restart control.

Cleanup completed through the shipped revision-checked provisioning command and
required service wrapper: the pair was revoked, the service drained, and exactly
five owned trial files and two empty directories were removed after identity,
ownership and hash checks. Normal service, embedding and queue health passed.
Global configuration was preserved; model, effort, approval and effective access
were unchanged. Raw permission-profile labels and duplicate entries differed, so
the full context was not byte-identical. No Relay message was sent; target pending,
claimed and matching reservation counts remained zero. Child startup/lifetime,
natural unload and zero-child bootstrap remain unqualified. Next-natural-turn
fallback does not satisfy automatic unloaded wake. No live configuration remains
armed; the recurring manager follow-up was paused at that stage.

The later fresh-chat trial in the separate approved test project exposed both
shadow tools before policy provisioning. App-created/delegated turns did not
register a Relay endpoint: matching Codex source runs UserPromptSubmit for user
input but not function-call-output or inter-agent input. One ordinary user message
then established a provider-confirmed endpoint, with pending/claimed/reservation
counts zero. The user turn also supplied a broader writable Documents/Codex root;
the current host-provided context was accepted and preserved, not described as
unchanged from the initial delegated turn. Normal project trust was preserved.

A finite policy for that exact fresh pair was provisioned and service health
passed, but automatic approval review rejected enrollment before execution because
the target retained the user's earlier no-tools instruction. Status was not called
and no retry occurred. That attempt did not test enrollment. The policy was revoked through
revision-checked provisioning, service storage removed, and normal service,
embedding and queue health verified. A failed stop caused by an already-absent PID
was recovered with one evidence-based invocation of the required wrapper.

At that checkpoint, project cleanup was incomplete: Windows accepted deletion of the exact owned
config and empty directory, but the directory remained visible and reopening it
returned access denied. A retained handle is possible, not proven. Original file
identities, owner and config contents were verified; a narrowly reviewed exception
allowed only the recorded additive ACL changes while preserving parent permissions.
No ACL reset, forced handle close, shared process kill or Desktop restart occurred.
Native status queries subsequently proved STATUS_DELETE_PENDING for both paths.
Normally archiving only the idle disposable released them; native absence checks
then passed, without a Desktop restart or permission change. The user explicitly
lifted the earlier no-tools restriction in the restored chat.

The next finite window still did not exercise enrollment: the restored chat had
no callable shadow entry, despite the earlier fresh-load catalog success. That
evidence was incorrectly reused across archive/restore. Ordinary MCP servers were
ready in the bounded log evidence; no shadow-server startup was recorded. This
does not establish a native enrollment failure. Cleanup archived the idle test
chat before project-file deletion, revoked the exact policy, removed both temporary
directories and restored normal service with all health checks passing. Global
trust, settings and empty delivery/reservation state were preserved. Shadow
authority is off and namespace cleanup is complete.

The replacement fresh chat remained loaded through an explicitly authorized
enrollment/status attempt. Both actual MCP calls succeeded exactly once: enrollment
returned `enrolled` / `ok` with a 300-second grant; status returned `inactive` /
`observed` with 294 seconds remaining. This proves eligible Desktop-launched MCP
startup, inherited capability presence, genuine request metadata and enrollment
through Pallium's protected native pipe. Neither shadow tool connects to Desktop;
the result does not prove use of Desktop's app-tools connection or automatic wake.
The idle test chat was normally archived before cleanup. Revision-checked revocation,
owned-file removal and the required service restart completed; service, embedding
and queue health passed. Temporary authority/configuration are absent, global
configuration and effective caller settings were preserved, and target pending,
claimed and matching reservation counts remain zero. Child lifetime/unload and
zero-child bootstrap remain unqualified. The next architecture decision is executor
availability; do not repeat enrollment or restored-chat configuration investigations.
The design document's header still describes shadow implementation as under review;
PR #255 and this live enrollment result supersede that stale delivery status.

A user-operated Desktop restart on 2026-09-28 was captured by an independent
PowerShell process. The capture shows the old Desktop/app-server/MCP processes
disappearing, followed by a new Desktop at 14:33:39 UTC and new MCP children at
14:33:50 UTC. Surviving process identities resolve to the installed Pallium MCP.
However, Desktop logs show automatic chat restoration beginning at 14:33:49 UTC,
before the first captured MCP child; Pallium became ready for a restored chat at
14:33:58 UTC. This qualifies ordinary MCP startup during Desktop chat restoration
without a new user turn, not executor availability with zero loaded chats. A
null-thread MCP inventory request also overlapped this startup, but the capture
does not attribute individual children to that request or establish its lifetime.
No bridge opt-in, grant, wake action or settings change was made for this witness.
Do not repeat the same restart while automatic restoration confounds the question.

Exact-version source resolves the separate discovery-lifetime question. The
[status handler](https://github.com/openai/codex/blob/0d9c7cbfa6cf1489f55a8a9542b75ddd2c061807/codex-rs/app-server/src/request_processors/mcp_processor.rs#L268)
uses a threadless snapshot for a null-thread request. Its
[snapshot implementation](https://github.com/openai/codex/blob/0d9c7cbfa6cf1489f55a8a9542b75ddd2c061807/codex-rs/codex-mcp/src/mcp/mod.rs#L485)
creates a local eager connection set, cancels startup at completion and returns
only snapshot data; connection destruction cancels its client token. This path
cannot supply a persistent executor. It does not prove which captured PID served
which request, or rule out every other host mechanism. The earlier supported-only,
child-owned custody constraint is superseded by the reviewed continuation below;
a detached helper or competing Codex runtime remains outside scope.

The task owner accepts useful partial coverage after normal use of one chat.
Before-first-chat availability after Desktop restart is not a prerequisite.
The accepted next slice is a default-off, inventory-only connection owned by the
existing Pallium service after explicit handoff from a legitimate MCP child.
Independent security review required distinct finite inventory authority, separate
from shadow enrollment and endpoint possession; the corrected plan is accepted.
Implementation shipped in [PR #256](https://github.com/rore/Pallium/pull/256); see
the [Work Record](../../.agent-workflow/tasks/codex-service-custody.md). The
default-off, inventory-only service-custody foundation was installed on
2026-09-28. It permits only the reviewed finite handoff for fixed inventory reads.
The child-exit custody witness is pending; this installed transport foundation does
not establish unloaded-recipient delivery or wake authority.

One exact child/service/Desktop process tuple may authorize one RAM connection.
Only fixed native tools/list is permitted in this slice. A bounded disposable
trial must observe the originating child actually exit, then successfully list
on the retained service connection. Archive alone is not exit evidence. A passing
transport test leads directly to a separately reviewed unloaded-recipient delivery
witness; it does not establish wake authority or delivery by itself. Service loss
requires normal-use bootstrap; Desktop loss invalidates the old connection.
Persistent credentials, automatic zero-child startup and an exhaustive restart
matrix are deferred. Existing uncertain-action fences and deferred busy-turn
semantics remain unchanged. No live handoff or new wake is armed; the manager's
recurring follow-up is active.

Remaining work:
- Qualify actual Desktop child startup/lifetime for the
  [optional Codex MCP Desktop bridge](../../docs/designs/codex-mcp-desktop-bridge.md);
  live enrollment passed as recorded above. One private offline exact-owner launcher-exit check passed:
  the child survived launcher exit, exited within a finite bound, and fake-baseline
  restoration cleaned only the exact owned files and root. This proves only the
  tested offline launcher-exit and cleanup path. Read-only inspection of installed process
  topology confirms ordinary Desktop → Codex → venv launcher → base interpreter MCP
  startup; it does not prove Desktop steering/cancellation, live inert-child lifetime,
  usable Desktop connection, or zero-child bootstrap. Earlier temporary opt-in attempts
  remain inconclusive: Desktop rejected programmatic initialization, and manual
  preparation initially ended before an observed user turn. The subsequent
  first supervised user turn found neither dedicated tool; the later fresh-chat
  catalog and registration checks passed as recorded above. Namespace cleanup is
  complete, including the successful replacement trial. Existing `env`/`env_vars`
  and server eligibility already express inert
  opt-in, so no new setup feature is needed. Live configuration remains held.
  Qualify service-owned connection lifetime after normal-chat bootstrap, then
  unloaded-recipient delivery. Automatic startup before any chat is deferred;
  host-safe admission including cold-to-busy races remains a separate requirement.
  New grants or generations must not bypass uncertain action fences.
  This is work in progress, not shipped automatic unloaded delivery.
- Qualify still-unproven interrupted/restart combinations with a bounded matrix
  of runtime, platform, interruption, existing evidence, and missing witness.
  Reuse passed recovery tests and live witnesses; do not repeat them without cause.
- Qualify Claude/Codex on macOS when that platform is needed.
- Implement and qualify OpenCode automatic activation. Its existing Relay
  integration and claim-timeout fix do not establish automatic wake support.

OpenCode wake remains a dependency of Copilot expansion. These residual gates do
not block activation capabilities, traces, work associations, or future
Claude/Codex workflow examples. A new correctness incident takes priority if one is found.
The milestone and incident history below preserves evidence; it is not a list of
new implementation tasks.

### Current readiness tracks

| Track | Owner | Next action |
|---|---|---|
| `RW-027` hook readiness | `.agent-workflow/tasks/codex-integration-readiness.md` | Keep hook definition stability and review visibility observable; run the real installed Codex task witness after stable reinstall. |
| `RW-028` Codex MCP exposure | host recovery follow-up | Same-host/project tasks expose different tool catalogs, including zero Pallium tools after successful hook delivery. Treat this as a Codex host registry/rehydration blocker; do not infer MCP health from hook/service health or add a speculative Pallium workaround. |
| `RW-029` stranded split identity | guarded Relay operations | Use the offline repair manifest for reviewed per-delivery dispositions. Version 2 can explicitly suppress a finite expired claim; it still refuses adoption, active or ambiguous claims, and automatic cleanup. |
| `RW-030` Claude install drift | installed integration lifecycle | Repoint the user-scoped Claude MCP and hooks from the development checkout to the stable installed checkout in the coordinated post-merge install window. Existing hosts retain old subprocesses until their normal restart. |
| `RW-031` Codex native activation reliability | automatic recovery blocked by upstream Codex contract | Actionable trace guidance and bounded failure/timing diagnostics explain retained uncertain submissions and help classify the next occurrence; they do not repair one. For uncertain Codex submissions, use a normal user prompt directly in the existing task: observed app-message delegation did not invoke UserPromptSubmit. Keep the delivery pending; do not resubmit or launch a second runtime. This is manual recovery, not automatic recovery. Revisit automation only if Codex exposes owner-routed cold activation plus idempotent exact-submission admission/readback. |
| `RW-032` compaction-safe Relay scope | recipient context continuity | A loaded Codex wake delivered and ACKed once with trusted scope in the hook-injected context; same-turn compaction later omitted that scope and blocked a scoped follow-up. Investigate runtime-owned identity/tool context or supported trusted reinjection. Do not recover authority from cwd, historical transcripts, or forwarded metadata. This is not a native wake failure or duplicate delivery. |
| `RW-035` loaded Codex claim correlation | `.agent-workflow/tasks/relay-late-claim-fence.md` | Forward fix shipped and installed: a matching exact claim stores same-generation recovery evidence atomically, and an in-flight old callback cannot correlate a replacement fence. Focused callback-loss through recovered delivery, race, migration/restart, and ACK tests pass. Historical accepted/null-correlation reservations remain fenced; the old incident cause is unproven and no live uncertain-native recovery is claimed. |

The dashboard diagnostic is shipped as read-only evidence, not repair. Do not bulk-repair stranded deliveries. The real installed witness gate remains required for send -> next-turn hook claim/injection/ACK -> reply and work-reference attach/detach qualification.
## Summary

Make immediate activation the default for every resolved Relay recipient while
preserving durable next-turn delivery as the automatic fallback. The sender does
not choose a delivery mode: Pallium persists first, uses the recipient runtime's
native wake mechanism when safe, and otherwise leaves the delivery pending.

## Why

Relay does not remove manual coordination if the user must prompt an idle recipient
merely to discover its mail. Claude Code, Codex, and OpenCode expose different
mechanisms for starting or queuing a turn, so Pallium needs small runtime-specific
adapters behind one observable delivery contract.

## Primary Product Outcome

After one user instruction, a developer session and an architect/reviewer session
can carry a bounded implementation-review-remediation exchange through explicit
Relay messages without the user prompting either recipient to check for mail. Each
send wakes the addressed live session, enters its model-visible context exactly
once, and can receive an explicit delivery-derived reply. The user re-enters only
for a permission, product decision, unresolved failure, or requested final result.

This is the main wake validation journey, not a later demo. It does not make
Pallium a team manager: the user still starts the work, agents explicitly choose
when and whom to message, and Pallium only persists, addresses, activates, and
reports delivery. `fix-relay-claim-before-context-emission` (`RF-005`) is a release
prerequisite because both wake and fallback must be loss-safe.

### Milestone order (user priority, 2026-08-31)

1. **Codex↔Codex dogfood first — Windows-qualified:** the existing Codex architect and developer
   sessions exchange a bounded task → result → review → remediation/verdict
   sequence through Relay alone. Send and reply activate the exact recipient in
   both directions; neither the user nor either agent sends a separate ping,
   invokes a wake command manually, or uses an app messaging tool to advance the test.
   Qualify the actual sessions used for work, not just disposable TUI substitutes.
2. **Claude↔Codex next — Claude wake qualified on Windows and Linux:** the
   cross-runtime journey is proven without a manual recipient turn. Claude macOS
   and Codex macOS qualification remain S4; neither reopens milestone 1.
3. **OpenCode later:** add its adapter after the first two milestones.

Milestone 1 includes the smallest persist-first coordinator needed by Codex,
dedupe, correlated admission, loss-safe active-writer fallback, wake/fallback claim-race protection,
restart/ambiguous-outcome recovery, expiry, bounded bursts/replies, and visible
fallback reasons. Exercise these through caller-surface regression tests plus a
live no-ping round trip; update local Codex integrations before acceptance.
Use the existing Relay developer session for implementation and architect review,
not a substitute subagent. Other runtimes retain next-turn delivery.

This is an independently acceptable dogfood milestone, not completion of the full
wake feature. Enable only qualified runtime/OS combinations; cross-platform
support remains required and unqualified combinations stay passive.

## Delivery Contract

1. Persist the message and immutable per-recipient deliveries before attempting
   activation.
2. For every resolved recipient, use its advertised wake capability by default;
   there is no sender-side `wake` option.
3. If idle, start a new turn. If busy, queue a distinct turn at the runtime's safe
   boundary; never steer Relay text into an active human-owned turn.
4. Mark the delivery complete only when the runtime confirms admission into the
   recipient context. A trigger request or transport acknowledgement is not enough.
5. If activation is unsupported, disabled, unavailable, stale, or fails, leave the
   same delivery pending for the existing next-natural-turn path. The immediate
   S2 contract gate below may add a terminal outcome only from separate,
   proven-terminal delivery evidence. Destination health never terminalizes an
   existing delivery; missing wake capability, ambiguous transport, and temporary
   runtime absence remain durable fallback, not failure.

Track activation separately from the durable delivery lifecycle. Operationally,
Pallium must distinguish `queued` (persisted, not activated), `triggered` (a runtime
turn was requested), and `delivered` (the runtime admitted the message). Never call
a message read, understood, or used. Stable message and delivery IDs must make wake
retries, runtime callbacks, and hook fallback idempotent.

## Runtime Feasibility and Constraints

Deeper source review on 2026-08-26 corrected the initial Phase 0 verdict. The
installed versions are Claude Code 2.1.250, Codex CLI 0.149.1, and OpenCode
1.18.19 on native Windows.

| Runtime | Current verdict | Proven mechanism | Remaining qualification |
|---|---|---|---|
| Codex | **Windows and Linux exact-session wake proven for runtime-loaded tasks; Windows overtaken-wake suppression proven** | Pallium writes a generic trigger through `codex queue --thread` from a validated neutral Codex home. The cross-process watcher starts a real turn when the target is loaded; for an unloaded target, Pallium keeps the Relay delivery pending until a later supported hook turn. Native unloaded-queue persistence is not claimed. The installed UserPromptSubmit hook claims and injects only after admission, and blocks an exact internal wake without verified rendered delivery before memory or model work. An installed Ubuntu 24.04 / WSL2 witness with Codex 0.153.4 proved loaded exact-session automatic wake, hook delivery, and return to idle. | Windows and Linux loaded-task live send → wake are proven. Windows atomic reply, reply-only idle-sender wake, and a no-manual-turn remediation round trip are proven. Do not claim unattended unloaded-task resume without a supported runtime workspace API; qualify macOS and remaining interrupted/restart variants before calling the adapter cross-platform complete. |
| OpenCode | Supported with a Pallium/OpenCode plugin coordinator | Server/plugin APIs expose stable sessions and async prompts. Agent Intercom demonstrates persist-first delivery, application metadata correlation, history verification before replay, safe busy deferral, and restart recovery. | A bare prompt_async 204 is transport acknowledgement only. Pallium needs the plugin-owned durable pending ledger and a Windows E2E proof. Deferred to after Claude Code wake is proven. |
| Claude Code | **Windows and Linux S1A+S1B qualified** | Installed Windows and Ubuntu 24.04 / Claude Code 2.1.250 witnesses proved native peer Relay → exact restart-surviving capability → Stop claim/injection/ACK → Claude reply without another human prompt. Linux used the installed UDS path. | Installed UDS qualification on macOS remains S4. |

**Claude registration foundation:** Windows and Linux S1A+S1B are live-witness qualified: trusted-local exact-session persistence, write-ahead intents, fail-closed rehydration, and event-driven idle-pending reconciliation survived the installed witnesses. The Linux witness used Ubuntu 24.04, Claude Code 2.1.250, and the installed UDS path. No DPAPI, silent time expiry, or lifetime redesign was added. Installed UDS qualification on macOS remains S4.
### Admission handshakes to preserve

**Codex:** Write one generic trigger through hidden `codex queue --thread` from a validated resolved local Codex home. The owning runtime watcher starts a loaded task; for an unloaded task, Pallium keeps the Relay delivery pending until a later supported hook turn, without relying on native queue persistence. After admission, the installed UserPromptSubmit hook claims and injects the bounded backlog under the target's pinned scope, then acknowledges hook delivery. If the exact internal wake cannot render a verified delivery because the response is empty, unavailable, malformed, timed out, or invalidly scoped, the hook emits Codex's native structured block decision before memory or model work. Queue launch failure leaves the delivery pending for startup/periodic recovery or ordinary next-turn delivery. No private App Server attachment or Codex state lookup is required.

**OpenCode:** the plugin persists the Relay item before broker acknowledgement,
checks recent session history for metadata.palliumRelayId, defers submission to a
safe boundary, calls the supported prompt API, and marks admission only when
session messages/events contain that exact ID. On restart it replays only items
not proven admitted. A server plugin can cover normal OpenCode sessions without
requiring every session to be launched by a Pallium wrapper.

**Claude Code:** Native peer frames start text turns but Claude 2.1.250 classifies them as internal `isMeta` events, so S0/S0.5 are misqualified for UserPromptSubmit admission. Claude reproduced S1A Stop continuation: every Stop registers idle; a non-recursive Stop makes one exact-scope `/relay/turn` with authoritative storage `max_chars=2360`, route admission marks busy, and renders the returned claimed set plus any compact backlog notice inside a fixed 2,400-character output budget, emits that exact set to stderr, then ACKs the emitted claims individually before exit 2 requests one continuation. Partial failure leaves unACKed claims lease-recoverable; all failure exits 0 and every non-continuing path re-registers idle after route admission. Storage budgets the exact emitted control template. `has_more` and `remaining_count` remain pending and are qualified under S1B rearm/continuation; the S1A witness historically proved one bounded batch. The `stop_hook_active` continuation Stop re-registers idle, ingests, and exits 0 without re-probing. No MCP/pin change belongs in S1A; durable state/reconciliation is S1B.

Each live session advertises only capabilities its integration actually proves:
passive, idle_wake, and busy_queue. Missing, expired, disabled, or lost capability
selects durable fallback. Runtime names are never global capability claims, and an
exited arbitrary process is not wakeable merely because its conversation can be
resumed by launching another process.

### Remaining production gates (priority updated 2026-09-07)

Gate each runtime independently. Claude Windows and Linux live wake evidence is
complete; only installed UDS qualification on macOS remains for that adapter.

1. **Codex-first product gate:** Windows exact-session wake is proven for tasks
   loaded by the Desktop-owned runtime through the cross-process queue watcher.
   Unloaded tasks retain Pallium's pending delivery until a supported hook turn;
   native queue persistence and unattended cold resume are not claimed. A real `codex:@relaydev` run received
   two outstanding attributed deliveries in one wake batch and atomically replied
   to both without a user ping or approval prompt. On 2026-09-08, live message
   `relay-msg-f07d6ebe0c054e4fa38872ef8a3393d7` reached the real concurrent
   Codex owner; its delivery-derived reply resumed the idle sender solely through
   Relay. The sender then issued remediation
   `relay-reply-5b5235201e41cfa596205f632ffbac301d41bae78c5628a9bec52a6e136a7710`,
   which the recipient admitted without a manual turn and answered `APPROVE`; the
   reply again resumed the idle sender. Sender-side reply admission and the bounded
   no-ping remediation journey are therefore proven. RW-026 closes the concrete
   wake-correlation diagnosis gap without changing delivery behavior. Remaining
   value gates are interrupted/restart reliability and macOS qualification when
   demanded.

2. **Claude Code production gates:** Windows S1A+S1B and installed Linux UDS
   live journeys are proven. Installed UDS qualification on macOS remains S4.
3. **MCP receive lifecycle foundation — shipped and Windows-qualified:**
   PR #99 provides runtime-owned per-call task identity and integration reload;
   the S2 evidence below records the completed recovery gate. It remains a
   separate fail-closed recovery path and must not be mixed with hook delivery.
   Qualification on another runtime/platform requires its own evidence.

### Next execution order (updated 2026-09-22)

RW-017 durable-by-default delivery, RW-016 installed-service metadata repair,
RW-018 taskkill race recovery, RW-019 Relay load resilience, and RW-020
diagnostic/restart readiness are merged and Windows-qualified. RW-026 closes the
concrete wake-correlation diagnosis gap without changing delivery behavior. The
2026-09-08 live gate completed sender-side reply admission and the no-ping
remediation journey.
The closed-recipient lifecycle slice subsequently shipped in PR #148 and
first-run setup qualification completed on 2026-09-08. Retention cleanup is paused
pending operational evidence. Relay reliability remains first: qualify the current hook-definition readiness and exact-recipient diagnostics before new wake-first activation qualification. Other activation capabilities, traces, work associations, and Claude/Codex validation may proceed independently. Wake-first retains the residual qualification listed at the top of this file; macOS is demand-driven and OpenCode activation precedes Copilot.

1. **S2 contract gate — complete in PR #98.** Delivery lifecycle
   (`pending`, `claimed`, `delivered`, `expired`; `failed` only on separate
   proven-terminal delivery evidence) remains independent from advisory destination
   health (`active` or `unreachable`). Destination-health transitions never
   change an existing delivery. Missing capability and recoverable or ambiguous
   transport leave it pending and retryable; advisory `unreachable` may reject new
   sends and clears on successful exact-session registration.
2. **S2 wake feedback and destination health — complete in PR #98.** Qualified
   Windows missing-pipe and POSIX missing-socket signals retain the durable
   registration as non-probed `unreachable`; the in-flight delivery remains
   pending. New exact/alias sends fail fast, strict timestamp CAS drops stale
   feedback, and successful exact registration restores both stores. Relay API
   status exposes delivery state and `destination_health` separately.
   Deterministic caller-surface review and installed Claude/Codex automatic-wake
   witnesses passed before merge.
3. **S2 Codex burst coalescing and overtaken-wake suppression complete.**
   PR #95 coalesces scheduling through admission. Because a native prompt already
   accepted by Codex cannot be cancelled, the exact internal trigger emits a native
   structured block decision only when a successful hook-time Relay turn confirms
   the complete canonical no-work state (`deliveries=[]`, `has_more=false`,
   `remaining_count=0`). Caller-surface coverage retains an accepted prompt, lets
   a competing real hook claim and ACK first, then proves the redundant prompt
   stops before memory/model work without losing or duplicating delivery. The
   installed Windows witness queued the exact trigger and recorded hook context then
   `task_complete` with `last_agent_message=null`, no user or assistant transcript
   item, and no requeue.
4. **S2 Codex MCP recovery and integration reload — complete in PR #99.**
   Runtime-owned per-call MCP metadata supplies exact task identity; inherited
   parent IDs and model arguments are ignored. Missing, malformed, or conflicting
   metadata fails closed before Relay HTTP with reload/upgrade guidance. Real
   stdio E2E and an installed fresh-session witness prove exact receive/ACK.
5. **S2 bounded backlog draining — complete in PR #101.** Default-three hook
   turns, continuation, new arrivals, ordering, oversized-first handling,
   duplicate-trigger loop prevention, and installed Codex plus Claude witnesses
   are complete. Keep the current three-message / 2,400-character limits until
   real burst measurement justifies a change.
6. **S3 Codex admission hardening — complete in PR #108; Windows-qualified
   (RW-015).** Exact session+container+actor ownership, launch outcome
   classification, strict-CAS unreachable feedback, deterministic caller-surface
   E2E, and a post-merge no-manual-turn installed witness are complete. Native
   accepted or timed-out queue writes remain coalesced because duplicate
   suppression is false.
7. **RW-017 durable-by-default Relay delivery — complete in PR #113 and
   Windows-qualified.** Omitted/null expiry now stays durable until terminal handling;
   explicit 60-second through 7-day expiry remains opt-in. Fast file-backed restart,
   dormancy, backlog, idempotency, dashboard, MCP, and installed automatic-wake
   evidence pass without wall-clock waits.
8. **RW-016 Windows installed-service metadata — merged and Windows-qualified.**
   Canonical startup carries the exact quoted home in BOM-marked UTF-16 launcher
   metadata; restart PID/log paths follow that home, malformed canonical metadata
   fails before stop, and legacy default-home launchers remain compatible. PR #114,
   deterministic default/custom/space/Unicode/literal-percent coverage, and an
   installed exact-home restart with healthy endpoints are complete.
9. **RW-018 Windows taskkill race recovery — merged in PR #115 and
   Windows-qualified.** A partial child-exit failure no longer skips later exact
   sweeps. The wrapper warns, kills every unique initial listener, verifies
   post-settle port quiescence, blocks a surviving listener before task start, and
   returns explicit success. Deterministic caller-surface coverage, green CI,
   independent review, the installed orphan-respawn replay, and exact-main healthy
   restart are complete.
10. **S3 reply/remediation gate — complete 2026-09-08.** Live request
    `relay-msg-f07d6ebe0c054e4fa38872ef8a3393d7` produced a delivery-derived
    reply that resumed the idle sender solely through Relay. Remediation
    `relay-reply-5b5235201e41cfa596205f632ffbac301d41bae78c5628a9bec52a6e136a7710`
    was admitted without a manual recipient turn, answered `APPROVE`, and again
    resumed the idle sender. No product defect appeared, so no production code or
    speculative correlation telemetry was added.
11. **Codex first-run setup qualification — complete 2026-09-08.** Setup now
    reports configuration installed and requires a Codex restart plus hook review
    if prompted before Relay wake is ready. An isolated Windows Codex 0.149.1 home
    showed all three hooks as new, persisted their trust only through Codex's review
    UI, ran SessionStart, UserPromptSubmit, and Stop, and returned the bounded witness
    response. No trust bypass or Pallium trust write was used; live Pallium hook
    trust entries remained unchanged.
   This setup gate is separate from runtime transport qualification.
12. **S4 additional platforms.** Qualify installed Claude UDS and Codex wake on
   macOS. Windows/Linux Claude and Windows/Linux loaded-task Codex wake remain
   complete and must not be reopened without contrary evidence.
13. **OpenCode active wake.** Implement only after the Claude/Codex contract above
    is stable; retain its current passive next-turn delivery meanwhile.

### Wake dogfood defect ledger

Every confirmed dogfood failure stays here until a caller-surface regression and,
where the runtime exists locally, an installed witness close it.

| ID | Observed failure | State and owner |
|---|---|---|
| `RW-001` | A busy Codex wake claimed at scheduling time; queued execution after the 60-second lease produced a stale receipt conflict. A related Windows CP1252 write stranded a claimed Unicode delivery. | **Fixed.** Claim now occurs in the admitted UserPromptSubmit hook and subprocess input is UTF-8. Delayed deterministic caller-surface and Unicode regressions cover both paths. |
| `RW-002` | Several close sends queued later generic Codex turns after the first admitted turn had already drained the payload, producing empty conversational acknowledgement turns. Live dogfood later reproduced the remaining race: Codex had already accepted one native queued prompt before a competing admitted turn consumed the delivery. | **Fixed and Windows-qualified; strengthened by RW-019.** PR #95 coalesces Pallium scheduling through admission. The exact internal hook trigger now blocks before memory/model work whenever it cannot render a verified delivery, including canonical empty, failure, timeout, malformed response, or invalid scope; ordinary prompts remain fail-open. Deterministic caller-surface coverage preserves successful delivery and prevents empty conversational turns. |
| `RW-003` | An agent treated one stale/duplicate receipt conflict as a reason to stop the surrounding task, and terminal reports triggered wasteful status-only replies. | **Fixed.** Installed guidance says the stale rule applies only to that delivery, work continues independently, substantive replies wait for completion or blockage, and terminal ACK-only deliveries receive no reply. `test_guidance_budget.py` and hook guidance tests pin the contract. |
| `RW-004` | Pallium restart lost in-memory Claude wake capability, so pending Relay work required a manual Claude turn. | **Fixed and Windows/Linux-qualified.** Durable exact-session capabilities, write-ahead intents, event-driven reconciliation, restart recovery, and installed no-manual-wake evidence are on `main`; macOS UDS remains S4. |
| `RW-005` | Missing Claude endpoints were evicted while deliveries stayed pending; restart feedback was omitted, transient callback failure could diverge the two health stores, and a late-bound recovery callback could update the wrong session. | **Fixed in PR #98.** Retained non-probed `unreachable`, strict stale-feedback CAS, exception-safe retry, bound per-candidate callbacks, self-healing registration, status exposure, deterministic E2E, and installed witnesses are complete. |
| `RW-006` | A Codex MCP child can lack runtime-owned session identity or inherit another Codex task's forwarded identity and claim the wrong inbox. | **Fixed.** Per-request Codex transport metadata is authoritative; inherited `CODEX_*`, configured thread values, and model arguments are ignored. Missing/conflicting/malformed identity fails closed before HTTP. One-child real-stdio E2E covers exact ASCII/Unicode receive+ACK, max-boundary receive validation, and refusal paths; the installed synthetic witness returned the exact new Codex task ID instead of the outer ID. |
| `RW-007` | A bounded turn can report `has_more` and `remaining_count`, but integrations did not prove automatic bounded continuation until the eligible backlog was empty. | **Fixed in PR #101 and Windows-qualified.** Default-three hook turns, fixed character reservation, Codex post-ACK continuation, Claude Stop/recovery continuation, safe candidate selection, caller-surface edge coverage, and installed automatic 3+2 Codex plus Claude wake witnesses are complete. |
| `RW-008` | Crash after claim but before context injection recovers the lease, yet may wait for a natural turn instead of being re-woken automatically. | **Fixed in PR #102 and Windows-qualified.** A read-only exact-session sweep re-wakes eligible expired claims at startup and every 30 seconds through the existing adapters. Deterministic Codex/Claude restart E2E and an installed Codex witness prove automatic reclaim, single ACK, and terminal empty state after the 60-second lease expires. |
| `RW-009` | Wake E2E leaked synthetic memory into the live store; the observed `a043f627-...` object appeared under `other`. | **Fixed; reversible cleanup complete.** The unmocked live request is covered. The exact historical set was tagged `rw009-synthetic-wake-e2e-leak`: 23 source items were forgotten and 89 derived memories soft-deleted. The default dashboard read path now returns zero visible rows for the contaminated container; audit mode retains all 89 memories, including the cited object, for recovery. |
| `RW-010` | The Windows restart wrapper could stop a healthy service while a checkout was mid-edit, reject the canonical task shape, target the wrong configured port, miss a surviving canonical service process, and print success before all required endpoints were ready. | **Fixed and Windows-qualified.** Preflight resolves both observed task shapes, preserves optional/Unicode working directories, validates the installed port before stop, sweeps canonical `service run` while preserving MCP bridges, and gates success on all three endpoints with bounded actionable failure. Fast real-script coverage is in the Windows smoke job. The installed legacy-task witness exited 0 after cold start; `/health` was `ok`, embeddings and ingestion were healthy, and queue health returned HTTP 200. |
| `RW-011` | A delegated agent can end or fail a model turn after hook delivery without the sender knowing whether requested work completed, causing manual polling or a stalled workflow. | **Optional product follow-up.** `idea-agent-relay.md` owns default-off `notify_on_turn_end`; it reports turn end/failure only and never reclassifies context delivery, infers task completion, or supervises work. |
| `RW-012` | A normal hook-injected delivery reached an agent without the trusted container and actor scope needed by `pallium_relay_reply`; reply failed closed and encouraged an out-of-band fallback. | **Fixed in PR #105; Windows-qualified.** Codex and every Claude hook delivery surface now append independently bounded exact scope before ACK; unsafe scope never claims. Real Codex queue and Claude UserPromptSubmit/Stop journeys parse that hook output and complete receiptless atomic replies, with wrong-scope, Unicode, maximum-boundary, backlog, and idempotence coverage. An installed Claude witness auto-woke, parsed the hook scope, and completed the exact receiptless reply without a manual turn or MCP receive. |
| `RW-013` | A Claude session reported its alias handle as `claude-code:claude_arch`, omitting the required `@`; the resulting exact-session selector returned 404 while the UUID worked. | **Fixed in PR #107; Windows-qualified.** Recipient pages now emit canonical `exact_selector` and `alias_selector` values. Existing routing was not rewritten: `codex:@relaydev` dogfood delivered and received `alias-ok`; caller-surface lifecycle coverage pins naming, transfer, close, exact fallback, alias send, filtering, and cross-scope isolation; Codex and Claude configs were reinstalled from clean main. |
| `RW-014` | `pallium_relay_recipients` can exceed the MCP response budget and return only a generic error instead of a usable bounded recipient result. | **Fixed in PR #107; Windows-qualified.** The MCP tool returns stable bounded pages with offset continuation and total count while preserving the HTTP list contract. Deterministic E2E covers all recorded boundaries without wall-clock waits. After reinstall and service restart from exact main, a fresh installed stdio child returned a 1,730-character page with all envelope fields, 5 of 89 recipients, canonical selectors, `has_more=true`, and `next_offset=5`. |
| `RW-015` | Two sends initially appeared stuck behind `destination_health=active`; later durable status and exact-task history proved both hook-delivered, including the vNext target after 57 seconds. The real latent gaps were boolean launch acceptance holding a generation after completed/no-hook exec, session-only admission, and session-only ownership suppressing another scope. | **Fixed in PR #108; Windows-qualified.** Wake ownership is keyed by session+container+actor; blocking exec completion requires the matching hook callback; definite no-hook failure reports strict-CAS `unreachable` without consuming delivery; accepted or timed-out writes stay coalesced. After exact-main reinstall and service restart, `relay-msg-cff1331...` auto-delivered once in 16 seconds and returned `RW015-INSTALLED-PASS` without a manual turn. |
| `RW-016` | Canonical Windows `pallium service install --home <custom>` wrote its task/VBS under the requested home but did not propagate that home to `service run`, so the launched service silently fell back to the default home; the ASCII VBS writer also could not represent non-ASCII interpreter/home paths. | **Fixed in PR #114; Windows-qualified.** Canonical VBS carries the exact quoted home in BOM-marked UTF-16; restart uses that metadata for PID/log paths, missing canonical home fails before stop, and legacy default-home launchers remain compatible. Deterministic CLI plus real-PowerShell coverage passes for default/custom/space/Unicode/literal-percent paths with no Linux code change or wall-clock sleep. The installed task launched the exact-home UTF-16 command and refreshed PID/port with all endpoints healthy. |
| `RW-017` | Relay messages still default to a 24-hour expiry, so unhandled work for a busy or dormant target can become terminal despite durable wake recovery. Dogfood reproduced the default when an omitted MCP expiry returned an `expires_at` exactly one day later. | **Fixed in PR #113; Windows-qualified.** Omitted/null expiry is represented durably without a schema rebuild; explicit 60-second through 7-day expiry remains opt-in. Fast file-backed restart/dormancy/backlog/idempotency/dashboard/MCP regressions pass. Installed dogfood returned `expires_at:null`, auto-delivered once, and produced durable atomic reply `RW017-INSTALLED-PASS` without a manual target turn. |
| `RW-018` | The Windows restart wrapper inherited `$ErrorActionPreference = "Stop"` at native `taskkill /T` calls, so a partial child-exit error aborted before later signature sweeps and task start; an orphan supervisor could then respawn the server while the wrapper failed and PID metadata stayed stale. | **Fixed in PR #115; Windows-qualified.** All tree kills share a best-effort helper with diagnostics, every unique initial listener is handled, later exact sweeps always run, an array-safe post-settle port gate blocks surviving listeners before start, and success exits 0 explicitly. Deterministic thrown/nonzero-kill and initial/persistent multi-listener regressions pass; the original installed orphan-respawn shape restarted cleanly, refreshed PID/port, kept all endpoints healthy, and auto-delivered one Relay wake. |
| `RW-019` | Under concurrent work, sync-route worker starvation made the DB-free health endpoint time out; hook cancellation could leave a late server-side claim; startup recovery ignored never-claimed pending work; pooled SQLite connections repeated lock-taking persistent PRAGMAs; valid raw Relay text could exceed the rendered budget after redaction expansion. | **Fixed in PR #123; Windows-qualified.** Relay has independent capacity and shutdown drain, health stays async, startup recovery covers pending plus expired claims, Codex admission fails closed without a verified delivery, persistent PRAGMAs initialize once, and redaction overflow is bounded safely. Deterministic caller-surface/contention coverage, the opt-in mixed-load witness, full CI, exact-main restart, and installed Relay dogfood passed. Durable cross-process wake reservation remains future scale work. |
| `RW-020` | During an active vector rebuild, the installed restart wrapper exhausted readiness even though the service later became healthy; /status and queue diagnostics previously amplified the delay. | **Fixed in this slice; Windows-qualified.** The wrapper keeps one monotonic deadline and increases only the default from 120 to 180 seconds, placing the documented moments-later recovery class inside one additional bounded minute while explicit budgets remain exact. Existing real-PowerShell lifecycle coverage passes without production-length sleeps. A no-argument installed restart completed in about 68 seconds against the current 11,093-source, 385.62 MB store; `/health` was ok with vectors and embeddings ready, `/status` reported healthy ingestion, and queue health returned HTTP 200. The witness did not naturally trigger a rebuild, so it does not claim a new rebuild-duration measurement. A 2026-09-14 follow-up found queue health taking 2.3–2.9 seconds on the larger live store while each probe was capped at two seconds; queue health now receives up to ten seconds within the same overall deadline. |
| `RW-021` | The filesystem-backed Claude wake reconciler durability test required four retry cycles within one second and flaked under loaded Linux 3.13 xdist even though the Relay delivery remained pending and retryable. | **Fixed in this slice.** The event wait keeps the same four-attempt state contract but uses a five-second failure ceiling and reports observed attempts on failure. It returns immediately on success, adds no sleep, and changes no production wake timing or retry behavior. |
| `RW-022` | A busy Codex target kept one Relay batch pending while periodic recovery blindly resubmitted already accepted native queue prompts. Dogfood recorded at least fourteen successful submissions, followed by thirty empty task starts after the first hook turn delivered the batch. | **Fixed in this slice.** Confirmed and ambiguous non-idempotent native writes now retain one live scheduler generation without blind retry; hook admission still clears ownership and startup still reconstructs pending work. A deterministic HTTP send → real scheduler → six recovery windows → actual UserPromptSubmit hook regression failed 6-to-1 before the fix and now proves one native queue submission, one delivery, empty-wake suppression, and rearm. Exact cross-service-restart deduplication remains part of durable wake reservation. |
| `RW-023` | Claude could discard Pallium UserPromptSubmit output at its eight-second host timeout because the hook's seven-second active-work budget began only after Python startup/imports, leaving just one second for all outer-process overhead. Setup also did not reconcile timeout changes into an existing managed hook entry. | **Fixed in this slice.** UserPromptSubmit now has a 12-second outer host window while active work remains capped at seven seconds. Setup updates only separator-normalized exact managed commands in place, preserves unrelated/malformed fields and existing duplicates, and remains idempotent. Fast deterministic regressions failed on the prior one-second slack and stale installed values, then pass with five seconds of total outer slack and migrated settings. |
| `RW-024` | Codex wake launched `codex exec resume` without an explicit cwd, so the child inherited the Pallium service checkout. A resumed task then adopted that workspace, derived the wrong Relay container scope, and sender lookup correctly failed closed with 404. | **Fixed in this slice.** The adapter no longer cold-resumes or reads private Codex workspace state. It writes one exact-thread native queue item from a validated neutral Codex home; loaded tasks wake through their owner, while unloaded-task correctness relies only on Pallium's pending delivery and a later hook turn. Caller-surface regressions pin explicit cwd, fail-closed unsafe paths, pending-before-hook, exact delivery, and single-flight behavior. |
| `RW-025` | A substantive hook-delivered assignment outlived its claim lease during investigation, so receiptless atomic reply returned the expected 409 even though the work completed. | **Tracked operational fallback.** The Relay error was surfaced and completion was sent as a new direct Relay message. Existing expired-claim recovery protects the original delivery; no automatic completion-message fallback is added unless this recurs as a product failure. |
| `RW-026` | Near-simultaneous Codex sends produced anonymous `failed` and `queued` wake logs. Durable state and task JSONL proved one hook delivery and one pending delivery followed by a direct app-message fallback, but the wake outcomes could not be assigned to a delivery or safely explained. | **Fixed as a diagnosis gap only.** Every attempted Codex wake now logs the canonical delivery ID, bounded SHA-256 fingerprints for session and container scope, a fixed safe reason category, and an optional numeric exit code; recovery candidates use the same correlation values. Hostile-reference and full launch-outcome regressions prove prompts, stderr, exception text, environment values, secrets, and local paths are not logged. Delivery routing, queueing, retry, claim, ACK, and app-message hook behavior are unchanged; this does not claim the observed failed wake was repaired. |
| `RW-031` | A Codex native queue call can persist a fresh queue row before its response is lost, while the public CLI returns nonzero and creates a new client message ID on every retry. Retaining an uncertain reservation prevents duplicate native turns but can leave a pending delivery without actionable recovery guidance. | **Pallium work closed; the remaining automatic-recovery gap is upstream.** PR #209 records exact-delivery hook start, payload emission, ACK, and bounded failure evidence. An installed busy-to-idle witness proved one accepted submission, one later safe turn, one injection, and one ACK; it did not exercise uncertain failure. Trace explanations distinguish queued, delivered, expired-before-claim, needs-intervention, mixed, and incomplete evidence. A later delivery in the same never-moved exact scope (generation 0) blocked by a retained uncertain fence after service restart now reuses only complete durable prepared/completed evidence to expose the same needs-intervention guidance; it never releases the fence or submits another native turn, and moved or ambiguous scope evidence fails closed. Startup and periodic recovery enumerate already-pending coalesced deliveries oldest-first so later items receive that association without weakening the single native-submission fence; default candidate reads and exact-ID rechecks remain unchanged. Review of the public CLI and app-server sources for Codex `0.155.0-alpha.9.2`, `0.156.1`, and `0.157.0-alpha.11` found no composition on those surfaces that wakes an unloaded task in its Desktop-owned app-server and atomically admits one exact queued submission. `codex exec resume` starts a second runtime, `thread/queue/start` is loaded-only, and the public queue path has no caller idempotency key. Therefore Pallium deliberately keeps the delivery pending for an ordinary supported recipient turn. This is not a Pallium release gate; revisit only when Codex provides owner-routed cold activation with server-side idempotency and authoritative admission results. |

| `RW-033` | A temporary service with an isolated Relay database but no Codex wake-dir override opened the installed shared wake registry; startup reconciliation logged seven missing reservations as stale and released their fences. The precise delivery impact was not established. | **Codex fix in this slice.** Registry selection follows the actual Relay database, startup recovery receives the app-owned registry, and process-global schedule keys include registry identity; deterministic two-instance coverage checks the foreign reservation file is unchanged. The distinct Claude hook-intent cross-instance risk from [issue #234](https://github.com/rore/Pallium/issues/234) is addressed by Relay-database-scoped Claude state, setup-pinned hook binding, pre-write marker checks, and two-instance hook/HTTP/outage tests. |

| `RW-034` | An exact Codex wake can commit its `/relay/turn` claim but lose the response at the hook's 0.75-second HTTP limit. The existing correlated lease-expiry recovery then waits at least 60 seconds plus a recovery sweep before another safe wake. | **Bounded prevention in this slice; native uncertainty remains separate.** Only the final HTTP request carrying the validated exact wake delivery ID may wait up to two seconds, with one second of the hook safe-work budget reserved for emission and ACK. Bootstrap, scope replay, ordinary prompts, and malformed wake text retain the 0.75-second cap; responses beyond two seconds still fail closed into existing exact-correlated recovery. Synthetic loopback HTTP plus actual-hook coverage verifies claim, emission, ACK, and the delayed-response boundary. This establishes a general failure class, not the uncorrelated historical incident's precise cause or universal latency immunity. |
| `RW-035` | One accepted loaded Codex wake started its recipient turn, but the hook reported Relay unavailable; a later exact-delivery claim committed with attempts 1 and no correlation in the retained wake reservation. The old server did not retain the request body or callback result. | **Forward fix in this slice; historical fence remains conservative.** An exact /relay/turn request captures the current reservation before claim. The claim transaction stores its generation only when the selected delivery and endpoint match; a post-claim callback also checks that same generation. If the callback is lost, an expired lease can rearm from the durable same-generation claim, while a live lease, ordinary or mismatched claim, legacy NULL, and uncertain native outcome without an exact claim remain fenced. Caller-surface callback-loss through recovered HTTP payload and ACK, generation-race, migration/restart, and ACK regressions pass. This does not establish the historical failure cause, clear its fence, or prove installed recovery from a live uncertain native submission. |

The Windows Claude regression floor remains: idle text and zero-tool turns, empty
Stop rearm, busy delivery, ordered bursts, Unicode, recursive-Stop loop prevention,
duplicate send/trigger, arrivals during continuation, preservation of the original
human-owned turn, exact scope, and no manual prompt after a case begins. Deterministic
tests cover the contract; installed runtime witnesses stay opt-in to protect budget.

The following related work stays separate to keep ownership clear:

- `add-relay-retention-and-lifecycle-hardening` owns bounded cleanup of the final
  session/destination/delivery states defined here; it must not invent liveness or
  terminal-failure semantics independently.
- `idea-agent-relay.md` retains the optional default-off `notify_on_turn_end`
  proposal. Turn end is not task completion and is not a prerequisite for delivery
  correctness.
- `validate-relay-dependency-workflows` is a paused documentation/examples follow-up;
  it does not gate reliability work or runtime expansion.
- `feat/clarify-relay-activation-snapshot` remains separate unmerged API-contract work: its evidence-scope and exact-trace-source fields complement this explanation slice but are not required for actionable failure guidance.
- The local wake-test pollution repair is complete and reversible: the exact 23
  synthetic source items are forgotten and 89 derived memories are soft-deleted
  under one audit reason; the default dashboard read path exposes none of them.
  This was operational data repair, not Relay routing behavior.
- **Next correctness and operations follow-ups (separate from S2):** RW-017 makes
  ordinary Relay work durable by default while preserving explicit expiry. RW-016's
  canonical Windows custom-home/Unicode launcher repair is merged and qualified.
  RW-018's taskkill-race recovery is merged and Windows-qualified; retain RW-010's
  regressions and installed witness as the operations floor. S3 Codex lifecycle gates
  are next.

The remaining S2 qualification is done only with caller-surface E2E for fresh
versus stale MCP hosts, bounded backlog, memory routing, Unicode, scope isolation,
restart, and idempotence. Existing unknown, passive, unreachable, self-healing
registration, retryable/qualified missing-endpoint transport, async status, burst
coalescing, and delivery-before-queued-execution regressions remain mandatory.
Tests must be fast and deterministic; installed-runtime witnesses remain opt-in
release gates.

**Core scope:** Derive the smallest coordinator from the Codex delivery trace.
Do not wait for a second adapter or build speculative multi-runtime machinery.
Choose bounded limits from Codex evidence; revisit only when adding another adapter.

### Implementation sequence — Codex first

**Codex (Windows/Linux loaded-task):** `codex queue --thread T` writes one generic trigger from a validated neutral Codex home. The owning Desktop watcher starts the loaded task; for an unloaded task, Pallium keeps the Relay delivery pending until an ordinary supported hook turn and does not rely on native queue persistence. The admitted UserPromptSubmit hook claims and injects the attributed batch under the target scope. Any exact internal trigger that cannot render a verified delivery is blocked before memory/model work, whether the Relay result is empty, unavailable, timed out, malformed, or invalidly scoped. MCP receive remains a separate fail-closed recovery path. Keep the adapter runtime/version-qualified until the remaining OS and lifecycle gates pass.

**Claude Code:** S0/S0.5 are misqualified because Claude 2.1.250 peer frames bypass `UserPromptSubmit` as internal `isMeta` events. Claude reproduced S1A Stop continuation; Codex architect review is clean, exact-scope bounded Stop `/relay/turn`, one emit of the successfully rendered claim set followed by individual ACKs, and one exit-2 continuation—not MCP—provide peer-wake admission. Do not treat generic native notice as delivery.
Keep Channels deferred and macOS passive until installed UDS E2E passes.

**OpenCode:** Deferred until after Claude Code AND Codex are both proven.

## In Scope

- wake every eligible resolved recipient by default, including runtime fan-out
- allow a recipient integration to explicitly disable wake and remain passive
- persist before attempting wake; retain next-natural-turn delivery as fallback
- queue busy recipients for a separate safe turn rather than steering an active
  human-owned turn
- confirm runtime admission before marking delivery complete
- make trigger attempts idempotent so wake and fallback cannot double-deliver
- expose wake attempts, admission, fallback reasons, failures, latency, and fan-out
  in Relay operational telemetry
- implement and validate the smallest supported native adapter for Claude Code,
  Codex, and OpenCode
- cover idle, busy, concurrent user input, unsupported capability, stale or closed
  sessions, runtime and Pallium restarts, duplicate triggers, permissions, fan-out,
  expiry, and reply-loop protection through public-surface E2E tests

## Safety and Cost Boundary

Wake changes Relay from passive information transport into an execution trigger:
the receiving model can consume tokens, invoke tools, and modify files. Therefore:

- Relay input is attributed peer input with lower authority than user instructions;
  it cannot grant consent, approve permissions, change runtime configuration, or
  bypass the recipient's sandbox and approval policy
- runtime-wide fan-out still wakes every resolved recipient by default, but the
  resulting turn count, failures, and observable usage must be visible
- bounded queues, duplicate/rate limits, and a finite reply-hop policy must prevent
  accidental wake storms and autonomous reply loops
- automatic replies are not implied by delivery; a reply remains an explicit Relay
  action derived from a received delivery ID
- an integration can explicitly disable wake, but passive delivery remains enabled
  unless Relay itself is disabled

## Out of Scope

- restarting an exited agent process or resuming a dormant harness automatically
- launching or managing a parallel runtime/session as a substitute for the
  existing session addressed by the sender
- spawning agents, assigning work, or supervising completion
- sender-selected wake syntax or semantic wake decisions
- treating runtime admission as proof that the agent understood or used a message
- automatic agent conversations or unbounded reply chains
- Pallium deciding that another review or implementation pass should happen; the
  participating agent must explicitly send each handoff or reply

## Done When

1. A Relay send is persisted and wakes every eligible resolved recipient without a
   user turn or sender delivery flag.
2. Busy recipients process the message in a separate safe turn, never by accidental
   steering of an active human-owned turn.
3. Unsupported, unavailable, stale, or passive recipients receive the same durable
   message exactly once on their next natural turn.
4. Delivery state and dashboard telemetry distinguish wake attempt, runtime
   admission, fallback, and terminal expiry without claiming downstream use.
5. Full-lifecycle E2E coverage verifies the observable contract through each
   supported runtime's real integration surface.
6. Relay-triggered turns preserve attribution, lower-authority treatment, sandbox
   policy, and ordinary permission prompts.
7. Queue, duplicate, rate, and reply-hop bounds terminate replay or reply storms
   while leaving the original durable delivery diagnosable.

8. A live Claude Code developer → Codex architect → Claude Code remediation →
   Codex verdict journey completes after one initial user instruction and no
   intermediate user prompts. Repeat with the runtime roles reversed where the
   installed integrations support it.
9. That journey remains exact-once and model-visible when either recipient is
   idle or busy, and across a Pallium or recipient-integration restart. If wake
   cannot be admitted, the delivery remains durable and the dashboard/status
   exposes the fallback or actionable failure rather than silently stalling.

## Notes

Implementation plan: [wake-first Relay delivery](../../docs/plans/2026-08-26-wake-first-relay-delivery.md).

Phase 0 decision and installed-runtime evidence:
[Relay wake Phase 0 decision record](../../docs/designs/017-relay-wake-phase0.md).

Current result: Codex exact-session wake writes one hidden `codex queue --thread` trigger from a validated neutral Codex home. A runtime that already loaded the target starts a real turn; for an unloaded target, Pallium retains the pending Relay delivery until its next supported hook turn and claims no native queue persistence. RW-024 removed hidden `codex exec resume` because inheriting the service cwd could mutate task workspace and Relay scope. Queue launch remains best-effort with durable natural-turn fallback on failure. The adapter encodes Relay prompts as UTF-8, and the pre-fix claim-before-queue behavior reproduced a 409 `claim lease has expired` when a delivery was claimed before queueing and the queued turn executed after the lease. The installed UserPromptSubmit hook claims only at admitted-turn execution; delayed busy-target caller-surface E2E proves no stale receipt, loss, or duplicate action. A later live empty turn exposed the native accepted-prompt race: another admitted turn can consume the delivery after Codex accepts the queued trigger. The original guard blocked only the complete canonical no-work response; RW-019 strengthens it so any exact internal trigger without a verified rendered delivery stops before memory/model work. Deterministic caller-surface coverage preserves successful delivery, proves a competing real hook consumes and ACKs exactly once, and stores a safe marker when redaction expansion would otherwise exceed the render budget. An installed exact-session witness queued the trigger and recorded hook context followed by `task_complete` with `last_agent_message=null` and no user or assistant transcript item. Later sustained busy-target dogfood exposed RW-022: periodic recovery resubmitted the accepted non-idempotent prompt until admission. The scheduler now retains one confirmed or ambiguous native write per live generation without blind retry; deterministic caller-surface coverage proves recovery sweeps do not add queued turns. Hook-delivery wake and per-session burst coalescing are proven for the tested Windows paths. A Relay-wide read-only sweep now re-wakes eligible expired claims for active exact Codex and Claude sessions immediately at service startup and every 30 seconds, then the admitted hook reclaims and ACKs normally; controlled-clock real-hook E2E covers both runtimes and both full-app restarts. An installed Windows Codex witness deliberately abandoned a claimed delivery, then observed automatic hook delivery on attempt two after the 60-second lease expired, without a manual wake. Codex MCP receive and bounded automatic backlog drain are Windows-qualified. An installed Ubuntu 24.04 / WSL2 witness with Codex 0.153.4 targeted session `01a0776f-337d-7013-8170-f55b37a32f30`; parent `relay-msg-c55a51edc4a9469e81068a4f5adc4763` / delivery `relay-delivery-0dcd69097ce040d5858a6103956773d7` moved from pending attempts=0 to delivered attempts=1, produced `CODEX_LINUX_WAKE_DELIVERED_TRUSTED_20260906`, and returned idle. Explicit repository and exact-hook hash trust were used, never the trust-bypass flag. Sender-side reply admission and the bounded no-ping remediation journey were re-proven on 2026-09-08 with both original sender resumes caused solely by Relay and no manual recipient turn. Remaining interrupted/restart reliability and macOS qualification remain. Startup recovery now enumerates all eligible coalesced pending/expired candidates in oldest-first order, while default reads remain one-per-endpoint and exact rechecks remain unchanged. RW-026 now correlates each attempted Codex wake and recovery candidate with bounded identifiers and safe launch categories; it improves diagnosis only and does not claim the observed failed wake was repaired. Claude Windows and installed Linux UDS wake are complete; macOS remains S4, and OpenCode remains deferred.

## Research References

Primary runtime sources:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code v2.1.224 release](https://github.com/anthropics/claude-code/releases/tag/v2.1.224)
- [Claude Code native-Windows delivery issue history](https://github.com/anthropics/claude-code/issues/86603)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex queue integration tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_queue.rs)
- [Codex Windows active-writer/no-attach limitation](https://github.com/openai/codex/issues/37450)
- [Codex atomic idle-only admission request](https://github.com/openai/codex/issues/38289)
- [Codex unloaded queue activation limitation](https://github.com/openai/codex/issues/44491)
- [Codex 0.155 exact-version exec resume implementation](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/exec/src/lib.rs)
- [Codex 0.155 exact-version queue service](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/ext/queue/src/service.rs)
- [Codex 0.155 exact-version queued-turn start](https://github.com/openai/codex/blob/4607249e430dac1c961df4dc615beae88e33cec8/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex 0.156.1 exact-version queued-turn start](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex 0.157.0-alpha.11 exact-version queued-turn start](https://github.com/openai/codex/blob/rust-v0.157.0-alpha.11/codex-rs/app-server/src/request_processors/thread_queue_processor.rs)
- [Codex background app-server daemon](https://github.com/openai/codex/blob/main/codex-rs/app-server-daemon/README.md)
- [OpenCode server API](https://opencode.ai/docs/server/)
- [OpenCode plugin API](https://opencode.ai/docs/plugins/)
- [OpenCode prompt acceptance without wake issue](https://github.com/anomalyco/opencode/issues/21524)
- [Claude Agent SDK session resume](https://code.claude.com/docs/en/agent-sdk/sessions)

Feasibility evidence, not dependencies or adoption evidence:

- [Agent Intercom Claude adapter](https://github.com/dataforxyz/agent-intercom-claude)
- [Agent Intercom Codex adapter](https://github.com/dataforxyz/agent-intercom-codex)
- [Agent Intercom OpenCode adapter](https://github.com/dataforxyz/agent-intercom-opencode)
- [Agent Mail](https://github.com/osteele/agent-mail)

The runtime APIs are evolving. Recheck the primary documentation, installed
versions, preview flags, and open-issue status rather than copying version-specific
adapter behavior from this roadmap item.

### Historical accepted Claude S1B restart-durability plan (Windows-qualified)

The critical outage window is Claude reaching Stop while Pallium is down: loopback registration fails and a restart would otherwise preserve stale busy. Canonical capability remains `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with exact scope/socket/token/generation plus `busy`, `idle`, or `wake_inflight(delivery_id, utc_attempt_time)`. The existing registry lock serializes normal register, state changes, and same-session intent take/apply/removal. Add only `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`: before HTTP registration, the hook atomically writes the exact state with a random `intent_id` and sends that id in the request. Under lock, the request id must equal the currently stored intent before any canonical mutation; mismatch rejects/no-ops. Success writes canonical then consumes only that exact intent. Ambiguous responses retain/retry the same intent, never create/rewrite a later one; crashes and delayed old requests are deterministically idempotent.

Persistence is state-specific: failed idle registration does not publish idle and failed idle→inflight does not transport; ordinary idle/inflight writes precede publication/effect. Failed busy persistence immediately marks memory busy and must make stale durable idle unloadable before continuing. If that cannot be quarantined/deleted, persist one `store-unusable` marker checked before startup loads capabilities; no rehydration occurs until trusted registration/intent repair. If neither quarantine nor marker persists, startup refuses rehydration while stale file exists. POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL; no DPAPI/custom DACL. Bad data is ignored, but a valid capability is not discarded solely for permission-setting failure. No TTL/age cleanup: online SessionEnd removes its record; offline SessionEnd writes a closed/removal intent. At the 256 cap only, non-admitting endpoint-absence checks may reclaim provably missing endpoints. Never `registry.probe`, auth, write, or open; POSIX socket nodes and busy/timeout Windows pipes are uncertainty, retained, and new registration rejects. Only SessionEnd or a truly missing endpoint is terminal; all uncertain transport is retryable.

Use a minimum read-only exact-scope storage/service pending-candidate query before recovery dispatch; it never claims/ACKs. Claimed/delivered/expired clears inflight retry; pending waits bounded grace then can retry. One event-driven reconciler is signaled by readiness/new-send/registration/intent consumption; its capped Condition/Event wait periodically scans write-ahead intents. Signals coalesce and retries continue indefinitely while exact pending+eligible work remains, with capped backoff and no busy loop or finite retry count. Crash windows prefer an extra empty admission, never lost Relay work.

Required fast E2E includes delayed old intent mismatch, every write-ahead intent crash/response-loss boundary, busy failure→restart with stale file, offline SessionEnd, crash-without-SessionEnd capacity pressure, live endpoint at cap with zero native writes/admissions, post-start intent discovery, corrupt intent/capability, Unicode path, duplicate/concurrency, typed transport, indefinite capped retry, and non-claiming query. Windows no-manual-re-registration restart wake/Stop claim/inject/reply is qualified.
**Review status:** Windows S1B and installed Linux UDS witnesses are accepted. macOS installed UDS qualification remains S4.
