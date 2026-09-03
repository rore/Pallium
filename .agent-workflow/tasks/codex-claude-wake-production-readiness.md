<!-- agent-workflow:start -->
**Outcome:**
S1A is complete: the installed no-human Windows witness proved a peer Relay message was claimed by Stop, injected through attributed stderr and exit 2, and answered without another human prompt. The next blocker is S1B restart durability: service restart loses the memory-only Claude registration and leaves delivery pending until a manual wake re-registers it.

**Target:**
Pallium Claude Code Relay availability.

**Scope:**
S1A changes are complete. S1B is plan-only: no runtime edit is authorized until Codex review accepts the smallest trusted-local persistence/recovery slice. Every Stop registers idle with existing exact session/container/actor derivation. If `stop_hook_active` is false, call scoped `/relay/turn`; route admission marks busy. Send `max_chars=2400` in every non-recursive `/relay/turn` POST; storage is the authoritative claim boundary and skips over-budget items while retaining later fitting items pending/claimable. Stop candidate-renders exactly the returned claimed set without a second formatter cap; ACK each candidate; reformat only the ACK-success subset for attributed stderr and exit 2 only when that subset is nonempty. If recursive, empty, failed, invalid, or render-empty, ingest and exit 0. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log`; no PR.

**Constraints:**
Peer text -> Stop -> one scoped `/relay/turn` POST with authoritative `max_chars=2400` -> candidate render of the returned claimed set -> individual ACK -> reformat successful subset -> exit 2 -> continuation acts -> next Stop re-registers idle, ingests, exits 0. Native transport never changes delivery. Existing Stop scope is authoritative; no MCP or model scope/identity. One bounded non-recursive Stop probe is accepted; `stop_hook_active` prevents recursion. Empty/failure/render-empty/all-ACK-failure exits 0; unACKed claimed items stay lease-recoverable. `has_more` and `remaining_count` remain pending and are unqualified until S1B rearm/continuation; the S1A witness proves one bounded batch only. No pins, MCP, durable socket/token state, reconciler, TTL change, DPAPI, secret table, durable attempts, Uvicorn subclass, SessionEnd, StopFailure, batching beyond one bounded batch, or schema change. Session pin is out of scope.

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
## S1B plan (plan only; no runtime edits)

The incident is narrowly scoped: restarting the service drops `ClaudeWakeRegistry`'s in-memory exact-session capability, so a persisted pending delivery cannot use native wake until a later hook re-registers it. Reuse the existing registry, Relay storage, dispatch, and transport; do not introduce a capability framework, schema migration, DPAPI, expiry timer, or alternate delivery path.

1. Persist one exact Claude registration record per `(runtime, session_ref)` in an app-owned, user-private local capability file: runtime, session/container/actor refs, socket path, token, generation, and idle/busy state. Validate with the current registry limits; write atomically (temporary sibling + replace) with owner-only permissions/ACL. If the file is missing, malformed, corrupt, stale against validation, or cannot be protected, load nothing and leave Relay delivery pending without logging a token or socket path.
2. Keep capability lifetime explicit rather than TTL-driven: there is no time-based deletion that silently disables wake. A hook registration replaces only its exact session record. Busy remains busy across restart until a trusted Stop/turn lifecycle changes it; never infer idle from service startup.
3. On service construction, rehydrate only validated records into the existing registry before accepting Relay wake dispatch. Once ready, reconcile each persisted **idle** capability at most once against already-pending exact-scope deliveries, using existing Relay selection/dispatch and existing one-shot worker coalescing. Reconciliation never claims, ACKs, or emits a delivery; a transport failure leaves it pending and retryable.
4. Keep concurrent behavior fail-closed: atomic read/replace plus the registry lock prevent torn state; duplicate registrations and concurrent send/restart dispatch produce at most one transport attempt per exact session; transport failure restores the eligible idle capability without changing delivery state. Persisted busy blocks dispatch until a trusted lifecycle signal.
5. Deterministic fast E2E must cover restart-after-idle, restart-while-busy, delivery pending before restart, send after restart, corrupt/stale capability rejection, Unicode file/socket paths, duplicate registration/concurrent send, and failed transport preserving pending retryability. The final gate is a real no-manual-re-registration Windows restart witness: register idle → restart service → send/pending delivery → native wake → Stop claim/inject/reply.

**S1B review gate:** Codex reviews this plan before any guarded-path/runtime change. S1A remains complete; overall status is Blocked only on S1B restart durability.