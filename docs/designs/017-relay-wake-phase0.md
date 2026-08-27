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

**Verdict:** Passive-only. The 2026-08-27 probe reached a separately launched
App Server, not the existing Codex session addressed by Relay. That path is
rejected for Relay wake and must not progress to an adapter.

**Transport-confirmed contract (partial — probe 2026-08-27):**
- `thread/queue/add` with `clientUserMessageId` is callable on Windows via stdio transport. Queue response preserves `clientUserMessageId` in `queuedSubmission`.
- `initialize` with `capabilities.experimentalApi: true` accepted; server returns `userAgent` with `0.149.1` on Windows.
- `stdio://` is the Windows default transport — daemon subcommand is Unix-only but stdio App Server works on Windows.
- Schema requires `--experimental` flag (`generate-json-schema --experimental`); non-experimental schema omits `thread/queue/add`.

**Why the candidate fails the product gate:**
- it creates or controls a Pallium-owned App Server rather than the addressed
  already-running Codex session;
- success would fragment session identity and conversation state;
- queue admission in that substitute runtime would not satisfy Relay delivery.

**Probe evidence:** `.local/phase0-probes/codex-0.149.1-stdio-probe-2026-08-27.json`

**Re-entry gate:** Resume Codex wake work only when a supported surface can target
the exact existing session identified by Relay and can prove all seven cases in
that same session. Do not use a managed App Server, resumed clone, or replacement
session as evidence.

**Rejected managed-runtime handshake (evidence only):**
1. Initialize App Server with `capabilities.experimentalApi: true`.
2. `thread/queue/add` with `clientUserMessageId = pallium:<delivery_id>` and attributed Relay payload as `input: [{type:"text", text:"..."}]`.
3. Queue response returns `queuedSubmission` with preserved `clientUserMessageId` → `wake_state = triggered`.
4. `item/started` event for a `userMessage` carrying the exact `clientUserMessageId` and content → `wake_state = admitted`, delivery complete.
5. `turn/completed` is execution completion, not delivery admission — do not use it.
6. `turn/steer` is forbidden. `turn/start` is not a substitute for the queue path.

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

**Verdict:** Passive-only. Native channel eligible (2.1.246 ≥ 2.1.234 Windows minimum); no probe run. Busy-turn semantics require an explicit decision before enabling `busy_queue` capability. Active wake adapter implementation blocked pending probe.

**Proven:**
- Native local inbox socket authenticates via local token; official cross-session messaging starts a new turn when idle.
- 2.1.246 clears the documented Windows minimum version.


**Open decision (required before PR 3):**
During an active turn, Claude Code reads inbox messages between tool calls. This *may* not create a distinct following turn, violating the non-negotiable "busy delivery never steers the active human-owned turn." Options:
- a) Advertise only `idle_wake`; busy messages wait for idle (defer, safe).
- b) Prove that inbox delivery during an active turn queues a distinct *following* turn (not mid-turn steering) and enable `busy_queue`.
- c) Channels as an alternative ingress if native inbox doesn't satisfy the separate-turn contract.

Until (a) or (b) is proven with a Windows disposable trace, Claude Code advertises only `idle_wake`.

**Admission handshake (idle path):**
1. Register the live inbox socket and local auth token as `idle_wake` capability.
2. Submit the attributed Relay payload to the inbox.
3. Admission: next turn started in that session carries the Pallium delivery ID in its envelope → `wake_state = admitted`.
4. If the session is not idle, no submission; delivery remains `pending` for next-natural-turn.

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

1. Claude Code busy-turn semantic: idle-only or proven separate-turn queue (see above).
2. Which candidate runtime can first prove activation of the exact existing
   addressed session; substitute managed sessions are categorically excluded.

## Re-estimate of remaining PRs

Based on Phase 0 corrected findings. Codex has no qualifying existing-session ingress; OpenCode requires plugin work; Claude Code requires the busy-turn decision.

| PR | Scope | Estimate |
|---|---|---|
| 2 | Durable core: wake metadata, state machine, leases, dispatcher, fake adapters, recovery | 3–5 days |
| 3 | Claude Code adapter (idle path; busy path conditional on open decision) | 2–3 days |
| 4 | OpenCode plugin coordinator + adapter | 3–4 days |
| 5 | Codex adapter, only after a supported existing-session ingress appears | Not scheduled |
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
