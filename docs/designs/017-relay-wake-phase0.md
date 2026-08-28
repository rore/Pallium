# Relay wake Phase 0 decision record

**Status:** Active — supersedes per-runtime verdict in 016
**Scope:** Installed Claude Code 2.1.250, Codex CLI 0.149.1, OpenCode 1.18.19, native Windows
**Gate:** Every runtime adapter in PR 3–5 must reference this record and pass all seven Phase 0 cases before merging.

## Per-runtime verdict

Verdicts are based on official documentation, integration tests, and installed-runtime probes. All three runtimes remain **passive-only** for production. Codex has proven exact-session `codex queue --thread` admission while idle and at a safe busy boundary. Claude Code has now proven exact-session idle wake through its native authenticated Windows inbox, but direct busy ingress is unsafe for Relay semantics and native duplicate suppression failed. OpenCode has partial transport evidence. No active wake adapter PR may merge until its runtime section is fully evidenced and coordinator-owned dedupe, admission, and fallback are implemented.

| Runtime | Verdict | Implementation order |
|---|---|---|
| Codex | **Passive-only; partial Phase 0** — exact-session `codex queue --thread` ingress is proven for idle and safe busy admission; native duplicate suppression failed | Production gated by cases 5, 6, and 7 plus coordinator-owned idempotency and fallback |
| OpenCode | **Passive-only** — transport confirmed via probe; active wake admission unobserved | Second |
| Claude Code | **Passive-only; partial Phase 0** — exact-session native Windows idle wake proven; busy ingress unsafe and native dedupe failed | Next, after idle-only coordinator gates |

### Codex

**Verdict: Partial — remain passive-only (updated 2026-08-27).**
Live Windows evidence proves that `codex queue --thread` targets the exact
already-running Codex TUI without Pallium owning or replacing it: idle and
safe busy-boundary delivery reached correlated model-visible turns. Production
remains gated on cases 5, 6, and 7 plus coordinator-owned idempotency and fallback.

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

**Live Phase 0 result (2026-08-27):**
1. Idle and safe busy-boundary exact-session admission passed with correlated
   model-visible markers.
2. Fresh post-restart wake passed, but case 6 remains PARTIAL / BLOCKED: no
   outstanding triggered delivery was recovered and no already-admitted delivery
   was proven exactly once.
3. Cases 5 and 7 remain BLOCKED. Native duplicate suppression failed, so a future
   coordinator must own dedupe and fallback before any production adapter.

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

**Verdict: Partial — remain passive-only (updated 2026-08-28).** Native
Windows exact-session wake is feasible through Claude Code's authenticated
per-session named pipe, but only at a verified idle boundary. Direct busy
submission is not Relay-safe, duplicate frames are admitted twice, and the
production admission callback/recovery coordinator does not yet exist.

**Bounded runtime qualification (Claude Code 2.1.246 → 2.1.250):**

- The official noninteractive self-update upgraded the installed runtime from
  2.1.246 to 2.1.250 without changing Claude settings or terminating existing
  sessions.
- The documented hidden development-Channel flag was exercised with an ignored,
  strict temporary MCP configuration on fresh disposable sessions. Both before
  and after the update, Claude reported Channels unavailable and ignored the
  development-channel flag. Channels are therefore not a usable fallback in the
  current account/provider environment; absence from `--help` was not used as
  evidence.
- `--session-id` is supported. Every live probe used a fresh disposable session
  with an explicit immutable ID; no existing session was resumed or contacted.
- A disposable loopback-only Pallium app received the normal `SessionStart` hook
  registration into its in-memory `ClaudeWakeRegistry`. Its injected transport
  used the credential only inside that same process. Socket/token values never
  entered model context, Relay, arguments, files, output, logs, responses, or
  commits.

**Native Windows results:**

| Phase 0 case | Verdict | Sanitized evidence |
|---|---|---|
| 1. Exact live session | PASS | One addressed disposable session received the marker; a simultaneously live non-target session did not. |
| 2. Idle attributed turn | PASS | A transport write to a verified-idle target started a distinct model-visible turn and Claude returned the unique marker. Transport ACK and model-visible admission were observed separately. |
| 3. Busy non-steering | FAIL for direct ingress / policy PASS only as `idle_wake` | During a 25-second tool call, native ingress inserted the wake into the active user turn. Claude completed the original request and did not process the wake as a distinct subsequent turn. Pallium must never invoke this transport while busy; defer to verified idle or use durable next-turn fallback. |
| 4. Correlated admission | PARTIAL | The disposable test correlated the exact marker in target history, but production still needs the receiving `Stop` hook to report the delivery ID before Relay marks admission. Pipe write is not admission. |
| 5. Closed/stale/unavailable | PARTIAL | After target exit, the registered pipe rejected transport with a missing-endpoint error. Production must classify this as stale/unavailable, clear the capability, and release fallback. Permission-denied remains unforced. |
| 6. Runtime/Pallium restart | PARTIAL | Every fresh runtime launch re-registered successfully through `SessionStart`; a closed endpoint was not reusable. Outstanding-trigger and already-admitted exactly-once recovery remain unproven. |
| 7. Ambiguous/duplicate | FAIL natively | Two byte-identical frames carrying the same message ID produced two queue operations and two user admissions. Pallium must deduplicate before native ingress and must not blind-retry an ambiguous write. |

**Idle and security boundaries:** `Stop` is the primary idle boundary;
`user_prompt_submit` exit is not. `idle_prompt` may be secondary telemetry. The
approved registration remains loopback-only, memory-only, fixed-TTL, and
redacted. The production adapter may advertise only `idle_wake`, never
`busy_queue`, until a future supported runtime contract proves distinct queued
turns. A process restart loses the memory-only registration by design and falls
back until the fresh session registers again.

