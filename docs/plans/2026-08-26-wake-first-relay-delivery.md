# Wake-first Relay delivery implementation plan

Status: superseded for milestone 1 by [Relay batches and Codex-first wake](../designs/relay-batch-codex-wake.md), proposed for independent review on 2026-08-31.

Historical planning below is retained for traceability, not as implementation
instructions. In particular, timeout-to-fallback, separate wake payload injection,
exactly-once claims and the provisional state inventory MUST NOT be implemented
from this document. Use the new design and its explicit evidence/review gates.
Roadmap item: `add-wake-first-relay-delivery`

Priority revision (2026-08-31): Codex↔Codex dogfood is milestone 1, Claude↔Codex
is milestone 2, OpenCode follows. The roadmap's milestone acceptance is canonical.
Milestone 1 must work between the existing architect and Relay developer sessions
without a separate user/agent ping or manual queue/app-tool activation in either
direction. Use that developer through Relay, not a substitute subagent. Update
local Codex integrations and complete architect review before accepting it.

## Outcome

After Pallium durably creates Relay deliveries, it automatically attempts to
activate every eligible live recipient. A supported idle recipient starts a new
turn; a supported busy recipient queues a distinct turn at a safe boundary. If
activation cannot be proven safe or available, the original delivery remains
pending and appears exactly once on the recipient's next natural turn.

The sender does not select a delivery mode. Wake is the default recipient
capability, with an integration-side passive opt-out.

## Non-negotiable contracts

- Persist the message and all fan-out deliveries before any runtime call.
- Relay peer text is attributed, lower-authority input and cannot grant approval.
- Runtime admission, not transport acknowledgement, completes a delivery.
- Wake and next-turn delivery race through one atomic ownership boundary.
- A transport-ambiguous trigger is never blindly retried unless the runtime
  supports Pallium's stable idempotency key.
- Unsupported, passive, stale, closed, or unavailable sessions retain normal
  next-turn delivery; an exited runtime is not relaunched.
- The recipient is the exact existing session selected by Relay. Launching,
  resuming, cloning, or managing another session is not wake and cannot satisfy
  feasibility or completion gates.
- Busy delivery never steers text into the active human-owned turn.
- No automatic replies, agent spawning, task assignment, or semantic wake choice.
- Runtime-wide addressing keeps the existing 25-recipient fan-out bound.

## First implementation step

Invoke the `/agent-workflow` skill on a new `codex/relay-wake-*` task branch,
create the expanded Work Record, run agent-redline against the intended files,
and obtain the approval required by its final risk classification before editing
production code. Treat each PR below as a separate workflow task.

## Phase 0 — prove each runtime ingress before designing adapters

Revalidate the installed Claude Code, Codex and OpenCode versions and public APIs.
Use disposable sessions and record protocol traces under `.local/`; commit only a
short decision record and deterministic test fixtures with secrets removed.

For each runtime, prove these cases through its supported public surface:

1. identify the exact live session corresponding to Pallium `session_ref`;
2. submit an attributed Relay turn while idle;
3. submit while a user-owned turn is busy without steering that turn;
4. observe a positive admission event tied to a supplied delivery/idempotency ID;
5. distinguish closed, stale, permission-denied and unavailable sessions;
6. verify behavior after the runtime or Pallium service restarts;
7. establish whether a trigger can be safely retried after an ambiguous response.

Expected decisions:

- **Claude Code (milestone 2):** the 2026-08-28 qualification proved native
  Windows idle ingress; busy ingress is unsafe and Channels were unavailable.
  Preserve idle-only dispatch and qualify admission/fallback before enabling it.
- **OpenCode:** use its supported server/plugin session status and prompt APIs.
  Confirm idle/busy queue semantics and the event that proves prompt admission.
- **Codex (milestone 1):** build on the recorded `codex queue --thread`
  idle/busy admission evidence, qualify the actual architect/developer pair, and
  close stale/permission, restart, and ambiguous-response cases. A managed App
  Server, resumed clone, or replacement process remains out of scope.

Gate: no runtime adapter enters implementation without passing all seven cases.
Failure for one runtime does not block supported runtimes because passive Relay is
the defined fallback.

## Target architecture

The following is a design inventory, not a requirement to build every mechanism
up front. For milestone 1, retain only what the Codex admission/recovery contract
needs; derive further shared abstractions when the Claude adapter requires them.

### Durable delivery and activation state

Keep the existing delivery lifecycle (`pending → claimed → delivered`, plus
`expired`) as the authority for exactly-once context admission. Add separate wake
metadata to each delivery rather than inventing a second message lifecycle:

- `wake_state`: `not_eligible | queued | triggering | triggered | admitted | fallback`
- `wake_capability`: capability snapshot used for this attempt
- `wake_attempts`, `wake_queued_at`, `wake_triggered_at`, `wake_admitted_at`
- `wake_deadline_at`, `wake_last_error`, `wake_fallback_reason`
- random, single-use wake callback capability stored only as a hash

Session registration advertises only currently supported capabilities:
`passive`, `idle_wake`, and `busy_queue`. Capability presence is a live claim, not
a promise that a dormant conversation can be relaunched. A wake capability has a
short lease and an adapter-instance generation. Heartbeats renew that lease;
close, lease expiry, integration disable, or instance replacement atomically
revokes it. A reservation and callback must match the same generation.

The service owns an allowlisted adapter registry keyed by runtime and adapter
instance. Session registration never accepts an arbitrary URL, command, pipe, or
socket path. Runtime-specific connection material is established only through the
documented integration bootstrap proven in Phase 0 and is not returned by Relay
HTTP, MCP, status, dashboard, telemetry, or logs.

Schema changes belong in `storage/sqlite_schema.py` and the existing additive
SQLite migration path. State transitions belong in `storage/sqlite_relay.py` and
must use the current immediate transaction boundary.

### One atomic admission race

Add storage operations with these semantics:

1. `relay_send` commits deliveries with wake state `queued` only for capability-
   eligible sessions; all others are `not_eligible` or `fallback` with a reason.
2. The wake dispatcher atomically reserves a still-pending delivery for one
   trigger attempt. It creates a random 256-bit callback token, stores only its
   hash, and binds it to delivery, recipient, adapter generation and deadline.
3. A next-natural-turn claim may win only before wake reservation or after wake
   has explicitly fallen back. It cannot claim a `triggering/triggered` delivery.
4. Runtime admission atomically changes the delivery to `delivered` and wake state
   to `admitted` only when the presented token hashes correctly and every binding
   still matches. Exact replay returns the same result; guessed, wrong-recipient,
   wrong-generation and expired tokens reveal no delivery data.
5. A proven pre-admission failure releases the same delivery to `pending/fallback`.
6. An ambiguous trigger remains suppressed until its deadline. At the deadline it
   falls back without another wake unless the adapter proved idempotent retry.
7. Expiry wins over all non-delivered states and rejects late callbacks.

Wake reservation is separate from the existing hook-owned claim token and its
60-second lease. Natural-turn acknowledgement can consume only a natural claim;
wake admission can consume only the private wake callback capability. Neither
token is model-visible. Reuse the storage transaction pattern, not the token.

### Runtime-neutral orchestration

Add one small wake coordinator at the Relay boundary. It receives already
persisted delivery IDs, asks the registered runtime adapter to trigger them, and
records only the normalized outcomes:

- `admitted`: recipient context accepted the Relay turn;
- `triggered`: runtime accepted a queued/start request; await admission callback;
- `unavailable`: immediately release to fallback;
- `rejected`: permanent fallback with a reason;
- `ambiguous`: wait for the admission deadline, then fallback without unsafe retry.

Adapters own runtime protocol details and return normalized outcomes. The generic
Relay service must not import Claude, Codex or OpenCode SDK types.

Each adapter must implement the complete proven handshake, not merely send a
prompt: reserve delivery → trigger a distinct runtime turn carrying a delivery-
bound internal envelope → integration observes that envelope entering model
history/context → integration calls admission with the private callback token.
Human-prompt hooks remain the fallback path and cannot manufacture wake admission.

Wake dispatch must not delay persistence or the sender response on model work.
Use the existing service lifecycle to run a bounded local dispatch loop over
durable `queued` rows. Wake work contains no LLM polling. On restart, the loop
recovers queued rows and resolves expired deadlines.

### Public service surface

Extend the existing Relay HTTP API, then use it from integrations:

- a separate integration-only registration/heartbeat surface binds truthful
  capabilities to a server-approved adapter instance and generation; ordinary
  `/relay/turn` continues registering passive session presence;
- an internal loopback admission endpoint accepts delivery ID + wake token;
- message status exposes delivery state plus normalized wake state/timestamps and
  fallback reason;
- the sender's existing send/reply schema remains compatible and gains no wake
  flag.

Loopback is a network exposure restriction, not authentication. Validate the
single-use callback capability and all delivery/session/generation bindings at the
API boundary. Never expose callback tokens, adapter connection material, or raw
runtime errors through MCP, status, logs, or the dashboard.

Reply requests must also carry the current runtime and session identity injected
by the integration. The service verifies it is the delivery recipient before
deriving the reply endpoints. Persist a numeric reply-hop count on the message and
reject a reply before creation when the configured finite bound is reached.

## Delivery sequence

1. Sender calls the existing Relay send/reply surface.
2. Pallium resolves recipients and commits message + per-recipient deliveries.
3. Eligible deliveries become durable wake work; send returns the message ID.
4. Dispatcher reserves each delivery and calls its runtime adapter with attributed
   Relay text and the private wake callback token.
