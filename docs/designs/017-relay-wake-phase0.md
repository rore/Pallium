# Relay wake Phase 0 decision record

**Status:** Active — supersedes per-runtime verdict in 016
**Scope:** Installed Claude Code 2.1.246, Codex CLI 0.149.1, OpenCode 1.18.19, native Windows
**Gate:** Every runtime adapter in PR 3–5 must reference this record and pass all seven Phase 0 cases before merging.

## Per-runtime verdict

Verdicts are based on official documentation, integration tests, and installed-runtime probes. All three runtimes are classified **passive-only**: natural-turn delivery is safe; active wake adapter implementation requires the full seven-case evidence listed in each runtime's "Remaining gates" section. Codex and OpenCode have partial transport-layer probes — admission and remaining cases are unobserved. Claude Code has no probe. No active wake adapter PR may merge until its runtime section is fully evidenced.

| Runtime | Verdict | Implementation order |
|---|---|---|
| Codex | **Passive-only** — managed App Server is a substitute runtime, not existing-session wake | Not scheduled |
| OpenCode | **Passive-only** — transport confirmed via probe; active wake admission unobserved | Second |
| Claude Code | **Passive-only** — native channel eligible; no probe run | Third |

### Codex

**Verdict: Probable — proceed to live Windows PoC (updated 2026-08-27).**
Strong source and integration-test evidence that `codex queue` targets the exact
already-running Codex TUI session via a shared durable SQLite queue, without
requiring Pallium to own or replace it. Live PoC required before PR 5 starts.

**Prior verdict (2026-08-27 probe):** Passive-only. The probe reached a
separately launched App Server, not the existing session. That path remains
rejected (see below).

**New mechanism confirmed by source + integration tests (2026-08-27 research):**

`codex queue --thread <THREAD_ID> --message "<payload>"` writes a user message
into `$CODEX_HOME/queue_1.sqlite` — the durable user-message queue. The
already-running Codex TUI process runs `QueuedItemService::watch_external_messages`,
which periodically checks SQLite's data version, gets thread IDs loaded in its
own `ThreadManager`, and dispatches wake attempts for threads with external queue
changes. No Pallium process-ownership of the target session; Pallium is the queue
writer and the existing user-owned TUI is the only process that processes the turn.

No `#[cfg(unix)]` around the queue watcher. The daemon/socket IPC limit is
Unix-only; the queue mechanism is cross-platform. Suitable for Windows PoC.

**Admission acknowledgement path:**
`UserPromptSubmit` hook fires for queued user messages. The existing Pallium
Codex hook can observe the delivery ID in the queued payload and call the
Pallium loopback admission endpoint. This is a clean admission proof from the
target session's own model-bound boundary.

**Busy behavior is correct:**
If the thread is busy, the message remains queued. When the active turn completes,
the lifecycle contributor drains the queue and starts a new distinct turn.
Relay invariant "busy delivery never steers the active turn" is satisfied.

**Integration test coverage:**
`externally_changed_queues_dispatch_independently_and_retry_failed_wakes` creates
an independent second state runtime writing `"written by another process"` to a
thread loaded in the running runtime, then verifies the running runtime detects
the external write and starts a model turn with the externally written message.
Also covers: independent loaded threads, delayed wake attempts, surviving while
thread not loaded, ordinary later resume, exact queue consumption.

**Live PoC required before PR 5:**
Run two cases on Windows:
1. Codex idle: `codex queue --thread T --message "[PALLIUM:R123] ..."` → same
   TUI wakes, `UserPromptSubmit` hook sees R123, admission confirmed.
2. Codex busy: R123 stays queued; current turn is not steered; after completion
   same TUI starts a new distinct turn with R123.
Both cases must pass all seven Phase 0 cases.

**The prior Codex App Server path remains rejected:**
It creates or controls a Pallium-owned App Server rather than the existing session.
The July 2026 upstream issue reports predate 0.149.1 and no longer describe the
current queue architecture. Do not use them as evidence that Codex lacks
exact-session ingress.

### OpenCode