**Channels decision:** Keep the official Channels path documented as a future
alternative, not an implementation dependency. It is preview/organization-gated
and unavailable in the qualified environment even on 2.1.250. Requalify only
when the runtime/account actually accepts the documented hidden flag; do not add
an installer, plugin, or persistent user configuration workaround.

**Remaining gates before a production Claude adapter:**

1. Coordinator-owned persist-first dedupe and one-attempt suppression before any
   native write; no retry after an ambiguous transport result.
2. Verified-idle dispatch from `Stop`/capability state, with busy, expired,
   missing, closed, or transport-error outcomes releasing durable next-turn
   fallback without opening the pipe.
3. Receiving-session admission correlation by exact delivery ID through the
   audited loopback callback; transport success alone cannot ACK Relay.
4. Restart E2E for outstanding and already-admitted deliveries, plus the
   remaining permission/unavailable error mapping.
5. Native macOS and Linux UDS E2E. Windows evidence is not a cross-platform
   guarantee; keep those platforms passive until separately proven.

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

## Remaining production gates (must resolve before adapter PRs)

1. Claude Code is `idle_wake` only: coordinator-owned idle gating, dedupe, exact admission, restart/error fallback, and macOS/Linux UDS E2E remain.
2. Channels is unavailable in the qualified environment; keep it deferred until the documented hidden flag is accepted by a future runtime/account combination.
3. Codex remaining Phase 0 gates: safely cover closed/stale/permission states, outstanding-trigger and already-admitted restart recovery, and ambiguous-response fallback with coordinator-owned dedupe.

## Re-estimate of remaining PRs

Updated based on 2026-08-27 Phase 0 evidence. Codex exact-session ingress is proven, but production remains gated.

| PR | Scope | Estimate |
|---|---|---|
| 2 | Durable core: wake metadata, state machine, leases, dispatcher, fake adapters, recovery | 3–5 days |
| 3 | Claude Code native idle-wake adapter; coordinator dedupe/admission/fallback; Windows E2E | 2–3 days |
| 4 | OpenCode plugin coordinator + adapter | 3–4 days |
| 5 | Codex adapter (queue_1.sqlite path; gated on remaining Phase 0 cases and coordinator dedupe/fallback) | 2–3 days |
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

## 2026-08-27 — Codex live Phase 0 evidence

**Verdict: partial — remain passive-only.** The exact existing Codex session accepted
attributed queued turns without a replacement runtime, but Phase 0 is not fully
cleared and no Codex wake adapter may proceed.

| Phase 0 case | Verdict | Evidence |
|---|---|---|
| 1. Exact live session | PASS | Every manager trigger addressed `01a039d6-68de-7210-bfbf-78a0b15df139`; no App Server, clone, resumed replacement, or managed substitute participated. |
| 2. Idle attributed turn | PASS | Queue item `01a044ec-adb3-75a1-9e77-2e5d0031f00a` admitted `PHASE0-IDLE-25ba0abf84154a678c6cdf96422baf89` as the next persisted user message and model-visible exact-task turn. |
| 3. Busy non-steering turn | PASS | The controlled busy baseline completed before `PHASE0-BUSY-3cfab422ada3422bb7f82fa935ad29e6` entered a distinct following exact-task turn. |
| 4. Correlated admission | PASS | Manager exact-rollout/task-history correlation and model-visible markers, not queue acceptance alone, established admission. |
| 5. Closed/stale/permission/unavailable | BLOCKED | An unknown UUID was rejected with `no rollout found` without touching the target. Closed and permission-denied states were not forced because doing so would close the addressed task or fabricate a failure. |
| 6. Pallium restart recovery | PARTIAL / BLOCKED | After `scripts/restart-service.ps1`, a fresh item `01a044f4-841d-75d3-b55e-42c2ccaecb11` admitted `PHASE0-RESTART-065c2ef792e44dbca01b0afa041b28ca` into exact-task turn `01a044f4-aa3f-7f93-bab3-34dc5e7c81cd`; `/health`, `/status`, and `/debug/queue/health` returned 200. This proves fresh post-restart wake only, not outstanding-trigger recovery or already-admitted exactly-once handling. |
| 7. Safe retry after ambiguous response | BLOCKED | No safe way was available to force an ambiguous transport response. A separate duplicate probe proved **native idempotency FAIL**: identical marker `PHASE0-DUPLICATE-ea66b0165ec84f4b869b52e7ca66e2b6` was admitted in two distinct turns from queue items `01a044f5-adf2-7300-8ff0-29516413b51e` and `01a044f5-baf2-7660-a7d1-daac66519ef0`. |

Consequences:

- `codex queue --thread` is a viable exact-session ingress for the proven cases,
  but it has no native duplicate suppression. Any future Pallium coordinator must
  dedupe by delivery/wake-attempt identity before invoking the adapter.
- Cases 5, 6, and 7 remain gates. Do not implement a production adapter, registry,
  dispatcher, schema, or capability advertisement from this evidence.
- The later app-status `interrupted` label for the successful busy turn conflicts
  with persisted/model-visible admission; treat it as a runtime-observability
  follow-up, not a negative admission result.
- Direct Codex MCP Relay receive lacked an injected session binding in this task.
  `fix-relay-receive-mcp-lifecycle` remains a prerequisite before adapter work.

Raw traces remain under `.local/phase0-probes/` and are intentionally untracked.