5. Immediate admission completes the delivery. Queued admission completes only
   when the integration observes the message entering the recipient context and
   calls back.
6. Any unsupported or safely diagnosed failure releases the original delivery to
   next-turn fallback. Existing hooks claim and acknowledge it normally.

## PR breakdown

### PR 1 — feasibility record and executable adapter contracts

- Run Phase 0 against installed runtimes.
- Add a decision record with the exact supported versions, public operations,
  admission signal and constraints for each runtime.
- Add protocol fixtures/fakes sufficient to test adapters without live models.
- Finalize the normalized adapter result contract; no production wake behavior.

Exit: Claude/OpenCode/Codex are each marked `supported`, `passive-only`, or
`blocked` with reproducible evidence. Re-estimate remaining PRs.

### PR 2 — durable core, recovery and observability

Likely files: `core/relay.py`, `storage/sqlite_relay.py`,
`storage/sqlite_schema.py`, `api/schemas.py`, `api/routes.py`, service lifecycle,
dashboard summary, and focused Relay tests.

- Add capability snapshots and wake metadata/migration.
- Add atomic reserve/admit/fallback/deadline operations.
- Add capability leases/generations, the allowlisted adapter registry, and bounded
  dispatcher with fake adapters disabled by default.
- Bind replies to the actual recipient identity and persist the hop count.
- Extend status and dashboard metrics without changing send syntax.
- Keep all adapters passive fakes in this PR.

Exit: deterministic fake-adapter E2E proves every state/race/restart transition.

### PR 3 — Codex adapter and milestone 1 dogfood acceptance

- Implement `codex queue --thread` only after the remaining Codex safety cases
  and actual architect/developer session ingress are qualified.
- Reuse the minimal PR 2 coordinator for dedupe, admission and durable fallback;
  never substitute a managed App Server, resumed clone, or replacement session.
- Update local Codex integration installation and operational diagnostics.
- Run caller-surface E2E for idle/busy, user-turn races, wake/fallback races,
  duplicates, queued bursts, expiry, stale sessions, permissions, restart and
  ambiguous outcomes; preserve attribution and sandbox/approval boundaries.
- Run a bounded live task → result → review → remediation/verdict exchange using
  the two existing Codex sessions. Every handoff uses Relay; no separate user or
  agent ping, manual queue command, or app-tool activation may advance the run.

Exit: milestone 1 is accepted only after this bidirectional no-ping journey,
regressions, local install verification and architect review pass. Claude and
OpenCode remain passive and do not block it.

### PR 4 — Claude Code adapter and milestone 2 handoff

- Extend the coordinator only for the qualified native idle-only ingress.
- Never inject while busy; defer safely and retain next-turn fallback.
- Update installers and add real-surface tests for idle admission, busy deferral,
  duplicate suppression, stale/restart/error fallback and admission correlation.
- Validate the unattended Claude↔Codex journey after the Codex milestone.

Exit: the qualified cross-runtime pair completes the bounded handoff without
manual pings; unqualified runtime/OS combinations remain passive.

### PR 5 — OpenCode adapter

- Implement only the server/plugin handshake proven in PR 1.
- Update installation and capability heartbeat lifecycle.
- Add its real-surface E2E harness and enable only after its live smoke matrix
  passes.

Exit: idle and busy OpenCode deliveries meet the same admission/fallback contract.

### PR 6 — cross-runtime regression journeys and public UX

- Run the three selected real-world Relay workflows across every supported pair.
- Verify fan-out, replies, expiry, restarts and mixed capable/passive recipients.
- Finish dashboard wording, operational runbook, installation docs and public
  examples from the validated scenarios.
- Update the roadmap only after the observable contract is verified.

## Required E2E matrix

Every test drives the caller's public HTTP/MCP/hook/plugin surface and verifies
state through Relay status/list/audit or the recipient runtime's observable turn.

- idle recipient admission; busy safe-boundary queue; concurrent user prompt race;
- capability absent/disabled/lost; stale, closed and exited session;
- permission denial, runtime unavailable, timeout and malformed callback;
- Pallium restart before trigger, after trigger and before admission callback;
- runtime restart in each corresponding window;
- duplicate send ID, trigger, callback, hook claim and acknowledgement;
- wake versus natural-turn claim in both possible orderings;
- wake callback token replay, guessing, wrong recipient and wrong generation;
- capability lease expiry, heartbeat loss and adapter-instance replacement;
- close/reopen with the same session ref and adapter disable during reservation;
- forbidden adapter locator/transport registration and callback data non-disclosure;
- message-ID retry after the dispatcher has reserved the original delivery;
- runtime fan-out with all capable, all passive and mixed recipients;
- message expiry while queued/triggered and late admission after expiry;
- maximum payload, Unicode payload, redacted payload and over-limit rejection;
- reply chain up to the chosen hop bound and rejection/fallback beyond it;
- bounded dispatcher queue and per-session rate limit under a burst;
- attribution and lower-authority text visible in the admitted runtime context;
- ordinary sandbox and permission prompts remain enforced.

