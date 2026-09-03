<!-- agent-workflow:start -->
**Outcome:**
S1A is complete: the installed no-human Windows witness proved a peer Relay message was claimed by Stop, injected through attributed stderr and exit 2, and answered without another human prompt. The next blocker is S1B restart durability: service restart loses the memory-only Claude registration and leaves delivery pending until a manual wake re-registers it.

**Target:**
Pallium Claude Code Relay availability.

**Scope:**
S1A changes are complete. S1B is plan-only: no runtime edit is authorized until Codex review accepts a trusted-local exact-capability lifecycle. The proposed state distinguishes `idle`, `busy`, and `wake_inflight` with delivery id and UTC attempt time; it persists each canonical mutation before publication/transport, includes a one-file-per-session outage registration intent from the hook, never claims or ACKs during recovery, and retains Relay as the source of once-only delivery truth. Every Stop registers idle with existing exact session/container/actor derivation. If `stop_hook_active` is false, call scoped `/relay/turn`; route admission marks busy. Send `max_chars=2400` in every non-recursive `/relay/turn` POST; storage is the authoritative claim boundary and skips over-budget items while retaining later fitting items pending/claimable. Stop candidate-renders exactly the returned claimed set without a second formatter cap; ACK each candidate; reformat only the ACK-success subset for attributed stderr and exit 2 only when that subset is nonempty. If recursive, empty, failed, invalid, or render-empty, ingest and exit 0. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log`; no PR.

**Constraints:**
Peer text -> Stop -> one scoped `/relay/turn` POST with authoritative `max_chars=2400` -> candidate render of the returned claimed set -> individual ACK -> reformat successful subset -> exit 2 -> continuation acts -> next Stop re-registers idle, ingests, exits 0. Native transport never changes delivery. Existing Stop scope is authoritative; no MCP or model scope/identity. One bounded non-recursive Stop probe is accepted; `stop_hook_active` prevents recursion. Empty/failure/render-empty/all-ACK-failure exits 0; unACKed claimed items stay lease-recoverable. `has_more` and `remaining_count` remain pending and are unqualified until S1B rearm/continuation; the S1A witness proves one bounded batch only. S1A introduced none of those durable mechanisms. The S1B plan is the narrow exception: one trusted-local exact-capability file plus one atomic per-session hook registration-intent file, a read-only exact-scope pending candidate query, event-driven reconciliation, best-effort SessionEnd/strictly-missing-endpoint cleanup, and explicit idle/busy/wake_inflight state. It still forbids DPAPI, a secret table, generic framework, claim/ACK during recovery, silent age eviction, alternate delivery paths, and secrets in logs.

**Completion criteria:**
1. Every Stop registers idle; only non-recursive Stop makes one exact scoped `/relay/turn` POST with `max_chars=2400`, which marks busy and claims no item outside that budget.
2. Storage `/relay/turn` `max_chars=2400` is the sole claim boundary; Stop calls `format_relay` without a competing cap on the returned claimed set, so a fitting delivery after a skipped over-budget item is rendered and considered for ACK. `common.acknowledge_relay` returns its successful items without changing existing callers; Stop ACKs candidates individually, reformats only successes, and exits 2 only for a nonempty successful subset. All-ACK failure exits 0; partial failure leaves only unACKed items lease-recoverable.
3. Continuation Stop re-registers idle, ingests result, exits 0, and does not re-probe; native wake never completes delivery.
4. Deterministic real-hook/HTTP E2E: pure-text zero-tool wake; none/one/max/over-budget/`has_more`; Unicode; missing/mismatch/failure; recursion guard; once-only, partial, and all-ACK failure; exit-2 success/failure boundary; duplicate empty; continuation ingest/rearm; lease recovery; fake clocks/events and no sleeps.
5. Installed Windows no-human text-only witness proves peer -> Stop -> continuation -> completion. S1B durability/reconciliation remains deferred.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
S1A changes normal end-of-turn Relay admission; bounded rendering, partial ACK, continuation, scope, and rearm require real caller-surface proof.

**Discovery:**
Claude 2.1.250 peer frames are internal `isMeta` text turns and bypass UserPromptSubmit, so S0/S0.5 were misqualified for peer admission. Claude reproduced a pure-peer-text Stop block/reason exit-2 continuation. Existing Stop derives exact scope and registers idle; existing `/relay/turn` callback marks matching registration busy. MCP/actor-pin is unnecessary.

**Material assumptions:**
- Claude supplies `stop_hook_active` on continuation Stop.
- Claude honors Stop exit 2 as one continuation for pure peer text.
- Existing Stop scope and route admission match or fail closed.
- Stderr is the proven attributed continuation surface.

**Plan:**
S0/S0.5 — MISQUALIFIED for causal peer admission.

S1A — COMPLETE: Architect Codex re-review accepted; installed no-human Windows witness passed (Stop claimed and injected `relay-msg-facf9ae3…`, Claude replied without a human prompt).

S1B — BLOCKED on plan review: service restart erases the memory-only Claude registration. Plan only: persist exact capability and state, rehydrate/reconcile safely, then prove restart behavior.

S2 — Evidence-driven peer/lifecycle hardening. S3 — Codex MCP recovery remains fail-closed. S4 — cross-platform live qualification.

**Verification plan:**
- Stop lifecycle → real hook + HTTP exact probe, busy mark, stderr, exit 2, recursive exit 0, ingest/rearm.
- Claim/render/ACK → storage `/relay/turn` `max_chars=2400` is authoritative; an over-budget skipped item followed by a fitting claimed item proves the entire returned set renders; storage and hook use the exact same control lines for the authoritative budget, then successful-subset reformat, `has_more`/`remaining_count`/Unicode, partial/all failure, and exactly-once ACK.
- Failure/duplicate → scope mismatch, request/render failure, partial/all ACK failure and exit-2 boundary, recursion, duplicate, `has_more`/`remaining_count` pending, and lease recovery.
- Installed behavior → no-human Windows pure text peer witness.
- Repository → focused/full tests, workflow/redline/diff; no production claim before witness.

**Plan review:**
2026-09-03 — Prior S1 durability and MCP S1A proposals are superseded. Architect review found route-admission rearm, UTF-8 stderr, and storage-template gaps; all are corrected. Codex architect re-review is CLEAN: real boundary regression proves storage selection and Claude rendering stay within the same budget while preserving skipped-overbudget/later-fit `has_more`/`remaining_count`.

**Approvals:**
Approved by user 2026-09-03: "you have blanket approval for all tasks you get from the architect". Codex architect re-review CLEAN 2026-09-03; installed S1A runtime witness PASS. No Claude use is authorized for S1B planning.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

2026-09-03 — Implemented S1A: non-recursive Claude Stop probes scoped `/relay/turn` once with `max_chars=2400`, renders exactly the returned claimed set without a formatter cap, ACKs individually, re-renders only 2xx-confirmed items to stderr, and exits 2 only for that nonempty subset. Recursive Stop re-registers idle without a probe. `acknowledge_relay` now returns only confirmed deliveries while existing callers may ignore the return. Architect re-review fixed empty/request/render/all-ACK-failure rearm after route admission, non-UTF-8 stderr buffer emission, and exact storage/hook template budgeting. Focused caller-surface regressions and exact storage/Claude boundary regression pass. Module-form affected suite, relay E2E, and isolation counts are recorded by final verification. Workflow and diff checks clean. `ruff` is unavailable in the environment. Architect re-review and installed S1A witness are PASS. Overall work is blocked on S1B restart durability planning and its eventual implementation/witness.
## S1B amended plan (plan only; no runtime edits)

**Incident / redline:** Service outage during Claude Stop is a distinct lost-handoff window: the hook's loopback registration fails, Claude becomes idle, and a later restart can reload stale `busy` forever. Durable capability and intent files may contain socket/token material, so no secret value, path, or token enters logs, exceptions, status, or tests. Relay remains authoritative for delivery; persistence/reconciliation never claims, ACKs, or emits it.

1. Canonical exact capability lives at `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with runtime/session/container/actor, socket/token, generation, UTC `updated_at` ordering value, and `{busy, idle, wake_inflight(delivery_id, utc_attempt_time)}`. Atomic sibling replace; POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL, with no DPAPI/custom DACL. Permissions are hygiene: malformed/invalid records are ignored, but a valid record is never discarded solely because permission-setting later reports failure.
2. Add the smallest cross-platform outage handoff: `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`. A Claude hook writes/replaces this one exact registration intent atomically only after loopback registration fails; the intent carries the same validated capability, lifecycle state, `updated_at`, and random intent id. On readiness the service atomically takes an intent, merges it only when newer than canonical state, durably writes canonical state before publishing it to the registry, then removes the consumed intent. A later intent remains for the next pass. A successful service registration writes canonical state first and records a newer `updated_at`, so an older outage intent cannot overwrite a trusted busy/idle mutation. This lets a Stop reached during outage supersede stale busy once the service returns, without a later hook, human prompt, or new send.
3. There is no TTL or age-based cleanup. Exact hook registration replaces canonical state only after its durable write. Best-effort SessionEnd removes its exact record; only an observed truly missing endpoint or SessionEnd is terminal and deletes it, avoiding the 256-record leak without silent eviction. Typed transport outcomes are conservative: `accepted` stays inflight pending observation; `retryable` restores idle; `terminal` means only missing endpoint and deletes. Permission denied, timeout, malformed transport response, and all other uncertainty are retryable.
4. Persist-before-effect ordering is mandatory. Register/busy/idle/inflight is published to the in-memory registry only after canonical atomic write succeeds. Busy mutation atomically replaces durable state before it can make memory busy, so restart cannot revive stale idle during active work. Before native write, persist idle→inflight with delivery id/time; if that persistence fails, do not write transport. Persistence failure is sanitized/observable (`persistence_failed`) and preserves a previously valid capability where possible; it never marks Relay delivery done. Test every write boundary: canonical registration, intent write/take/merge/delete, busy/idle, idle→inflight, terminal delete, and atomic replace failure.
5. Add the minimum read-only storage/service exact-scope pending-candidate query; it rechecks without claim/ACK and distinguishes pending from claimed/delivered/expired. Recovery checks it after restart: claimed/delivered/expired clears inflight retry; pending inflight waits one bounded grace then retries. Crashes before persistence, after inflight persistence/before native write, and after native write prefer at most an extra empty admission over lost work; Relay action remains once-only.
6. Use one small event-driven reconciler, signaled by service readiness, new Relay send, successful registration, and intent consumption. Signals coalesce through existing registry workers. While exact pending work and matching eligible idle/inflight capability remain, retries continue indefinitely with a capped backoff interval; there is no finite retry count and no human/new-send dependency. Retryable transport restores idle; accepted stays inflight until read-only observation; terminal deletes only under the strict rule above.
7. Deterministic fast E2E: restart-after-idle; restart-while-busy whose Claude Stop occurs while Pallium is down and then recovers with no later hook/human/send; pending-before-restart; send-after-restart; crashes before/after canonical/intent/inflight writes and native write; corrupt/stale intent/capability; permission-setting/persistence failure with sanitized observability; Unicode paths; duplicate registration/concurrent send; accepted/retryable/terminal classification; infinite eligible retry with capped interval; and exact query never claiming/ACKing. Final real Windows witness: register idle → restart/outage or already-pending exact delivery → native wake → Stop claim/inject/reply, with no manual re-registration or user prompt.

**S1B review gate:** This amended plan is NOT CLEAN until Codex accepts the outage handoff, durable ordering, read-only query, indefinite bounded-backoff reconciler, and conservative cleanup semantics. S1A remains complete; overall status is Blocked only on S1B restart durability.