**Verdict:** Passive-only. Transport layer confirmed via probe (2026-08-27); active wake admission not yet observed. Active wake adapter implementation blocked pending full seven-case evidence.

**Transport-confirmed behaviors (partial — probe 2026-08-27):**
- Server and plugin APIs expose stable session IDs and `prompt_async`.
- `prompt_async` body requires a `parts` array (`[{"type":"text","text":"..."}]`); `content` key is rejected with 400.
- `metadata.palliumRelayId` is accepted in the `prompt_async` body but **NOT persisted in message info**. Message info contains only: `id`, `sessionID`, `role`, `time`, `agent`, `model`. Correlation via metadata field lookup will fail.
- Admission correlation must embed the relay ID in text content and search by text, not by metadata field.

**Not yet observed (required before PR 4):**
- Model-visible admission: session message containing the relay ID text marker confirmed in event stream.
- Busy-deferral: plugin holds item in ledger while session busy, submits at idle boundary.
- App restart recovery.
- Session-states behavior.
- Ambiguous-retry behavior.

**Probe evidence:** `.local/phase0-probes/opencode-1.18.19-probe-2026-08-27.json`

**Remaining gates before PR 4:**
1. ~~Prove a bare `prompt_async` 204 is transport acknowledgement only — not admission.~~ **Confirmed by probe 2026-08-27**: 204 is transport ACK only.
2. Implement and prove the plugin-owned durable pending ledger that serializes against session-idle.
3. Prove admission via text-content event stream (metadata not persisted in message info).

**Admission handshake:**
1. Plugin persists the Relay item locally before any broker call.
2. Plugin checks recent session history for `relay_id=pallium:<delivery_id>` text marker to detect prior admission (restart safety). Metadata lookup will not work — metadata is not persisted in message info.
3. At a proven safe boundary (session idle), call `prompt_async` with `parts: [{type: "text", text: "... relay_id=pallium:<delivery_id>"}]` and `metadata.palliumRelayId` (belt-and-suspenders; metadata may be used by future event streams even if absent from message info).
4. Admission: session messages contain the exact `relay_id=...` text marker → `wake_state = admitted`.
5. Busy deferral: plugin holds the item in its local ledger; does not call `prompt_async` until idle.
6. On Pallium restart: plugin replays only items not found in session history.

### Claude Code

**Verdict:** Passive-only pending live PoC. Exact-session wake is functionally
available via native named-pipe messaging; two paths differ in auth stability.

**Idle boundary correction (2026-08-27 research):**
`user_prompt_submit` hook exit is NOT the idle boundary. The correct signal is
the `Stop` hook, which fires when the main Claude Code agent finishes responding.
`idle_prompt` matcher also fires when Claude is waiting for the next prompt and
can serve as secondary telemetry. Do not treat `user_prompt_submit` exit as
model-turn idle.

**Path A: Native named-pipe (preferred, auth seam requires live PoC)**
Each eligible session owns a named-pipe inbox. Idle delivery starts a new turn.
Busy delivery is accepted between tool calls (exact semantics — separate
following turn vs mid-turn steering — must be proven).

`CLAUDE_CODE_MESSAGING_TOKEN` is documented as an own-child credential for
hooks and Bash commands. There is no public contract stating that an independent
long-running Pallium daemon can hold that token and qualify as own-child. On
Windows the auth may be primarily token-based (no Unix process ancestry), which
could allow it experimentally, but this is undocumented behavior. A separate
peer-token/key mechanism exists internally (reverse-engineered in claude-code-socket-transport
for ≤2.1.233) but is not a public API.

Live PoC required: (a) non-child Pallium process holds the token → sends to
pipe → verify idle wake in the same session; (b) classify result as supported
or implementation detail. If (a) fails, fall back to Path C.

**Path B: Channels (supported external ingress, preview/opt-in)**
Channels push external events into the already-open session without spawning a
new process. Pallium sends a channel notification; the existing session receives
it. Requires `--channels plugin:pallium` at session start; Enterprise/Team must
allow it. Research preview. Multiple events while busy are grouped into one turn
(weaker one-delivery-per-turn invariant than Codex queue).