Live-runtime smoke tests are separate from deterministic CI: CI uses captured
protocol fixtures/fakes, while a documented Windows smoke script verifies the
installed Claude Code, Codex and OpenCode versions before release.

## Operational UX and metrics

The dashboard should answer: is Relay operating, is wake operating, and what is
wrong now? Show a compact current-state summary:

- delivery totals by pending/delivered/expired;
- wake totals by queued/triggered/admitted/fallback;
- admission latency and oldest queued/triggered age;
- capable/passive/stale sessions by runtime;
- fallback/failure counts grouped by normalized reason;
- fan-out turn count and rate-limit/reply-hop rejections.

Only active problems enter “Pallium needs attention”: overdue queued/triggered
wake work, repeated adapter failure, or a runtime claiming capability without a
reachable ingress. Normal passive fallback is visible but is not an alert.

## Rollout and rollback

- Ship schema/API support before enabling any live capability advertisement.
- Enable one runtime adapter at a time after its live smoke matrix passes.
- Disabling an adapter immediately stops new wake attempts and leaves existing
  undelivered messages available to next-turn hooks.
- Migration is additive; rollback ignores wake metadata while preserving message
  and delivery rows.
- Restart the installed service only through `scripts/restart-service.ps1`, then
  verify `/health`, `/status`, and `/debug/queue/health` on port 19836.

## Runtime-specific gates (priority revised 2026-08-31)

The earlier all-runtime implementation block is superseded. Codex-first work does
not wait for Claude or OpenCode, but does not waive the safety gates.

1. **Codex milestone:** existing-session idle/busy ingress is partially proven.
   Close Phase 0 cases 5–7, confirm the actual architect/developer pair, and agree
   the admission/recovery contract before enabling production wake.
2. **Claude milestone:** native Windows idle wake is proven; busy ingress is
   unsafe and Channels were unavailable. Its coordinator/adapter admission,
   dedupe and fallback gates apply when adding Claude, not to milestone 1.
3. **MCP receive foundation:** `fix-relay-receive-mcp-lifecycle` is merged;
   reuse receipt-based recovery without raw HTTP or exposed claim tokens.

**PR 2 scope:** implement the smallest coordinator required by Codex evidence.
Do not require two adapter traces or build the full architecture inventory
speculatively. Choose bounded admission, rate, hop and queue limits from Codex
behavior, then revisit only when a later adapter requires it.

## Planning decisions still required

These are resolved in PR 1 from runtime evidence, not guessed during core work:

1. exact supported runtime versions and feature flags;
2. exact admission callback/event for each runtime;
3. for milestone 2, qualify the native Claude idle-only adapter; Channels stays
   deferred unless new evidence changes its availability;
4. the Codex admission/recovery handshake for the actual existing addressed
   sessions, building on the recorded queue ingress evidence;
5. adapter locator lifetime and whether any runtime needs ephemeral registration;
6. numeric admission deadline, dispatcher bound, rate limit and reply-hop bound,
   chosen from measured runtime behavior rather than arbitrary constants.

## Cross-state transition decisions for PR 1

PR 1 must publish the complete transition table before PR 2 starts. At minimum it
must cover every delivery state crossed with capability disable/expiry, session
close/reopen, adapter replacement, trigger acceptance, admission deadline, message
expiry, natural-turn claim and callback. The default rules are:

- message expiry is terminal for every non-delivered path; all late callbacks fail;
- close, capability loss or adapter replacement before trigger releases to passive
  fallback and invalidates the callback capability;
- the same events after an acknowledged trigger do not permit natural-turn claim
  until the admission deadline, preventing double delivery;
- admission before the deadline wins only with the still-bound callback token;
- deadline expiry invalidates that token and releases the original delivery once;
- reopening the same session creates a new adapter generation and cannot revive or
  admit work reserved by the old generation.

## Completion gate

Milestone 1 is independently acceptable when the Codex adapter, no-ping live
round trip, required failure regressions, local installations and architect review
pass. Keep the overall wake feature active for Claude and OpenCode follow-up;
cross-platform enablement requires evidence for each runtime/OS combination.

Wake-first is done only when every supported runtime passes the full lifecycle
matrix, every unsupported path demonstrably falls back exactly once, dashboard
state explains failures without exposing secrets, local installers are updated,
and a clean-context result review has no unresolved correctness or safety finding.