**Path C fallback:** Path A fails → use Channels as the supported external ingress.

**`notify_idle` / `notify_when_idle`:**
The `notify_when_idle` option on a SendMessage call asks another Claude Code
session to send one notice when it next goes idle. It is a one-shot
inter-session signal, not a subscribe/poll stream. No public API for Pallium
to receive an idle event stream. `Stop` hook is sufficient.

**`artifact_yield`:** Internal/unproven. Do not build on it.

**Remaining gates before PR 3:**
1. Live Windows PoC: prove Path A (non-child Pallium daemon) or confirm Path C.
2. Busy-turn semantic: prove Path A busy delivery queues a distinct following
   turn (not mid-turn steering); or restrict to `idle_wake` only.
3. Admission correlation: `Stop` hook on receiving session confirms delivery ID
   present in the turn, calls loopback admission endpoint.
All seven Phase 0 cases must pass.

## Seven Phase 0 cases

All adapters must prove these cases before entering implementation. The fixtures in `tests/relay/wake/fixtures/<runtime>/` encode expected protocol shapes for deterministic CI.

| # | Case | Pass condition |
|---|---|---|
| 1 | Identify live session for `session_ref` | Pallium resolves a session registered by the integration; closed or unknown refs are rejected |
| 2 | Submit attributed Relay turn while idle | A distinct new turn starts; delivery/idempotency ID is present in the turn envelope |
| 3 | Submit while user-owned turn is busy | No steering of the active turn. `busy_queue` adapters: message queued for a subsequent distinct turn. `idle_wake`-only adapters (e.g. Claude Code in current policy): `unavailable` outcome, natural-turn fallback enabled. Claude Code correctly yields `unavailable` — this is a pass, not a failure. |
| 4 | Observe positive admission event tied to delivery ID | `wake_state → admitted` only on the correlated event, not on transport ACK |
| 5 | Distinguish closed, stale, permission-denied, unavailable | Each non-eligible state maps to a specific fallback reason; no retry on permanent failure |
| 6 | Behavior after runtime or Pallium restart | Outstanding triggered deliveries are recovered; already-admitted deliveries are idempotent |
| 7 | Safe retry after ambiguous response | Trigger suppressed until admission deadline; fallback released once without another wake attempt, unless the runtime proves the ID idempotent |

## Normalized adapter result contract

Adapters return one of five normalized outcomes to the wake coordinator:

| Outcome | Meaning | Wake state after |
|---|---|---|
| `admitted` | Correlated admission event received | `admitted` → delivery complete |
| `triggered` | Runtime accepted request; await callback | `triggered` → wait for deadline |
| `unavailable` | Session closed, not found, or capability gone | `fallback` with reason |
| `rejected` | Permanent failure (permission, version, policy) | `fallback` with reason |
| `ambiguous` | Transport accepted but admission unconfirmed | `triggered` → wait for deadline, then `fallback` |

The generic wake coordinator must not import runtime-specific types. All protocol details stay inside the adapter.

## Wake state transition table

The complete machine-readable matrix (all 6 states × 15 events) is in [`tests/fixtures/relay_wake/contract.json`](../../tests/fixtures/relay_wake/contract.json). The rows below cover the cases most likely to have implementation surprises.

| State | Event | Next state | Notes |
|---|---|---|---|
| `queued` | wake dispatcher reserves delivery | `triggering` | Atomic; natural-turn claim blocked until fallback |
| `triggering` | adapter returns `triggered`/`admitted` | `triggered` / `admitted` | |
| `triggering` | adapter returns `unavailable`/`rejected` | `fallback` | Natural-turn claim re-enabled |
| `triggering` | adapter returns `ambiguous` | `triggered` | Wait for deadline; no retry unless idempotency proven |
| `triggered` | admission callback with valid token | `admitted` | Delivery complete |
| `triggered` | admission deadline exceeded | `fallback` | Token invalidated; natural-turn claim re-enabled |
| `triggered` | `capability_disabled` or session close | `triggered` (stays until deadline) | No new trigger attempt; deadline still governs |
| `triggered` | message expiry | `fallback` | Expiry wins; late callbacks rejected |
| `admitted` | any event | `admitted` | Terminal; no expiry; callbacks idempotent |
| `fallback` | natural-turn hook claims delivery | delivery `pending→claimed` | Normal hook path |
| `fallback` | message expiry | delivery `expired` | Terminal |
| `not_eligible` | message expiry | delivery `expired` | Never entered wake path |
| `queued` or `triggering` | message expiry | `expire` | Terminal; matches canonical matrix — expiry is not a fallback path |
| `queued` | `capability_disabled` | `fallback` | Before trigger; immediate fallback |
| any | session reopen (new adapter generation) | old-generation callbacks rejected | New registration creates new generation; old tokens invalid |
| `triggered` | late callback after deadline | `reject` | Token single-use; after `admission_deadline → fallback`, subsequent callbacks are rejected |
| `not_eligible` | coordinator CAS session-idle succeeds | `queued` | Atomic; natural-turn hook locked out until fallback |
| `not_eligible` | coordinator CAS session-idle fails (session busy) | `not_eligible` | Natural-turn hook claims at next idle boundary; wake deferred |

## Provisional numeric parameters

Working values for adapter development. None have been measured against an installed runtime. Each parameter lists the basis for the estimate and the gate that must confirm or replace it before the corresponding adapter PR merges.

| Parameter | Provisional value | Basis | Gate |
|---|---|---|---|
| Admission deadline | 120 s | One ~42 s observed idle turn; 3× buffer — not a captured trace | PR 4: measure with OpenCode plugin probe |
| Max concurrent wake attempts | 4 | Estimated local I/O bound; not measured | Gate: load probe before PR 2 |
| Retry on ambiguous | 0 | Policy — prevents double delivery on non-idempotent runtimes | Runtime-specific idempotency proof required to enable |
| Wake starts per recipient per minute | 6 | Estimated storm guard; not measured | Gate: measure before PR 2 |
| Reply hop bound | 4 | Existing Relay audit bound; not a wake-specific measurement | Carries over from Relay contract; validate in PR 2 |
| Fan-out recipient bound | 25 | Existing Relay limit | Unchanged; validate in PR 2 |
| Capability heartbeat interval | 15 s | Unconfirmed | Gate: measure against each runtime before PR 3–5 |
| Capability lease | 45 s | 3× heartbeat; provisional | Gate: same as heartbeat |

## Decisions still open (must resolve before PR 2)

1. Claude Code busy-turn semantic: prove distinct following turn or restrict to idle_wake only.
2. Claude Code auth path: Path A (non-child daemon token) or Path C (Channels).
3. Codex live Windows PoC: confirm queue_1.sqlite watcher fires in existing TUI, UserPromptSubmit hook sees delivery ID, busy case queues correctly.

## Re-estimate of remaining PRs

Updated based on 2026-08-27 research findings. Codex is now live-PoC priority (was blocked).

| PR | Scope | Estimate |
|---|---|---|
| 2 | Durable core: wake metadata, state machine, leases, dispatcher, fake adapters, recovery | 3–5 days |
| 3 | Claude Code adapter (Path A or C; idle path confirmed; busy path conditional) | 2–3 days |
| 4 | OpenCode plugin coordinator + adapter | 3–4 days |
| 5 | Codex adapter (queue_1.sqlite path; pending live Windows PoC) | 2–3 days |
| 6 | Cross-runtime journeys, dashboard, docs, runbook | 2–3 days |

## Primary references

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex queue integration tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_queue.rs)
- [OpenCode server API](https://opencode.ai/docs/server/)
- [OpenCode plugin API](https://opencode.ai/docs/plugins/)
- Phase 0 initial probes and provisional state contract: [016-relay-wake-feasibility.md](016-relay-wake-feasibility.md)
- Full roadmap item: [add-wake-first-relay-delivery](../../roadmap/features/add-wake-first-relay-delivery.md)
